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


def _published_at(entry: dict[str, Any]) -> tuple[str, float] | None:
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
        return None
    age_hours = max((now - dt).total_seconds() / 3600.0, 0.5)
    return dt.isoformat().replace("+00:00", "Z"), age_hours


def _flat_score(*, views: int, age_hours: float | None, rank: int, result_count: int, query_hits: int) -> tuple[float, float, float]:
    """Rank flat YouTube search results without opening individual video pages."""
    relevance = max(result_count - rank + 1, 1) / max(result_count, 1)
    popularity = math.log10(max(views, 0) + 1.0)
    repeat_signal = min(max(query_hits, 1), 5) * 3.0
    freshness = 0.0
    views_per_hour = 0.0
    if age_hours is not None:
        age = max(age_hours, 0.5)
        views_per_hour = views / age
        freshness = max(0.0, 1.0 - min(age, 168.0) / 168.0) * 5.0
    # Search rank + repeated appearance are the fallback signal when flat search
    # omits an exact upload timestamp. View count is useful but bounded by log.
    score = relevance * 8.0 + popularity * 5.0 + repeat_signal + freshness
    return round(score, 4), round(views_per_hour, 2), round(relevance, 4)


def scan_trends_with_ytdlp(state: dict[str, Any]) -> dict[str, Any]:
    """Discover YouTube trend candidates with zero API keys.

    GitHub shared runner IPs are often challenged if yt-dlp opens every video
    watch page. `extract_flat` deliberately avoids those per-video requests and
    uses only YouTube search-result metadata. The same public video media is
    never downloaded. We aggregate multiple fresh-intent searches, reward items
    that recur across queries, and use view/date metadata when it is available.
    """
    from yt_dlp import YoutubeDL

    niche = str(state["niche"]).strip()
    queries = [
        niche,
        f"{niche} latest",
        f"{niche} today",
        f"{niche} news",
        f"{niche} explained",
        f"{niche} shorts",
    ]
    wanted = max(int(state.get("top_videos", 6)) * 3, 12)
    lookback = max(int(state.get("lookback_hours", 72)), 6)
    results_per_query = max(12, min(wanted, 20))

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "extract_flat": True,
        "lazy_playlist": False,
        "socket_timeout": 25,
        "geo_bypass_country": str(state.get("region") or "US"),
    }

    by_id: dict[str, dict[str, Any]] = {}
    with YoutubeDL(opts) as ydl:
        for query in queries:
            try:
                info = ydl.extract_info(f"ytsearch{results_per_query}:{query}", download=False)
            except Exception as exc:
                print(f"yt-dlp flat search failed for {query!r}: {type(exc).__name__}: {exc}")
                continue
            entries = [entry for entry in ((info or {}).get("entries") or []) if entry and entry.get("id")]
            for rank, entry in enumerate(entries, start=1):
                video_id = str(entry["id"])
                publication = _published_at(entry)
                published_at: str | None = None
                age_hours: float | None = None
                if publication is not None:
                    published_at, age_hours = publication
                    # If YouTube gave us a real date, enforce the requested
                    # freshness window with small tolerance for day granularity.
                    if age_hours > lookback * 1.75:
                        continue

                views = _int(entry.get("view_count"))
                likes = _int(entry.get("like_count"))
                comments = _int(entry.get("comment_count"))
                previous = by_id.get(video_id)
                query_hits = int((previous or {}).get("queryHits") or 0) + 1
                score, vph, search_relevance = _flat_score(
                    views=views,
                    age_hours=age_hours,
                    rank=rank,
                    result_count=max(len(entries), 1),
                    query_hits=query_hits,
                )
                candidate = {
                    "videoId": video_id,
                    "title": str(entry.get("title") or ""),
                    "channelTitle": str(entry.get("channel") or entry.get("uploader") or ""),
                    "publishedAt": published_at,
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "ageHours": round(age_hours, 2) if age_hours is not None else None,
                    "viewsPerHour": vph,
                    "engagementRate": 0.0,
                    "trendScore": score,
                    "searchRelevance": search_relevance,
                    "queryHits": query_hits,
                    "url": str(entry.get("url") or entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"),
                    "discoverySource": "yt-dlp-flat-search",
                }
                # Preserve the best populated title/channel across duplicate hits.
                if previous:
                    if not candidate["title"]:
                        candidate["title"] = previous.get("title", "")
                    if not candidate["channelTitle"]:
                        candidate["channelTitle"] = previous.get("channelTitle", "")
                    candidate["views"] = max(views, _int(previous.get("views")))
                by_id[video_id] = candidate

    candidates = sorted(
        by_id.values(),
        key=lambda x: (x["queryHits"], x["trendScore"], x["views"]),
        reverse=True,
    )
    if not candidates:
        raise RuntimeError(f"yt-dlp flat trend fallback returned no usable search results for niche={niche!r}")
    state["candidates"] = candidates[:wanted]
    print(f"yt-dlp flat trend fallback selected {len(state['candidates'])} candidates without watch-page requests")
    return state
