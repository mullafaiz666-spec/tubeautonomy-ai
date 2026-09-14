#!/usr/bin/env python3
"""TubeAutonomy zero-touch content factory.

Discovers fast-moving YouTube topics, studies transcripts as research signals,
creates a new script/angle with Gemini, enforces an originality gate, and emits
one TubeVerse render job. Source video media is never copied into the render.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph


class FactoryState(TypedDict, total=False):
    niche: str
    region: str
    lookback_hours: int
    top_videos: int
    format: str
    candidates: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    draft: dict[str, Any]
    originality: dict[str, Any]
    originality_feedback: str
    attempt: int
    job_path: str
    metadata_path: str


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def trend_score(views: int, likes: int, comments: int, age_hours: float) -> tuple[float, float, float]:
    age = max(age_hours, 0.5)
    views_per_hour = views / age
    engagement = (likes + comments) / max(views, 1)
    # Velocity dominates. Engagement and freshness break ties without allowing
    # tiny videos with one like to outrank genuinely fast-moving topics.
    freshness = max(0.0, 1.0 - min(age, 96.0) / 96.0)
    score = math.log10(views_per_hour + 1.0) * 12.0 + min(engagement * 100.0, 12.0) + freshness * 5.0
    return round(score, 4), round(views_per_hour, 2), round(engagement, 6)


def scan_trends(state: FactoryState) -> FactoryState:
    from googleapiclient.discovery import build

    api_key = env_required("YOUTUBE_API_KEY")
    youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
    published_after = iso_z(utc_now() - timedelta(hours=state["lookback_hours"]))

    # Search multiple intent variants so one literal query does not dominate.
    niche = state["niche"].strip()
    queries = [niche, f"{niche} news", f"{niche} explained", f"{niche} shorts"]
    ids: list[str] = []
    for query in queries:
        response = youtube.search().list(
            part="snippet",
            q=query,
            type="video",
            order="viewCount",
            publishedAfter=published_after,
            regionCode=state["region"],
            maxResults=25,
            safeSearch="moderate",
        ).execute()
        for item in response.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            if video_id and video_id not in ids:
                ids.append(video_id)

    if not ids:
        raise RuntimeError(f"YouTube trend scan returned no videos for niche={niche!r}")

    candidates: list[dict[str, Any]] = []
    for start in range(0, len(ids), 50):
        response = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(ids[start:start + 50]),
            maxResults=50,
        ).execute()
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            published_at = snippet.get("publishedAt")
            if not published_at:
                continue
            age_hours = max((utc_now() - parse_dt(published_at)).total_seconds() / 3600.0, 0.5)
            views = safe_int(stats.get("viewCount"))
            likes = safe_int(stats.get("likeCount"))
            comments = safe_int(stats.get("commentCount"))
            score, vph, engagement = trend_score(views, likes, comments, age_hours)
            candidates.append({
                "videoId": item["id"],
                "title": snippet.get("title", ""),
                "channelTitle": snippet.get("channelTitle", ""),
                "publishedAt": published_at,
                "views": views,
                "likes": likes,
                "comments": comments,
                "ageHours": round(age_hours, 2),
                "viewsPerHour": vph,
                "engagementRate": engagement,
                "trendScore": score,
                "url": f"https://www.youtube.com/watch?v={item['id']}",
            })

    candidates.sort(key=lambda x: (x["trendScore"], x["viewsPerHour"]), reverse=True)
    state["candidates"] = candidates[: max(state["top_videos"] * 3, 12)]
    return state


def _transcript_text(video_id: str) -> str:
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id)
    text = " ".join(getattr(snippet, "text", "") for snippet in fetched)
    return re.sub(r"\s+", " ", text).strip()


def collect_research(state: FactoryState) -> FactoryState:
    sources: list[dict[str, Any]] = []
    for candidate in state["candidates"]:
        if len(sources) >= state["top_videos"]:
            break
        item = dict(candidate)
        try:
            transcript = _transcript_text(candidate["videoId"])
        except Exception as exc:  # transcript availability varies by video
            transcript = ""
            item["transcriptError"] = type(exc).__name__
        # Enough context for structure/theme analysis, never the entire corpus.
        item["transcript"] = transcript[:14000]
        sources.append(item)

    if not sources:
        raise RuntimeError("no research sources available")
    state["sources"] = sources
    return state


def _json_from_model(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model did not return a JSON object")
    return json.loads(cleaned[start:end + 1])


def write_story(state: FactoryState) -> FactoryState:
    from google import genai

    client = genai.Client(api_key=env_required("GEMINI_API_KEY"))
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    attempt = int(state.get("attempt", 0)) + 1
    state["attempt"] = attempt

    research = []
    for s in state["sources"]:
        research.append({
            "title": s["title"],
            "channel": s["channelTitle"],
            "viewsPerHour": s["viewsPerHour"],
            "trendScore": s["trendScore"],
            "transcriptExcerpt": s.get("transcript", ""),
        })

    feedback = state.get("originality_feedback", "")
    duration_hint = "45-75 seconds" if state["format"] == "shorts" else "4-8 minutes"
    prompt = f"""
You are the Story Writer for an autonomous YouTube studio.
Niche: {state['niche']}
Target format: {state['format']} ({duration_hint})

The JSON below is RESEARCH ONLY. It shows what audiences currently respond to.
Do not copy sentences, distinctive phrasing, jokes, scene order, titles, or a
creator's presentation. Infer the underlying audience interest and create a
new work with a different angle, examples, structure, wording, and visuals.

Research:
{json.dumps(research, ensure_ascii=False)}

Previous originality feedback (if any):
{feedback or 'none'}

Return ONLY valid JSON with this shape:
{{
  "title": "original YouTube title under 90 characters",
  "description": "original description",
  "tags": ["tag1", "tag2"],
  "hook": "first-line hook",
  "angle": "what is genuinely new about this version",
  "script": "complete narration",
  "thumbnailText": "2-5 words",
  "scenes": [
    {{
      "narration": "scene narration excerpt",
      "visualPrompt": "specific original visual to create",
      "keywords": ["visual", "search", "terms"]
    }}
  ]
}}

Rules:
- Add useful information or a fresh explanatory/story angle beyond the sources.
- Never mention that the script was derived from other creators.
- No fabricated quotes or claims presented as facts.
- Avoid repetitive generic filler and mass-produced phrasing.
- The scenes must cover the whole narration in chronological order.
""".strip()

    response = client.models.generate_content(model=model, contents=prompt)
    draft = _json_from_model(response.text or "")
    required = ["title", "description", "tags", "script", "thumbnailText", "scenes"]
    missing = [key for key in required if not draft.get(key)]
    if missing:
        raise RuntimeError(f"writer output missing fields: {missing}")
    if len(str(draft["script"]).split()) < 45:
        raise RuntimeError("writer produced an implausibly short script")
    state["draft"] = draft
    return state


def _chunks(text: str, words: int = 180) -> list[str]:
    tokens = text.split()
    return [" ".join(tokens[i:i + words]) for i in range(0, len(tokens), words) if tokens[i:i + words]]


def _shingles(text: str, n: int = 8) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def originality_gate(state: FactoryState) -> FactoryState:
    from sentence_transformers import SentenceTransformer, util

    script = str(state["draft"]["script"])
    source_texts = [s.get("transcript", "") for s in state["sources"] if s.get("transcript")]
    chunks = [chunk for text in source_texts for chunk in _chunks(text)]

    semantic_max = 0.0
    if chunks:
        model = SentenceTransformer(os.environ.get("ORIGINALITY_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))
        script_embedding = model.encode(script, convert_to_tensor=True, normalize_embeddings=True)
        chunk_embeddings = model.encode(chunks, convert_to_tensor=True, normalize_embeddings=True)
        semantic_max = float(util.cos_sim(script_embedding, chunk_embeddings).max().item())

    script_shingles = _shingles(script)
    source_shingles = set().union(*(_shingles(text) for text in source_texts)) if source_texts else set()
    lexical_overlap = len(script_shingles & source_shingles) / max(len(script_shingles), 1)

    semantic_limit = float(os.environ.get("ORIGINALITY_SEMANTIC_MAX", "0.86"))
    lexical_limit = float(os.environ.get("ORIGINALITY_8GRAM_MAX", "0.05"))
    passed = semantic_max <= semantic_limit and lexical_overlap <= lexical_limit
    report = {
        "passed": passed,
        "semanticMax": round(semantic_max, 4),
        "semanticLimit": semantic_limit,
        "eightGramOverlap": round(lexical_overlap, 4),
        "eightGramLimit": lexical_limit,
        "attempt": state["attempt"],
    }
    state["originality"] = report

    if not passed:
        state["originality_feedback"] = (
            "Rewrite from a substantially different structure and angle. "
            f"Current max semantic similarity={semantic_max:.3f}; "
            f"8-word phrase overlap={lexical_overlap:.3f}. "
            "Do not merely paraphrase the research transcripts."
        )
        if state["attempt"] >= 3:
            raise RuntimeError(f"originality gate failed after 3 attempts: {report}")
    return state


def originality_route(state: FactoryState) -> str:
    return "package" if state["originality"]["passed"] else "rewrite"


def package_render_job(state: FactoryState) -> FactoryState:
    draft = state["draft"]
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^a-z0-9]+", "-", state["niche"].lower()).strip("-")[:32] or "video"
    run_id = f"auto-{stamp}-{slug}"
    render_dir = Path("render-queue")
    audit_dir = Path("autonomy-runs")
    render_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    aspect = "9:16" if state["format"] == "shorts" else "16:9"
    job = {
        "id": run_id,
        "source": "tubeautonomy-autopilot",
        "title": str(draft["title"])[:100],
        "description": str(draft["description"])[:5000],
        "tags": [str(x)[:40] for x in draft.get("tags", [])][:25],
        "thumbnailText": str(draft.get("thumbnailText", ""))[:80],
        "script": str(draft["script"]),
        "aspectRatio": aspect,
        "voiceEngine": "kokoro",
        "mediaUrls": [],
        "scenes": draft.get("scenes", []),
        "autonomy": {
            "niche": state["niche"],
            "region": state["region"],
            "format": state["format"],
            "angle": draft.get("angle", ""),
            "hook": draft.get("hook", ""),
            "originality": state["originality"],
            "generatedAt": iso_z(utc_now()),
            "sourceVideoIds": [s["videoId"] for s in state["sources"]],
        },
    }
    job_path = render_dir / f"{run_id}.json"
    job_path.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")

    audit = {
        "runId": run_id,
        "niche": state["niche"],
        "region": state["region"],
        "generatedAt": iso_z(utc_now()),
        "originality": state["originality"],
        "selectedTrendSources": [
            {k: s[k] for k in ["videoId", "title", "channelTitle", "publishedAt", "views", "viewsPerHour", "trendScore", "url"]}
            for s in state["sources"]
        ],
        "renderJob": str(job_path),
    }
    metadata_path = audit_dir / f"{run_id}.json"
    metadata_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")

    state["job_path"] = str(job_path)
    state["metadata_path"] = str(metadata_path)
    print(json.dumps({"runId": run_id, "jobPath": str(job_path), "metadataPath": str(metadata_path), "originality": state["originality"]}))
    return state


def build_graph():
    graph = StateGraph(FactoryState)
    graph.add_node("scan", scan_trends)
    graph.add_node("research", collect_research)
    graph.add_node("write", write_story)
    graph.add_node("originality", originality_gate)
    graph.add_node("package", package_render_job)
    graph.set_entry_point("scan")
    graph.add_edge("scan", "research")
    graph.add_edge("research", "write")
    graph.add_edge("write", "originality")
    graph.add_conditional_edges("originality", originality_route, {"rewrite": "write", "package": "package"})
    graph.add_edge("package", END)
    return graph.compile()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche", default=os.environ.get("AUTONOMY_NICHE", "artificial intelligence"))
    parser.add_argument("--region", default=os.environ.get("AUTONOMY_REGION", "US"))
    parser.add_argument("--lookback-hours", type=int, default=int(os.environ.get("AUTONOMY_LOOKBACK_HOURS", "72")))
    parser.add_argument("--top-videos", type=int, default=int(os.environ.get("AUTONOMY_TOP_VIDEOS", "6")))
    parser.add_argument("--format", choices=["shorts", "long"], default=os.environ.get("AUTONOMY_FORMAT", "shorts"))
    parser.add_argument("--result-file", default="autonomy-result.json")
    args = parser.parse_args()

    initial: FactoryState = {
        "niche": args.niche,
        "region": args.region.upper(),
        "lookback_hours": max(6, min(args.lookback_hours, 168)),
        "top_videos": max(3, min(args.top_videos, 10)),
        "format": args.format,
        "attempt": 0,
    }
    result = build_graph().invoke(initial)
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
