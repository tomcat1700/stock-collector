#!/usr/bin/env python3
"""Apply period-aware trading-day retention cleanup for public.kline_minute."""

from __future__ import annotations

import argparse
import datetime as dt

from db import PgConfig, add_pg_args, finish_job, psql_execute, psql_query, require_password, sql_quote, start_job


ONE_MINUTE_PERIODS = (1,)
MULTI_PERIODS = (5, 15, 30, 60)


def sql_int_list(values: tuple[int, ...]) -> str:
    return ", ".join(str(value) for value in values)


def fetch_recent_trade_dates(
    config: PgConfig,
    periods: tuple[int, ...],
    retention_trading_days: int,
) -> list[dt.date]:
    rows = psql_query(
        config,
        f"""
        SELECT trade_date::text AS trade_date
        FROM (
            SELECT DISTINCT trade_date
            FROM public.kline_minute
            WHERE trade_date IS NOT NULL
              AND period IN ({sql_int_list(periods)})
            ORDER BY trade_date DESC
            LIMIT {retention_trading_days}
        ) recent_dates
        ORDER BY trade_date DESC;
        """,
    )
    return [dt.date.fromisoformat(row["trade_date"]) for row in rows]


def period_boundary(
    retained_dates: list[dt.date],
    retention_trading_days: int,
) -> dt.date | None:
    if len(retained_dates) < retention_trading_days:
        return None
    return retained_dates[-1]


def stale_predicate(
    one_minute_boundary: dt.date | None,
    multi_period_boundary: dt.date | None,
) -> str:
    clauses = ["trade_date IS NULL"]
    if one_minute_boundary is not None:
        clauses.append(f"(period = 1 AND trade_date < DATE {sql_quote(one_minute_boundary.isoformat())})")
    if multi_period_boundary is not None:
        clauses.append(
            f"(period IN ({sql_int_list(MULTI_PERIODS)}) "
            f"AND trade_date < DATE {sql_quote(multi_period_boundary.isoformat())})"
        )
    return " OR ".join(clauses)


def fetch_stale_summary(
    config: PgConfig,
    one_minute_boundary: dt.date | None,
    multi_period_boundary: dt.date | None,
) -> list[dict[str, str]]:
    return psql_query(
        config,
        f"""
        SELECT
            period::text AS period,
            COALESCE(trade_date::text, '<NULL>') AS trade_date,
            count(*)::bigint AS row_count
        FROM public.kline_minute
        WHERE {stale_predicate(one_minute_boundary, multi_period_boundary)}
        GROUP BY period, trade_date
        ORDER BY period, trade_date NULLS FIRST;
        """,
    )


def delete_stale_rows(
    config: PgConfig,
    one_minute_boundary: dt.date | None,
    multi_period_boundary: dt.date | None,
    batch_size: int,
    max_batches: int | None,
) -> int:
    total_deleted = 0
    batches = 0
    predicate = stale_predicate(one_minute_boundary, multi_period_boundary)

    while True:
        if max_batches is not None and batches >= max_batches:
            break

        rows = psql_query(
            config,
            f"""
            WITH stale AS (
                SELECT instrument_id, bar_time, period
                FROM public.kline_minute
                WHERE {predicate}
                ORDER BY trade_date NULLS FIRST, period, bar_time
                LIMIT {batch_size}
            ),
            deleted AS (
                DELETE FROM public.kline_minute AS k
                USING stale
                WHERE k.instrument_id = stale.instrument_id
                  AND k.bar_time = stale.bar_time
                  AND k.period = stale.period
                RETURNING 1
            )
            SELECT count(*)::bigint AS deleted_count
            FROM deleted;
            """,
        )
        deleted_count = int(rows[0]["deleted_count"])
        if deleted_count == 0:
            break

        total_deleted += deleted_count
        batches += 1
        print(
            "cleanup_kline_minute batch",
            f"batch={batches}",
            f"deleted={deleted_count}",
            f"total_deleted={total_deleted}",
        )

    return total_deleted


def vacuum_kline_minute(config: PgConfig) -> None:
    psql_execute(config, "VACUUM (ANALYZE) public.kline_minute;")


def print_plan(
    one_minute_trading_days: int,
    one_minute_dates: list[dt.date],
    one_minute_boundary: dt.date | None,
    multi_period_trading_days: int,
    multi_period_dates: list[dt.date],
    multi_period_boundary: dt.date | None,
    stale_summary: list[dict[str, str]],
    dry_run: bool,
) -> int:
    stale_rows = sum(int(row["row_count"]) for row in stale_summary)
    print(
        "cleanup_kline_minute plan",
        f"dry_run={dry_run}",
        f"one_minute_trading_days={one_minute_trading_days}",
        "one_minute_retained_trade_dates=" + ",".join(day.isoformat() for day in one_minute_dates),
        f"one_minute_boundary={one_minute_boundary.isoformat() if one_minute_boundary else '<not_enough_dates>'}",
        f"multi_period_trading_days={multi_period_trading_days}",
        "multi_period_retained_trade_dates=" + ",".join(day.isoformat() for day in multi_period_dates),
        f"multi_period_boundary={multi_period_boundary.isoformat() if multi_period_boundary else '<not_enough_dates>'}",
        f"stale_rows={stale_rows}",
    )
    if stale_summary:
        stale_dates = ",".join(f"period={row['period']}:{row['trade_date']}:{row['row_count']}" for row in stale_summary)
        print("cleanup_kline_minute stale_trade_dates", stale_dates)
    else:
        print("cleanup_kline_minute stale_trade_dates <none>")
    return stale_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup kline_minute by retained trading-day count")
    add_pg_args(parser)
    parser.add_argument("--one-minute-trading-days", type=int, default=45)
    parser.add_argument("--multi-period-trading-days", type=int, default=120)
    parser.add_argument("--retention-trading-days", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--batch-size", type=int, default=50_000)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--vacuum", action="store_true")
    args = parser.parse_args()

    if args.retention_trading_days is not None:
        args.one_minute_trading_days = args.retention_trading_days
    if args.one_minute_trading_days < 1:
        raise SystemExit("--one-minute-trading-days must be >= 1")
    if args.multi_period_trading_days < 1:
        raise SystemExit("--multi-period-trading-days must be >= 1")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")

    config = PgConfig.from_args(args)
    require_password(config)

    one_minute_dates = fetch_recent_trade_dates(config, ONE_MINUTE_PERIODS, args.one_minute_trading_days)
    one_minute_boundary = period_boundary(one_minute_dates, args.one_minute_trading_days)
    multi_period_dates = fetch_recent_trade_dates(config, MULTI_PERIODS, args.multi_period_trading_days)
    multi_period_boundary = period_boundary(multi_period_dates, args.multi_period_trading_days)
    stale_summary = fetch_stale_summary(config, one_minute_boundary, multi_period_boundary)
    stale_rows = print_plan(
        one_minute_trading_days=args.one_minute_trading_days,
        one_minute_dates=one_minute_dates,
        one_minute_boundary=one_minute_boundary,
        multi_period_trading_days=args.multi_period_trading_days,
        multi_period_dates=multi_period_dates,
        multi_period_boundary=multi_period_boundary,
        stale_summary=stale_summary,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        return 0

    job_run_id = start_job(config, job_name="cleanup_kline_minute", job_type="maintenance")
    try:
        residual_deleted = delete_stale_rows(
            config,
            one_minute_boundary=one_minute_boundary,
            multi_period_boundary=multi_period_boundary,
            batch_size=args.batch_size,
            max_batches=args.max_batches,
        )
        if args.vacuum:
            vacuum_kline_minute(config)
        finish_job(config, job_run_id, status="success", processed_count=residual_deleted)
        print(
            "cleanup_kline_minute completed",
            f"one_minute_trading_days={args.one_minute_trading_days}",
            f"one_minute_boundary={one_minute_boundary.isoformat() if one_minute_boundary else '<not_enough_dates>'}",
            f"multi_period_trading_days={args.multi_period_trading_days}",
            f"multi_period_boundary={multi_period_boundary.isoformat() if multi_period_boundary else '<not_enough_dates>'}",
            f"residual_deleted={residual_deleted}",
            f"processed_count={residual_deleted}",
            f"vacuum={args.vacuum}",
        )
        return 0
    except Exception as exc:  # pragma: no cover
        finish_job(config, job_run_id, status="error", processed_count=0, error_message=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
