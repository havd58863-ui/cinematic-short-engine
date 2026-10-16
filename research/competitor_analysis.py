"""Competitor discovery using publicly indexed pages; no scraping around access controls."""
from __future__ import annotations
from typing import Any
from .trend_finder import search_public_web
from .source_registry import deduplicate_sources


def analyze_public_examples(niche: str, max_results: int = 6, region: str = "us-en") -> dict[str, Any]:
    queries = [
        f'site:tiktok.com/@ "{niche}"',
        f'{niche} TikTok creator video examples',
    ]
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for query in queries:
        try:
            items.extend(search_public_web(query, max_results=max_results, region=region))
        except Exception as exc:
            errors.append(f"{query}: {type(exc).__name__}: {exc}")
    results = deduplicate_sources(items)
    for item in results:
        url = item.get("url", "")
        item["example_type"] = "TikTok-indexed page" if "tiktok.com/" in url else "public web example"
        item["performance_metrics"] = None
        item["performance_note"] = "No verified TikTok view, follower, or engagement metrics were obtained in this step."
    return {
        "niche": niche,
        "examples": results,
        "retrieval_errors": errors,
        "limitations": [
            "Search results expose only publicly indexed examples; they do not establish complete competitor coverage.",
            "Performance metrics are omitted unless independently and explicitly returned by a verified source.",
            "No login, CAPTCHA, or access-control bypass is attempted.",
        ],
    }
