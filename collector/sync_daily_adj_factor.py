#!/usr/bin/env python3
"""Sync Tushare adj_factor into public.daily_adj_factor."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import pathlib
import tempfile
import time

try:
    import pandas as pd
    import tushare as ts
except ImportError as exc:  # pragma: no cover
    raise SystemExit("tushare and pandas are required. Install collector/requirements.txt") from exc

from db import PgConfig, add_pg_args, exec_psql_file, finish_job, psql_query, require_password, start_job
from reconcile_daily import resolve_tushare_token
from sync_daily_basic import fetch_trade_dates_from_tushare


FIELDNAMES = [
    "instrument_id",
    "trade_date",
    "adj_factor",
    "source",
    "updated_at",
]


def parse_tushare_date(value: object) -> str:
    return dt.datetime.strptime(str(value).strip(), "%Y%m%d").date().isoformat()


def to_decimal_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def fetch_kline_trade_date_bounds(config: PgConfig) -> tuple[dt.date, dt.date]:
    rows = psql_query(
        config,
        """
        SELECT min(kd.trade_date) AS min_trade_date,
               max(kd.trade_date) AS max_trade_date
        FROM public.kline_daily kd
        JOIN public.instruments i
            ON i.instrument_id = kd.instrument_id
        WHERE i.type = 'stock'
          AND kd.close IS NOT NULL;
        """,
    )
    if not rows or not rows[0].get("min_trade_date") or not rows[0].get("max_trade_date"):
        raise RuntimeError("No stock kline_daily rows found for adj_factor date bounds")
    return (
        dt.date.fromisoformat(rows[0]["min_trade_date"]),
        dt.date.fromisoformat(rows[0]["max_trade_date"]),
    )


def existing_factor_dates(config: PgConfig, date_from: dt.date, date_to: dt.date) -> set[dt.date]:
    rows = psql_query(
        config,
        f"""
        SELECT trade_date
        FROM public.daily_adj_factor
        WHERE trade_date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
        GROUP BY trade_date;
        """,
    )
    return {dt.date.fromisoformat(row["trade_date"]) for row in rows if row.get("trade_date")}


def normalize_rows(frame: pd.DataFrame) -> list[dict[str, str | None]]:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rows: list[dict[str, str | None]] = []
    for raw_row in frame.to_dict(orient="records"):
        adj_factor = to_decimal_text(raw_row.get("adj_factor"))
        if not adj_factor:
            continue
        rows.append(
            {
                "instrument_id": str(raw_row["ts_code"]).strip().upper(),
                "trade_date": parse_tushare_date(raw_row["trade_date"]),
                "adj_factor": adj_factor,
                "source": "tushare_adj_factor",
                "updated_at": now,
            }
        )
    return rows


def write_csv(rows: list[dict[str, str | None]], path: pathlib.Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def build_upsert_sql(csv_path: pathlib.Path) -> str:
    escaped_csv = str(csv_path).replace("'", "''")
    return f"""
BEGIN;

CREATE TEMP TABLE tmp_daily_adj_factor (
    instrument_id varchar(30),
    trade_date date,
    adj_factor numeric(18,6),
    source varchar(32),
    updated_at timestamptz
) ON COMMIT DROP;

\\copy tmp_daily_adj_factor FROM '{escaped_csv}' WITH (FORMAT csv, HEADER true)

INSERT INTO public.daily_adj_factor (
    instrument_id,
    trade_date,
    adj_factor,
    source,
    updated_at
)
SELECT
    instrument_id,
    trade_date,
    adj_factor,
    source,
    updated_at
FROM tmp_daily_adj_factor
ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
    adj_factor = EXCLUDED.adj_factor,
    source = EXCLUDED.source,
    updated_at = EXCLUDED.updated_at;

COMMIT;
"""


def sync_adj_factor_rows(config: PgConfig, rows: list[dict[str, str | None]]) -> None:
    if not rows:
        return
    with tempfile.TemporaryDirectory(prefix="stock_realtime_adj_factor_") as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        csv_path = tmp_path / "daily_adj_factor.csv"
        sql_path = tmp_path / "daily_adj_factor_upsert.sql"
        write_csv(rows, csv_path)
        sql_path.write_text(build_upsert_sql(csv_path), encoding="utf-8")
        exec_psql_file(config, sql_path)


def run_sync_for_trade_date(
    config: PgConfig,
    trade_date: dt.date,
    pro: object,
) -> int:
    frame = pro.adj_factor(trade_date=trade_date.strftime("%Y%m%d"))
    if frame.empty:
        return 0
    rows = normalize_rows(frame)
    sync_adj_factor_rows(config, rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync public.daily_adj_factor from Tushare")
    add_pg_args(parser)
    parser.add_argument("--trade-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--date-from", default=None, help="YYYY-MM-DD")
    parser.add_argument("--date-to", default=None, help="YYYY-MM-DD")
    parser.add_argument("--all-from-kline", action="store_true", help="Use stock kline_daily min/max dates")
    parser.add_argument("--missing-only", action="store_true", help="Skip trade dates already present")
    parser.add_argument("--sleep-seconds", type=float, default=0.12)
    parser.add_argument("--tushare-token", default="")
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)
    token = resolve_tushare_token(args.tushare_token)

    if args.trade_date:
        trade_dates = [dt.date.fromisoformat(args.trade_date)]
    else:
        if args.all_from_kline:
            date_from, date_to = fetch_kline_trade_date_bounds(config)
        elif args.date_from and args.date_to:
            date_from = dt.date.fromisoformat(args.date_from)
            date_to = dt.date.fromisoformat(args.date_to)
        else:
            raise SystemExit("Provide --trade-date, --date-from/--date-to, or --all-from-kline")
        trade_dates = fetch_trade_dates_from_tushare(date_from, date_to, token)
        if args.missing_only:
            existing_dates = existing_factor_dates(config, date_from, date_to)
            trade_dates = [trade_date for trade_date in trade_dates if trade_date not in existing_dates]

    ts.set_token(token)
    pro = ts.pro_api()
    total_rows = 0
    total_errors = 0
    for index, trade_date in enumerate(trade_dates, start=1):
        job_run_id = start_job(
            config,
            job_name="sync_daily_adj_factor",
            job_type="collector",
            run_date=trade_date,
        )
        try:
            synced_rows = run_sync_for_trade_date(config, trade_date, pro)
            status = "success" if synced_rows else "skipped"
            finish_job(config, job_run_id, status=status, processed_count=synced_rows)
            total_rows += synced_rows
            print(
                "sync_daily_adj_factor completed",
                f"trade_date={trade_date.isoformat()}",
                f"status={status}",
                f"rows={synced_rows}",
                f"progress={index}/{len(trade_dates)}",
            )
        except Exception as exc:  # pragma: no cover
            total_errors += 1
            finish_job(config, job_run_id, status="error", processed_count=0, error_message=str(exc))
            print(
                "sync_daily_adj_factor error",
                f"trade_date={trade_date.isoformat()}",
                f"message={exc}",
            )
            raise
        if args.sleep_seconds > 0 and index < len(trade_dates):
            time.sleep(args.sleep_seconds)

    print(
        "sync_daily_adj_factor summary",
        f"dates={len(trade_dates)}",
        f"rows={total_rows}",
        f"errors={total_errors}",
    )
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
