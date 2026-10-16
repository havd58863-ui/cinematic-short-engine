from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

class ResearchUnavailable(RuntimeError):
    pass

def search_public_web(query: str, max_results: int = 8, region: str = "us-en") -> list[dict[str, Any]]:
    """Search accessible public web pages and preserve provenance; it does not fetch TikTok analytics."""
    try:
        from ddgs import DDGS
    except Exception as exc:
        raise ResearchUnavailable("Install ddgs to enable web research: pip install 'ddgs>=9.0'") from exc
    timestamp = datetime.now(timezone.utc).isoformat()
    results = []
    try:
        with DDGS() as ddgs:
            raw = ddgs.text(query, region=region, max_results=max_results)
            for item in raw or []:
                url = item.get("href") or item.get("url")
                if not url:
                    continue
                results.append({
                    "title": item.get("title", "").strip(),
                    "url": url,
                    "snippet": item.get("body", "").strip(),
                    "source": "DDGS public web search",
                    "collected_at_utc": timestamp,
                    "published_at": item.get("date"),
                    "metrics": {},
                    "metrics_note": "No TikTok view/engagement metrics inferred from web-search results.",
                })
    except Exception as exc:
        raise ResearchUnavailable(f"Public web search failed: {type(exc).__name__}: {exc}") from exc
    return results

def build_research_queries(topic: str | None = None, region: str = "us-en") -> list[str]:
    if topic:
        return [f"{topic} latest developments", f"{topic} TikTok trend examples", f"{topic} evidence report"]
    return [
        "TikTok trends this week United States creator trends",
        "viral TikTok story formats this week US",
        "recent surprising stories US public reports",
    ]
