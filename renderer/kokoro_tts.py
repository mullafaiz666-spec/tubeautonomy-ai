#!/usr/bin/env python3
"""Render TubeVerse narration locally with Kokoro 82M."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def split_text(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("output")
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--lang", default="a")
    ap.add_argument("--speed", type=float, default=1.0)
    args = ap.parse_args()

    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    text = Path(args.script).read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit("empty script")

    pipeline = KPipeline(lang_code=args.lang)
    rate = 24000
    silence = np.zeros(int(rate * 0.10), dtype=np.float32)
    audio_parts = []
    chunks = split_text(text)
    for chunk in chunks:
        for _gs, _ps, audio in pipeline(chunk, voice=args.voice, speed=args.speed):
            audio_parts.append(np.asarray(audio, dtype=np.float32))
            audio_parts.append(silence)

    if not audio_parts:
        raise SystemExit("Kokoro produced no audio")
    merged = np.concatenate(audio_parts)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, merged, rate)
    print({"engine": "kokoro", "voice": args.voice, "sampleRate": rate, "seconds": len(merged) / rate})


if __name__ == "__main__":
    main()
