#!/usr/bin/env python3
"""Optional autonomous ComfyUI/LTX visual department.

This adapter deliberately keeps ComfyUI as a separate GPL service. TubeVerse
sends scene prompts to ComfyUI's public API contract and only consumes produced
media. If the endpoint/workflow is not configured or a scene fails, the script
records the failure and exits successfully so Wikimedia/fallback visuals can
still complete the video.

Configuration:
  COMFYUI_URL                 e.g. http://gpu-host:8188
  COMFYUI_API_TOKEN           optional Bearer token for a reverse proxy
  COMFYUI_WORKFLOW_JSON       API-format workflow JSON (usually a GitHub secret)
  COMFYUI_WORKFLOW_PATH       alternative local API-format workflow file
  COMFYUI_PROMPT_NODE         optional explicit positive-text node id
  COMFYUI_TIMEOUT_SECONDS     default 420
  COMFYUI_SCENE_SECONDS       image-to-clip duration, default 7

The workflow must be exported in ComfyUI API format. It can be an image workflow
or an LTX/video workflow; this adapter discovers returned image/video files from
ComfyUI history and converts still images/webm outputs into MP4 scene clips.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TEXT_NODE_CLASSES = {
    "CLIPTextEncode",
    "CLIPTextEncodeFlux",
    "TextEncodeQwenImageEditPlus",
    "PrimitiveStringMultiline",
}


def headers() -> dict[str, str]:
    result = {"Content-Type": "application/json", "User-Agent": "TubeVerse-Autonomy/1.0"}
    token = os.environ.get("COMFYUI_API_TOKEN", "").strip()
    if token:
        result["Authorization"] = f"Bearer {token}"
    return result


def request_json(url: str, method: str = "GET", payload: dict | None = None, timeout: int = 30) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(url, data=data, method=method, headers=headers())
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def request_bytes(url: str, timeout: int = 120) -> bytes:
    req = Request(url, headers=headers())
    with urlopen(req, timeout=timeout) as response:
        return response.read()


def load_workflow() -> dict[str, Any] | None:
    raw = os.environ.get("COMFYUI_WORKFLOW_JSON", "").strip()
    if raw:
        return json.loads(raw)
    path = os.environ.get("COMFYUI_WORKFLOW_PATH", "").strip()
    if path and Path(path).is_file():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return None


def choose_prompt_node(workflow: dict[str, Any]) -> str:
    explicit = os.environ.get("COMFYUI_PROMPT_NODE", "").strip()
    if explicit:
        if explicit not in workflow:
            raise ValueError(f"COMFYUI_PROMPT_NODE={explicit!r} is not present in workflow")
        return explicit

    # Prefer known positive text encoders; otherwise accept the first node with a
    # string `text` input. Operators can pin the exact node through the env var.
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") or {}
        if node.get("class_type") in TEXT_NODE_CLASSES and isinstance(inputs.get("text"), str):
            text = inputs.get("text", "").lower()
            if not any(x in text for x in ["negative prompt", "low quality", "blurry"]):
                return str(node_id)
    for node_id, node in workflow.items():
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if isinstance(inputs, dict) and isinstance(inputs.get("text"), str):
            return str(node_id)
    raise ValueError("could not discover a ComfyUI text-prompt node; set COMFYUI_PROMPT_NODE")


def inject_scene(workflow: dict[str, Any], node_id: str, prompt: str, seed: int) -> dict[str, Any]:
    result = copy.deepcopy(workflow)
    result[node_id].setdefault("inputs", {})["text"] = prompt
    # Randomize each scene without depending on a particular sampler/node name.
    for node in result.values():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        inputs = node["inputs"]
        for field in ("seed", "noise_seed"):
            if field in inputs and isinstance(inputs[field], int):
                inputs[field] = seed
    return result


def queue_prompt(base: str, workflow: dict[str, Any], prompt_id: str) -> str:
    payload = {"prompt": workflow, "client_id": str(uuid.uuid4()), "prompt_id": prompt_id}
    response = request_json(f"{base}/prompt", method="POST", payload=payload, timeout=30)
    if response.get("error"):
        raise RuntimeError(f"ComfyUI rejected workflow: {response['error']}")
    return str(response.get("prompt_id") or prompt_id)


def wait_history(base: str, prompt_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        history = request_json(f"{base}/history/{prompt_id}", timeout=30)
        if prompt_id in history:
            item = history[prompt_id]
            status = item.get("status") or {}
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI execution failed: {status}")
            if item.get("outputs") is not None:
                return item
        time.sleep(2)
    raise TimeoutError(f"ComfyUI prompt {prompt_id} exceeded {timeout_seconds}s")


def output_descriptors(history_item: dict[str, Any]) -> list[dict[str, str]]:
    descriptors: list[dict[str, str]] = []
    for output in (history_item.get("outputs") or {}).values():
        if not isinstance(output, dict):
            continue
        for key in ("videos", "gifs", "images", "audio"):
            values = output.get(key) or []
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, dict) and item.get("filename"):
                    descriptors.append({
                        "filename": str(item["filename"]),
                        "subfolder": str(item.get("subfolder") or ""),
                        "type": str(item.get("type") or "output"),
                        "kind": key,
                    })
    return descriptors


def download_output(base: str, descriptor: dict[str, str], destination: Path) -> Path:
    query = urlencode({
        "filename": descriptor["filename"],
        "subfolder": descriptor["subfolder"],
        "type": descriptor["type"],
    })
    suffix = Path(descriptor["filename"]).suffix.lower() or ".bin"
    target = destination.with_suffix(suffix)
    target.write_bytes(request_bytes(f"{base}/view?{query}"))
    return target


def to_scene_mp4(source: Path, destination: Path, seconds: float) -> None:
    suffix = source.suffix.lower()
    if suffix == ".mp4":
        shutil.copy2(source, destination)
        return
    if suffix in {".webm", ".mov", ".mkv", ".gif"}:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(source), "-an", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", str(destination)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    # Still image -> subtle Ken Burns clip, suitable for MoneyPrinter assembly.
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(source), "-t", str(seconds),
        "-vf", "scale=1080:-2:force_original_aspect_ratio=increase,crop=1080:1920,"
               "zoompan=z='min(zoom+0.0008,1.08)':d=1:s=1080x1920:fps=30,format=yuv420p",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(destination)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene_plan")
    ap.add_argument("output_dir")
    ap.add_argument("--manifest", default=None)
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest) if args.manifest else out_dir / "manifest.json"

    base = os.environ.get("COMFYUI_URL", "").strip().rstrip("/")
    workflow = load_workflow()
    if not base or workflow is None:
        manifest = {
            "enabled": False,
            "generated": 0,
            "reason": "COMFYUI_URL and an API-format workflow are required",
            "scenes": [],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest))
        return

    timeout_seconds = max(30, int(os.environ.get("COMFYUI_TIMEOUT_SECONDS", "420")))
    scene_seconds = max(2.0, float(os.environ.get("COMFYUI_SCENE_SECONDS", "7")))
    prompt_node = choose_prompt_node(workflow)
    scene_plan = json.loads(Path(args.scene_plan).read_text(encoding="utf-8"))
    scenes = scene_plan.get("scenes") or []
    results: list[dict[str, Any]] = []

    # Health check. A dead GPU server must never block the fallback render path.
    try:
        request_json(f"{base}/system_stats", timeout=15)
    except Exception as exc:
        manifest = {"enabled": True, "generated": 0, "reason": f"ComfyUI unavailable: {type(exc).__name__}: {exc}", "scenes": []}
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest))
        return

    for ordinal, scene in enumerate(scenes, start=1):
        idx = int(scene.get("index") or ordinal)
        prompt = str(scene.get("visualPrompt") or scene.get("narration") or "cinematic editorial scene").strip()
        record: dict[str, Any] = {"index": idx, "prompt": prompt, "status": "failed"}
        try:
            prompt_id = f"tubeverse-{uuid.uuid4()}"
            seed = (int(time.time() * 1000) + idx * 104729) % 2_147_483_647
            prepared = inject_scene(workflow, prompt_node, prompt, seed)
            prompt_id = queue_prompt(base, prepared, prompt_id)
            history = wait_history(base, prompt_id, timeout_seconds)
            descriptors = output_descriptors(history)
            if not descriptors:
                raise RuntimeError("ComfyUI completed but returned no downloadable visual output")

            # Prefer actual video/gif outputs over still images.
            descriptors.sort(key=lambda d: {"videos": 0, "gifs": 1, "images": 2}.get(d["kind"], 9))
            source = download_output(base, descriptors[0], out_dir / f"source-{idx:02}")
            scene_mp4 = out_dir / f"scene-{idx:02}.mp4"
            to_scene_mp4(source, scene_mp4, scene_seconds)
            record.update({
                "status": "generated",
                "promptId": prompt_id,
                "sourceFile": source.name,
                "sceneFile": scene_mp4.name,
                "outputKind": descriptors[0]["kind"],
            })
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        results.append(record)

    generated = sum(1 for x in results if x["status"] == "generated")
    manifest = {
        "enabled": True,
        "engine": "comfyui",
        "promptNode": prompt_node,
        "generated": generated,
        "requested": len(scenes),
        "scenes": results,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"engine": "comfyui", "generated": generated, "requested": len(scenes)}))


if __name__ == "__main__":
    main()
