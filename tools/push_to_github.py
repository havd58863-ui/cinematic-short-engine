#!/usr/bin/env python3
"""Push this project directory to a GitHub repository through the Git database API.

Useful as a one-time bootstrap when a remote GitHub integration cannot see an empty
or private repository. Requires GITHUB_TOKEN from the environment with Contents:
Read and write permission for the target repository. The token is never printed,
embedded in source, or written to disk.

This helper adds/updates project files without deleting unrelated remote files.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_ROOT = "https://api.github.com"
EXCLUDED_DIRS = {".git", ".pytest_cache", "__pycache__", ".venv", "venv", "jobs", "model_cache", "outputs", "huggingface", "dist", "build"}
EXCLUDED_NAMES = {".env", "GITHUB_TOKEN", "secrets.json"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".mp4", ".mov", ".mkv", ".wav", ".mp3", ".flac", ".png", ".jpg", ".jpeg", ".safetensors", ".ckpt", ".bin", ".zip"}


class GitHubAPIError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str, owner_repo: str):
        pieces = owner_repo.strip().split("/", 1)
        if len(pieces) != 2 or not all(pieces):
            raise ValueError("Repository must use owner/name format.")
        self.owner_repo = "/".join(pieces)
        self.base = f"{API_ROOT}/repos/{self.owner_repo}"
        self.token = token

    def request(self, method: str, endpoint: str, body: dict[str, Any] | None = None, allow_404: bool = False) -> Any:
        url = endpoint if endpoint.startswith("https://") else self.base + endpoint
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cinematic-short-engine-bootstrap",
            "Content-Type": "application/json; charset=utf-8",
        })
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            if allow_404 and exc.code == 404:
                return None
            # Never echo request headers or token.
            raise GitHubAPIError(f"GitHub API {method} {endpoint} returned HTTP {exc.code}: {text[:1200]}") from None
        except urllib.error.URLError as exc:
            raise GitHubAPIError(f"Network error while calling GitHub API: {exc.reason}") from None


def collect_project_files(root: Path) -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if path.name in EXCLUDED_NAMES or (path.name.startswith(".env.") and path.name != ".env.example") or path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        if path.name.endswith(".egg-info"):
            continue
        # Text and notebook files only; this project does not commit generated media.
        try:
            raw = path.read_bytes()
            raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            print(f"Skipping non-UTF-8 file: {rel}")
            continue
        files.append((rel.as_posix(), raw))
    # Put README first in sorted display; the Git tree itself is path ordered anyway.
    files.sort(key=lambda item: (item[0] != "README.md", item[0]))
    if not files:
        raise GitHubAPIError(f"No source files were found under {root}.")
    return files


def push_project(root: Path, owner_repo: str, token: str, branch_override: str | None = None) -> dict[str, Any]:
    client = GitHubClient(token, owner_repo)
    repo = client.request("GET", "")
    if repo.get("full_name", "").lower() != owner_repo.lower():
        raise GitHubAPIError("GitHub returned a different repository than requested; stopped for safety.")
    branch = branch_override or repo.get("default_branch") or "main"
    ref = client.request("GET", f"/git/ref/heads/{urllib.parse.quote(branch, safe='')}", allow_404=True)
    parent_sha: str | None = ref.get("object", {}).get("sha") if ref else None
    base_tree_sha = None
    if parent_sha:
        parent = client.request("GET", f"/git/commits/{parent_sha}")
        base_tree_sha = parent.get("tree", {}).get("sha")

    files = collect_project_files(root)
    tree_items = []
    for idx, (rel, raw) in enumerate(files, start=1):
        blob = client.request("POST", "/git/blobs", {"content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"})
        tree_items.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"Prepared {idx}/{len(files)}: {rel}")
        # Gentle pacing avoids bursts if many files are added from a mobile session.
        time.sleep(0.05)

    tree_payload: dict[str, Any] = {"tree": tree_items}
    if base_tree_sha:
        tree_payload["base_tree"] = base_tree_sha
    new_tree = client.request("POST", "/git/trees", tree_payload)
    commit_payload: dict[str, Any] = {"message": "Build open-source TikTok AI Director implementation", "tree": new_tree["sha"], "parents": [parent_sha] if parent_sha else []}
    commit = client.request("POST", "/git/commits", commit_payload)
    commit_sha = commit["sha"]
    if ref:
        encoded_branch = urllib.parse.quote(branch, safe="")
        client.request("PATCH", f"/git/refs/heads/{encoded_branch}", {"sha": commit_sha, "force": False})
    else:
        client.request("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": commit_sha})
    return {"repository": repo.get("html_url", f"https://github.com/{owner_repo}"), "branch": branch, "commit": commit_sha, "files": len(files), "commit_url": commit.get("html_url")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Project root directory; defaults to current directory")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "havd58863-ui/cinematic-short-engine"), help="GitHub owner/repository")
    parser.add_argument("--branch", default=None, help="Override the repository default branch")
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("Missing GITHUB_TOKEN environment variable. Use a Colab Secret; never paste a token into a notebook cell or commit it.", file=sys.stderr)
        return 2
    root = Path(args.root).resolve()
    if not (root / "pyproject.toml").is_file():
        print(f"No pyproject.toml found in {root}; point --root at the project root.", file=sys.stderr)
        return 2
    try:
        result = push_project(root, args.repo, token, args.branch)
    except Exception as exc:
        print(f"Push failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("Push complete:")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
