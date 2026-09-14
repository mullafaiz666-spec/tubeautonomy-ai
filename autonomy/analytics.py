#!/usr/bin/env python3
"""Build compact channel-performance memory from TubeAutonomy publications."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STOP = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "this", "that", "these", "those", "you", "your",
    "how", "why", "what", "when", "from", "into", "about", "new", "video", "shorts",
}


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def now() -> datetime:
    return datetime.now(timezone.utc)


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def score_video(views: int, likes: int, comments: int, age_hours: float) -> float:
    engagement = (likes + comments) / max(views, 1)
    velocity = views / max(age_hours, 1.0)
    return round(math.log10(views + 1) * 3.0 + math.log10(velocity + 1) * 5.0 + min(engagement * 100, 10), 4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", default="publishing-history")
    ap.add_argument("--output", default="learning/channel-performance.json")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("missing YOUTUBE_API_KEY")

    history_dir = Path(args.history_dir)
    histories = []
    if history_dir.exists():
        for path in sorted(history_dir.glob("*.json"), reverse=True)[: max(1, args.limit)]:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("videoId"):
                    histories.append(item)
            except Exception:
                continue

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not histories:
        payload = {"generatedAt": now().isoformat(), "videos": [], "topTerms": [], "message": "No TubeAutonomy publications recorded yet."}
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload))
        return

    from googleapiclient.discovery import build
    youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
    by_id = {str(x["videoId"]): x for x in histories}
    ids = list(by_id)
    videos: list[dict[str, Any]] = []

    for start in range(0, len(ids), 50):
        response = youtube.videos().list(
            part="snippet,statistics,status",
            id=",".join(ids[start:start + 50]),
            maxResults=50,
        ).execute()
        for item in response.get("items", []):
            video_id = item["id"]
            history = by_id.get(video_id, {})
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            uploaded = history.get("uploadedAt") or snippet.get("publishedAt") or now().isoformat()
            try:
                age_hours = max((now() - parse_dt(uploaded)).total_seconds() / 3600.0, 1.0)
            except Exception:
                age_hours = 1.0
            views = safe_int(stats.get("viewCount"))
            likes = safe_int(stats.get("likeCount"))
            comments = safe_int(stats.get("commentCount"))
            videos.append({
                "videoId": video_id,
                "title": snippet.get("title") or history.get("title") or "",
                "uploadedAt": uploaded,
                "privacy": (item.get("status") or {}).get("privacyStatus"),
                "views": views,
                "likes": likes,
                "comments": comments,
                "ageHours": round(age_hours, 2),
                "viewsPerHour": round(views / age_hours, 2),
                "engagementRate": round((likes + comments) / max(views, 1), 6),
                "performanceScore": score_video(views, likes, comments, age_hours),
                "niche": history.get("niche"),
                "angle": history.get("angle"),
                "sourceRunId": history.get("sourceRunId"),
            })

    videos.sort(key=lambda x: x["performanceScore"], reverse=True)
    terms: Counter[str] = Counter()
    for video in videos[:15]:
        weight = max(1, int(round(video["performanceScore"])))
        for token in re.findall(r"[a-z0-9]+", str(video["title"]).lower()):
            if len(token) >= 3 and token not in STOP and not token.isdigit():
                terms[token] += weight

    payload = {
        "generatedAt": now().isoformat().replace("+00:00", "Z"),
        "sampleSize": len(videos),
        "topTerms": [term for term, _ in terms.most_common(20)],
        "videos": videos,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"sampleSize": len(videos), "topTerms": payload["topTerms"][:10]}))


if __name__ == "__main__":
    main()
