#!/usr/bin/env python3
"""Zero-key scene planner for TubeVerse.

Produces a ShortGPT-compatible-ish scene manifest from a prepared script.  This
local planner is intentionally deterministic so GitHub Actions can render even
when no LLM/API key is configured.  A future ShortGPT/Gemini adapter can replace
this planner without changing the manifest consumed by the renderer.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

STOP = {
    "a","an","and","are","as","at","be","but","by","for","from","has","have","he","her","his",
    "i","in","is","it","its","of","on","or","our","she","that","the","their","them","they","this",
    "to","was","we","were","will","with","you","your","into","than","then","can","could","should"
}


def sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [re.sub(r"\s+", " ", x).strip() for x in chunks if x.strip()]


def keywords(text: str, limit: int = 5) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", text.lower())
    counts: dict[str, int] = {}
    order: list[str] = []
    for word in words:
        if word in STOP:
            continue
        if word not in counts:
            order.append(word)
            counts[word] = 0
        counts[word] += 1
    order.sort(key=lambda w: (-counts[w], order.index(w)))
    return order[:limit]


def build_plan(script: str, max_scenes: int) -> list[dict]:
    parts = sentences(script)
    if not parts:
        raise ValueError("script contains no usable sentences")
    # Keep output compact for Shorts; fold overflow into the last scene.
    if len(parts) > max_scenes:
        head = parts[: max_scenes - 1]
        head.append(" ".join(parts[max_scenes - 1 :]))
        parts = head
    result = []
    for idx, text in enumerate(parts, start=1):
        result.append({
            "index": idx,
            "narration": text,
            "keywords": keywords(text),
            "visualPrompt": f"cinematic editorial b-roll illustrating: {text}",
        })
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("output")
    ap.add_argument("--max-scenes", type=int, default=6)
    args = ap.parse_args()
    script = Path(args.script).read_text(encoding="utf-8")
    plan = build_plan(script, max(1, min(args.max_scenes, 12)))
    payload = {"version": 1, "engine": "tubeverse-local", "scenes": plan}
    Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"scenes": len(plan), "output": args.output}))


if __name__ == "__main__":
    main()
