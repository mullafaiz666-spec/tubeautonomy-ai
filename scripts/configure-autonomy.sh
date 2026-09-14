#!/usr/bin/env bash
set -euo pipefail

REPO="mullafaiz666-spec/tubeautonomy-ai"
BRANCH="tubeverse-actions"

command -v gh >/dev/null || { echo "GitHub CLI (gh) is required."; exit 2; }
command -v python >/dev/null || { echo "Python 3 is required."; exit 2; }
gh auth status >/dev/null || { echo "Run: gh auth login"; exit 2; }

echo "TubeAutonomy one-time secure setup"
echo "Secrets are sent directly to GitHub and are not written to this repository."

read -rsp "YouTube Data API key: " YOUTUBE_API_KEY; echo
read -rsp "Gemini API key: " GEMINI_API_KEY; echo
read -rsp "Google OAuth client ID: " YOUTUBE_CLIENT_ID; echo
read -rsp "Google OAuth client secret: " YOUTUBE_CLIENT_SECRET; echo

for value_name in YOUTUBE_API_KEY GEMINI_API_KEY YOUTUBE_CLIENT_ID YOUTUBE_CLIENT_SECRET; do
  if [ -z "${!value_name}" ]; then echo "$value_name cannot be empty"; exit 2; fi
done

echo "Installing the one-time OAuth helper..."
python -m pip install -q 'google-auth>=2.40' 'google-auth-oauthlib>=1.2'

TMP_AUTH="$(mktemp)"
trap 'rm -f "$TMP_AUTH"' EXIT
export YOUTUBE_CLIENT_ID YOUTUBE_CLIENT_SECRET
python publisher/oauth_bootstrap.py --result-file "$TMP_AUTH"
YOUTUBE_REFRESH_TOKEN="$(python - "$TMP_AUTH" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['refreshToken'])
PY
)"
test -n "$YOUTUBE_REFRESH_TOKEN"

echo "Saving encrypted repository secrets..."
printf '%s' "$YOUTUBE_API_KEY" | gh secret set YOUTUBE_API_KEY --repo "$REPO"
printf '%s' "$GEMINI_API_KEY" | gh secret set GEMINI_API_KEY --repo "$REPO"
printf '%s' "$YOUTUBE_CLIENT_ID" | gh secret set YOUTUBE_CLIENT_ID --repo "$REPO"
printf '%s' "$YOUTUBE_CLIENT_SECRET" | gh secret set YOUTUBE_CLIENT_SECRET --repo "$REPO"
printf '%s' "$YOUTUBE_REFRESH_TOKEN" | gh secret set YOUTUBE_REFRESH_TOKEN --repo "$REPO"

read -rp "Channel niche [artificial intelligence]: " AUTONOMY_NICHE
AUTONOMY_NICHE="${AUTONOMY_NICHE:-artificial intelligence}"
read -rp "YouTube region code [IN]: " AUTONOMY_REGION
AUTONOMY_REGION="${AUTONOMY_REGION:-IN}"
read -rp "Format shorts/long [shorts]: " AUTONOMY_FORMAT
AUTONOMY_FORMAT="${AUTONOMY_FORMAT:-shorts}"
case "$AUTONOMY_FORMAT" in shorts|long) ;; *) echo "Format must be shorts or long"; exit 2;; esac
read -rp "Publishing privacy private/unlisted/public [public]: " YOUTUBE_PRIVACY
YOUTUBE_PRIVACY="${YOUTUBE_PRIVACY:-public}"
case "$YOUTUBE_PRIVACY" in private|unlisted|public) ;; *) echo "Invalid privacy"; exit 2;; esac

gh variable set AUTONOMY_NICHE --repo "$REPO" --body "$AUTONOMY_NICHE"
gh variable set AUTONOMY_REGION --repo "$REPO" --body "$AUTONOMY_REGION"
gh variable set AUTONOMY_FORMAT --repo "$REPO" --body "$AUTONOMY_FORMAT"
gh variable set YOUTUBE_PRIVACY --repo "$REPO" --body "$YOUTUBE_PRIVACY"

echo "Credentials configured. Starting the first autonomous content run..."
gh workflow run autonomous-content-factory.yml \
  --repo "$REPO" \
  --ref "$BRANCH" \
  -f niche="$AUTONOMY_NICHE" \
  -f region="$AUTONOMY_REGION" \
  -f format="$AUTONOMY_FORMAT"

echo "Started. From now on the scheduled trend → write → render → QA → publish → learn loop runs without per-video approval."
