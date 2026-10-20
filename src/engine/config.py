"""Configuration loading and two-account DNA separation checks."""

from __future__ import annotations

import os
import pathlib
from typing import Any

import yaml

ACCOUNT_FILES: dict[str, str] = {
    "account_01_psychology": "account_01_psychology.yaml",
    "account_02_storytelling": "account_02_storytelling.yaml",
}


class ConfigError(RuntimeError):
    """Raised when repository configuration is missing or internally inconsistent."""


def find_config_dir(explicit: str | pathlib.Path | None = None) -> pathlib.Path:
    """Locate the repository config directory without depending on the install layout."""
    candidates: list[pathlib.Path] = []
    if explicit:
        candidates.append(pathlib.Path(explicit))
    if os.getenv("ENGINE_CONFIG_DIR"):
        candidates.append(pathlib.Path(os.environ["ENGINE_CONFIG_DIR"]))

    cwd = pathlib.Path.cwd().resolve()
    candidates.extend(parent / "config" for parent in (cwd, *cwd.parents))
    candidates.append(pathlib.Path(__file__).resolve().parents[2] / "config")

    for candidate in candidates:
        if (candidate / "accounts").is_dir():
            return candidate
    raise ConfigError("Could not locate config/accounts; set ENGINE_CONFIG_DIR.")


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Missing configuration file: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"Expected a YAML mapping in {path}")
    return value


def list_accounts(config_dir: str | pathlib.Path | None = None) -> list[str]:
    root = find_config_dir(config_dir)
    present: list[str] = []
    for account_id, filename in ACCOUNT_FILES.items():
        if (root / "accounts" / filename).is_file():
            present.append(account_id)
    return present


def load_account(
    account_id: str,
    config_dir: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    try:
        filename = ACCOUNT_FILES[account_id]
    except KeyError as exc:
        valid = ", ".join(sorted(ACCOUNT_FILES))
        raise ConfigError(f"Unknown account '{account_id}'. Valid accounts: {valid}") from exc
    root = find_config_dir(config_dir)
    account = load_yaml(root / "accounts" / filename)
    if account.get("id") != account_id:
        raise ConfigError(
            f"Account file {filename} declares id={account.get('id')!r}, expected {account_id!r}"
        )
    return account


def _require_fields(account_id: str, account: dict[str, Any], fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if field not in account]
    if missing:
        raise ConfigError(f"{account_id} is missing required fields: {', '.join(missing)}")


def validate_configuration(config_dir: str | pathlib.Path | None = None) -> dict[str, Any]:
    """Validate account separation and cross-file references before any generation."""
    root = find_config_dir(config_dir)
    found = list_accounts(root)
    if set(found) != set(ACCOUNT_FILES):
        raise ConfigError(f"Expected both account files, found: {found}")

    accounts = {account_id: load_account(account_id, root) for account_id in ACCOUNT_FILES}
    common = ("id", "name", "language", "voice", "music", "length", "cross_account_forbidden")
    for account_id, account in accounts.items():
        _require_fields(account_id, account, common)
        forbidden = account.get("cross_account_forbidden")
        if not isinstance(forbidden, list) or not forbidden:
            raise ConfigError(f"{account_id} must declare non-empty cross_account_forbidden rules")
        if account.get("language", {}).get("voice") != "en":
            raise ConfigError(f"{account_id} violates the DNA English-voice rule")

    psych = accounts["account_01_psychology"]
    story = accounts["account_02_storytelling"]
    _require_fields(
        "account_01_psychology",
        psych,
        ("core_promise", "content_pillars", "script_structure", "hook_families", "visual"),
    )
    _require_fields(
        "account_02_storytelling",
        story,
        ("identity_line", "story_pillars", "story_progression", "bibles", "continuity_gate", "visual"),
    )
    if story.get("visual", {}).get("ai_first") is not True:
        raise ConfigError("Account 02 must remain AI-first according to the DNA")
    if "character_bible_fields" in psych.get("bibles", {}):
        raise ConfigError("Account 01 must not import Account 02 character-bible identity")
    if psych.get("name") == story.get("name"):
        raise ConfigError("The two accounts must have distinct names")

    voices = load_yaml(root / "voices.yaml")
    for account_id, account in accounts.items():
        ref = str(account.get("voice", {}).get("profile_ref", ""))
        if not ref.startswith("voices.yaml#"):
            raise ConfigError(f"{account_id} has an invalid voice profile reference: {ref!r}")
        profile_key = ref.split("#", 1)[1]
        profile = voices.get(profile_key)
        if not isinstance(profile, dict):
            raise ConfigError(f"Voice profile {profile_key!r} is missing from voices.yaml")
        if profile.get("engine") != "gemini_tts":
            raise ConfigError(f"Voice profile {profile_key!r} must use Gemini TTS as the primary engine")

    quality = load_yaml(root / "quality_gates.yaml")
    technical = quality.get("technical", {})
    if technical.get("resolution") != [1080, 1920] or technical.get("fps") != 30:
        raise ConfigError("Technical master must remain 1080x1920 at 30fps unless the DNA is versioned")

    return {
        "ok": True,
        "config_dir": str(root),
        "accounts": {
            account_id: {
                "name": account["name"],
                "voice_language": account["language"]["voice"],
                "cross_forbidden_rules": len(account["cross_account_forbidden"]),
            }
            for account_id, account in accounts.items()
        },
        "technical_master": {"resolution": technical["resolution"], "fps": technical["fps"]},
    }
