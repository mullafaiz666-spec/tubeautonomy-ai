#!/usr/bin/env python3
"""Fetch explicitly supplied, owned/licensed media URLs for a TubeVerse job.

This tool does not discover or scrape media. It only processes URLs deliberately
placed in the job's `mediaUrls` array and is intended for content the operator
owns or is licensed to reuse.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_file")
    ap.add_argument("output_dir")
    args = ap.parse_args()

    job = json.loads(Path(args.job_file).read_text(encoding="utf-8"))
    urls = job.get("mediaUrls") or []
    if not isinstance(urls, list) or len(urls) > 8:
        raise SystemExit("mediaUrls must be an array with at most 8 URLs")
    if not urls:
        print(json.dumps({"downloaded": []}))
        return

    from yt_dlp import YoutubeDL

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    downloaded = []
    opts = {
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(out / "%(autonumber)02d-%(id)s.%(ext)s"),
        "playlist_items": "1",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with YoutubeDL(opts) as ydl:
        for url in urls:
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                raise SystemExit(f"invalid media URL: {url!r}")
            info = ydl.extract_info(url, download=True)
            downloaded.append({"url": url, "title": info.get("title"), "id": info.get("id")})

    (out / "downloads.json").write_text(json.dumps(downloaded, indent=2), encoding="utf-8")
    print(json.dumps({"downloaded": downloaded}))


if __name__ == "__main__":
    main()
