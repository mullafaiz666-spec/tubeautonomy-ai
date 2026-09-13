#!/usr/bin/env python3
"""Transcribe a rendered MP4 with faster-whisper and fail on silent/broken output."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("output_json")
    ap.add_argument("--srt", default=None)
    ap.add_argument("--model", default="tiny.en")
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(args.video, beam_size=1, vad_filter=True)
    segments = list(segments_iter)
    text = " ".join(s.text.strip() for s in segments if s.text.strip()).strip()
    payload = {
        "engine": "faster-whisper",
        "model": args.model,
        "language": info.language,
        "languageProbability": info.language_probability,
        "text": text,
        "wordCount": len(text.split()),
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments
        ],
    }
    Path(args.output_json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.srt:
        lines = []
        for i, s in enumerate(segments, 1):
            if not s.text.strip():
                continue
            lines += [str(i), f"{srt_time(s.start)} --> {srt_time(s.end)}", s.text.strip(), ""]
        Path(args.srt).write_text("\n".join(lines), encoding="utf-8")

    if payload["wordCount"] < 3:
        raise SystemExit(f"render QA failed: only {payload['wordCount']} transcribed words")
    print(json.dumps({"wordCount": payload["wordCount"], "language": payload["language"]}))


if __name__ == "__main__":
    main()
