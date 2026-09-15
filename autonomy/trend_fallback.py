#!/usr/bin/env python3
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _published_at(entry: dict[str, Any]) -> tuple[str, float]:
    now = datetime.now(timezone.utc)
    timestamp = entry.get("timestamp") or entry.get("release_timestamp")
    dt: datetime | None = None
    if timestamp:
        try:
            dt = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            dt = None
    if dt is None:
        raw = str(entry.get("upload_date") or "")
        if len(raw) == 8 and raw.isdigit():
            try:
                dt = datetime.strptime(raw, "%Y%m%d").replace(tzinfo=timezone.utc)
            except ValueError:
                dt = None
    if dt is None:
        dt = now
    age_hours = max((now - dt).total_seconds() / 3600.0, 0.5)
    return dt.isoformat().replace("+00:00", "Z"), age_hours


def _score(views: int, likes: int, comments: int, age_hours: float) -> tuple[float, float, float]:
    age = max(age_hours, 0.5)
    views_per_hour = views / age
    engagement = (likes + comments) / max(views, 1)
    freshness = max(0.0, 1.0 - min(age, 96.0) / 96.0)
    score = math.log10(views_per_hour + 1.0) * 12.0 + min(engagement * 100.0, 12.0) + freshness * 5.0
    return round(score, 4), round(views_per_hour, 2), round(engagement, 6)


def scan_trends_with_ytdlp(state: dict[str, Any]) -> dict[str, Any]:
    """Discover recent YouTube videos without a Data API key.

    This uses yt-dlp only for public metadata. It never downloads competitor
    media and feeds only titles/statistics/video IDs to the research stage.
    """
    from yt_dlp import YoutubeDL

    niche = str(state["niche"]).strip()
    queries = [niche, f"{niche} news", f"{niche} explained", f"{niche} shorts"]
    wanted = max(int(state.get("top_videos", 6)) * 3, 12)
    lookback = max(int(state.get("lookback_hours", 72)), 6)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "socket_timeout": 20,
        "noplaylist": True,
        "geo_bypass_country": str(state.get("region") or "US"),
    }

    by_id: dict[str, dict[str, Any]] = {}
    with YoutubeDL(opts) as ydl:
        for query in queries:
            try:
                info = ydl.extract_info(f"ytsearchdate8:{query}", download=False)
            except Exception:
                continue
            for entry in (info or {}).get("entries") or []:
                if not entry or not entry.get("id"):
                    continue
                video_id = str(entry["id"])
                published_at, age_hours = _published_at(entry)
                # Search results occasionally contain older material. Keep a
                # little tolerance because upload dates can be day-granularity.
                if age_hours > lookback * 1.75:
                    continue
                views = _int(entry.get("view_count"))
                likes = _int(entry.get("like_count"))
                comments = _int(entry.get("comment_count"))
                score, vph, engagement = _score(views, likes, comments, age_hours)
                candidate = {
                    "videoId": video_id,
                    "title": str(entry.get("title") or ""),
                    "channelTitle": str(entry.get("channel") or entry.get("uploader") or ""),
                    "publishedAt": published_at,
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "ageHours": round(age_hours, 2),
                    "viewsPerHour": vph,
                    "engagementRate": engagement,
                    "trendScore": score,
                    "url": str(entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"),
                    "discoverySource": "yt-dlp",
                }
                previous = by_id.get(video_id)
                if previous is None or candidate["trendScore"] > previous["trendScore"]:
                    by_id[video_id] = candidate

    candidates = sorted(by_id.values(), key=lambda x: (x["trendScore"], x["viewsPerHour"]), reverse=True)
    if not candidates:
        raise RuntimeError(f"yt-dlp trend fallback returned no usable videos for niche={niche!r}")
    state["candidates"] = candidates[:wanted]
    return state
