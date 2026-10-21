"""Negative/positive unit cases for engine.validation (owner spec section 19)."""

from engine.contracts import AccountId
from engine.validation import (
    BeatBudget,
    FailureCode,
    ScriptConstraints,
    ValidationStatus,
    validate_script,
)

SPOKEN = ["hook", "curiosity", "psychological_mechanism", "realization", "final_line"]

PSYCH = ScriptConstraints(
    account=AccountId.PSYCHOLOGY,
    spoken_fields=SPOKEN,
    required_fields=[*SPOKEN, "title"],
    total_words=(150, 230),
    beat_budgets={
        "hook": BeatBudget(min_words=8, max_words=12),
        "curiosity": BeatBudget(min_words=32, max_words=48),
        "psychological_mechanism": BeatBudget(min_words=60, max_words=85),
        "realization": BeatBudget(min_words=45, max_words=65),
        "final_line": BeatBudget(min_words=12, max_words=20),
    },
    hook_field="hook",
    hook_max_words=12,
    must_differ=[("psychological_mechanism", "realization"), ("realization", "final_line")],
)


def filler(tag: str, count: int) -> str:
    return " ".join(f"{tag}{i}" for i in range(count)) + "."


def valid_psych() -> dict:
    return {
        "title": "The Weight of Quiet",
        "hook": filler("h", 10),
        "curiosity": filler("c", 40),
        "psychological_mechanism": filler("m", 70),
        "realization": filler("r", 55),
        "final_line": filler("f", 15),
    }


def codes(report) -> set[FailureCode]:
    return {issue.code for issue in report.issues}


def test_valid_script_passes():
    report = validate_script(valid_psych(), PSYCH)
    assert report.status is ValidationStatus.PASSED
    assert report.issues == []
    assert report.metrics["spoken_words"] == 190


def test_beat_too_short_names_field_and_deficit():
    obj = valid_psych()
    obj["psychological_mechanism"] = filler("m", 30)
    report = validate_script(obj, PSYCH)
    assert FailureCode.BEAT_BELOW_MIN in codes(report)
    issue = next(i for i in report.issues if i.code is FailureCode.BEAT_BELOW_MIN)
    assert issue.field == "psychological_mechanism"
    assert "30" in issue.repair_hint  # exact deficit named, no generic 'make it longer'


def test_hook_over_three_seconds_rejected():
    obj = valid_psych()
    obj["hook"] = filler("h", 13)
    report = validate_script(obj, PSYCH)
    assert FailureCode.HOOK_TOO_LONG in codes(report)


def test_unsupported_research_claim_rejected():
    obj = valid_psych()
    obj["psychological_mechanism"] = filler("m", 65) + " Research shows this always happens."
    report = validate_script(obj, PSYCH)
    assert FailureCode.UNSUPPORTED_CLAIM in codes(report)


def test_camera_direction_inside_narration_rejected():
    obj = valid_psych()
    obj["curiosity"] = filler("c", 33) + " The camera pans out slowly here."
    report = validate_script(obj, PSYCH)
    assert FailureCode.STAGE_DIRECTION_IN_NARRATION in codes(report)


def test_banned_cta_rejected():
    obj = valid_psych()
    obj["final_line"] = filler("f", 12)[:-1] + " like and subscribe."
    report = validate_script(obj, PSYCH)
    assert FailureCode.BANNED_PHRASE in codes(report)


def test_empty_required_beat_rejected():
    obj = valid_psych()
    obj["curiosity"] = "   "
    report = validate_script(obj, PSYCH)
    assert FailureCode.EMPTY_FIELD in codes(report)


def test_repeated_sentences_rejected():
    obj = valid_psych()
    obj["psychological_mechanism"] = " ".join(["Silence grows heavier each night without answers."] * 9)
    report = validate_script(obj, PSYCH)
    assert FailureCode.REPETITION in codes(report)


def test_non_english_narration_rejected():
    obj = valid_psych()
    arabic = "هذا النص عربي بالكامل ولا ينتمي إلى السكريبت الإنجليزي أبدا في هذا الحساب"
    obj["curiosity"] = " ".join([arabic] * 3) + "."
    report = validate_script(obj, PSYCH)
    assert FailureCode.LANGUAGE_MISMATCH in codes(report)


def test_duplicated_function_fields_rejected():
    spec = ScriptConstraints(
        account=AccountId.STORYTELLING,
        spoken_fields=["journey"],
        required_fields=["journey", "after_image", "hero_shot"],
        total_words=(10, 300),
        beat_budgets={"journey": BeatBudget(min_words=5, max_words=200)},
        must_differ=[("after_image", "hero_shot")],
    )
    same = "A single lantern flickers in the distance, lighting the way through the snow."
    obj = {"journey": filler("j", 40), "after_image": same, "hero_shot": same}
    report = validate_script(obj, spec)
    assert FailureCode.FIELD_DUPLICATION in codes(report)


def test_total_above_max_rejected():
    spec = ScriptConstraints(
        account=AccountId.PSYCHOLOGY,
        spoken_fields=["journey"],
        required_fields=["journey"],
        total_words=(10, 50),
        beat_budgets={"journey": BeatBudget(min_words=5, max_words=200)},
    )
    report = validate_script({"journey": filler("j", 80)}, spec)
    assert FailureCode.WORDS_ABOVE_MAX in codes(report)


def test_missing_field_named():
    obj = valid_psych()
    del obj["title"]
    report = validate_script(obj, PSYCH)
    assert FailureCode.MISSING_FIELD in codes(report)


def test_non_object_fails_validation_outright():
    report = validate_script("not a script", PSYCH)
    assert report.status is ValidationStatus.FAILED
    assert report.issues[0].code is FailureCode.SCHEMA_INVALID


def test_editor_nested_script_validates():
    spec = PSYCH.model_copy(update={"required_fields": SPOKEN})
    script = {k: v for k, v in valid_psych().items() if k != "title"}
    obj = {"revised_script": script}
    report = validate_script(obj, spec, script_field="revised_script")
    assert report.status is ValidationStatus.PASSED


from engine.validation import validate_editor_extras  # noqa: E402


def test_editor_extras_require_justified_edits():
    ok = {"edits": [{"where": "hook", "change": "cut preamble", "why": "lands hook in time"}] * 4}
    assert validate_editor_extras(ok) == []
    few = validate_editor_extras({"edits": [{"where": "a", "change": "b", "why": "one two three four"}]})
    assert few[0].code is FailureCode.EDITS_TOO_FEW
    no_why = validate_editor_extras({"edits": [{"where": "a", "change": "b", "why": ""}] * 4})
    assert no_why and no_why[0].code is FailureCode.EDIT_WHY_MISSING
