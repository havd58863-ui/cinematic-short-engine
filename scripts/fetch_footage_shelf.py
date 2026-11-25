"""Download the curated footage shelf on a runner that is not rate limited.

The pipeline itself prefers Pexels; this script exists so the Wikimedia fallback
can be fetched once, verified, and attached to a release instead of being pulled
during a render.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import time

import httpx
import yaml

USER_AGENT = "cinematic-short-engine/0.1 (production pipeline)"
SHELF = pathlib.Path("shelf")


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower())[:48].strip("_")


def probe(path: pathlib.Path) -> tuple[int, int, float]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(result.stdout)
    stream = payload["streams"][0]
    return int(stream["width"]), int(stream["height"]), float(payload["format"]["duration"])


def download(client: httpx.Client, url: str, target: pathlib.Path) -> bool:
    for attempt in range(5):
        try:
            with client.stream("GET", url) as response:
                if response.status_code == 429:
                    wait = int(response.headers.get("retry-after", 30 * (attempt + 1)))
                    print(f"   429, waiting {wait}s", flush=True)
                    time.sleep(min(wait, 120))
                    continue
                response.raise_for_status()
                tmp = target.with_suffix(target.suffix + ".part")
                with tmp.open("wb") as handle:
                    for chunk in response.iter_bytes(1 << 20):
                        handle.write(chunk)
                tmp.replace(target)
                return True
        except (httpx.HTTPError, OSError) as exc:
            print(f"   retry after {exc}", flush=True)
            time.sleep(8 * (attempt + 1))
    return False


def main() -> int:
    catalog = yaml.safe_load(pathlib.Path("config/footage_catalog.yaml").read_text(encoding="utf-8"))
    SHELF.mkdir(exist_ok=True)
    manifest: list[dict] = []
    seen: set[str] = set()
    with httpx.Client(follow_redirects=True, timeout=180.0, headers={"User-Agent": USER_AGENT}) as client:
        for account, entries in catalog.items():
            for entry in entries:
                url = entry["url"].split("?")[0]
                if url in seen:
                    continue
                seen.add(url)
                suffix = pathlib.Path(url).suffix or ".webm"
                target = SHELF / f"{slug(entry['title'])}{suffix}"
                if not target.exists():
                    print(f"[{account}] {entry['title'][:50]}", flush=True)
                    if not download(client, url, target):
                        print("   failed", flush=True)
                        continue
                    time.sleep(4)
                try:
                    width, height, duration = probe(target)
                except subprocess.CalledProcessError:
                    target.unlink(missing_ok=True)
                    continue
                if width < 1280 or duration < 4.0:
                    print(f"   rejected {width}x{height} {duration:.1f}s", flush=True)
                    target.unlink(missing_ok=True)
                    continue
                manifest.append(
                    {
                        "account": account,
                        "theme": entry["query"],
                        "title": entry["title"],
                        "credit": entry.get("credit", ""),
                        "file": target.name,
                        "width": width,
                        "height": height,
                        "duration": round(duration, 2),
                    }
                )
    (SHELF / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"collected {len(manifest)} clips", flush=True)
    return 0 if manifest else 1


if __name__ == "__main__":
    raise SystemExit(main())
