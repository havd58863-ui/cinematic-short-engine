#!/usr/bin/env python3
"""Fetch OpenMontage at the exact commit pinned in vendor/openmontage.lock.json."""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCK = ROOT / "vendor" / "openmontage.lock.json"
DEFAULT_DEST = ROOT / "vendor" / "openmontage"


def git(*args: str, cwd: pathlib.Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )


def current_head(dest: pathlib.Path) -> str | None:
    if not (dest / ".git").exists():
        return None
    result = git("rev-parse", "HEAD", cwd=dest, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=pathlib.Path, default=DEFAULT_DEST)
    parser.add_argument("--force", action="store_true", help="replace an existing non-matching checkout")
    args = parser.parse_args()

    if shutil.which("git") is None:
        print("ERROR: git is required", file=sys.stderr)
        return 2

    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    repository = lock["repository"]
    commit = lock["commit"]
    dest = args.dest.resolve()

    head = current_head(dest)
    if head == commit:
        print(f"OpenMontage already pinned at {commit}: {dest}")
        return 0
    if dest.exists() and any(dest.iterdir()):
        if not args.force:
            print(
                f"ERROR: {dest} exists but is not at {commit}. Re-run with --force to replace it.",
                file=sys.stderr,
            )
            return 3
        shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    git("clone", "--filter=blob:none", "--no-checkout", repository, str(dest))
    git("checkout", "--detach", commit, cwd=dest)
    actual = current_head(dest)
    if actual != commit:
        print(f"ERROR: expected {commit}, got {actual}", file=sys.stderr)
        return 4
    print(f"OpenMontage pinned at {commit}: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
