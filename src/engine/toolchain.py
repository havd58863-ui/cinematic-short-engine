"""Toolchain manifest loading and privacy-safe local diagnostics."""

from __future__ import annotations

import importlib.util
import os
import pathlib
import platform
import shutil
import sys
from typing import Any

from engine.config import ConfigError, find_config_dir, load_yaml

SECRET_ENV_NAMES = (
    "GEMINI_API_KEY",
    "REACTOR_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_OWNER_CHAT_ID",
    "PEXELS_API_KEY",
)


def load_toolchain(config_dir: str | pathlib.Path | None = None) -> dict[str, Any]:
    return load_yaml(find_config_dir(config_dir) / "toolchain.yaml")


def _repo_root(config_dir: pathlib.Path) -> pathlib.Path:
    return config_dir.parent


def validate_toolchain_manifest(config_dir: str | pathlib.Path | None = None) -> dict[str, Any]:
    root = find_config_dir(config_dir)
    manifest = load_yaml(root / "toolchain.yaml")
    allowed_statuses = set(manifest.get("status_values", []))
    tools = manifest.get("tools")
    if not isinstance(tools, list) or not tools:
        raise ConfigError("toolchain.yaml must contain a non-empty tools list")

    seen: set[str] = set()
    errors: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            errors.append("Every tool entry must be a mapping")
            continue
        tool_id = str(tool.get("id", ""))
        if not tool_id:
            errors.append("A tool entry is missing id")
            continue
        if tool_id in seen:
            errors.append(f"Duplicate tool id: {tool_id}")
        seen.add(tool_id)

        status = tool.get("verification", {}).get("status")
        if status not in allowed_statuses:
            errors.append(f"{tool_id} has unknown verification status {status!r}")

        install = tool.get("install", {})
        lock = install.get("lock") if isinstance(install, dict) else None
        if install.get("mode") == "python_lock" and lock:
            if not (_repo_root(root) / str(lock)).is_file():
                errors.append(f"{tool_id} references a missing lock file: {lock}")

    if errors:
        raise ConfigError("; ".join(errors))
    return {"ok": True, "tool_count": len(tools), "tool_ids": sorted(seen)}


def _module_present(name: str) -> bool:
    """Presence check that never raises (dotted names import their parent package)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def diagnose(config_dir: str | pathlib.Path | None = None) -> dict[str, Any]:
    """Report installed local capabilities without importing heavy packages or exposing secrets."""
    manifest = load_toolchain(config_dir)
    modules: dict[str, bool] = {}
    binaries: dict[str, str | None] = {}

    for tool in manifest.get("tools", []):
        for module in tool.get("python_modules") or []:
            modules[str(module)] = _module_present(str(module))
        for binary in tool.get("binaries") or []:
            binaries[str(binary)] = shutil.which(str(binary))

    return {
        "python": {
            "version": platform.python_version(),
            "required_major_minor": manifest.get("python", {}).get("required"),
            "ok": sys.version_info[:2] == (3, 12),
            "executable": sys.executable,
        },
        "modules": modules,
        "binaries": binaries,
        "secrets_present": {name: bool(os.getenv(name)) for name in SECRET_ENV_NAMES},
        "notes": [
            "Secrets are reported as present/absent only; values are never printed.",
            "Module presence is checked without importing heavy ML libraries.",
            "Live Gemini and Reactor checks require the owner's keys and are separate smoke gates.",
        ],
    }
