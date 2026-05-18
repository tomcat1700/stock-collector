#!/usr/bin/env python3
"""Calculate system-owned daily MA indicators from local daily bars."""

from __future__ import annotations

import argparse
import datetime as dt
import re

from db import PgConfig, add_pg_args, finish_job, psql_execute, require_password, start_job


MA_WINDOWS = (5, 10, 20, 55, 233)


def date_filter_sql(date_from: dt.date | None, date_to: dt.date | None) -> str:
    clauses: list[str] = []
    if date_from:
        clauses.append(f"trade_date >= '{date_from.isoformat()}'")
    if date_to:
        clauses.append(f"trade_date <= '{date_to.isoformat()}'")
    if not clauses:
        return "TRUE"
    return " AND ".join(clauses)


def build_calculate_sql(
    date_from: dt.date | None,
    date_to: dt.date | None,
    is_final: bool,
) -> str:
    final_sql = "true" if is_final else "false"
    target_filter = date_filter_sql(date_from, date_to)
    return f"""
WITH latest_adj AS (
    SELECT DISTINCT ON (instrument_id)
        instrument_id,
        trade_date AS adjustment_anchor_date,
        adj_factor AS latest_adj_factor
    FROM public.daily_adj_factor
    ORDER BY instrument_id, trade_date DESC
),
base AS (
    SELECT
        kd.instrument_id,
        kd.trade_date,
        CASE
            WHEN i.type = 'stock' THEN 'qfq_close'
            WHEN i.type = 'index' THEN 'close'
            ELSE 'close'
        END AS price_basis,
        CASE
            WHEN i.type = 'stock' THEN la.adjustment_anchor_date
            ELSE NULL::date
        END AS adjustment_anchor_date,
        CASE
            WHEN i.type = 'stock'
                 AND daf.adj_factor IS NOT NULL
                 AND la.latest_adj_factor IS NOT NULL
                 AND la.latest_adj_factor <> 0
                THEN kd.close * daf.adj_factor / la.latest_adj_factor
            WHEN i.type = 'index'
                THEN kd.close
            ELSE NULL::numeric
        END AS basis_close
    FROM public.kline_daily kd
    JOIN public.instruments i
        ON i.instrument_id = kd.instrument_id
    LEFT JOIN public.daily_adj_factor daf
        ON daf.instrument_id = kd.instrument_id
       AND daf.trade_date = kd.trade_date
    LEFT JOIN latest_adj la
        ON la.instrument_id = kd.instrument_id
    WHERE kd.close IS NOT NULL
      AND i.type IN ('stock', 'index')
),
windowed AS (
    SELECT
        instrument_id,
        trade_date,
        price_basis,
        adjustment_anchor_date,
        CASE WHEN count(basis_close) OVER w5 = 5
            THEN round(avg(basis_close) OVER w5, 6) END AS ma5,
        CASE WHEN count(basis_close) OVER w10 = 10
            THEN round(avg(basis_close) OVER w10, 6) END AS ma10,
        CASE WHEN count(basis_close) OVER w20 = 20
            THEN round(avg(basis_close) OVER w20, 6) END AS ma20,
        CASE WHEN count(basis_close) OVER w55 = 55
            THEN round(avg(basis_close) OVER w55, 6) END AS ma55,
        CASE WHEN count(basis_close) OVER w233 = 233
            THEN round(avg(basis_close) OVER w233, 6) END AS ma233
    FROM base
    WINDOW
        w5 AS (PARTITION BY instrument_id, price_basis ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
        w10 AS (PARTITION BY instrument_id, price_basis ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
        w20 AS (PARTITION BY instrument_id, price_basis ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
        w55 AS (PARTITION BY instrument_id, price_basis ORDER BY trade_date ROWS BETWEEN 54 PRECEDING AND CURRENT ROW),
        w233 AS (PARTITION BY instrument_id, price_basis ORDER BY trade_date ROWS BETWEEN 232 PRECEDING AND CURRENT ROW)
),
target_rows AS (
    SELECT *
    FROM windowed
    WHERE {target_filter}
)
INSERT INTO public.daily_indicator (
    instrument_id,
    trade_date,
    price_basis,
    adjustment_anchor_date,
    ma5,
    ma10,
    ma20,
    ma55,
    ma233,
    is_final,
    source,
    version,
    calculated_at,
    updated_at
)
SELECT
    instrument_id,
    trade_date,
    price_basis,
    adjustment_anchor_date,
    ma5,
    ma10,
    ma20,
    ma55,
    ma233,
    {final_sql},
    'system_ma',
    1,
    now(),
    now()
FROM target_rows
ON CONFLICT (instrument_id, trade_date, price_basis) DO UPDATE SET
    adjustment_anchor_date = EXCLUDED.adjustment_anchor_date,
    ma5 = EXCLUDED.ma5,
    ma10 = EXCLUDED.ma10,
    ma20 = EXCLUDED.ma20,
    ma55 = EXCLUDED.ma55,
    ma233 = EXCLUDED.ma233,
    is_final = EXCLUDED.is_final,
    source = EXCLUDED.source,
    version = EXCLUDED.version,
    calculated_at = EXCLUDED.calculated_at,
    updated_at = EXCLUDED.updated_at;
"""


def parse_inserted_count(stdout: str) -> int:
    matches = re.findall(r"INSERT\s+0\s+(\d+)", stdout)
    if not matches:
        return 0
    return int(matches[-1])


def run_calculate(
    config: PgConfig,
    date_from: dt.date | None,
    date_to: dt.date | None,
    is_final: bool,
) -> int:
    result = psql_execute(config, build_calculate_sql(date_from, date_to, is_final))
    return parse_inserted_count(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate public.daily_indicator MA values")
    add_pg_args(parser)
    parser.add_argument("--trade-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--date-from", default=None, help="YYYY-MM-DD")
    parser.add_argument("--date-to", default=None, help="YYYY-MM-DD")
    parser.add_argument("--all", action="store_true", help="Calculate all kline_daily dates")
    parser.add_argument("--is-final", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    if args.trade_date and (args.date_from or args.date_to or args.all):
        raise SystemExit("--trade-date cannot be combined with date range or --all")
    if args.all and (args.date_from or args.date_to):
        raise SystemExit("--all cannot be combined with date range")

    if args.trade_date:
        date_from = date_to = dt.date.fromisoformat(args.trade_date)
    elif args.all:
        date_from = date_to = None
    elif args.date_from and args.date_to:
        date_from = dt.date.fromisoformat(args.date_from)
        date_to = dt.date.fromisoformat(args.date_to)
    else:
        raise SystemExit("Provide --trade-date, --date-from/--date-to, or --all")

    config = PgConfig.from_args(args)
    require_password(config)

    run_date = date_to or date_from
    job_run_id = start_job(
        config,
        job_name="calculate_daily_indicator",
        job_type="collector",
        run_date=run_date,
    )
    try:
        processed_count = run_calculate(config, date_from, date_to, args.is_final)
        finish_job(config, job_run_id, status="success", processed_count=processed_count)
        print(
            "calculate_daily_indicator completed",
            f"date_from={date_from.isoformat() if date_from else 'all'}",
            f"date_to={date_to.isoformat() if date_to else 'all'}",
            f"is_final={args.is_final}",
            f"rows={processed_count}",
        )
        return 0
    except Exception as exc:  # pragma: no cover
        finish_job(config, job_run_id, status="error", processed_count=0, error_message=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
