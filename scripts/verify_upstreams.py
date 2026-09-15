#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=45,
        check=False,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="integrations/upstreams.json")
    ap.add_argument("--strict-optional", action="store_true")
    args = ap.parse_args()

    data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    results: list[dict[str, object]] = []
    failures: list[str] = []

    for item in data.get("upstreams", []):
        name = str(item["name"])
        repo = str(item["repo"])
        branch = str(item.get("defaultBranch") or "HEAD")
        required = bool(item.get("required", False))

        proc = run_git("ls-remote", "--exit-code", "--heads", repo, branch)
        branch_ok = proc.returncode == 0 and bool(proc.stdout.strip())

        pinned = item.get("pinnedCommit")
        pinned_ok = None
        if pinned:
            # Check all advertised refs for the pinned SHA. The build itself also
            # validates the checkout when MoneyPrinterTurbo is fetched.
            refs = run_git("ls-remote", repo)
            pinned_ok = refs.returncode == 0 and str(pinned) in refs.stdout

        ok = branch_ok and (pinned_ok is not False)
        results.append(
            {
                "name": name,
                "repo": repo,
                "branch": branch,
                "required": required,
                "reachable": branch_ok,
                "pinnedCommitVisible": pinned_ok,
                "integration": item.get("integration"),
            }
        )

        if not ok and (required or args.strict_optional):
            failures.append(name)

    print(json.dumps({"results": results, "failures": failures}, indent=2))
    if failures:
        print("Required upstream verification failed: " + ", ".join(failures), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
