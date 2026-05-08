#!/usr/bin/env python3
"""Runtime helpers for collector orchestration and failover state."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_STATE_PATH = Path(__file__).with_name("runtime") / "source_failover_state.json"
DEFAULT_PRIMARY = "eastmoney"
FAILOVER_ORDER = ("eastmoney", "sina")


@dataclass
class SourceFailoverState:
    preferred_source: str = DEFAULT_PRIMARY
    current_primary: str = DEFAULT_PRIMARY
    consecutive_primary_errors: int = 0
    consecutive_preferred_probe_success: int = 0
    last_trade_day_probe_marker: str | None = None
    last_open_fix_date: str | None = None
    last_close_fix_date: str | None = None
    last_collect_slot: str | None = None
    last_non_trading_notice_date: str | None = None
    last_probe_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, payload: dict | None) -> "SourceFailoverState":
        if not payload:
            return cls()
        defaults = cls()
        data = {
            field: payload.get(field, getattr(defaults, field))
            for field in defaults.__dataclass_fields__  # type: ignore[attr-defined]
        }
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()


def load_state(path: str | Path = DEFAULT_STATE_PATH) -> SourceFailoverState:
    state_path = Path(path)
    if not state_path.exists():
        return SourceFailoverState(updated_at=_now_iso())
    try:
        return SourceFailoverState.from_dict(json.loads(state_path.read_text(encoding="utf-8")))
    except Exception:
        return SourceFailoverState(updated_at=_now_iso())


def save_state(state: SourceFailoverState, path: str | Path = DEFAULT_STATE_PATH) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = _now_iso()
    state_path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_source(source: str | None) -> str:
    if not source:
        return DEFAULT_PRIMARY
    candidate = source.strip().lower()
    if candidate not in FAILOVER_ORDER:
        return DEFAULT_PRIMARY
    return candidate


def source_preference_order(preferred_source: str | None) -> list[str]:
    preferred = normalize_source(preferred_source)
    ordered = [preferred]
    for source in FAILOVER_ORDER:
        if source not in ordered:
            ordered.append(source)
    return ordered


def compute_backoff_seconds(error_count: int, base_seconds: int = 3, max_seconds: int = 60) -> int:
    if error_count <= 0:
        return base_seconds
    delay = base_seconds * (2 ** max(error_count - 1, 0))
    return min(max_seconds, max(base_seconds, int(delay)))


def mark_success(
    state: SourceFailoverState,
    source: str,
    batch_id: str | None = None,
    trade_date: str | None = None,
    is_trading_day: bool | None = None,
) -> SourceFailoverState:
    source = normalize_source(source)
    state.current_primary = source
    state.consecutive_primary_errors = 0
    if source == normalize_source(state.preferred_source):
        state.consecutive_preferred_probe_success = 0
    if batch_id:
        state.last_collect_slot = batch_id
    if trade_date:
        if is_trading_day is False:
            state.last_non_trading_notice_date = trade_date
        elif source == "eastmoney":
            state.last_open_fix_date = trade_date
            state.last_close_fix_date = trade_date
    return state


def mark_failure(
    state: SourceFailoverState,
    source: str,
    threshold: int = 3,
) -> tuple[SourceFailoverState, bool]:
    source = normalize_source(source)
    switched = False
    if source == state.current_primary:
        state.consecutive_primary_errors += 1
        if state.consecutive_primary_errors >= max(threshold, 1):
            state.current_primary = next(
                candidate for candidate in FAILOVER_ORDER if candidate != source
            )
            state.consecutive_primary_errors = 0
            switched = True
    else:
        state.consecutive_primary_errors = max(state.consecutive_primary_errors, 1)
    return state, switched


def should_probe_preferred(
    state: SourceFailoverState,
    iteration: int,
    probe_every_iterations: int,
) -> bool:
    if probe_every_iterations <= 0:
        return False
    return (
        normalize_source(state.current_primary) != normalize_source(state.preferred_source)
        and iteration % probe_every_iterations == 0
    )


def mark_preferred_probe(
    state: SourceFailoverState,
    success: bool,
    recovery_threshold: int = 2,
) -> tuple[SourceFailoverState, bool]:
    state.last_probe_at = _now_iso()
    switched = False
    preferred = normalize_source(state.preferred_source)
    if normalize_source(state.current_primary) == preferred:
        state.consecutive_preferred_probe_success = 0
        return state, switched
    if success:
        state.consecutive_preferred_probe_success += 1
        if state.consecutive_preferred_probe_success >= max(recovery_threshold, 1):
            state.current_primary = preferred
            state.consecutive_primary_errors = 0
            state.consecutive_preferred_probe_success = 0
            switched = True
        return state, switched
    state.consecutive_preferred_probe_success = 0
    return state, switched
