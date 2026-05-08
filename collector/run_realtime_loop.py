#!/usr/bin/env python3
"""Run realtime collection in a loop during market hours."""

from __future__ import annotations

import argparse
import datetime as dt
import time
from pathlib import Path

from collect_realtime import probe_source_trade_date, run_collection
from db import PgConfig, add_pg_args, finish_job, log_quality, require_password, start_job
from runtime_control import (
    DEFAULT_STATE_PATH,
    compute_backoff_seconds,
    load_state,
    mark_failure,
    mark_preferred_probe,
    mark_success,
    normalize_source,
    save_state,
    should_probe_preferred,
)

SOFT_FAILURE_STATUSES = {"stale_snapshot", "empty_payload"}
CN_TZ = dt.timezone(dt.timedelta(hours=8))
OFF_SESSION_POLL_SECONDS = 1.0


def in_a_share_trading_session(now: dt.datetime) -> tuple[bool, str]:
    local_now = now.astimezone(CN_TZ)
    current = local_now.timetz().replace(tzinfo=None)
    if dt.time(9, 29, 56) <= current <= dt.time(11, 30, 3):
        return True, "am_session"
    if dt.time(12, 59, 58) <= current <= dt.time(15, 0, 3):
        return True, "pm_session"
    if current < dt.time(9, 29, 56):
        return False, "pre_open"
    if current < dt.time(12, 59, 58):
        return False, "lunch_break"
    return False, "closed"


def main() -> int:
    parser = argparse.ArgumentParser(description="Loop collect_realtime on a fixed interval")
    add_pg_args(parser)
    parser.add_argument("--source", default="eastmoney")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--interval-seconds", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=0, help="0 means infinite loop")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--preferred-source", default="eastmoney")
    parser.add_argument("--failure-threshold", type=int, default=3)
    parser.add_argument("--preferred-probe-every", type=int, default=5)
    parser.add_argument("--recovery-threshold", type=int, default=2)
    parser.add_argument("--backoff-base-seconds", type=int, default=3)
    parser.add_argument("--backoff-max-seconds", type=int, default=60)
    parser.add_argument("--off-session-sleep-seconds", type=int, default=30)
    parser.add_argument("--heartbeat-every-seconds", type=float, default=2.0)
    parser.add_argument("--disable-trading-hours-gate", action="store_true")
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)
    state_path = Path(args.state_file)
    state = load_state(state_path)
    state.preferred_source = normalize_source(args.preferred_source)
    if not state.current_primary:
        state.current_primary = state.preferred_source or normalize_source(args.source)
    soft_failure_streak = 0
    success_count = 0
    non_success_count = 0
    hard_failure_count = 0
    last_gate_phase: str | None = None
    cached_probe_date: dt.date | None = None
    cached_probe_is_trading_day: bool | None = None
    iteration = 0
    heartbeat_every_seconds = max(args.heartbeat_every_seconds, 0.1)
    last_heartbeat_monotonic = 0.0

    def maybe_log_loop_heartbeat(
        reason: str,
        *,
        force: bool = False,
        payload: dict | None = None,
    ) -> None:
        nonlocal last_heartbeat_monotonic
        now_monotonic = time.monotonic()
        if not force and now_monotonic - last_heartbeat_monotonic < heartbeat_every_seconds:
            return
        heartbeat_payload = {
            "iteration": iteration,
            "reason": reason,
            "current_primary": state.current_primary,
            "preferred_source": state.preferred_source,
            "last_collect_slot": state.last_collect_slot,
            "success_count": success_count,
            "non_success_count": non_success_count,
            "hard_failure_count": hard_failure_count,
        }
        if payload:
            heartbeat_payload.update(payload)
        try:
            log_quality(
                config,
                data_domain="realtime_collect",
                issue_type="loop_heartbeat",
                issue_message=f"run_realtime_loop active reason={reason}",
                issue_level="info",
                payload=heartbeat_payload,
            )
            last_heartbeat_monotonic = now_monotonic
        except Exception as exc:  # pragma: no cover
            print(
                "run_realtime_loop heartbeat-log-error",
                f"iteration={iteration}",
                f"reason={reason}",
                f"message={exc}",
            )

    while args.iterations == 0 or iteration < args.iterations:
        iteration += 1
        local_now = dt.datetime.now(CN_TZ)
        today_iso = local_now.date().isoformat()
        if cached_probe_date != local_now.date():
            cached_probe_date = local_now.date()
            cached_probe_is_trading_day = None
        if not args.disable_trading_hours_gate:
            trading_now, gate_phase = in_a_share_trading_session(local_now)
            if trading_now and cached_probe_is_trading_day is not True:
                try:
                    probe_result = probe_source_trade_date(
                        config,
                        preferred_source=state.preferred_source or args.source,
                        limit=1,
                    )
                    probe_trade_date = str(probe_result.get("trade_date") or "")
                    cached_probe_is_trading_day = probe_trade_date == today_iso
                except Exception as exc:  # pragma: no cover
                    cached_probe_is_trading_day = False
                    print(
                        "run_realtime_loop trade-day-probe-error",
                        f"iteration={iteration}",
                        f"message={exc}",
                    )
                if cached_probe_is_trading_day is not True:
                    last_gate_phase = gate_phase
                    time.sleep(OFF_SESSION_POLL_SECONDS)
                    continue
            if not trading_now:
                last_gate_phase = gate_phase
                time.sleep(OFF_SESSION_POLL_SECONDS)
                continue
            if last_gate_phase is not None:
                print(
                    "run_realtime_loop trading-session-resume",
                    f"iteration={iteration}",
                    f"phase={gate_phase}",
                )
                maybe_log_loop_heartbeat(
                    "trading_session_resume",
                    force=True,
                    payload={"phase": gate_phase},
                )
                last_gate_phase = None
        current_source = normalize_source(state.current_primary or args.source)
        if should_probe_preferred(
            state,
            iteration=iteration,
            probe_every_iterations=max(args.preferred_probe_every, 1),
        ):
            try:
                probe_result = run_collection(
                    config,
                    source=state.preferred_source,
                    limit=args.limit,
                    allow_fallback=False,
                )
                probe_status = str(probe_result.get("status") or "unknown")
                probe_success = probe_status == "success"
                state, recovered = mark_preferred_probe(
                    state,
                    success=probe_success,
                    recovery_threshold=max(args.recovery_threshold, 1),
                )
                if probe_success:
                    if recovered:
                        state = mark_success(
                            state,
                            source=state.preferred_source,
                            batch_id=str(probe_result.get("batch_id") or ""),
                        )
                    else:
                        state.last_collect_slot = str(probe_result.get("batch_id") or "")
                save_state(state, state_path)
                print(
                    "run_realtime_loop preferred-probe",
                    f"iteration={iteration}",
                    f"status={probe_status}",
                    f"source={probe_result.get('source', state.preferred_source)}",
                    f"recovered={recovered}",
                    f"fetch_watchlist_seconds={probe_result.get('fetch_watchlist_seconds', 0.0)}",
                    f"latest_state_seconds={probe_result.get('latest_state_seconds', 0.0)}",
                    f"fetch_source_seconds={probe_result.get('fetch_source_seconds', 0.0)}",
                    f"normalize_seconds={probe_result.get('normalize_seconds', 0.0)}",
                    f"upsert_realtime_quotes_seconds={probe_result.get('upsert_realtime_quotes_seconds', 0.0)}",
                    f"aggregate_1m_seconds={probe_result.get('aggregate_1m_seconds', 0.0)}",
                    f"aggregate_multi_period_seconds={probe_result.get('aggregate_multi_period_seconds', 0.0)}",
                    f"total_seconds={probe_result.get('total_seconds', 0.0)}",
                )
                if not probe_success:
                    non_success_count += 1
                maybe_log_loop_heartbeat(
                    "preferred_probe",
                    payload={
                        "probe_status": probe_status,
                        "probe_source": str(probe_result.get("source", state.preferred_source)),
                        "probe_recovered": recovered,
                    },
                )
                if probe_success:
                    continue
            except Exception as exc:  # pragma: no cover
                non_success_count += 1
                log_quality(
                    config,
                    data_domain="realtime_collect",
                    issue_type="preferred_probe_error",
                    issue_message=str(exc),
                    issue_level="warn",
                    payload={"iteration": iteration, "source": state.preferred_source},
                )
                state, _ = mark_preferred_probe(
                    state,
                    success=False,
                    recovery_threshold=max(args.recovery_threshold, 1),
                )
                save_state(state, state_path)
                print(
                    "run_realtime_loop preferred-probe-error",
                    f"iteration={iteration}",
                    f"source={state.preferred_source}",
                    f"message={exc}",
                )
                maybe_log_loop_heartbeat(
                    "preferred_probe_error",
                    force=True,
                    payload={"probe_source": state.preferred_source},
                )
        collect_job_run_id: int | None = None
        try:
            collect_job_run_id = start_job(
                config,
                job_name="collect_realtime",
                job_type="collector",
                run_date=dt.datetime.now(CN_TZ).date(),
            )
            result = run_collection(
                config,
                source=current_source,
                limit=args.limit,
                allow_fallback=False,
            )
            resolved_source = str(result.get("source") or current_source)
            result_status = str(result.get("status") or "unknown")
            if result_status != "success":
                non_success_count += 1
                finish_job(
                    config,
                    job_run_id=collect_job_run_id,
                    status="partial",
                    processed_count=int(result.get("row_count") or 0),
                    error_message=result_status,
                )
                if result_status in SOFT_FAILURE_STATUSES:
                    soft_failure_streak += 1
                    backoff_seconds = compute_backoff_seconds(
                        soft_failure_streak,
                        base_seconds=max(args.backoff_base_seconds, 1),
                        max_seconds=max(args.backoff_max_seconds, 1),
                    )
                    print(
                        "run_realtime_loop soft-fail",
                        f"iteration={iteration}",
                        f"status={result_status}",
                        f"source={resolved_source}",
                        f"soft_streak={soft_failure_streak}",
                        f"backoff_seconds={backoff_seconds}",
                        f"batch_id={result.get('batch_id', '')}",
                        f"fetch_watchlist_seconds={result.get('fetch_watchlist_seconds', 0.0)}",
                        f"latest_state_seconds={result.get('latest_state_seconds', 0.0)}",
                        f"fetch_source_seconds={result.get('fetch_source_seconds', 0.0)}",
                        f"normalize_seconds={result.get('normalize_seconds', 0.0)}",
                        f"upsert_realtime_quotes_seconds={result.get('upsert_realtime_quotes_seconds', 0.0)}",
                        f"aggregate_1m_seconds={result.get('aggregate_1m_seconds', 0.0)}",
                        f"aggregate_multi_period_seconds={result.get('aggregate_multi_period_seconds', 0.0)}",
                        f"total_seconds={result.get('total_seconds', 0.0)}",
                    )
                    maybe_log_loop_heartbeat(
                        "soft_fail",
                        payload={
                            "status": result_status,
                            "source": resolved_source,
                            "batch_id": str(result.get("batch_id") or ""),
                            "soft_failure_streak": soft_failure_streak,
                        },
                    )
                    time.sleep(backoff_seconds)
                    continue
                soft_failure_streak = 0
                save_state(state, state_path)
                print(
                    "run_realtime_loop skip",
                    f"iteration={iteration}",
                    f"status={result_status}",
                    f"source={resolved_source}",
                    f"batch_id={result.get('batch_id', '')}",
                    f"fetch_watchlist_seconds={result.get('fetch_watchlist_seconds', 0.0)}",
                    f"latest_state_seconds={result.get('latest_state_seconds', 0.0)}",
                    f"fetch_source_seconds={result.get('fetch_source_seconds', 0.0)}",
                    f"normalize_seconds={result.get('normalize_seconds', 0.0)}",
                    f"upsert_realtime_quotes_seconds={result.get('upsert_realtime_quotes_seconds', 0.0)}",
                    f"aggregate_1m_seconds={result.get('aggregate_1m_seconds', 0.0)}",
                    f"aggregate_multi_period_seconds={result.get('aggregate_multi_period_seconds', 0.0)}",
                    f"total_seconds={result.get('total_seconds', 0.0)}",
                )
                maybe_log_loop_heartbeat(
                    "non_success_skip",
                    payload={
                        "status": result_status,
                        "source": resolved_source,
                        "batch_id": str(result.get("batch_id") or ""),
                    },
                )
                continue

            finish_job(
                config,
                job_run_id=collect_job_run_id,
                status="success",
                processed_count=int(result.get("row_count") or 0),
                error_message=None,
            )
            state = mark_success(
                state,
                source=resolved_source,
                batch_id=str(result.get("batch_id") or ""),
            )
            soft_failure_streak = 0
            success_count += 1
            save_state(state, state_path)
            print(
                "run_realtime_loop tick",
                f"iteration={iteration}",
                f"rows={result['row_count']}",
                f"batch_id={result['batch_id']}",
                f"source={resolved_source}",
                f"fetch_watchlist_seconds={result.get('fetch_watchlist_seconds', 0.0)}",
                f"latest_state_seconds={result.get('latest_state_seconds', 0.0)}",
                f"fetch_source_seconds={result.get('fetch_source_seconds', 0.0)}",
                f"normalize_seconds={result.get('normalize_seconds', 0.0)}",
                f"upsert_realtime_quotes_seconds={result.get('upsert_realtime_quotes_seconds', 0.0)}",
                f"aggregate_1m_seconds={result.get('aggregate_1m_seconds', 0.0)}",
                f"aggregate_multi_period_seconds={result.get('aggregate_multi_period_seconds', 0.0)}",
                f"total_seconds={result.get('total_seconds', 0.0)}",
            )
            maybe_log_loop_heartbeat(
                "tick",
                payload={
                    "rows": int(result["row_count"]),
                    "batch_id": str(result["batch_id"]),
                    "source": resolved_source,
                },
            )
        except KeyboardInterrupt:
            if collect_job_run_id is not None:
                finish_job(
                    config,
                    job_run_id=collect_job_run_id,
                    status="partial",
                    processed_count=0,
                    error_message="interrupted",
                )
            maybe_log_loop_heartbeat(
                "keyboard_interrupt",
                force=True,
                payload={"source": current_source},
            )
            return 130
        except Exception as exc:  # pragma: no cover
            non_success_count += 1
            hard_failure_count += 1
            soft_failure_streak = 0
            if collect_job_run_id is not None:
                finish_job(
                    config,
                    job_run_id=collect_job_run_id,
                    status="error",
                    processed_count=0,
                    error_message=str(exc),
                )
            log_quality(
                config,
                data_domain="realtime_collect",
                issue_type="loop_error",
                issue_message=str(exc),
                issue_level="error",
                payload={"iteration": iteration, "source": current_source},
            )
            state, switched = mark_failure(
                state,
                source=current_source,
                threshold=max(args.failure_threshold, 1),
            )
            save_state(state, state_path)
            backoff_seconds = compute_backoff_seconds(
                state.consecutive_primary_errors or 1,
                base_seconds=max(args.backoff_base_seconds, 1),
                max_seconds=max(args.backoff_max_seconds, 1),
            )
            print(
                "run_realtime_loop error",
                f"iteration={iteration}",
                f"source={current_source}",
                f"switched={switched}",
                f"backoff_seconds={backoff_seconds}",
                f"message={exc}",
            )
            maybe_log_loop_heartbeat(
                "loop_error",
                force=True,
                payload={"source": current_source, "switched": switched},
            )
            if not args.continue_on_error:
                raise
            time.sleep(backoff_seconds)
            continue

    maybe_log_loop_heartbeat(
        "loop_stopped",
        force=True,
        payload={"status": "completed", "iterations": iteration},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
