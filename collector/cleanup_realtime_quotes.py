#!/usr/bin/env python3
"""Apply trading-day retention cleanup for public.realtime_quotes."""

from __future__ import annotations

import argparse
import datetime as dt

from db import PgConfig, add_pg_args, finish_job, psql_execute, psql_query, require_password, sql_quote, start_job


def fetch_recent_trade_dates(config: PgConfig, retention_trading_days: int) -> list[dt.date]:
    rows = psql_query(
        config,
        f"""
        SELECT trade_date::text AS trade_date
        FROM (
            SELECT DISTINCT trade_date
            FROM public.realtime_quotes
            WHERE trade_date IS NOT NULL
            ORDER BY trade_date DESC
            LIMIT {retention_trading_days}
        ) recent_dates
        ORDER BY trade_date DESC;
        """,
    )
    return [dt.date.fromisoformat(row["trade_date"]) for row in rows]


def cutoff_timestamp(boundary_trade_date: dt.date) -> str:
    return f"{boundary_trade_date.isoformat()} 00:00:00+08"


def stale_predicate(boundary_trade_date: dt.date | None) -> str:
    if boundary_trade_date is None:
        return "trade_date IS NULL"
    return f"trade_date < DATE {sql_quote(boundary_trade_date.isoformat())} OR trade_date IS NULL"


def fetch_stale_summary(
    config: PgConfig,
    boundary_trade_date: dt.date | None,
) -> list[dict[str, str]]:
    return psql_query(
        config,
        f"""
        SELECT
            COALESCE(trade_date::text, '<NULL>') AS trade_date,
            count(*)::bigint AS row_count
        FROM public.realtime_quotes
        WHERE {stale_predicate(boundary_trade_date)}
        GROUP BY trade_date
        ORDER BY trade_date NULLS FIRST;
        """,
    )


def drop_old_chunks(config: PgConfig, boundary_trade_date: dt.date) -> int:
    rows = psql_query(
        config,
        f"""
        SELECT count(*)::int AS dropped_chunks
        FROM drop_chunks(
            'public.realtime_quotes'::regclass,
            older_than => TIMESTAMPTZ {sql_quote(cutoff_timestamp(boundary_trade_date))}
        );
        """,
    )
    return int(rows[0]["dropped_chunks"])


def delete_stale_rows(
    config: PgConfig,
    boundary_trade_date: dt.date | None,
    batch_size: int,
    max_batches: int | None,
) -> int:
    total_deleted = 0
    batches = 0
    predicate = stale_predicate(boundary_trade_date)

    while True:
        if max_batches is not None and batches >= max_batches:
            break

        rows = psql_query(
            config,
            f"""
            WITH deleted AS (
                DELETE FROM public.realtime_quotes
                WHERE ctid IN (
                    SELECT ctid
                    FROM public.realtime_quotes
                    WHERE {predicate}
                    ORDER BY trade_date NULLS FIRST, quote_time
                    LIMIT {batch_size}
                )
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
            "cleanup_realtime_quotes batch",
            f"batch={batches}",
            f"deleted={deleted_count}",
            f"total_deleted={total_deleted}",
        )

    return total_deleted


def vacuum_realtime_quotes(config: PgConfig) -> None:
    psql_execute(config, "VACUUM (ANALYZE) public.realtime_quotes;")


def print_plan(
    retention_trading_days: int,
    retained_dates: list[dt.date],
    boundary_trade_date: dt.date | None,
    stale_summary: list[dict[str, str]],
    dry_run: bool,
) -> int:
    stale_rows = sum(int(row["row_count"]) for row in stale_summary)
    print(
        "cleanup_realtime_quotes plan",
        f"dry_run={dry_run}",
        f"retention_trading_days={retention_trading_days}",
        "retained_trade_dates=" + ",".join(day.isoformat() for day in retained_dates),
        f"boundary_trade_date={boundary_trade_date.isoformat() if boundary_trade_date else '<not_enough_dates>'}",
        f"stale_rows={stale_rows}",
    )
    if stale_summary:
        stale_dates = ",".join(f"{row['trade_date']}:{row['row_count']}" for row in stale_summary)
        print("cleanup_realtime_quotes stale_trade_dates", stale_dates)
    else:
        print("cleanup_realtime_quotes stale_trade_dates <none>")
    return stale_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup realtime_quotes by retained trading-day count")
    add_pg_args(parser)
    parser.add_argument("--retention-trading-days", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=50_000)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--vacuum", action="store_true")
    args = parser.parse_args()

    if args.retention_trading_days < 1:
        raise SystemExit("--retention-trading-days must be >= 1")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")

    config = PgConfig.from_args(args)
    require_password(config)

    retained_dates = fetch_recent_trade_dates(config, args.retention_trading_days)
    boundary_trade_date = retained_dates[-1] if len(retained_dates) >= args.retention_trading_days else None
    stale_summary = fetch_stale_summary(config, boundary_trade_date)
    stale_rows = print_plan(
        retention_trading_days=args.retention_trading_days,
        retained_dates=retained_dates,
        boundary_trade_date=boundary_trade_date,
        stale_summary=stale_summary,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        return 0

    job_run_id = start_job(config, job_name="cleanup_realtime_quotes", job_type="maintenance")
    try:
        dropped_chunks = drop_old_chunks(config, boundary_trade_date) if boundary_trade_date else 0
        residual_deleted = delete_stale_rows(
            config,
            boundary_trade_date=boundary_trade_date,
            batch_size=args.batch_size,
            max_batches=args.max_batches,
        )
        if args.vacuum:
            vacuum_realtime_quotes(config)
        processed_count = stale_rows if dropped_chunks else residual_deleted
        finish_job(config, job_run_id, status="success", processed_count=processed_count)
        print(
            "cleanup_realtime_quotes completed",
            f"retention_trading_days={args.retention_trading_days}",
            f"boundary_trade_date={boundary_trade_date.isoformat() if boundary_trade_date else '<not_enough_dates>'}",
            f"dropped_chunks={dropped_chunks}",
            f"residual_deleted={residual_deleted}",
            f"processed_count={processed_count}",
            f"vacuum={args.vacuum}",
        )
        return 0
    except Exception as exc:  # pragma: no cover
        finish_job(config, job_run_id, status="error", processed_count=0, error_message=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
