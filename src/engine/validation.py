"""Deterministic script validation — layers 1-3 of the quality gates.

Used identically by the writing-model acceptance gate and (later) production.
Semantic critique (layer 4) is deliberately NOT here: in the gate the owner is
the blind judge; in production a second role critiques. This module never
guesses quality — it only enforces measurable contracts and names every
failure with a code, the field, the expected bound and the actual value.

Status semantics (owner spec, writing gate v2):
  PASSED            -> no hard issue found
  REPAIR_REQUIRED   -> hard issue(s) that a bounded repair loop may fix
  FAILED            -> input is not even a script-shaped object
The terminal `failed_validation` after exhausted repairs is the harness's call.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import Field

from engine.contracts import AccountId, StrictModel

BANNED_PHRASES = (
    "dark psychology",
    "mind control",
    "like and subscribe",
    "in this video",
    "smash that like",
)

_CLAIM_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bresearch (shows|proves|found|suggests)\b",
        r"\bstudies (show|prove|found|suggest)\b",
        r"\bscience (says|proves|shows)\b",
        r"\bscientists (say|found|proved)\b",
        r"\bpsychologists (say|found|have found|prove)\b",
        r"\bproven fact\b",
        r"\bit is (scientifically )?proven\b",
    )
)

_CAMERA_VERBS = (
    r"(pans?|zooms?|cuts?|lingers?|drifts?|glides?|pulls back|"
    r"pushes in|reveals?|follows?|settles?)"
)
_STAGE_DIRECTION_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        rf"\bthe camera\b[^.!?]{{0,24}}\b{_CAMERA_VERBS}\b",
        r"\bcamera (pans?|zooms?|cuts?|lingers?|pulls back|pushes in)\b",
        r"\bcut to\b",
        r"\bfade (in|out)\b",
        r"\bclose-up\b",
        r"\b(wide|medium|aerial|drone) shot\b",
        r"\bscene (opens|fades)\b",
    )
)

_WORD_RE = re.compile(r"[^\s]+")
_TOKEN_RE = re.compile(r"[a-z0-9']+")
_SENTENCE_RE = re.compile(r"[.!?]+")


class ValidationStatus(StrEnum):
    PASSED = "passed_validation"
    REPAIR_REQUIRED = "repair_required"
    FAILED = "failed_validation"


class FailureCode(StrEnum):
    SCHEMA_INVALID = "SCHEMA_INVALID"
    MISSING_FIELD = "MISSING_FIELD"
    EMPTY_FIELD = "EMPTY_FIELD"
    WORDS_BELOW_MIN = "WORDS_BELOW_MIN"
    WORDS_ABOVE_MAX = "WORDS_ABOVE_MAX"
    BEAT_BELOW_MIN = "BEAT_BELOW_MIN"
    BEAT_ABOVE_MAX = "BEAT_ABOVE_MAX"
    HOOK_TOO_LONG = "HOOK_TOO_LONG"
    BANNED_PHRASE = "BANNED_PHRASE"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    STAGE_DIRECTION_IN_NARRATION = "STAGE_DIRECTION_IN_NARRATION"
    FIELD_DUPLICATION = "FIELD_DUPLICATION"
    REPETITION = "REPETITION"
    LANGUAGE_MISMATCH = "LANGUAGE_MISMATCH"
    EDITS_TOO_FEW = "EDITS_TOO_FEW"
    EDIT_WHY_MISSING = "EDIT_WHY_MISSING"


class ValidationIssue(StrictModel):
    code: FailureCode
    field: str | None = None
    expected: str = Field(min_length=1, max_length=300)
    actual: str = Field(min_length=1, max_length=300)
    repair_hint: str = Field(min_length=1, max_length=600)


class BeatBudget(StrictModel):
    min_words: int = Field(ge=0)
    max_words: int = Field(gt=0)


class ScriptConstraints(StrictModel):
    account: AccountId
    spoken_fields: list[str] = Field(min_length=1)
    required_fields: list[str] = Field(min_length=1)
    total_words: tuple[int, int]
    beat_budgets: dict[str, BeatBudget] = Field(default_factory=dict)
    hook_field: str | None = None
    hook_max_words: int | None = Field(default=None, gt=0)
    must_differ: list[tuple[str, str]] = Field(default_factory=list)
    min_english_ratio: float = Field(default=0.95, ge=0, le=1)
    max_repetition_ratio: float = Field(default=0.15, ge=0, le=1)
    duplication_threshold: float = Field(default=0.85, ge=0, le=1)


class ValidationReport(StrictModel):
    status: ValidationStatus
    issues: list[ValidationIssue] = Field(default_factory=list)
    metrics: dict[str, float | int | str | bool] = Field(default_factory=dict)


def words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def english_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    en = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return round(en / len(letters), 3)


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _Jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _repetition_ratio(text: str) -> float:
    sentences = [s.strip().lower() for s in _SENTENCE_RE.split(text) if len(s.strip()) > 12]
    if not sentences:
        return 0.0
    return round(1 - len(set(sentences)) / len(sentences), 3)


def _issue(code: FailureCode, field: str | None, expected: str, actual: str, hint: str) -> ValidationIssue:
    return ValidationIssue(code=code, field=field, expected=expected, actual=actual, repair_hint=hint)


def _lookup(obj: Mapping[str, Any], script_obj: Mapping[str, Any], field: str) -> Any:
    if field in script_obj:
        return script_obj.get(field)
    return obj.get(field)


def validate_script(
    obj: Any,
    spec: ScriptConstraints,
    *,
    script_field: str | None = None,
) -> ValidationReport:
    """Validate one script object against measurable contracts (layers 1-3)."""
    if not isinstance(obj, Mapping):
        issue = _issue(
            FailureCode.SCHEMA_INVALID,
            None,
            "a JSON object matching the script schema",
            f"{type(obj).__name__} instead of object",
            "Regenerate the full JSON object exactly per schema.",
        )
        return ValidationReport(status=ValidationStatus.FAILED, issues=[issue], metrics={})

    script_obj: Mapping[str, Any] = obj
    if script_field:
        nested = obj.get(script_field)
        script_obj = nested if isinstance(nested, Mapping) else {}

    issues: list[ValidationIssue] = []
    metrics: dict[str, float | int | str | bool] = {}

    for field in spec.required_fields:
        if _lookup(obj, script_obj, field) is None:
            issues.append(
                _issue(FailureCode.MISSING_FIELD, field, "field present", "absent",
                       f"Add the missing '{field}' field with real content.")
            )

    spoken_texts: dict[str, str] = {}
    for field in spec.spoken_fields:
        value = script_obj.get(field)
        text = value.strip() if isinstance(value, str) else ""
        spoken_texts[field] = text
        metrics[f"words_{field}"] = words(text)
        if field in spec.required_fields and not text:
            issues.append(
                _issue(FailureCode.EMPTY_FIELD, field, "non-empty spoken text", "empty",
                       f"Write '{field}'; an empty beat is a dead scene.")
            )
        budget = spec.beat_budgets.get(field)
        if budget and text:
            count = words(text)
            if count < budget.min_words:
                issues.append(
                    _issue(
                        FailureCode.BEAT_BELOW_MIN,
                        field,
                        f"{budget.min_words}-{budget.max_words} words",
                        f"{count} words",
                        f"Expand '{field}' by at least {budget.min_words - count} words with NEW "
                        "substance (a concrete moment, cause or consequence). Do not restate other beats.",
                    )
                )
            elif count > budget.max_words:
                issues.append(
                    _issue(
                        FailureCode.BEAT_ABOVE_MAX,
                        field,
                        f"{budget.min_words}-{budget.max_words} words",
                        f"{count} words",
                        f"Tighten '{field}' by about {count - budget.max_words} words; keep only "
                        "what this beat must uniquely carry.",
                    )
                )

    spoken = " ".join(spoken_texts[f] for f in spec.spoken_fields)
    total = words(spoken)
    metrics["spoken_words"] = total
    lo, hi = spec.total_words
    if total < lo:
        issues.append(
            _issue(FailureCode.WORDS_BELOW_MIN, None, f"{lo}-{hi} total spoken words", f"{total} words",
                   "The script is too short; expand per the beat-level hints, never with filler.")
        )
    elif total > hi:
        issues.append(
            _issue(FailureCode.WORDS_ABOVE_MAX, None, f"{lo}-{hi} total spoken words", f"{total} words",
                   "The script is too long; cut redundancy, keep every beat's unique job.")
        )

    if spec.hook_field and spec.hook_max_words:
        hook_words = words(spoken_texts.get(spec.hook_field, ""))
        metrics["hook_words"] = hook_words
        if hook_words > spec.hook_max_words:
            issues.append(
                _issue(
                    FailureCode.HOOK_TOO_LONG,
                    spec.hook_field,
                    f"<= {spec.hook_max_words} words (lands inside 3 seconds)",
                    f"{hook_words} words",
                    "Compress the hook to one breath; move the explanation into curiosity.",
                )
            )

    lower = spoken.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lower:
            issues.append(
                _issue(FailureCode.BANNED_PHRASE, None, "no banned/copycat-creator phrasing",
                       f"found: '{phrase}'",
                       "Remove it; this channel never announces itself or begs for engagement.")
            )

    for pattern in _CLAIM_PATTERNS:
        match = pattern.search(spoken)
        if match:
            issues.append(
                _issue(
                    FailureCode.UNSUPPORTED_CLAIM,
                    None,
                    "no research-style authority claims without a checkable source",
                    f"found: '{match.group(0)}'",
                    "Delete the authority claim or rephrase as a tentative, proportional "
                    "interpretation ('often', 'can'); never present it as established fact.",
                )
            )
            break

    for pattern in _STAGE_DIRECTION_PATTERNS:
        match = pattern.search(spoken)
        if match:
            issues.append(
                _issue(
                    FailureCode.STAGE_DIRECTION_IN_NARRATION,
                    None,
                    "spoken narration free of camera/stage directions",
                    f"found: '{match.group(0)}'",
                    "Move visual direction out of the narration; the voice performs the story, "
                    "it never describes the camera.",
                )
            )
            break

    ratio = english_ratio(spoken)
    metrics["english_ratio"] = ratio
    if spoken and ratio < spec.min_english_ratio:
        issues.append(
            _issue(FailureCode.LANGUAGE_MISMATCH, None, f"English ratio >= {spec.min_english_ratio}",
                   f"{ratio}",
                   "Scripts are English-only under the DNA; remove non-English narration.")
        )

    repetition = _repetition_ratio(spoken)
    metrics["repetition_ratio"] = repetition
    if repetition > spec.max_repetition_ratio:
        issues.append(
            _issue(FailureCode.REPETITION, None, f"sentence repetition <= {spec.max_repetition_ratio}",
                   f"{repetition}",
                   "Each beat must add a new fact, image or turn; rewrite repeated sentences.")
        )

    for left, right in spec.must_differ:
        a = _lookup(obj, script_obj, left)
        b = _lookup(obj, script_obj, right)
        if isinstance(a, str) and isinstance(b, str) and a.strip() and b.strip():
            similarity = 1.0 if a.strip() == b.strip() else _Jaccard(a, b)
            metrics[f"similarity_{left}__{right}"] = round(similarity, 3)
            if similarity >= spec.duplication_threshold:
                issues.append(
                    _issue(
                        FailureCode.FIELD_DUPLICATION,
                        right,
                        f"'{left}' and '{right}' must do different jobs "
                        f"(token overlap < {spec.duplication_threshold})",
                        f"similarity {round(similarity, 3)}",
                        f"Rewrite '{right}' for its own function instead of echoing '{left}'.",
                    )
                )

    status = ValidationStatus.PASSED if not issues else ValidationStatus.REPAIR_REQUIRED
    return ValidationReport(status=status, issues=issues, metrics=metrics)


def validate_editor_extras(
    obj: Any,
    *,
    min_edits: int = 4,
    max_edits: int = 7,
) -> list[ValidationIssue]:
    """Retention-editor contract on top of validate_script (edits must carry WHYs)."""
    issues: list[ValidationIssue] = []
    edits = obj.get("edits") if isinstance(obj, Mapping) else None
    if not isinstance(edits, list) or not (min_edits <= len(edits) <= max_edits):
        count = len(edits) if isinstance(edits, list) else 0
        issues.append(
            _issue(
                FailureCode.EDITS_TOO_FEW,
                "edits",
                f"{min_edits}-{max_edits} justified edits",
                f"{count} edits",
                "List the meaningful structural changes you made; generic praise is not an edit.",
            )
        )
        return issues
    for index, edit in enumerate(edits):
        why = edit.get("why", "") if isinstance(edit, Mapping) else ""
        if not isinstance(why, str) or len(why.split()) < 4:
            issues.append(
                _issue(
                    FailureCode.EDIT_WHY_MISSING,
                    f"edits[{index}].why",
                    "a concrete reason (>= 4 words) naming the fixed problem",
                    "missing or empty",
                    "State the flaw in the draft and exactly how this change repairs it.",
                )
            )
    return issues
