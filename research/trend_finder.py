"""Trend discovery through accessible public sources. TikTok metrics are never fabricated."""
from __future__ import annotations
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
import re
import urllib.error
import urllib.request

CREATIVE_CENTER_URL = "https://ads.tiktok.com/creative/creativeCenter/trends"


class _VisibleText(HTMLParser):
    """Small stdlib HTML parser that intentionally ignores script/style payloads."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden_depth += 1
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.hidden_depth:
            self.hidden_depth -= 1
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value:
            return
        if self.in_title:
            self.title_parts.append(value)
        if not self.hidden_depth:
            self.parts.append(value)


def creative_center_status(timeout: float = 12.0) -> dict[str, Any]:
    """Actually check the public Creative Center landing page without bypassing controls.

    This only reports trend items embedded in public HTML. A JS-only page or access
    restriction is recorded as unavailable; it is never treated as an empty trend list
    or filled with invented hashtags/metrics.
    """
    retrieved = datetime.now(timezone.utc).isoformat()
    base: dict[str, Any] = {
        "name": "TikTok Creative Center",
        "url": CREATIVE_CENTER_URL,
        "retrieved_at_utc": retrieved,
        "http_status": None,
        "final_url": CREATIVE_CENTER_URL,
        "page_title": None,
        "public_hashtags_found": [],
        "metrics": {},
        "trend_data_status": "not_retrieved",
    }
    request = urllib.request.Request(CREATIVE_CENTER_URL, headers={
        "User-Agent": "Mozilla/5.0 (compatible; CinematicShortEngine/1.0; +https://github.com/havd58863-ui/cinematic-short-engine)",
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
            body = response.read(2_000_000)
        base.update({"http_status": status, "final_url": final_url, "content_type": content_type})
        if status < 200 or status >= 300 or "html" not in content_type.lower():
            base.update({"status": "unavailable", "trend_data_status": "not_retrieved", "note": f"Official page returned HTTP {status} or non-HTML content; no trend metrics were inferred."})
            return base
        parser = _VisibleText()
        parser.feed(body.decode("utf-8", errors="replace"))
        visible_text = " ".join(parser.parts)
        hashtags = list(dict.fromkeys(re.findall(r"(?<![\w])#[A-Za-z0-9_]{2,50}", visible_text)))[:100]
        base["page_title"] = " ".join(parser.title_parts)[:300] or None
        base["public_hashtags_found"] = [{"hashtag": tag, "source_url": final_url, "retrieved_at_utc": retrieved, "metrics": {}} for tag in hashtags]
        if hashtags:
            base.update({"status": "accessible_public_html_with_hashtags", "trend_data_status": "partial_public_html", "note": "Only hashtags actually present in visible official page HTML are listed. They are not asserted to be ranked/current trends; no metric was available in the extracted HTML."})
        else:
            base.update({"status": "accessible_landing_page_no_embedded_trend_data", "trend_data_status": "not_retrieved", "note": "The official landing page responded, but no visible trend items were embedded in its HTML. It may require client-side rendering or interactive access; no trends or metrics were invented."})
        return base
    except urllib.error.HTTPError as exc:
        base.update({"status": "blocked_or_unavailable", "http_status": exc.code, "trend_data_status": "not_retrieved", "note": f"Official Creative Center returned HTTP {exc.code}. Access controls were not bypassed; no trend metrics were inferred."})
        return base
    except Exception as exc:
        base.update({"status": "unavailable", "trend_data_status": "not_retrieved", "error": f"{type(exc).__name__}: {exc}", "note": "Official page could not be retrieved from this runtime; public web research will be reported separately."})
        return base


def search_public_web(query: str, max_results: int = 8, region: str = "us-en") -> list[dict[str, Any]]:
    """Search accessible public pages and preserve provenance; does not fetch TikTok analytics."""
    try:
        from ddgs import DDGS
    except Exception as exc:
        raise ResearchUnavailable("DDGS is unavailable. Install the research dependencies from requirements-colab.txt.") from exc
    timestamp = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []
    try:
        with DDGS() as ddgs:
            raw = ddgs.text(query, region=region, max_results=max_results)
            for item in raw or []:
                url = item.get("href") or item.get("url")
                if not url:
                    continue
                results.append({
                    "title": str(item.get("title") or "").strip(),
                    "url": url,
                    "snippet": str(item.get("body") or "").strip(),
                    "source": "DDGS public web search",
                    "source_type": "public_web_search",
                    "collected_at_utc": timestamp,
                    "published_at": item.get("date"),
                    "metrics": {},
                    "metrics_note": "No TikTok view, follower, engagement, or trend metrics inferred from search results.",
                })
    except ResearchUnavailable:
        raise
    except Exception as exc:
        raise ResearchUnavailable(f"Public web search failed: {type(exc).__name__}: {exc}") from exc
    return results


def extract_page_text(url: str, max_chars: int = 12000) -> dict[str, Any]:
    """Extract article text from a publicly accessible page; failures are returned as explicit status."""
    try:
        import trafilatura
    except Exception as exc:
        return {"url": url, "status": "unavailable", "error": f"Trafilatura not installed: {exc}", "text": ""}
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {"url": url, "status": "unavailable", "error": "Page could not be fetched; it may block automated access.", "text": ""}
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=True, favor_recall=True) or ""
        return {"url": url, "status": "success" if text else "empty", "text": text[:max_chars], "error": None if text else "No readable article text extracted."}
    except Exception as exc:
        return {"url": url, "status": "unavailable", "error": f"{type(exc).__name__}: {exc}", "text": ""}


def google_trends_interest(keywords: list[str], timeframe: str = "today 3-m", geo: str = "US") -> dict[str, Any]:
    """Optional Google Trends search-interest signal, explicitly not TikTok analytics."""
    try:
        from pytrends.request import TrendReq
        client = TrendReq(hl="en-US", tz=0, timeout=(10, 25))
        client.build_payload(keywords[:5], timeframe=timeframe, geo=geo)
        frame = client.interest_over_time()
        rows = frame.reset_index().to_dict(orient="records") if not frame.empty else []
        return {"provider": "Google Trends via pytrends", "status": "success", "geo": geo, "timeframe": timeframe, "rows": rows, "note": "Google search-interest index only; never TikTok views or engagement."}
    except Exception as exc:
        return {"provider": "Google Trends via pytrends", "status": "unavailable", "geo": geo, "timeframe": timeframe, "rows": [], "error": f"{type(exc).__name__}: {exc}", "note": "Google Trends is optional and can be rate-limited or unavailable."}


def build_research_queries(topic: str | None = None, region: str = "us-en") -> list[str]:
    if topic:
        return [
            f'"{topic}" latest developments United States',
            f'"{topic}" evidence report government OR research',
            f'site:tiktok.com "{topic}" TikTok video examples',
            f'"{topic}" short-form video storytelling ideas',
        ]
    return [
        'TikTok Creative Center US trending hashtags this week',
        'United States recent surprising stories government report this week',
        'viral TikTok storytelling formats examples US creators',
        'site:consumerfinance.gov OR site:bls.gov OR site:census.gov recent report US',
    ]


class ResearchUnavailable(RuntimeError):
    pass
