#!/usr/bin/env python3
"""Add recent SH/SZ listings to the collector watchlist."""

from __future__ import annotations

import argparse

from db import PgConfig, add_pg_args, finish_job, psql_query, require_password, start_job


def add_new_listings_to_pool(
    config: PgConfig,
    min_listing_days: int,
    lookback_days: int,
) -> int:
    rows = psql_query(
        config,
        f"""
        WITH candidates AS (
            SELECT i.instrument_id
            FROM public.instruments i
            LEFT JOIN public.collector_watchlist cw
                ON cw.instrument_id = i.instrument_id
            WHERE cw.instrument_id IS NULL
              AND i.type = 'stock'
              AND COALESCE(i.status, 'active') = 'active'
              AND i.market IN ('SH', 'SZ')
              AND i.list_date IS NOT NULL
              AND i.list_date <= current_date - {min_listing_days}
              AND i.list_date >= current_date - {lookback_days}
              AND i.code ~ '^[0-9]{{6}}$'
        ),
        inserted AS (
            INSERT INTO public.collector_watchlist (
                instrument_id,
                name,
                instrument_type
            )
            SELECT
                instrument_id,
                (SELECT name FROM public.instruments i WHERE i.instrument_id = candidates.instrument_id),
                'stock'
            FROM candidates
            ORDER BY instrument_id
            ON CONFLICT (instrument_id) DO NOTHING
            RETURNING instrument_id
        )
        SELECT count(*) AS inserted_count
        FROM inserted;
        """,
    )
    return int(rows[0]["inserted_count"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Add recent SH/SZ new listings to collector watchlist")
    add_pg_args(parser)
    parser.add_argument("--min-listing-days", type=int, default=5)
    parser.add_argument("--lookback-days", type=int, default=30)
    args = parser.parse_args()

    if args.min_listing_days < 0:
        raise SystemExit("--min-listing-days must be >= 0")
    if args.lookback_days < args.min_listing_days:
        raise SystemExit("--lookback-days must be >= --min-listing-days")

    config = PgConfig.from_args(args)
    require_password(config)

    job_run_id = start_job(config, job_name="add_new_listings_to_pool", job_type="collector")
    try:
        inserted_count = add_new_listings_to_pool(
            config,
            min_listing_days=args.min_listing_days,
            lookback_days=args.lookback_days,
        )
        finish_job(config, job_run_id, status="success", processed_count=inserted_count)
        print(
            "add_new_listings_to_pool completed",
            f"min_listing_days={args.min_listing_days}",
            f"lookback_days={args.lookback_days}",
            f"inserted={inserted_count}",
        )
        return 0
    except Exception as exc:  # pragma: no cover
        finish_job(config, job_run_id, status="error", processed_count=0, error_message=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
