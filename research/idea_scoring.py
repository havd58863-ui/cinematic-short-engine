"""Explainable topic ranking; freshness is date-aware, never a prediction of virality."""
from __future__ import annotations
from typing import Any
from datetime import datetime, timezone, timedelta
import re

CURIOSITY_TERMS = ("why", "secret", "unexpected", "never", "hidden", "what happens", "warning", "mystery", "surprising", "mistake", "revealed", "impossible", "nobody")
VISUAL_TERMS = ("image", "video", "visual", "experiment", "map", "chart", "scene", "camera", "evidence", "object", "timeline", "before", "after")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _parse_publication_time(value: Any, now: datetime) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    relative = re.search(r"\b(\d+)\s+(minutes?|mins?|hours?|days?|weeks?|months?|years?)\s+ago\b", lowered)
    if relative:
        amount = int(relative.group(1)); unit = relative.group(2)
        if unit.startswith(("minute", "min")): delta = timedelta(minutes=amount)
        elif unit.startswith("hour"): delta = timedelta(hours=amount)
        elif unit.startswith("day"): delta = timedelta(days=amount)
        elif unit.startswith("week"): delta = timedelta(days=7 * amount)
        elif unit.startswith("month"): delta = timedelta(days=30 * amount)
        else: delta = timedelta(days=365 * amount)
        return now - delta
    candidate = text.replace("Z", "+00:00")
    try:
        return _as_utc(datetime.fromisoformat(candidate))
    except ValueError:
        pass
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _freshness_points(published_at: Any, now: datetime) -> tuple[int, float | None]:
    published = _parse_publication_time(published_at, now)
    if published is None:
        return 0, None
    age_days = (now - published).total_seconds() / 86400
    # Future timestamps beyond a small clock tolerance are not treated as fresh.
    if age_days < -1:
        return 0, round(age_days, 2)
    age_days = max(0.0, age_days)
    if age_days <= 7:
        return 5, round(age_days, 2)
    if age_days <= 30:
        return 3, round(age_days, 2)
    if age_days <= 90:
        return 1, round(age_days, 2)
    return 0, round(age_days, 2)


def evaluate_dna_gate(title: str, snippet_text: str, account_profile: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Mandatory account DNA gate check before weighted scoring."""
    if not account_profile:
        return True, "No account profile supplied; DNA gate passed by default."
    account_id = account_profile.get("account_id", "")
    text = (title + " " + snippet_text).lower()

    if "account_01" in account_id:
        # Forbidden: medical advice, diagnosing viewers
        forbidden = ["diagnos", "medical advice", "cure your", "treatment for", "symptom of your disorder"]
        for term in forbidden:
            if term in text:
                return False, f"Account 01 DNA Gate Failed: forbidden phrase '{term}' found (no medical claims/diagnosing)."
    elif "account_02" in account_id:
        # Forbidden: non-storytelling clickbait, generic listicles
        forbidden = ["top 5 life hacks", "quick trick", "unbelievable hack", "buy this now"]
        for term in forbidden:
            if term in text:
                return False, f"Account 02 DNA Gate Failed: forbidden phrase '{term}' found (must be narrative storytelling)."

    return True, f"{account_id} DNA Gate Passed."


def score_idea(title: str, sources: list[dict[str, Any]], target_audience: str = "US TikTok viewers", hardware_feasibility: int = 5, related_series: int = 8, now_utc: datetime | None = None, account_profile: dict[str, Any] | None = None, published_catalogue: list[str] | None = None) -> dict[str, Any]:
    now = _as_utc(now_utc or datetime.now(timezone.utc))
    combined_snippets = " ".join(str(s.get("title", "")) + " " + str(s.get("snippet", "")) for s in sources)
    dna_passed, dna_reason = evaluate_dna_gate(title, combined_snippets, account_profile)

    text = (title + " " + combined_snippets).lower()
    grounded = [s for s in sources if s.get("url")]
    evidence = min(20, len(grounded) * 5)
    freshness_details = []
    for source in grounded:
        date_value = source.get("published_at") or source.get("date")
        points, age_days = _freshness_points(date_value, now)
        freshness_details.append({"url": source["url"], "published_at": date_value, "age_days": age_days, "points": points})
    freshness = min(15, sum(item["points"] for item in freshness_details))
    curiosity = min(15, sum(1 for term in CURIOSITY_TERMS if term in text) * 3)
    visual = min(12, sum(1 for term in VISUAL_TERMS if term in text) * 2)
    originality = 8 if title and len(set(title.lower().split())) >= 6 else 4
    feasibility = max(0, min(10, int(hardware_feasibility)))
    series = max(0, min(10, int(related_series)))
    specificity = min(10, max(2, int(len(title.split()) * 1.2)))

    # Topic Saturation Penalty against published catalogue
    saturation_penalty = 0
    if published_catalogue and title:
        title_words = set(title.lower().split())
        for past_item in published_catalogue:
            past_words = set(past_item.lower().split())
            if title_words and past_words:
                overlap = len(title_words.intersection(past_words)) / len(title_words)
                if overlap > 0.6:
                    saturation_penalty += 15

    total = round(evidence + freshness + curiosity + visual + originality + feasibility + series + specificity - saturation_penalty, 1)
    final_score = max(0, min(100, total)) if dna_passed else 0.0

    return {
        "title": title,
        "account_id": account_profile.get("account_id") if account_profile else "default",
        "dna_gate_passed": dna_passed,
        "dna_gate_reason": dna_reason,
        "target_audience": target_audience,
        "score": final_score,
        "components": {
            "source_evidence_max_20": evidence,
            "freshness_signal_max_15": freshness,
            "hook_curiosity_max_15": curiosity,
            "visual_storytelling_max_12": visual,
            "originality_heuristic_max_8": originality,
            "hardware_feasibility_max_10": feasibility,
            "series_potential_max_10": series,
            "specificity_max_10": specificity,
            "saturation_penalty": saturation_penalty,
        },
        "freshness_evidence": freshness_details,
        "evidence_urls": [s["url"] for s in grounded],
        "scored_at_utc": now.isoformat(),
        "limitations": [
            "Explainable heuristic score, not a measured prediction of TikTok views, watch time, or retention.",
            "Freshness points are based only on parseable publication dates returned by accessible sources; missing dates receive zero points.",
            "Competitor metrics and audience demographics are not inferred.",
        ],
    }


def rank_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(candidates, key=lambda item: (float(item.get("score", 0)), len(item.get("evidence_urls", []))), reverse=True)


def rank_topic_results(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Backward-compatible alias used by existing callers."""
    return rank_candidates(candidates)
