#!/usr/bin/env python3
"""One-time YouTube OAuth consent bootstrap.

Google requires one interactive owner authorization. This script requests the
scopes TubeAutonomy needs for upload plus read-only channel/analytics access and
returns only the refresh token needed by unattended GitHub Actions runs.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def value(arg: str | None, env_name: str) -> str:
    result = (arg or os.environ.get(env_name, "")).strip()
    if not result:
        raise SystemExit(f"missing {env_name}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", default=None)
    ap.add_argument("--client-secret", default=None)
    ap.add_argument("--result-file", default=None, help="optional secure temporary JSON result")
    ap.add_argument("--no-open-browser", action="store_true")
    args = ap.parse_args()

    client_id = value(args.client_id, "YOUTUBE_CLIENT_ID")
    client_secret = value(args.client_secret, "YOUTUBE_CLIENT_SECRET")

    from google_auth_oauthlib.flow import InstalledAppFlow

    config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(config, scopes=SCOPES)
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        open_browser=not args.no_open_browser,
        authorization_prompt_message="Open this URL to authorize TubeAutonomy:\n{url}\n",
        success_message="TubeAutonomy authorization completed. You can close this browser tab.",
        access_type="offline",
        prompt="consent",
    )
    if not credentials.refresh_token:
        raise SystemExit("Google did not return a refresh token; revoke the old grant and run again with consent")

    result = {
        "refreshToken": credentials.refresh_token,
        "scopes": list(credentials.scopes or SCOPES),
    }
    if args.result_file:
        path = Path(args.result_file)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        print(f"Refresh token written to {path}. Delete this temporary file after storing the GitHub secret.")
    else:
        print(credentials.refresh_token)


if __name__ == "__main__":
    main()
