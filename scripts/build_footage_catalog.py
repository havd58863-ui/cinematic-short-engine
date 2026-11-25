"""Build the footage catalog from the Internet Archive mirror of Pixabay.

Commons search relevance is poor and its CDN rate-limits hard, so the mirror of
the Pixabay free library is the default behind the Pexels API: real graded stock,
no key, and it downloads reliably.
"""

from __future__ import annotations

import pathlib
import sys

import httpx
import yaml

sys.path.insert(0, "src")
from engine.media.stock import ARCHIVE_FORMATS, USER_AGENT  # noqa: E402

# Theme -> words that must appear in an item title to qualify.
THEMES: dict[str, tuple[str, ...]] = {
    "rain_window": ("rain", "window", "drops"),
    "ocean_rocks": ("ocean", "waves", "rocks", "sea", "coast"),
    "storm_lightning": ("storm", "lightning", "thunder", "clouds"),
    "fog_lake": ("fog", "mist", "forest", "lake"),
    "sunrise_sea": ("sunrise", "sunset", "sea", "beach"),
    "city_night": ("city", "night", "street", "traffic"),
    "candle": ("candle", "fire", "flame", "fireplace"),
    "moon_sea": ("moon", "stars", "night", "sky"),
    "lighthouse": ("lighthouse", "coast", "ocean", "wave"),
    "sea_calm": ("sea", "ocean", "horizon", "calm", "beach"),
    "fishing_boats": ("boat", "ship", "sailing", "sea"),
    "snow_street": ("snow", "winter", "snowfall", "cold"),
    "train_window": ("train", "railway", "travel"),
    "bookshelf": ("book", "library", "paper"),
    "fireplace": ("fire", "fireplace", "wood", "flame"),
    "dust_light": ("light", "sunbeam", "dust", "sun"),
}

ACCOUNTS = {
    "account_01_psychology": [
        "rain_window", "ocean_rocks", "storm_lightning", "fog_lake",
        "sunrise_sea", "city_night", "candle", "moon_sea",
    ],
    "account_02_storytelling": [
        "lighthouse", "sea_calm", "fishing_boats", "snow_street",
        "train_window", "bookshelf", "fireplace", "fog_lake",
        "sunrise_sea", "moon_sea", "dust_light",
    ],
}


def harvest(limit: int = 420) -> list[dict]:
    listing = httpx.get(
        "https://archive.org/advancedsearch.php",
        params={
            "q": "mediatype:movies AND pixabay",
            "fl[]": ["identifier", "title"],
            "rows": limit,
            "output": "json",
            "sort[]": "downloads desc",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=60.0,
    )
    listing.raise_for_status()
    items: list[dict] = []
    for doc in listing.json().get("response", {}).get("docs", []):
        title = str(doc.get("title") or "")
        if "pixabay" not in title.lower():
            continue
        try:
            meta = httpx.get(
                f"https://archive.org/metadata/{doc['identifier']}",
                headers={"User-Agent": USER_AGENT},
                timeout=40.0,
            ).json()
        except httpx.HTTPError:
            continue
        videos = [
            item
            for item in meta.get("files", [])
            if item.get("format", "").lower() in ARCHIVE_FORMATS
            and 800_000 < int(item.get("size", 0) or 0) < 45_000_000
        ]
        if not videos:
            continue
        chosen = max(videos, key=lambda item: int(item.get("size", 0)))
        items.append(
            {
                "title": title,
                "url": f"https://archive.org/download/{doc['identifier']}/{chosen['name']}",
                "credit": f"Internet Archive mirror of Pixabay free stock — {title}",
                "width": 0,
                "height": 0,
                "size_mb": round(int(chosen.get("size", 0)) / 1e6, 1),
            }
        )
        print(f"  harvested {len(items):3d} {title[:60]}", flush=True)
    return items


def classify(items: list[dict]) -> dict[str, list[dict]]:
    catalog: dict[str, list[dict]] = {}
    for account, themes in ACCOUNTS.items():
        entries: list[dict] = []
        used: set[str] = set()
        for theme in themes:
            words = THEMES[theme]
            scored = []
            for item in items:
                if item["url"] in used:
                    continue
                title = item["title"].lower()
                hits = sum(1 for word in words if word in title)
                if hits >= 2:
                    scored.append((hits, item))
            scored.sort(key=lambda pair: -pair[0])
            for _, item in scored[:3]:
                used.add(item["url"])
                entries.append({**item, "query": theme})
        catalog[account] = entries
    return catalog


def main() -> int:
    items = harvest()
    catalog = classify(items)
    pathlib.Path("config/footage_catalog.yaml").write_text(
        yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    for account, entries in catalog.items():
        covered = sorted({entry["query"] for entry in entries})
        print(f"{account}: {len(entries)} clips across {len(covered)} themes: {covered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
