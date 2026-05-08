#!/usr/bin/env python3
"""Compatibility launcher for legacy collector startup scripts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required for the legacy collector launcher") from exc


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_realtime_loop import main as run_realtime_loop_main


def _build_args_from_config(config_path: Path) -> list[str]:
    if not config_path.exists():
        raise SystemExit(f"collector config not found: {config_path}")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise SystemExit(f"collector config must be a mapping: {config_path}")

    args: list[str] = []
    for key in ("host", "port", "user", "password", "dbname", "source", "preferred_source", "state_file"):
        value = payload.get(key)
        if value not in (None, ""):
            args.extend([f"--{key.replace('_', '-')}", str(value)])
    for key in (
        "limit",
        "interval_seconds",
        "iterations",
        "failure_threshold",
        "preferred_probe_every",
        "recovery_threshold",
        "backoff_base_seconds",
        "backoff_max_seconds",
        "off_session_sleep_seconds",
    ):
        value = payload.get(key)
        if value not in (None, ""):
            args.extend([f"--{key.replace('_', '-')}", str(value)])

    if payload.get("continue_on_error", True):
        args.append("--continue-on-error")
    if payload.get("disable_trading_hours_gate", False):
        args.append("--disable-trading-hours-gate")
    return args


def main() -> int:
    parser = argparse.ArgumentParser(description="Legacy wrapper for collector run_realtime_loop")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    forwarded_args = _build_args_from_config(config_path)
    old_argv = sys.argv
    try:
        sys.argv = [old_argv[0], *forwarded_args]
        return run_realtime_loop_main()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())
