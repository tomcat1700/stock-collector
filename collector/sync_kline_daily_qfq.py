#!/usr/bin/env python3
"""Precompute forward-adjusted daily stock K-lines into public.kline_daily_qfq."""

from __future__ import annotations

import argparse
import datetime as dt
import re

from db import PgConfig, add_pg_args, finish_job, psql_execute, require_password, sql_quote, start_job


def parse_inserted_count(stdout: str) -> int:
    matches = re.findall(r"INSERT\s+0\s+(\d+)", stdout)
    if not matches:
        return 0
    return int(matches[-1])


def build_full_rebuild_instruments_sql(
    all_rows: bool,
    instrument_ids: list[str],
) -> str:
    if instrument_ids:
        literals = ", ".join(sql_quote(item.strip().upper()) for item in instrument_ids if item.strip())
        if not literals:
            raise ValueError("instrument_ids is empty after trimming")
        return f"""
    SELECT la.instrument_id
    FROM latest_adj la
    JOIN public.instruments i
      ON i.instrument_id = la.instrument_id
    WHERE i.type = 'stock'
      AND la.instrument_id IN ({literals})
"""

    if all_rows:
        return """
    SELECT la.instrument_id
    FROM latest_adj la
    JOIN public.instruments i
      ON i.instrument_id = la.instrument_id
    WHERE i.type = 'stock'
"""

    return """
    -- Stocks whose latest adj_factor anchor changed or have no qfq rows yet.
    -- When anchor_factor changes, the whole history for that stock must be rebuilt.
    SELECT la.instrument_id
    FROM latest_adj la
    JOIN public.instruments i
      ON i.instrument_id = la.instrument_id
    LEFT JOIN existing_anchor ea
      ON ea.instrument_id = la.instrument_id
    WHERE i.type = 'stock'
      AND (
          ea.instrument_id IS NULL
          OR ea.anchor_factor IS DISTINCT FROM la.anchor_factor
      )
"""


def build_date_only_instruments_sql(
    trade_date: dt.date | None,
    all_rows: bool,
    instrument_ids: list[str],
) -> str:
    if trade_date is None or all_rows or instrument_ids:
        return """
    SELECT NULL::character varying(30) AS instrument_id
    WHERE FALSE
"""

    trade_date_sql = sql_quote(trade_date.isoformat())
    return f"""
    -- Stocks with a newly available/changed daily bar for this trade date.
    -- Exclude full-rebuild stocks so normal daily sync only updates the new row.
    SELECT kd.instrument_id
    FROM public.kline_daily kd
    JOIN public.instruments i
      ON i.instrument_id = kd.instrument_id
    WHERE i.type = 'stock'
      AND kd.trade_date = {trade_date_sql}::date
      AND NOT EXISTS (
          SELECT 1
          FROM full_rebuild_instruments fri
          WHERE fri.instrument_id = kd.instrument_id
      )
"""


def build_sync_sql(
    trade_date: dt.date | None,
    all_rows: bool,
    instrument_ids: list[str],
    is_final: bool,
) -> str:
    final_sql = "true" if is_final else "false"
    full_targets_sql = build_full_rebuild_instruments_sql(all_rows, instrument_ids)
    date_targets_sql = build_date_only_instruments_sql(trade_date, all_rows, instrument_ids)
    trade_date_filter = sql_quote(trade_date.isoformat()) + "::date" if trade_date else "NULL::date"
    return f"""
WITH latest_adj AS (
    SELECT DISTINCT ON (instrument_id)
        instrument_id,
        trade_date AS anchor_trade_date,
        adj_factor AS anchor_factor
    FROM public.daily_adj_factor
    WHERE adj_factor IS NOT NULL
      AND adj_factor <> 0
    ORDER BY instrument_id, trade_date DESC
),
existing_anchor AS (
    SELECT DISTINCT ON (instrument_id)
        instrument_id,
        anchor_factor
    FROM public.kline_daily_qfq
    ORDER BY instrument_id, trade_date DESC
),
full_rebuild_instruments AS (
{full_targets_sql}
),
date_only_instruments AS (
{date_targets_sql}
),
full_adjusted AS (
    SELECT
        kd.instrument_id,
        kd.trade_date,
        CASE WHEN kd.open IS NOT NULL THEN round(kd.open * daf.adj_factor / la.anchor_factor, 6) END AS open,
        CASE WHEN kd.high IS NOT NULL THEN round(kd.high * daf.adj_factor / la.anchor_factor, 6) END AS high,
        CASE WHEN kd.low IS NOT NULL THEN round(kd.low * daf.adj_factor / la.anchor_factor, 6) END AS low,
        CASE WHEN kd.close IS NOT NULL THEN round(kd.close * daf.adj_factor / la.anchor_factor, 6) END AS close,
        kd.volume,
        kd.amount,
        daf.adj_factor,
        la.anchor_trade_date,
        la.anchor_factor
    FROM public.kline_daily kd
    JOIN full_rebuild_instruments ti
      ON ti.instrument_id = kd.instrument_id
    JOIN public.daily_adj_factor daf
      ON daf.instrument_id = kd.instrument_id
     AND daf.trade_date = kd.trade_date
    JOIN latest_adj la
      ON la.instrument_id = kd.instrument_id
    WHERE kd.close IS NOT NULL
      AND daf.adj_factor IS NOT NULL
      AND la.anchor_factor IS NOT NULL
      AND la.anchor_factor <> 0
),
full_windowed AS (
    SELECT
        full_adjusted.*,
        lag(close) OVER (PARTITION BY instrument_id ORDER BY trade_date) AS prev_close
    FROM full_adjusted
),
full_final AS (
    SELECT
        instrument_id,
        trade_date,
        open,
        high,
        low,
        close,
        volume,
        amount,
        CASE
            WHEN prev_close IS NOT NULL THEN round(close - prev_close, 6)
            ELSE NULL::numeric
        END AS change,
        CASE
            WHEN prev_close IS NOT NULL AND prev_close <> 0 THEN round((close - prev_close) / prev_close * 100, 6)
            ELSE NULL::numeric
        END AS pct_change,
        CASE
            WHEN prev_close IS NOT NULL AND prev_close <> 0 AND high IS NOT NULL AND low IS NOT NULL
                THEN round((high - low) / prev_close * 100, 6)
            ELSE NULL::numeric
        END AS amplitude,
        adj_factor,
        anchor_trade_date,
        anchor_factor
    FROM full_windowed
),
date_adjusted AS (
    SELECT
        kd.instrument_id,
        kd.trade_date,
        CASE WHEN kd.open IS NOT NULL THEN round(kd.open * daf.adj_factor / la.anchor_factor, 6) END AS open,
        CASE WHEN kd.high IS NOT NULL THEN round(kd.high * daf.adj_factor / la.anchor_factor, 6) END AS high,
        CASE WHEN kd.low IS NOT NULL THEN round(kd.low * daf.adj_factor / la.anchor_factor, 6) END AS low,
        CASE WHEN kd.close IS NOT NULL THEN round(kd.close * daf.adj_factor / la.anchor_factor, 6) END AS close,
        kd.volume,
        kd.amount,
        prev_qfq.close AS prev_close,
        daf.adj_factor,
        la.anchor_trade_date,
        la.anchor_factor
    FROM public.kline_daily kd
    JOIN date_only_instruments ti
      ON ti.instrument_id = kd.instrument_id
    JOIN public.daily_adj_factor daf
      ON daf.instrument_id = kd.instrument_id
     AND daf.trade_date = kd.trade_date
    JOIN latest_adj la
      ON la.instrument_id = kd.instrument_id
    LEFT JOIN LATERAL (
        SELECT q.close
        FROM public.kline_daily_qfq q
        WHERE q.instrument_id = kd.instrument_id
          AND q.trade_date < kd.trade_date
        ORDER BY q.trade_date DESC
        LIMIT 1
    ) prev_qfq ON TRUE
    WHERE kd.trade_date = {trade_date_filter}
      AND kd.close IS NOT NULL
      AND daf.adj_factor IS NOT NULL
      AND la.anchor_factor IS NOT NULL
      AND la.anchor_factor <> 0
),
date_final AS (
    SELECT
        instrument_id,
        trade_date,
        open,
        high,
        low,
        close,
        volume,
        amount,
        CASE
            WHEN prev_close IS NOT NULL THEN round(close - prev_close, 6)
            ELSE NULL::numeric
        END AS change,
        CASE
            WHEN prev_close IS NOT NULL AND prev_close <> 0 THEN round((close - prev_close) / prev_close * 100, 6)
            ELSE NULL::numeric
        END AS pct_change,
        CASE
            WHEN prev_close IS NOT NULL AND prev_close <> 0 AND high IS NOT NULL AND low IS NOT NULL
                THEN round((high - low) / prev_close * 100, 6)
            ELSE NULL::numeric
        END AS amplitude,
        adj_factor,
        anchor_trade_date,
        anchor_factor
    FROM date_adjusted
),
final_rows AS (
    SELECT * FROM full_final
    UNION ALL
    SELECT * FROM date_final
)
INSERT INTO public.kline_daily_qfq (
    instrument_id,
    trade_date,
    open,
    high,
    low,
    close,
    volume,
    amount,
    change,
    pct_change,
    amplitude,
    adj_factor,
    anchor_trade_date,
    anchor_factor,
    is_final,
    source,
    version,
    calculated_at,
    updated_at
)
SELECT
    instrument_id,
    trade_date,
    open,
    high,
    low,
    close,
    volume,
    amount,
    change,
    pct_change,
    amplitude,
    adj_factor,
    anchor_trade_date,
    anchor_factor,
    {final_sql},
    'system_qfq',
    1,
    now(),
    now()
FROM final_rows
ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    amount = EXCLUDED.amount,
    change = EXCLUDED.change,
    pct_change = EXCLUDED.pct_change,
    amplitude = EXCLUDED.amplitude,
    adj_factor = EXCLUDED.adj_factor,
    anchor_trade_date = EXCLUDED.anchor_trade_date,
    anchor_factor = EXCLUDED.anchor_factor,
    is_final = EXCLUDED.is_final,
    source = EXCLUDED.source,
    version = EXCLUDED.version,
    calculated_at = EXCLUDED.calculated_at,
    updated_at = EXCLUDED.updated_at;
"""


def run_sync(
    config: PgConfig,
    trade_date: dt.date | None,
    all_rows: bool,
    instrument_ids: list[str],
    is_final: bool,
) -> int:
    result = psql_execute(config, build_sync_sql(trade_date, all_rows, instrument_ids, is_final))
    return parse_inserted_count(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync public.kline_daily_qfq from kline_daily + daily_adj_factor")
    add_pg_args(parser)
    parser.add_argument("--trade-date", default=None, help="YYYY-MM-DD; update the date row plus full rebuild for anchor changes")
    parser.add_argument("--all", action="store_true", help="Rebuild all stock qfq rows")
    parser.add_argument(
        "--instrument-id",
        action="append",
        default=[],
        help="Full rebuild for one instrument_id; can be provided multiple times",
    )
    parser.add_argument("--is-final", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    if args.all and args.trade_date:
        raise SystemExit("--all cannot be combined with --trade-date")
    if not args.all and not args.trade_date and not args.instrument_id:
        raise SystemExit("Provide --trade-date, --all, or --instrument-id")

    trade_date = dt.date.fromisoformat(args.trade_date) if args.trade_date else None

    config = PgConfig.from_args(args)
    require_password(config)

    run_date = trade_date or dt.date.today()
    job_run_id = start_job(
        config,
        job_name="sync_kline_daily_qfq",
        job_type="collector",
        run_date=run_date,
    )
    try:
        processed_count = run_sync(config, trade_date, args.all, args.instrument_id, args.is_final)
        finish_job(config, job_run_id, status="success", processed_count=processed_count)
        print(
            "sync_kline_daily_qfq completed",
            f"mode={'all' if args.all else 'trade_date' if trade_date else 'instrument'}",
            f"trade_date={trade_date.isoformat() if trade_date else ''}",
            f"instrument_count={len(args.instrument_id)}",
            f"is_final={args.is_final}",
            f"rows={processed_count}",
        )
        return 0
    except Exception as exc:  # pragma: no cover
        finish_job(config, job_run_id, status="error", processed_count=0, error_message=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
