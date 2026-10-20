"""Command-line entry point for foundation diagnostics."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

from engine.config import ConfigError, list_accounts, load_account, validate_configuration
from engine.toolchain import diagnose, validate_toolchain_manifest


def _emit(value: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for key, item in value.items():
        print(f"{key}: {item}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cinematic-engine")
    parser.add_argument("--config-dir", type=pathlib.Path)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Inspect local tools without exposing secrets")
    doctor.add_argument("--json", action="store_true")

    validate = sub.add_parser("validate-config", help="Validate DNA account separation and references")
    validate.add_argument("--json", action="store_true")

    toolchain = sub.add_parser("validate-toolchain", help="Validate the pinned tool manifest")
    toolchain.add_argument("--json", action="store_true")

    accounts = sub.add_parser("accounts", help="List configured accounts")
    accounts.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            result = diagnose(args.config_dir)
        elif args.command == "validate-config":
            result = validate_configuration(args.config_dir)
        elif args.command == "validate-toolchain":
            result = validate_toolchain_manifest(args.config_dir)
        elif args.command == "accounts":
            result = {
                account_id: load_account(account_id, args.config_dir)["name"]
                for account_id in list_accounts(args.config_dir)
            }
        else:  # pragma: no cover - argparse enforces the commands above
            raise AssertionError(args.command)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    _emit(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
