#!/usr/bin/env python3
"""Launch the TubeAutonomy graph with compact channel-performance memory."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pipeline


def memory_context(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        return "No prior channel-performance memory is available yet."
    try:
        memory = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return "Prior channel-performance memory could not be parsed."

    videos = memory.get("videos") or []
    compact = []
    for video in videos[:8]:
        compact.append({
            "title": video.get("title"),
            "performanceScore": video.get("performanceScore"),
            "viewsPerHour": video.get("viewsPerHour"),
            "engagementRate": video.get("engagementRate"),
            "angle": video.get("angle"),
        })
    return (
        "CHANNEL PERFORMANCE MEMORY (our own prior uploads, not competitor research):\n"
        + json.dumps({"topTerms": (memory.get("topTerms") or [])[:12], "bestRecentUploads": compact}, ensure_ascii=False)
        + "\nUse this only to learn audience preferences. Do not repeat the same title, angle, hook, or story."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", default=os.environ.get("AUTONOMY_NICHE", "artificial intelligence"))
    ap.add_argument("--region", default=os.environ.get("AUTONOMY_REGION", "US"))
    ap.add_argument("--lookback-hours", type=int, default=int(os.environ.get("AUTONOMY_LOOKBACK_HOURS", "72")))
    ap.add_argument("--top-videos", type=int, default=int(os.environ.get("AUTONOMY_TOP_VIDEOS", "6")))
    ap.add_argument("--format", choices=["shorts", "long"], default=os.environ.get("AUTONOMY_FORMAT", "shorts"))
    ap.add_argument("--memory", default="learning/channel-performance.json")
    ap.add_argument("--result-file", default="autonomy-result.json")
    args = ap.parse_args()

    initial: pipeline.FactoryState = {
        "niche": args.niche,
        "region": args.region.upper(),
        "lookback_hours": max(6, min(args.lookback_hours, 168)),
        "top_videos": max(3, min(args.top_videos, 10)),
        "format": args.format,
        "attempt": 0,
        # pipeline.write_story already gives this field to Gemini. Supplying our
        # own historical performance here makes the first draft channel-aware;
        # any later originality failure replaces it with stricter rewrite advice.
        "originality_feedback": memory_context(args.memory),
    }
    result = pipeline.build_graph().invoke(initial)
    summary = {
        "jobPath": result["job_path"],
        "metadataPath": result["metadata_path"],
        "title": result["draft"]["title"],
        "originality": result["originality"],
    }
    Path(args.result_file).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
