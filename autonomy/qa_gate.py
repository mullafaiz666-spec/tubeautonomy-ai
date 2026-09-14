#!/usr/bin/env python3
"""Machine gate for unattended publishing.

Autonomous jobs fail closed: a video is not eligible for automatic upload
unless the rendered speech substantially matches the intended script and the
media probe is sane. Manual/demo jobs are explicitly marked skipped so the
regular renderer remains usable without creating an autonomous publish signal.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def write_report(path: str, payload: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_json")
    ap.add_argument("qa_json")
    ap.add_argument("ffprobe_json")
    ap.add_argument("--report", default="output/autonomy-qa.json")
    args = ap.parse_args()

    job = json.loads(Path(args.job_json).read_text(encoding="utf-8"))

    # Manual/demo renders must continue to work, but they must never be mistaken
    # for machine-approved autonomous uploads by the downstream publisher.
    if job.get("source") != "tubeautonomy-autopilot":
        write_report(args.report, {
            "passed": False,
            "skipped": True,
            "eligibleForAutoPublish": False,
            "reason": "job is not a tubeautonomy-autopilot job",
            "source": job.get("source") or "manual",
        })
        return

    qa = json.loads(Path(args.qa_json).read_text(encoding="utf-8"))
    probe = json.loads(Path(args.ffprobe_json).read_text(encoding="utf-8"))

    script = words(str(job.get("script") or ""))
    heard = words(str(qa.get("text") or ""))
    if not script or not heard:
        raise SystemExit("QA failed: missing intended or transcribed speech")

    script_set = set(script)
    heard_set = set(heard)
    vocabulary_recall = len(script_set & heard_set) / max(len(script_set), 1)
    length_ratio = len(heard) / max(len(script), 1)

    fmt = probe.get("format", {})
    duration = float(fmt.get("duration") or 0)
    size = int(fmt.get("size") or 0)
    title = str(job.get("title") or "")
    originality = (job.get("autonomy") or {}).get("originality") or {}

    checks = {
        "originalityPassed": bool(originality.get("passed", False)),
        "speechVocabularyRecall": round(vocabulary_recall, 4),
        "speechLengthRatio": round(length_ratio, 4),
        "durationSeconds": round(duration, 3),
        "fileSize": size,
        "titleLength": len(title),
        "wordCount": int(qa.get("wordCount") or 0),
    }

    failures = []
    if not checks["originalityPassed"]:
        failures.append("originality gate not passed")
    if vocabulary_recall < 0.52:
        failures.append(f"speech/script vocabulary recall too low: {vocabulary_recall:.3f}")
    if not 0.55 <= length_ratio <= 1.45:
        failures.append(f"speech/script length ratio abnormal: {length_ratio:.3f}")
    if duration < 5 or duration > 600:
        failures.append(f"duration out of policy: {duration:.2f}s")
    if size < 50_000:
        failures.append(f"video file too small: {size}")
    if not 5 <= len(title) <= 100:
        failures.append(f"invalid title length: {len(title)}")
    if checks["wordCount"] < 20:
        failures.append(f"too few transcribed words: {checks['wordCount']}")

    report = {
        "passed": not failures,
        "skipped": False,
        "eligibleForAutoPublish": not failures,
        "checks": checks,
        "failures": failures,
    }
    write_report(args.report, report)
    if failures:
        raise SystemExit("machine publish gate failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
