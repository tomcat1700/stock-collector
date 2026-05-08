#!/usr/bin/env python3
"""Run minute aggregation on its own schedule from public.realtime_quotes."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from db import PgConfig, add_pg_args, finish_job, psql_query, require_password, start_job

CN_TZ = dt.timezone(dt.timedelta(hours=8))
DEFAULT_STATE_PATH = Path(__file__).with_name("runtime") / "minute_aggregation_state.json"


@dataclass
class MinuteAggregationState:
    last_1m_slot: str | None = None
    last_5m_slot: str | None = None
    last_15m_slot: str | None = None
    last_30m_slot: str | None = None
    last_60m_slot: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, payload: dict | None) -> "MinuteAggregationState":
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
    return dt.datetime.now(CN_TZ).isoformat()


def load_state(path: str | Path = DEFAULT_STATE_PATH) -> MinuteAggregationState:
    state_path = Path(path)
    if not state_path.exists():
        return MinuteAggregationState(updated_at=_now_iso())
    try:
        return MinuteAggregationState.from_dict(json.loads(state_path.read_text(encoding="utf-8")))
    except Exception:
        return MinuteAggregationState(updated_at=_now_iso())


def save_state(state: MinuteAggregationState, path: str | Path = DEFAULT_STATE_PATH) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = _now_iso()
    state_path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def in_a_share_trading_session(now: dt.datetime) -> bool:
    current = now.astimezone(CN_TZ).timetz().replace(tzinfo=None)
    return (
        dt.time(9, 29, 56) <= current <= dt.time(11, 30, 3)
        or dt.time(12, 59, 58) <= current <= dt.time(15, 0, 3)
    )


def local_slot(now: dt.datetime) -> str:
    return now.astimezone(CN_TZ).strftime("%Y-%m-%dT%H:%M")


def should_run_1m(now: dt.datetime, state: MinuteAggregationState) -> bool:
    local_now = now.astimezone(CN_TZ)
    current = local_now.timetz().replace(tzinfo=None)
    if current in {dt.time(9, 30), dt.time(13, 0)}:
        return False
    slot = local_slot(local_now)
    return state.last_1m_slot != slot


def should_run_5m(now: dt.datetime, state: MinuteAggregationState) -> bool:
    local_now = now.astimezone(CN_TZ)
    current = local_now.timetz().replace(tzinfo=None)
    slot = local_slot(local_now)
    if current in {dt.time(9, 30), dt.time(13, 0)}:
        return False
    if local_now.minute % 5 != 0:
        return False
    return state.last_5m_slot != slot


def should_run_15m(now: dt.datetime, state: MinuteAggregationState) -> bool:
    local_now = now.astimezone(CN_TZ)
    slot = local_slot(local_now)
    if (local_now.hour, local_now.minute) in {(9, 30), (13, 0)}:
        return False
    if local_now.minute % 15 != 0:
        return False
    return state.last_15m_slot != slot


def should_run_30m(now: dt.datetime, state: MinuteAggregationState) -> bool:
    local_now = now.astimezone(CN_TZ)
    slot = local_slot(local_now)
    if (local_now.hour, local_now.minute) in {(9, 30), (13, 0)}:
        return False
    if local_now.minute not in {0, 30}:
        return False
    return state.last_30m_slot != slot


def should_run_60m(now: dt.datetime, state: MinuteAggregationState) -> bool:
    local_now = now.astimezone(CN_TZ)
    slot = local_slot(local_now)
    if (local_now.hour, local_now.minute) not in {(10, 30), (11, 30), (14, 0), (15, 0)}:
        return False
    return state.last_60m_slot != slot


def run_aggregate_function(config: PgConfig, function_name: str, lookback_minutes: int) -> int:
    rows = psql_query(
        config,
        f"SELECT public.{function_name}({lookback_minutes}) AS updated_count;",
    )
    return int(rows[0]["updated_count"]) if rows and rows[0].get("updated_count") else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Loop minute aggregation from realtime_quotes")
    add_pg_args(parser)
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--iterations", type=int, default=0, help="0 means infinite loop")
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)
    state_path = Path(args.state_file)
    state = load_state(state_path)
    iteration = 0

    while args.iterations == 0 or iteration < args.iterations:
        iteration += 1
        now = dt.datetime.now(CN_TZ)
        if not in_a_share_trading_session(now):
            save_state(state, state_path)
            dt_sleep = max(args.poll_seconds, 0.1)
            import time

            time.sleep(dt_sleep)
            continue

        scheduled: list[tuple[str, int, str]] = []
        slot = local_slot(now)
        if should_run_1m(now, state):
            scheduled.append(("aggregate_1min_kline", 10, "last_1m_slot"))
        if should_run_5m(now, state):
            scheduled.append(("aggregate_5min_kline", 60, "last_5m_slot"))
        if should_run_15m(now, state):
            scheduled.append(("aggregate_15min_kline", 180, "last_15m_slot"))
        if should_run_30m(now, state):
            scheduled.append(("aggregate_30min_kline", 240, "last_30m_slot"))
        if should_run_60m(now, state):
            scheduled.append(("aggregate_60min_kline", 480, "last_60m_slot"))

        if not scheduled:
            save_state(state, state_path)
            import time

            time.sleep(max(args.poll_seconds, 0.1))
            continue

        job_run_id = start_job(
            config,
            job_name="aggregate_kline_minute",
            job_type="collector",
            run_date=now.date(),
        )
        total_updated = 0
        executed: list[str] = []
        try:
            for function_name, lookback_minutes, state_field in scheduled:
                updated = run_aggregate_function(config, function_name, lookback_minutes)
                total_updated += updated
                executed.append(f"{function_name}={updated}")
                setattr(state, state_field, slot)

            save_state(state, state_path)
            finish_job(
                config,
                job_run_id=job_run_id,
                status="success",
                processed_count=total_updated,
                error_message=";".join(executed) if executed else None,
            )
            print(
                "aggregate_kline_minute completed",
                f"slot={slot}",
                f"functions={','.join(executed)}",
                f"total_updated={total_updated}",
            )
        except Exception as exc:  # pragma: no cover
            finish_job(
                config,
                job_run_id=job_run_id,
                status="error",
                processed_count=total_updated,
                error_message=str(exc),
            )
            raise

        import time

        time.sleep(max(args.poll_seconds, 0.1))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
