#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from scene_plan import build_plan, keywords as local_keywords

job_path = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)
job = json.loads(job_path.read_text(encoding="utf-8"))

title = str(job.get("title") or "TubeVerse AI").strip()[:120]
script = str(job.get("script") or job.get("prompt") or "").strip()
if len(script) < 20:
    raise SystemExit("job script/prompt must be at least 20 characters")
aspect = str(job.get("aspectRatio") or "9:16")
if aspect not in {"9:16", "16:9", "1:1"}:
    raise SystemExit(f"unsupported aspectRatio: {aspect}")

(out_dir / "title.txt").write_text(title, encoding="utf-8")
(out_dir / "script.txt").write_text(script, encoding="utf-8")


def normalize_ai_scenes(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    result: list[dict] = []
    for idx, item in enumerate(raw[:12], start=1):
        if not isinstance(item, dict):
            continue
        narration = re.sub(r"\s+", " ", str(item.get("narration") or "")).strip()
        visual_prompt = re.sub(r"\s+", " ", str(item.get("visualPrompt") or "")).strip()
        raw_keywords = item.get("keywords") or []
        keys = [str(x).strip().lower() for x in raw_keywords if str(x).strip()][:6] if isinstance(raw_keywords, list) else []
        if not keys:
            keys = local_keywords(visual_prompt or narration)
        if not narration and not visual_prompt:
            continue
        result.append({
            "index": idx,
            "narration": narration or f"Scene {idx}",
            "keywords": keys,
            "visualPrompt": visual_prompt or f"cinematic editorial b-roll illustrating: {narration}",
            "source": "ai-visual-director",
        })
    return result


plan = normalize_ai_scenes(job.get("scenes"))
plan_engine = "tubeautonomy-visual-director" if plan else "tubeverse-local"
if not plan:
    plan = build_plan(script, max_scenes=6)
(out_dir / "scene-plan.json").write_text(
    json.dumps({"version": 1, "engine": plan_engine, "scenes": plan}, indent=2),
    encoding="utf-8",
)
meta = {
    "title": title,
    "aspectRatio": aspect,
    "sceneCount": len(plan),
    "scenePlanEngine": plan_engine,
    "voiceEngine": str(job.get("voiceEngine") or "kokoro"),
    "mediaUrls": job.get("mediaUrls") or [],
    "source": job.get("source") or "manual",
}
(out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

# Deterministic scene-card fallback. These cards guarantee a render even when
# open-license search or a GPU visual worker is unavailable. The scene keywords
# now come from the AI visual director when an autonomous job supplies them.
size = {"9:16": "540x960", "16:9": "960x540", "1:1": "720x720"}[aspect]
font_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
font_regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
colors = ["0x111827", "0x172554", "0x3b0764", "0x042f2e", "0x3f1d0d", "0x27272a"]
scene_files = []


def esc(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
    )


for scene in plan:
    idx = int(scene["index"])
    keyword_line = "  •  ".join(scene.get("keywords") or ["TubeVerse"])
    scene_file = out_dir / f"scene-{idx:02}.mp4"
    scene_files.append(scene_file)
    filter_graph = (
        f"drawtext=fontfile={font_bold}:text='TUBEVERSE AI':fontcolor=white:fontsize=34:"
        "x=(w-text_w)/2:y=h*0.36,"
        f"drawtext=fontfile={font_regular}:text='SCENE {idx:02}':fontcolor=0xa78bfa:fontsize=22:"
        "x=(w-text_w)/2:y=h*0.45,"
        f"drawtext=fontfile={font_regular}:text='{esc(keyword_line[:72])}':fontcolor=0xd1d5db:fontsize=18:"
        "x=(w-text_w)/2:y=h*0.52,"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
        "text='autonomous open video render':fontcolor=0x94a3b8:fontsize=16:"
        "x=(w-text_w)/2:y=h*0.88"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"color=c={colors[(idx - 1) % len(colors)]}:s={size}:r=30:d=12",
            "-vf", filter_graph,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
            str(scene_file),
        ],
        check=True,
    )

concat_file = out_dir / "scenes.txt"
concat_file.write_text(
    "\n".join(f"file '{p.resolve()}'" for p in scene_files) + "\n", encoding="utf-8"
)
bg = out_dir / "background.mp4"
subprocess.run(
    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(bg)],
    check=True,
)

print(json.dumps({
    "title": title,
    "aspectRatio": aspect,
    "background": str(bg),
    "scriptChars": len(script),
    "scenes": len(plan),
    "scenePlanEngine": plan_engine,
}))
