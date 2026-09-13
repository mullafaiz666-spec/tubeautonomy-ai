#!/usr/bin/env python3
"""Source open-licensed Wikimedia Commons images and turn them into video clips.

The source is zero-key. Every selected item is filtered to common permissive
Creative Commons/public-domain licenses and an attribution manifest is written
beside the generated clips. When Commons has no suitable result for a scene,
TubeVerse copies that scene's deterministic local fallback so scene order is
never broken.
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "TubeVerseAI/0.3 (open-video-renderer; GitHub Actions)"
ALLOWED_MARKERS = (
    "cc by",
    "cc-by",
    "cc0",
    "public domain",
    "public-domain",
)
GENERIC_QUERY_WORDS = {
    "tubeverse", "running", "real", "actual", "test", "proves", "system",
    "created", "free", "public", "showing", "produce", "instead", "only",
}


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


def build_query(scene: dict) -> str:
    raw = [str(x).lower().strip() for x in (scene.get("keywords") or []) if str(x).strip()]
    meaningful = [word for word in raw if word not in GENERIC_QUERY_WORDS]
    chosen = meaningful[:2]
    if "video" not in chosen:
        chosen.append("video")
    if len(chosen) < 3:
        chosen.append("technology")
    return " ".join(chosen[:3])


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
    query_tokens = {token for token in query.lower().split() if len(token) > 2}
    candidates: list[tuple[int, dict]] = []
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
        title = page.get("title") or ""
        title_tokens = set(title.lower().replace("file:", "").replace("_", " ").split())
        overlap = len(query_tokens & title_tokens)
        item = {
            "title": title,
            "downloadUrl": source_url,
            "descriptionUrl": info.get("descriptionurl") or "",
            "license": ext_value(meta, "LicenseShortName") or ext_value(meta, "UsageTerms"),
            "licenseUrl": ext_value(meta, "LicenseUrl"),
            "artist": ext_value(meta, "Artist"),
            "credit": ext_value(meta, "Credit"),
            "attribution": ext_value(meta, "Attribution"),
        }
        candidates.append((overlap, item))
    if not candidates:
        return None
    candidates.sort(key=lambda entry: entry[0], reverse=True)
    return candidates[0][1]


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


def copy_fallback(scene_plan_path: Path, output: Path, index: int) -> bool:
    source = scene_plan_path.parent / f"scene-{index:02}.mp4"
    target = output / f"scene-{index:02}.mp4"
    if not source.is_file():
        return False
    shutil.copy2(source, target)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scene_plan")
    parser.add_argument("meta")
    parser.add_argument("output_dir")
    args = parser.parse_args()

    scene_plan_path = Path(args.scene_plan)
    plan = json.loads(scene_plan_path.read_text(encoding="utf-8"))
    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    aspect = meta.get("aspectRatio", "9:16")
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    attribution: list[dict] = []
    selections: list[dict] = []

    for scene in plan.get("scenes") or []:
        index = int(scene.get("index") or len(selections) + 1)
        query = build_query(scene)
        item = None
        try:
            item = search_one(query)
        except Exception as exc:
            print(json.dumps({"scene": index, "query": query, "warning": f"Commons search failed: {exc}"}))

        if item:
            extension = ".png" if ".png" in item["downloadUrl"].lower() else ".jpg"
            image_path = output / f"scene-{index:02}{extension}"
            clip_path = output / f"scene-{index:02}.mp4"
            try:
                download(item["downloadUrl"], image_path)
                render_clip(image_path, clip_path, aspect)
                item.update({"scene": index, "query": query, "localClip": clip_path.name})
                attribution.append(item)
                selections.append({"scene": index, "source": "wikimedia-commons", "query": query, "title": item["title"]})
                print(json.dumps({"scene": index, "query": query, "selected": item["title"], "license": item["license"]}))
                continue
            except Exception as exc:
                print(json.dumps({"scene": index, "query": query, "warning": f"Commons render failed: {exc}"}))
                image_path.unlink(missing_ok=True)
                clip_path.unlink(missing_ok=True)
        else:
            print(json.dumps({"scene": index, "query": query, "warning": "no permitted Commons image"}))

        if copy_fallback(scene_plan_path, output, index):
            selections.append({"scene": index, "source": "tubeverse-fallback", "query": query})
            print(json.dumps({"scene": index, "fallback": True}))

    (output / "attribution.json").write_text(
        json.dumps(attribution, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output / "selection-manifest.json").write_text(
        json.dumps(selections, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({
        "sceneClips": len(list(output.glob('scene-*.mp4'))),
        "commonsClips": len(attribution),
        "fallbackClips": sum(1 for item in selections if item.get('source') == 'tubeverse-fallback'),
        "attribution": str(output / 'attribution.json'),
    }))


if __name__ == "__main__":
    main()
