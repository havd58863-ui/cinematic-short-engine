"""Script intake: load an approved script and prove it against the contract.

Scripts are authored elsewhere (the writing model, or a human). This module is
the gate they pass before a single frame is rendered.
"""

from __future__ import annotations

import json
import pathlib

import yaml

from engine.contracts import AccountId
from engine.validation import BeatBudget, ScriptConstraints, ValidationReport, validate_script

SPOKEN_FIELDS: dict[AccountId, list[str]] = {
    AccountId.PSYCHOLOGY: ["hook", "curiosity", "psychological_mechanism", "realization", "final_line"],
    AccountId.STORYTELLING: [
        "cold_open", "question", "journey", "discovery", "emotional_turn", "payoff", "after_image",
    ],
}
REQUIRED_EXTRA: dict[AccountId, list[str]] = {
    AccountId.PSYCHOLOGY: ["title", "hook_family", "visual_metaphor"],
    AccountId.STORYTELLING: ["title", "world", "hero_shot"],
}


class ScriptError(RuntimeError):
    pass


def load(path: str | pathlib.Path) -> dict:
    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ScriptError("script must be a JSON object")
    return payload


def build_spec(config: dict, account: AccountId) -> ScriptConstraints:
    raw = config["constraints"][account.value]
    shared = config["constraints"]["shared"]
    return ScriptConstraints(
        account=account,
        spoken_fields=SPOKEN_FIELDS[account],
        required_fields=[*SPOKEN_FIELDS[account], *REQUIRED_EXTRA[account]],
        total_words=tuple(raw["total_words"]),
        beat_budgets={
            key: BeatBudget(min_words=value[0], max_words=value[1])
            for key, value in raw["beat_budgets"].items()
        },
        hook_field=raw.get("hook_field"),
        hook_max_words=raw.get("hook_max_words"),
        must_differ=[tuple(pair) for pair in raw.get("must_differ", [])],
        **shared,
    )


def validate(
    script: dict, account: AccountId, config_dir: str | pathlib.Path | None = None
) -> ValidationReport:
    root = pathlib.Path(config_dir) if config_dir else pathlib.Path("config")
    config = yaml.safe_load((root / "writing_gate.yaml").read_text(encoding="utf-8"))
    return validate_script(script, build_spec(config, account))


def assert_valid(
    script: dict, account: AccountId, config_dir: str | pathlib.Path | None = None
) -> ValidationReport:
    report = validate(script, account, config_dir)
    if report.status.value != "passed_validation":
        failures = ", ".join(sorted({issue.code.value for issue in report.issues}))
        raise ScriptError(f"script rejected by the contract: {failures}")
    return report


def beat_order(account: AccountId) -> list[str]:
    return SPOKEN_FIELDS[account]


def beats(script: dict, account: AccountId) -> list[dict]:
    """Spoken beats in narrative order, each with its visual direction."""
    directed = {entry["field"]: entry for entry in script.get("beats", [])}
    ordered: list[dict] = []
    for field in beat_order(account):
        entry = directed.get(field)
        if entry is None:
            raise ScriptError(f"beat {field!r} has no visual direction")
        ordered.append(
            {
                "field": field,
                "text": script[field],
                "visual": entry["visual"],
                "tags": entry.get("tags", []),
                "why": entry["why"],
            }
        )
    return ordered
