"""Footage acquisition.

Pexels is used when a key is configured because its library is graded and
cinematic. Wikimedia Commons is the keyless fallback: lower production value,
but licensed and real, which still satisfies the no-stills rule.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import subprocess
import time

import httpx

from engine.director.allocate import Clip
from engine.edit.edl import ShotSource
from engine.edit.render import measure_luma

USER_AGENT = "cinematic-short-engine/0.1 (production pipeline)"
MIN_WIDTH = 1280
MAX_BYTES = 90 * 1024 * 1024
STOPWORDS = {"a", "an", "the", "of", "in", "on", "at", "with", "and", "to", "for", "by"}


class StockError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class Candidate:
    url: str
    credit: str
    title: str
    width: int
    height: int
    size_bytes: int


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return [word for word in words if word not in STOPWORDS and len(word) > 2]


def probe(path: str | pathlib.Path) -> tuple[int, int, float]:
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


def _download(client: httpx.Client, url: str, target: pathlib.Path, attempts: int = 4) -> bool:
    if target.exists() and target.stat().st_size > 200_000:
        return True
    for attempt in range(attempts):
        try:
            with client.stream("GET", url) as response:
                if response.status_code == 429:
                    wait = int(response.headers.get("retry-after", 20 * (attempt + 1)))
                    time.sleep(min(wait, 90))
                    continue
                response.raise_for_status()
                tmp = target.with_suffix(target.suffix + ".part")
                with tmp.open("wb") as handle:
                    for chunk in response.iter_bytes(1 << 20):
                        handle.write(chunk)
                if tmp.stat().st_size < 200_000:
                    tmp.unlink(missing_ok=True)
                    return False
                tmp.replace(target)
                return True
        except (httpx.HTTPError, OSError):
            time.sleep(6 * (attempt + 1))
    return False


def search_pexels(api_key: str, query: str, *, per_page: int = 3) -> list[Candidate]:
    response = httpx.get(
        "https://api.pexels.com/videos/search",
        params={"query": query, "per_page": per_page, "orientation": "portrait", "size": "medium"},
        headers={"Authorization": api_key},
        timeout=30.0,
    )
    response.raise_for_status()
    found: list[Candidate] = []
    for video in response.json().get("videos", []):
        files = sorted(
            (f for f in video.get("video_files", []) if f.get("width")),
            key=lambda f: -f["width"],
        )
        usable = [f for f in files if f["width"] >= 720]
        if not usable:
            continue
        chosen = usable[0]
        found.append(
            Candidate(
                url=chosen["link"],
                credit=f"Pexels — {video.get('user', {}).get('name', 'unknown')} ({video['url']})",
                title=f"pexels_{video['id']}",
                width=int(chosen["width"]),
                height=int(chosen["height"]),
                size_bytes=0,
            )
        )
    return found


def search_wikimedia(query: str, *, limit: int = 4) -> list[Candidate]:
    response = httpx.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:video {query}",
            "gsrnamespace": 6,
            "gsrlimit": limit * 3,
            "prop": "imageinfo",
            "iiprop": "url|size|mime|dimensions|extmetadata",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    found: list[Candidate] = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        if not info.get("mime", "").startswith("video/"):
            continue
        if int(info.get("width", 0)) < MIN_WIDTH:
            continue
        if int(info.get("size", 0)) > MAX_BYTES:
            continue
        meta = info.get("extmetadata", {})
        raw_artist = re.sub("<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
        artist = raw_artist or "Wikimedia contributor"
        licence = meta.get("LicenseShortName", {}).get("value", "CC")
        found.append(
            Candidate(
                url=info["url"],
                credit=f"Wikimedia Commons — {artist} ({licence})",
                title=page["title"].replace("File:", ""),
                width=int(info["width"]),
                height=int(info["height"]),
                size_bytes=int(info.get("size", 0)),
            )
        )
        if len(found) >= limit:
            break
    return found


def load_catalog(path: str | pathlib.Path, account: str | None = None) -> list[dict]:
    import yaml

    payload = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}
    if account and account in payload:
        return list(payload[account])
    return [entry for entries in payload.values() for entry in entries]


def _from_catalog(entries: list[dict], query: str) -> list[Candidate]:
    exact = [entry for entry in entries if entry.get("query") == query]
    if exact:
        entries = exact
    wanted = set(tokens(query))
    scored: list[tuple[int, dict]] = []
    for entry in entries:
        haystack = set(tokens(entry.get("query", "")) + tokens(entry.get("title", "")))
        scored.append((len(wanted & haystack), entry))
    scored.sort(key=lambda item: -item[0])
    chosen = [entry for score, entry in scored if score > 0][:6] or [entry for _, entry in scored[:4]]
    return [
        Candidate(
            url=entry["url"],
            credit=entry.get("credit", "Wikimedia Commons"),
            title=entry["title"],
            width=int(entry.get("width", 0)),
            height=int(entry.get("height", 0)),
            size_bytes=int(float(entry.get("size_mb", 0)) * 1e6),
        )
        for entry in chosen
    ]


def acquire(
    queries: list[str],
    out_dir: str | pathlib.Path,
    *,
    pexels_key: str | None = None,
    per_query: int = 1,
    catalog: str | pathlib.Path | None = None,
    account: str | None = None,
) -> list[Clip]:
    """Download footage for each visual query and describe it as an allocator clip."""
    directory = pathlib.Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    entries = load_catalog(catalog, account) if catalog else []
    clips: list[Clip] = []
    seen_urls: set[str] = set()
    with httpx.Client(follow_redirects=True, timeout=120.0, headers={"User-Agent": USER_AGENT}) as client:
        for query in queries:
            if pexels_key:
                candidates = search_pexels(pexels_key, query, per_page=per_query + 1)
            elif entries:
                candidates = _from_catalog(entries, query)
            else:
                candidates = search_wikimedia(query, limit=per_query + 2)
            taken = 0
            for candidate in candidates:
                if taken >= per_query or candidate.url in seen_urls:
                    continue
                suffix = pathlib.Path(candidate.url.split("?")[0]).suffix or ".mp4"
                slug = re.sub(r"[^a-z0-9]+", "_", candidate.title.lower())[:48].strip("_")
                target = directory / f"{slug}{suffix}"
                if not _download(client, candidate.url, target):
                    continue
                try:
                    width, height, duration = probe(target)
                except (subprocess.CalledProcessError, KeyError, IndexError):
                    target.unlink(missing_ok=True)
                    continue
                if width < MIN_WIDTH or duration < 4.0:
                    continue
                seen_urls.add(candidate.url)
                clips.append(
                    Clip(
                        path=str(target),
                        source=ShotSource.STOCK,
                        tags=sorted(set(tokens(query) + tokens(candidate.title))),
                        duration_seconds=round(duration, 3),
                        mean_luma=measure_luma(target, at=min(1.0, duration / 3), seconds=1.0),
                        credit=candidate.credit,
                    )
                )
                taken += 1
            time.sleep(2)
    if not clips:
        raise StockError("no usable footage was acquired for the requested queries")
    return clips
