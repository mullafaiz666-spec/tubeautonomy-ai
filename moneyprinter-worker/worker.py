#!/usr/bin/env python3
"""TubeVerse MoneyPrinterTurbo worker.

Claims jobs whose model is ``moneyprinter`` from the TubeVerse worker API, runs
MoneyPrinterTurbo locally, mirrors progress back to TubeVerse, uploads the final
MP4 using TubeVerse's upload contract, and marks the job complete.

MoneyPrinterTurbo is not embedded into Netlify. It runs on user-controlled
compute (local machine / VM / Colab) next to this worker.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

TUBEVERSE_BASE_URL = os.getenv("TUBEVERSE_BASE_URL", "https://tubeverse-ai.netlify.app").rstrip("/")
WORKER_TOKEN = os.getenv("TUBEVERSE_WORKER_TOKEN", "").strip()
API_PREFIX = os.getenv("TUBEVERSE_API_PREFIX", "auto").strip()
POLL_SECONDS = max(3, int(os.getenv("POLL_SECONDS", "8")))
MPT_BASE_URL = os.getenv("MONEYPRINTER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
MPT_HOME = Path(os.getenv("MONEYPRINTER_HOME", "./MoneyPrinterTurbo")).expanduser().resolve()
MPT_API_KEY = os.getenv("MONEYPRINTER_API_KEY", "").strip()
MPT_AUTOSTART = os.getenv("MONEYPRINTER_AUTOSTART", "1").lower() not in {"0", "false", "no"}
MPT_VIDEO_SOURCE = os.getenv("MONEYPRINTER_VIDEO_SOURCE", "pexels").strip() or "pexels"
MPT_VOICE_NAME = os.getenv("MONEYPRINTER_VOICE_NAME", "en-US-AriaNeural-Female").strip()
MPT_BGM_TYPE = os.getenv("MONEYPRINTER_BGM_TYPE", "random").strip() or "random"
MPT_BGM_VOLUME = float(os.getenv("MONEYPRINTER_BGM_VOLUME", "0.15"))
MPT_TIMEOUT_SECONDS = max(300, int(os.getenv("MONEYPRINTER_TASK_TIMEOUT", "3600")))
MPT_USE_PROMPT_AS_SCRIPT = os.getenv("MONEYPRINTER_PROMPT_AS_SCRIPT", "1").lower() not in {"0", "false", "no"}
MAX_UPLOAD_BYTES = int(os.getenv("TUBEVERSE_MAX_UPLOAD_BYTES", str(200 * 1024 * 1024)))

if not WORKER_TOKEN:
    raise SystemExit("Missing TUBEVERSE_WORKER_TOKEN. Register a MoneyPrinter worker in TubeVerse first.")

TV_HEADERS = {"Authorization": f"Bearer {WORKER_TOKEN}"}
MPT_HEADERS = {"x-api-key": MPT_API_KEY} if MPT_API_KEY else {}
_mpt_process: subprocess.Popen | None = None
_resolved_api_prefix: str | None = None


def _decode_json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Non-JSON response from {response.url}: {response.text[:500]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected JSON response from {response.url}: {type(data).__name__}")
    return data


def _candidate_prefixes() -> list[str]:
    if API_PREFIX not in {"", "auto"}:
        return [API_PREFIX if API_PREFIX.startswith("/") else f"/{API_PREFIX}"]
    # Netlify migration uses /api; the previous Floot build used /_api.
    return ["/api", "/_api"]


def tv_post(path: str, payload: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    global _resolved_api_prefix
    prefixes = [_resolved_api_prefix] if _resolved_api_prefix else _candidate_prefixes()
    last_error: Exception | None = None
    for prefix in prefixes:
        if not prefix:
            continue
        url = f"{TUBEVERSE_BASE_URL}{prefix}{path}"
        headers = dict(TV_HEADERS)
        try:
            if payload is None:
                response = requests.post(url, headers=headers, timeout=timeout)
            else:
                headers["Content-Type"] = "application/json"
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if response.status_code == 404 and _resolved_api_prefix is None:
                continue
            if not response.ok:
                raise RuntimeError(f"TubeVerse {path} failed: HTTP {response.status_code}: {response.text[:1000]}")
            _resolved_api_prefix = prefix
            return _decode_json(response)
        except Exception as exc:  # try legacy prefix only when auto-detecting
            last_error = exc
            if _resolved_api_prefix is not None:
                raise
    raise last_error or RuntimeError(f"Could not resolve TubeVerse API prefix for {path}")


def update_job(job_id: str, status: str, progress: int, *, output_url: str | None = None,
               error_message: str | None = None) -> dict[str, Any]:
    return tv_post("/worker/update", {
        "id": job_id,
        "status": status,
        "progress": max(0, min(100, int(progress))),
        "outputUrl": output_url,
        "errorMessage": error_message,
    })


def heartbeat() -> None:
    try:
        tv_post("/worker/heartbeat", timeout=20)
    except Exception:
        # Older TubeVerse builds update last_seen_at on claim/update and may not
        # expose a dedicated heartbeat endpoint yet.
        pass


def mpt_request(method: str, path: str, *, json_body: dict[str, Any] | None = None,
                stream: bool = False, timeout: int = 60) -> requests.Response:
    url = f"{MPT_BASE_URL}{path}"
    response = requests.request(method, url, headers=MPT_HEADERS, json=json_body,
                                stream=stream, timeout=timeout)
    if not response.ok:
        raise RuntimeError(f"MoneyPrinterTurbo {path} failed: HTTP {response.status_code}: {response.text[:1500]}")
    return response


def mpt_ready() -> bool:
    try:
        # /docs is served by FastAPI even if API auth is configured on v1 routes.
        return requests.get(f"{MPT_BASE_URL}/docs", timeout=3).status_code < 500
    except requests.RequestException:
        return False


def start_moneyprinter_if_needed() -> None:
    global _mpt_process
    if mpt_ready():
        return
    if not MPT_AUTOSTART:
        raise RuntimeError(f"MoneyPrinterTurbo is not reachable at {MPT_BASE_URL}")
    if not MPT_HOME.is_dir():
        raise RuntimeError(
            f"MoneyPrinterTurbo checkout not found at {MPT_HOME}. "
            "Run moneyprinter-worker/install_moneyprinter.sh first."
        )
    uv = shutil.which("uv")
    python = shutil.which("python3") or shutil.which("python") or sys.executable
    if uv:
        cmd = [uv, "run", "uvicorn", "app.asgi:app", "--host", "127.0.0.1", "--port", "8080"]
    else:
        cmd = [python, "-m", "uvicorn", "app.asgi:app", "--host", "127.0.0.1", "--port", "8080"]
    print("Starting MoneyPrinterTurbo API locally...")
    _mpt_process = subprocess.Popen(cmd, cwd=str(MPT_HOME))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if _mpt_process.poll() is not None:
            raise RuntimeError(f"MoneyPrinterTurbo exited during startup with code {_mpt_process.returncode}")
        if mpt_ready():
            print("MoneyPrinterTurbo API is ready.")
            return
        time.sleep(2)
    raise RuntimeError("Timed out waiting for MoneyPrinterTurbo API startup")


def extract_terms(text: str, limit: int = 8) -> list[str]:
    """Cheap local fallback so a supplied script doesn't require an LLM just for stock search terms."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", text.lower())
    stop = {
        "the", "and", "that", "this", "with", "from", "into", "your", "about", "have", "will",
        "would", "there", "their", "they", "them", "then", "than", "when", "where", "what", "which",
        "while", "also", "just", "over", "under", "very", "more", "most", "some", "video", "scene",
        "shot", "camera", "cinematic", "create", "make", "using", "through", "after", "before", "because",
    }
    result: list[str] = []
    for word in words:
        if word in stop or word in result:
            continue
        result.append(word)
        if len(result) >= limit:
            break
    return result or ["technology", "future", "people"]


def subject_from_prompt(prompt: str) -> str:
    clean = " ".join(prompt.split())
    return clean[:180] if clean else "TubeVerse video"


def create_moneyprinter_task(job: dict[str, Any]) -> str:
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        raise RuntimeError("TubeVerse job has an empty prompt")
    payload: dict[str, Any] = {
        "video_subject": subject_from_prompt(prompt),
        "video_script": prompt if MPT_USE_PROMPT_AS_SCRIPT else "",
        "video_terms": extract_terms(prompt),
        "video_aspect": job.get("aspectRatio") or job.get("aspect_ratio") or "16:9",
        "video_count": 1,
        "video_source": MPT_VIDEO_SOURCE,
        "video_clip_duration": 5,
        "video_concat_mode": "random",
        "match_materials_to_script": False,
        "voice_name": MPT_VOICE_NAME,
        "voice_volume": 1.0,
        "voice_rate": 1.0,
        "bgm_type": MPT_BGM_TYPE,
        "bgm_volume": MPT_BGM_VOLUME,
        "subtitle_enabled": True,
        "subtitle_position": "bottom",
        "subtitle_display_mode": "sentence",
        "subtitle_animation": "none",
        "text_fore_color": "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width": 1.5,
        "font_size": 60,
        "n_threads": max(1, min(8, os.cpu_count() or 2)),
        "paragraph_number": 1,
    }
    data = _decode_json(mpt_request("POST", "/api/v1/videos", json_body=payload, timeout=60))
    if int(data.get("status", 0)) != 200:
        raise RuntimeError(f"MoneyPrinterTurbo rejected task: {data}")
    task = data.get("data") or {}
    task_id = task.get("task_id") if isinstance(task, dict) else None
    if not task_id:
        raise RuntimeError(f"MoneyPrinterTurbo did not return task_id: {data}")
    return str(task_id)


def poll_moneyprinter(task_id: str, tv_job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + MPT_TIMEOUT_SECONDS
    last_progress = -1
    while time.monotonic() < deadline:
        data = _decode_json(mpt_request("GET", f"/api/v1/tasks/{task_id}", timeout=30))
        if int(data.get("status", 0)) != 200:
            raise RuntimeError(f"MoneyPrinterTurbo task query failed: {data}")
        task = data.get("data") or {}
        if not isinstance(task, dict):
            raise RuntimeError(f"Unexpected MoneyPrinterTurbo task payload: {task!r}")
        state = int(task.get("state", 4))
        progress = max(0, min(100, int(task.get("progress", 0) or 0)))
        # Reserve 1-5% for TubeVerse claim/setup and 96-100% for upload/finalization.
        tv_progress = 5 + round(progress * 0.90)
        if tv_progress != last_progress and state == 4:
            update_job(tv_job_id, "rendering", tv_progress)
            last_progress = tv_progress
        if state == 1:
            return task
        if state == -1:
            stage = task.get("failed_stage") or "pipeline"
            error = task.get("error") or "MoneyPrinterTurbo task failed"
            raise RuntimeError(f"MoneyPrinterTurbo {stage}: {error}")
        heartbeat()
        time.sleep(POLL_SECONDS)
    raise RuntimeError(f"MoneyPrinterTurbo task {task_id} timed out after {MPT_TIMEOUT_SECONDS}s")


def download_mpt_video(task: dict[str, Any], destination: Path) -> None:
    videos = task.get("videos") or []
    if not isinstance(videos, list) or not videos:
        raise RuntimeError("MoneyPrinterTurbo completed without a video output")
    source = str(videos[0])
    url = source if source.startswith(("http://", "https://")) else urljoin(f"{MPT_BASE_URL}/", source.lstrip("/"))
    with requests.get(url, headers=MPT_HEADERS, stream=True, timeout=1800) as response:
        if not response.ok:
            raise RuntimeError(f"Could not download MoneyPrinterTurbo output: HTTP {response.status_code}")
        with destination.open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    output.write(chunk)
    if destination.stat().st_size <= 0:
        raise RuntimeError("MoneyPrinterTurbo output download was empty")


def upload_output(job_id: str, path: Path) -> str:
    size = path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise RuntimeError(f"Output is {size / (1024*1024):.1f} MB, above TubeVerse worker limit")
    ticket = tv_post("/worker/upload", {
        "id": job_id,
        "contentType": "video/mp4",
        "sizeBytes": size,
    })

    # Preferred contract: presigned object-storage PUT (Floot legacy and compatible Netlify adapters).
    upload_url = ticket.get("uploadUrl") or ticket.get("presignedUrl")
    if upload_url:
        with path.open("rb") as source:
            response = requests.put(str(upload_url), data=source, headers={"Content-Type": "video/mp4"}, timeout=1800)
        if not response.ok:
            raise RuntimeError(f"TubeVerse upload failed: HTTP {response.status_code}: {response.text[:500]}")
        public_url = ticket.get("publicUrl") or ticket.get("url")
        if not public_url:
            raise RuntimeError("TubeVerse upload ticket omitted publicUrl")
        return str(public_url)

    # Portable Netlify contract can return a chunk target when a direct presigned URL is unavailable.
    upload_id = ticket.get("uploadId")
    chunk_size = int(ticket.get("chunkSize") or 4 * 1024 * 1024)
    if upload_id:
        total_chunks = (size + chunk_size - 1) // chunk_size
        with path.open("rb") as source:
            for index in range(total_chunks):
                chunk = source.read(chunk_size)
                prefix = _resolved_api_prefix or _candidate_prefixes()[0]
                url = f"{TUBEVERSE_BASE_URL}{prefix}/worker/upload-chunk?id={job_id}&uploadId={upload_id}&index={index}"
                response = requests.post(url, headers={**TV_HEADERS, "Content-Type": "application/octet-stream"}, data=chunk, timeout=300)
                if not response.ok:
                    raise RuntimeError(f"TubeVerse chunk {index} failed: HTTP {response.status_code}: {response.text[:500]}")
        result = tv_post("/worker/upload-complete", {
            "id": job_id,
            "uploadId": upload_id,
            "totalChunks": total_chunks,
            "sizeBytes": size,
            "contentType": "video/mp4",
        })
        public_url = result.get("publicUrl") or result.get("url")
        if not public_url:
            raise RuntimeError("TubeVerse chunked upload completion omitted publicUrl")
        return str(public_url)

    raise RuntimeError(f"Unsupported TubeVerse upload contract: {ticket}")


def process(job: dict[str, Any]) -> None:
    job_id = str(job.get("id") or "")
    if not job_id:
        raise RuntimeError("Claimed TubeVerse job has no id")
    if str(job.get("model")) != "moneyprinter":
        raise RuntimeError(f"MoneyPrinter worker received unsupported model {job.get('model')!r}")
    if str(job.get("mode") or "text") != "text":
        raise RuntimeError("MoneyPrinter worker currently supports TubeVerse text jobs only")
    print(f"\nClaimed {job_id}: {str(job.get('prompt') or '')[:120]}")
    try:
        update_job(job_id, "rendering", 3)
        start_moneyprinter_if_needed()
        task_id = create_moneyprinter_task(job)
        print(f"MoneyPrinterTurbo task: {task_id}")
        task = poll_moneyprinter(task_id, job_id)
        update_job(job_id, "rendering", 96)
        with tempfile.TemporaryDirectory(prefix="tubeverse-moneyprinter-") as tmp:
            output_path = Path(tmp) / f"{job_id}.mp4"
            download_mpt_video(task, output_path)
            update_job(job_id, "rendering", 98)
            public_url = upload_output(job_id, output_path)
        update_job(job_id, "complete", 100, output_url=public_url)
        print(f"Completed {job_id}: {public_url}")
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        try:
            update_job(job_id, "failed", 100, error_message=message[:1900])
        except Exception:
            traceback.print_exc()


def main() -> None:
    print("TubeVerse MoneyPrinterTurbo Worker")
    print("TubeVerse:", TUBEVERSE_BASE_URL)
    print("MoneyPrinterTurbo:", MPT_BASE_URL)
    print("Worker family: moneyprinter")
    print("Stock/material source:", MPT_VIDEO_SOURCE)
    while True:
        try:
            heartbeat()
            result = tv_post("/worker/claim", timeout=60)
            job = result.get("job")
            if job:
                process(job)
            else:
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("\nWorker stopped.")
            if _mpt_process and _mpt_process.poll() is None:
                _mpt_process.terminate()
            return
        except Exception as exc:
            print(f"Worker loop error: {exc}", file=sys.stderr)
            time.sleep(max(POLL_SECONDS, 10))


if __name__ == "__main__":
    main()
