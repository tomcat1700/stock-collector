#!/usr/bin/env python3
"""Fill one 15:00 closing realtime snapshot from final daily bars."""

from __future__ import annotations

import argparse
import datetime as dt

from db import PgConfig, add_pg_args, finish_job, psql_query, require_password, start_job


def fill_closing_realtime(config: PgConfig, trade_date: dt.date) -> tuple[int, int]:
    rows = psql_query(
        config,
        f"""
        WITH source_rows AS (
            SELECT
                kd.instrument_id,
                ((kd.trade_date::text || ' 15:00:00+08')::timestamptz) AS quote_time,
                COALESCE(i.name, kd.instrument_id) AS name,
                kd.open,
                CASE
                    WHEN kd.close IS NOT NULL AND kd.change IS NOT NULL
                        THEN kd.close - kd.change
                    ELSE NULL
                END AS pre_close,
                kd.close AS current,
                kd.high,
                kd.low,
                kd.volume,
                kd.amount,
                kd.change,
                kd.pct_change AS change_pct,
                kd.amplitude,
                kd.trade_date,
                time '15:00:00' AS trade_time,
                now() AS created_at,
                TRUE AS is_closing,
                'tushare_close_fill'::varchar(20) AS source,
                'close_call'::varchar(20) AS session_phase,
                kd.volume AS cum_volume,
                kd.amount AS cum_amount,
                GREATEST(COALESCE(kd.volume, 0) - COALESCE(prev.volume, 0), 0) AS delta_volume,
                GREATEST(COALESCE(kd.amount, 0) - COALESCE(prev.amount, 0), 0) AS delta_amount,
                kd.close IS NOT NULL AS is_valid,
                'close_fill_' || to_char(kd.trade_date, 'YYYYMMDD') AS ingest_batch_id,
                jsonb_build_object(
                    'source', kd.source,
                    'fill_reason', 'daily_close_backfill',
                    'daily_updated_at', kd.updated_at
                ) AS raw_payload
            FROM public.kline_daily kd
            JOIN public.collector_watchlist cw
                ON cw.instrument_id = kd.instrument_id
            LEFT JOIN public.instruments i
                ON i.instrument_id = kd.instrument_id
            LEFT JOIN LATERAL (
                SELECT rt.volume, rt.amount
                FROM public.realtime_quotes rt
                WHERE rt.instrument_id = kd.instrument_id
                  AND rt.trade_date = kd.trade_date
                  AND rt.quote_time < ((kd.trade_date::text || ' 15:00:00+08')::timestamptz)
                ORDER BY rt.quote_time DESC
                LIMIT 1
            ) prev ON TRUE
            WHERE kd.trade_date = DATE '{trade_date.isoformat()}'
              AND kd.close IS NOT NULL
        ),
        inserted AS (
            INSERT INTO public.realtime_quotes (
                instrument_id,
                quote_time,
                name,
                open,
                pre_close,
                current,
                high,
                low,
                volume,
                amount,
                change,
                change_pct,
                amplitude,
                trade_date,
                trade_time,
                created_at,
                is_closing,
                source,
                session_phase,
                cum_volume,
                cum_amount,
                delta_volume,
                delta_amount,
                is_valid,
                ingest_batch_id,
                raw_payload
            )
            SELECT
                instrument_id,
                quote_time,
                name,
                open,
                pre_close,
                current,
                high,
                low,
                volume,
                amount,
                change,
                change_pct,
                amplitude,
                trade_date,
                trade_time,
                created_at,
                is_closing,
                source,
                session_phase,
                cum_volume,
                cum_amount,
                delta_volume,
                delta_amount,
                is_valid,
                ingest_batch_id,
                raw_payload
            FROM source_rows
            ON CONFLICT (instrument_id, quote_time) DO NOTHING
            RETURNING 1
        )
        SELECT
            (SELECT count(*) FROM source_rows) AS candidate_count,
            (SELECT count(*) FROM inserted) AS inserted_count;
        """,
    )
    candidate_count = int(rows[0]["candidate_count"]) if rows else 0
    inserted_count = int(rows[0]["inserted_count"]) if rows else 0
    return candidate_count, inserted_count


def refresh_minute_aggregates(config: PgConfig) -> dict[str, int]:
    rows = psql_query(
        config,
        """
        SELECT 'aggregate_1min_kline' AS function_name, public.aggregate_1min_kline(720) AS updated_count
        UNION ALL
        SELECT 'aggregate_5min_kline', public.aggregate_5min_kline(720)
        UNION ALL
        SELECT 'aggregate_15min_kline', public.aggregate_15min_kline(720)
        UNION ALL
        SELECT 'aggregate_30min_kline', public.aggregate_30min_kline(720)
        UNION ALL
        SELECT 'aggregate_60min_kline', public.aggregate_60min_kline(720);
        """,
    )
    return {row["function_name"]: int(row["updated_count"]) for row in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill 15:00 realtime close from kline_daily")
    add_pg_args(parser)
    parser.add_argument("--trade-date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)
    trade_date = dt.date.fromisoformat(args.trade_date)
    job_run_id = start_job(
        config,
        job_name="fill_closing_realtime",
        job_type="collector",
        run_date=trade_date,
    )
    try:
        candidate_count, inserted_count = fill_closing_realtime(config, trade_date)
        aggregate_counts = refresh_minute_aggregates(config)
        status = "success" if candidate_count > 0 else "skipped"
        finish_job(
            config,
            job_run_id=job_run_id,
            status=status,
            processed_count=inserted_count,
            error_message=";".join(
                f"{name}={count}" for name, count in aggregate_counts.items()
            ),
        )
        print(
            "fill_closing_realtime completed",
            f"trade_date={trade_date.isoformat()}",
            f"status={status}",
            f"candidates={candidate_count}",
            f"inserted={inserted_count}",
            "aggregates="
            + ",".join(f"{name}={count}" for name, count in aggregate_counts.items()),
        )
    except Exception as exc:  # pragma: no cover
        finish_job(
            config,
            job_run_id=job_run_id,
            status="error",
            processed_count=0,
            error_message=str(exc),
        )
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
