#!/usr/bin/env bash
set -euo pipefail

MPT_REPO="https://github.com/harry0703/MoneyPrinterTurbo.git"
MPT_COMMIT="79d7d122ae09ad9e294afff787a473401026f681"
TARGET="${MONEYPRINTER_HOME:-$PWD/MoneyPrinterTurbo}"

command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "Python 3.11+ is required" >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo "FFmpeg is required" >&2; exit 1; }

if [ ! -d "$TARGET/.git" ]; then
  git clone "$MPT_REPO" "$TARGET"
fi

git -C "$TARGET" fetch --depth 1 origin "$MPT_COMMIT"
git -C "$TARGET" checkout --detach "$MPT_COMMIT"

if ! command -v uv >/dev/null; then
  python3 -m pip install --user uv
  export PATH="$HOME/.local/bin:$PATH"
fi

(
  cd "$TARGET"
  uv sync --frozen
  if [ ! -f config.toml ]; then
    cp config.example.toml config.toml
  fi
)

echo "MoneyPrinterTurbo pinned at $MPT_COMMIT"
echo "Edit $TARGET/config.toml only for optional provider keys/settings."
echo "Keep the API bound to localhost; TubeVerse worker talks to it locally."
