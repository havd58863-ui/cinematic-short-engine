"""Objective script analysis: timing estimates and beat extraction without claiming retention guarantees."""
from __future__ import annotations
import re
from typing import Any


def estimate_duration_seconds(script: str, words_per_minute: int = 155) -> float:
    words = len(re.findall(r"\b[\w’'-]+\b", script))
    return round(words / max(int(words_per_minute), 1) * 60, 1)


def validate_script_structure(script: str, account_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validates structural beats required for Account 01 or Account 02."""
    if not account_profile:
        return {"valid": True, "stages_found": [], "missing_stages": [], "notes": "No account profile supplied."}

    account_id = account_profile.get("account_id", "")
    expected_structure = account_profile.get("script_structure", [])
    text_lower = script.lower()

    found = []
    missing = []

    for stage in expected_structure:
        # Check if stage marker or semantic equivalents exist in script
        stage_key = stage.lower()
        if stage_key in text_lower or any(word in text_lower for word in stage_key.split()):
            found.append(stage)
        else:
            missing.append(stage)

    valid = len(missing) == 0
    return {
        "account_id": account_id,
        "valid": valid,
        "stages_found": found,
        "missing_stages": missing,
        "expected_structure": expected_structure,
    }


def analyze_script(script: str, target_seconds: int = 45, words_per_minute: int = 155, account_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    text = script.strip()
    if not text:
        raise ValueError("Script is empty.")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    words = re.findall(r"\b[\w’'-]+\b", text)
    first_sentence = sentences[0] if sentences else paragraphs[0].splitlines()[0]
    opening_hook_words = len(re.findall(r"\b[\w’'-]+\b", first_sentence))
    duration = estimate_duration_seconds(text, words_per_minute)
    structure_val = validate_script_structure(text, account_profile)
    return {
        "word_count": len(words),
        "script_structure_validation": structure_val,
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "estimated_duration_seconds": duration,
        "target_duration_seconds": int(target_seconds),
        "duration_delta_seconds": round(duration - int(target_seconds), 1),
        "opening_hook": first_sentence,
        "opening_hook_word_count": opening_hook_words,
        "hook_warning": "Opening sentence may take longer than 2-3 seconds; consider a shorter first line." if opening_hook_words > 9 else None,
        "narration_paragraphs": paragraphs,
        "pacing_warning": "Script estimate is outside target by more than 20%." if abs(duration-int(target_seconds)) > max(8, int(target_seconds)*0.2) else None,
        "retention_structure_checklist": {
            "immediate_hook": bool(first_sentence) and opening_hook_words <= 9,
            "progressive_beats": len(paragraphs) >= 3 or len(sentences) >= 5,
            "clear_payoff": any(term in text.lower() for term in ("because", "so", "that means", "the truth", "here is why", "which is why", "finally", "instead")),
            "cta_present_but_not_required": any(term in text.lower() for term in ("follow", "comment", "save this", "share this")),
        },
        "limitations": ["Heuristic checks flag review targets; they do not guarantee viewer retention or virality."],
    }
