#!/usr/bin/env python3
"""Source open-licensed Wikimedia Commons images and turn them into video clips.

The source is zero-key. Every selected item is filtered to common permissive
Creative Commons/public-domain licenses and an attribution manifest is written
beside the generated clips. Network/search failure is intentionally non-fatal;
the workflow can always use TubeVerse's deterministic scene-card fallback.
"""
from __future__ import annotations

import argparse
import html
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "TubeVerseAI/0.2 (open-video-renderer; GitHub Actions)"
ALLOWED_MARKERS = (
    "cc by",
    "cc-by",
    "cc0",
    "public domain",
    "public-domain",
)


def clean(value: str | None) -> str:
    if not value:
        return ""
    return html.unescape(value).replace("<br />", " ").replace("<br>", " ").strip()


def ext_value(meta: dict, key: str) -> str:
    item = meta.get(key) or {}
    return clean(item.get("value") if isinstance(item, dict) else str(item))


def allowed_license(meta: dict) -> bool:
    license_name = (ext_value(meta, "LicenseShortName") or ext_value(meta, "UsageTerms")).lower()
    return any(marker in license_name for marker in ALLOWED_MARKERS)


def search_one(query: str) -> dict | None:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": "12",
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": "1400",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.load(response)
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        info_list = page.get("imageinfo") or []
        if not info_list:
            continue
        info = info_list[0]
        mime = (info.get("mime") or "").lower()
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            continue
        meta = info.get("extmetadata") or {}
        if not allowed_license(meta):
            continue
        source_url = info.get("thumburl") or info.get("url")
        if not source_url:
            continue
        return {
            "title": page.get("title") or "",
            "downloadUrl": source_url,
            "descriptionUrl": info.get("descriptionurl") or "",
            "license": ext_value(meta, "LicenseShortName") or ext_value(meta, "UsageTerms"),
            "licenseUrl": ext_value(meta, "LicenseUrl"),
            "artist": ext_value(meta, "Artist"),
            "credit": ext_value(meta, "Credit"),
            "attribution": ext_value(meta, "Attribution"),
        }
    return None


def download(url: str, output: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as response:
        output.write_bytes(response.read())


def render_clip(image: Path, clip: Path, aspect: str, seconds: int = 9) -> None:
    width, height = {
        "9:16": (540, 960),
        "16:9": (960, 540),
        "1:1": (720, 720),
    }[aspect]
    fg_w = int(width * 0.92)
    fg_h = int(height * 0.82)
    filters = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma=28[bg2];"
        f"[fg]scale={fg_w}:{fg_h}:force_original_aspect_ratio=decrease[fg2];"
        f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.10:t=fill,format=yuv420p[v]"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-i", str(image),
            "-filter_complex", filters,
            "-map", "[v]", "-t", str(seconds), "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
            str(clip),
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scene_plan")
    parser.add_argument("meta")
    parser.add_argument("output_dir")
    args = parser.parse_args()

    plan = json.loads(Path(args.scene_plan).read_text(encoding="utf-8"))
    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    aspect = meta.get("aspectRatio", "9:16")
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    attribution: list[dict] = []

    for scene in plan.get("scenes") or []:
        index = int(scene.get("index") or len(attribution) + 1)
        words = [str(x) for x in (scene.get("keywords") or []) if str(x).strip()]
        query = " ".join(words[:3]).strip()
        if not query:
            continue
        try:
            item = search_one(query)
        except Exception as exc:
            print(json.dumps({"scene": index, "query": query, "warning": f"Commons search failed: {exc}"}))
            continue
        if not item:
            print(json.dumps({"scene": index, "query": query, "warning": "no permitted Commons image"}))
            continue
        extension = ".png" if ".png" in item["downloadUrl"].lower() else ".jpg"
        image_path = output / f"scene-{index:02}{extension}"
        clip_path = output / f"scene-{index:02}.mp4"
        try:
            download(item["downloadUrl"], image_path)
            render_clip(image_path, clip_path, aspect)
        except Exception as exc:
            print(json.dumps({"scene": index, "query": query, "warning": f"Commons render failed: {exc}"}))
            image_path.unlink(missing_ok=True)
            clip_path.unlink(missing_ok=True)
            continue
        item.update({"scene": index, "query": query, "localClip": clip_path.name})
        attribution.append(item)
        print(json.dumps({"scene": index, "query": query, "selected": item["title"], "license": item["license"]}))

    manifest = output / "attribution.json"
    manifest.write_text(json.dumps(attribution, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"commonsClips": len(attribution), "attribution": str(manifest)}))


if __name__ == "__main__":
    main()
