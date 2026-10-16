"""Provenance registry for public research results; never invents platform metrics."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_source(item: dict[str, Any]) -> dict[str, Any]:
    url = str(item.get("url") or item.get("href") or "").strip()
    parsed = urlparse(url) if url else None
    return {
        "title": str(item.get("title") or "Untitled source").strip(),
        "url": url,
        "domain": parsed.netloc.lower() if parsed else "",
        "snippet": str(item.get("snippet") or item.get("body") or "").strip(),
        "source_type": str(item.get("source_type") or item.get("source") or "public_web"),
        "published_at": item.get("published_at") or item.get("date"),
        "retrieved_at_utc": item.get("retrieved_at_utc") or item.get("collected_at_utc") or utc_now(),
        "metrics": item.get("metrics") if isinstance(item.get("metrics"), dict) else {},
        "metrics_note": str(item.get("metrics_note") or "No platform performance metrics were inferred."),
        "extracted_text": str(item.get("extracted_text") or ""),
    }


def deduplicate_sources(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for raw in items:
        item = normalize_source(raw)
        url = item["url"]
        if not url:
            continue
        previous = by_url.get(url)
        if previous is None or (len(item["extracted_text"]) > len(previous["extracted_text"])):
            by_url[url] = item
    return list(by_url.values())


def attach_metrics(source: dict[str, Any], metrics: dict[str, Any], provider: str) -> dict[str, Any]:
    """Attach only metrics explicitly collected from a provider; caller owns provenance."""
    clean = {k: v for k, v in metrics.items() if v is not None}
    output = normalize_source(source)
    output["metrics"] = clean
    output["metrics_provider"] = provider
    output["metrics_note"] = "Metrics recorded as returned by the named provider; not inferred from search snippets."
    return output
