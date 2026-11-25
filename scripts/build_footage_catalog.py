"""Build a curated footage catalog from Wikimedia Commons.

Searching at render time is fragile (rate limits, relevance noise). This script
records vetted candidates once, and production reads the catalog instead.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

import httpx
import yaml

sys.path.insert(0, "src")
from engine.media.stock import search_wikimedia  # noqa: E402

QUERIES = {
    "psychology": [
        "rain window", "ocean waves", "waves rocks", "fog forest",
        "sunrise sea", "night city lights", "storm clouds",
    ],
    "storytelling": [
        "lighthouse", "storm sea", "fishing boats", "dust light",
        "beam light water", "window snow", "sunrise sea", "old book",
    ],
}


def collect(query: str, attempts: int = 4) -> list[dict]:
    for attempt in range(attempts):
        try:
            found = search_wikimedia(query, limit=4)
            return [
                {
                    "url": item.url,
                    "title": item.title,
                    "width": item.width,
                    "height": item.height,
                    "size_mb": round(item.size_bytes / 1e6, 1),
                    "credit": item.credit,
                }
                for item in found
            ]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 429:
                raise
            time.sleep(8 * (attempt + 1))
    return []


def main() -> int:
    catalog: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for account, queries in QUERIES.items():
        entries: list[dict] = []
        for query in queries:
            results = collect(query)
            for item in results:
                if item["url"] in seen or item["size_mb"] > 60:
                    continue
                seen.add(item["url"])
                entries.append({**item, "query": query})
            print(f"{account:14s} {query:18s} -> {len(results)}")
            time.sleep(3)
        catalog[account] = entries
    target = pathlib.Path("config/footage_catalog.yaml")
    target.write_text(yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"wrote {target} with {sum(len(v) for v in catalog.values())} clips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
