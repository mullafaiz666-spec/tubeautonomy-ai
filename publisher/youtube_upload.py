#!/usr/bin/env python3
"""Upload a machine-verified TubeVerse MP4 to YouTube.

Secrets are read only from environment variables and are never stored in the
repository. Uploading requires --confirm-upload so callers must explicitly
acknowledge that verification gates have passed. Privacy defaults to private.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing required secret environment variable: {name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--category-id", default="28")
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    parser.add_argument("--thumbnail", default=None)
    parser.add_argument("--result-json", default=None)
    parser.add_argument("--confirm-upload", action="store_true")
    args = parser.parse_args()

    if not args.confirm_upload:
        raise SystemExit("refusing upload: --confirm-upload is required after verification")
    video = Path(args.video)
    if not video.is_file() or video.stat().st_size < 10_000:
        raise SystemExit(f"invalid video file: {video}")

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    credentials = Credentials(
        token=None,
        refresh_token=env_required("YOUTUBE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=env_required("YOUTUBE_CLIENT_ID"),
        client_secret=env_required("YOUTUBE_CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()][:30]
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": args.title[:100],
                "description": args.description[:5000],
                "tags": tags,
                "categoryId": args.category_id,
            },
            "status": {"privacyStatus": args.privacy, "selfDeclaredMadeForKids": False},
        },
        media_body=MediaFileUpload(str(video), chunksize=-1, resumable=True, mimetype="video/mp4"),
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"upload {int(status.progress() * 100)}%")
    video_id = response["id"]

    if args.thumbnail:
        thumb = Path(args.thumbnail)
        if not thumb.is_file():
            raise SystemExit(f"thumbnail not found: {thumb}")
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg"),
        ).execute()

    result = {
        "videoId": video_id,
        "privacy": args.privacy,
        "url": f"https://youtu.be/{video_id}",
        "title": args.title[:100],
        "publishedBy": "tubeautonomy-autopilot",
        "uploadedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if args.result_json:
        out = Path(args.result_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
