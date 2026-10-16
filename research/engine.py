"""End-to-end research assembly, topic candidate generation and provenance persistence."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import json
from .trend_finder import build_research_queries, search_public_web, creative_center_status, extract_page_text, google_trends_interest
from .source_registry import deduplicate_sources
from .idea_scoring import score_idea, rank_candidates
from .competitor_analysis import analyze_public_examples


def _fallback_candidates(sources: list[dict[str, Any]], max_items: int = 8) -> list[dict[str, Any]]:
    """Use actual article titles as candidate seeds if language-model idea drafting is unavailable."""
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for source in sources:
        title = str(source.get("title") or "").strip()
        norm = title.casefold()
        if not title or len(title.split()) < 4 or norm in seen:
            continue
        seen.add(norm)
        items.append({"title": title, "angle": "Investigate the public source and build a short-form explanation", "evidence_urls": [source["url"]], "idea_source": "actual_public_search_title"})
        if len(items) >= max_items:
            break
    return items


def _llm_candidates(sources: list[dict[str, Any]], max_items: int = 8) -> list[dict[str, Any]]:
    try:
        from director.scriptwriter_adapter import generate_structured_json
        source_lines = "\n".join(f"[{i}] TITLE: {s.get('title')}\nURL: {s.get('url')}\nDATE: {s.get('published_at') or 'unavailable'}\nSNIPPET: {s.get('snippet','')}" for i, s in enumerate(sources[:16], 1))
        prompt = f"""Propose {max_items} distinct original English TikTok video ideas for US viewers, grounded only in the evidence below. Output one JSON object: {{\"ideas\":[{{\"title\":\"...\",\"angle\":\"...\",\"evidence_urls\":[\"exact URL from supplied list\"]}}]}}. Do not invent metrics, details, or URLs. Prefer a compelling question, visual proof, practical stakes, or a mystery with a genuine evidence-based payoff. Never promise virality.
SOURCES:\n{source_lines}"""
        data = generate_structured_json(prompt)
        allowed_urls = {str(s.get("url")) for s in sources if s.get("url")}
        ideas = []
        for item in data.get("ideas", []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            urls = [url for url in item.get("evidence_urls", []) if url in allowed_urls] if isinstance(item.get("evidence_urls"), list) else []
            if title and urls:
                ideas.append({"title": title, "angle": str(item.get("angle", "")), "evidence_urls": urls, "idea_source": "llm_grounded_in_supplied_sources"})
        return ideas
    except Exception:
        return []


def _hardware_feasibility_score() -> tuple[int, dict[str, Any]]:
    """Score media feasibility from detected local resources; this is not a quality claim."""
    from generation.image_generation import environment_report
    env = environment_report()
    if env.get("cuda_available"):
        vram = float(env.get("gpu_memory_gb") or 0)
        score = 10 if vram >= 40 else 8 if vram >= 12 else 6 if vram >= 6 else 3
    elif __import__("os").getenv("PIXABAY_API_KEY") or __import__("os").getenv("PEXELS_API_KEY"):
        score = 4
    else:
        score = 2
    env["topic_feasibility_score"] = score
    return score, env


def research_topic(topic: str | None, max_results: int = 6, region: str = "us-en", extract_top_n: int = 3, output_dir: str | Path | None = None) -> dict[str, Any]:
    queries = build_research_queries(topic, region)
    raw_sources: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for query in queries:
        try:
            raw_sources.extend(search_public_web(query, max_results=max_results, region=region))
        except Exception as exc:
            errors.append({"query": query, "error": f"{type(exc).__name__}: {exc}"})
    sources = deduplicate_sources(raw_sources)
    # Extract a bounded number of accessible pages; keep snippets and provenance if extraction is blocked.
    for source in sources[:max(0, int(extract_top_n))]:
        extracted = extract_page_text(source["url"])
        source["extraction_status"] = extracted.get("status")
        source["extraction_error"] = extracted.get("error")
        source["extracted_text"] = extracted.get("text", "")
    trend_status = creative_center_status()
    competitor_report = analyze_public_examples(topic or "US TikTok current-interest stories", max_results=min(4, max_results), region=region)
    # Add competitor examples into the source registry, but retain their distinct role.
    sources = deduplicate_sources([*sources, *competitor_report.get("examples", [])])

    if topic:
        candidate_seeds = [{"title": topic.strip(), "angle": "User-specified topic", "evidence_urls": [s["url"] for s in sources if s.get("url")], "idea_source": "user_topic"}]
    else:
        candidate_seeds = _llm_candidates(sources) if sources else []
        if not candidate_seeds:
            candidate_seeds = _fallback_candidates(sources)
    candidates: list[dict[str, Any]] = []
    hardware_score, hardware_report = _hardware_feasibility_score()
    for seed in candidate_seeds:
        allowed = set(seed.get("evidence_urls", []))
        related = [s for s in sources if s.get("url") in allowed]
        candidate = score_idea(seed["title"], related, hardware_feasibility=hardware_score)
        candidate.update({"angle": seed.get("angle", ""), "idea_source": seed.get("idea_source"), "evidence_urls": [s.get("url") for s in related if s.get("url")]})
        candidates.append(candidate)
    candidates = rank_candidates(candidates)

    trends = {"status": "not_requested", "note": "Set ENABLE_PYTRENDS=true to request an optional Google Trends search-interest signal."}
    if __import__("os").getenv("ENABLE_PYTRENDS", "false").lower() == "true":
        keywords = [x["title"][:80] for x in candidates[:5]]
        if keywords:
            trends = google_trends_interest(keywords)
    report = {
        "topic": topic,
        "region": region,
        "queries": queries,
        "sources": sources,
        "candidate_ideas": candidates,
        "creative_center": trend_status,
        "competitor_analysis": competitor_report,
        "google_trends": trends,
        "search_errors": errors,
        "retrieved_source_count": len(sources),
        "runtime_hardware": hardware_report,
        "warnings": [
            "TikTok Creative Center is recorded as an official entry point; metrics are not claimed unless retrieved from an accessible page.",
            "Scores are prioritization heuristics, not predictions of virality.",
            "Automated competitor discovery only covers accessible public/indexed pages.",
        ],
    }
    if output_dir:
        out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
        for name, value in [("research_report.json", report), ("sources.json", sources), ("candidate_ideas.json", candidates), ("competitors.json", competitor_report), ("creative_center_status.json", trend_status), ("google_trends.json", trends)]:
            (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report
