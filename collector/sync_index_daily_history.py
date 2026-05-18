#!/usr/bin/env python3
"""Sync index daily bars into public.kline_daily for configured indices."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import pathlib
import tempfile

try:
    import pandas as pd
    import tushare as ts
except ImportError as exc:  # pragma: no cover
    raise SystemExit("tushare and pandas are required. Install collector/requirements.txt") from exc

from db import PgConfig, add_pg_args, exec_psql_file, finish_job, psql_query, require_password, start_job
from reconcile_daily import FIELDNAMES, build_tushare_daily_row, build_upsert_sql, resolve_tushare_token


def fetch_index_ids(config: PgConfig) -> list[str]:
    rows = psql_query(
        config,
        """
        SELECT instrument_id
        FROM public.instruments
        WHERE type = 'index'
          AND COALESCE(status, 'active') = 'active'
        ORDER BY instrument_id;
        """,
    )
    return [row["instrument_id"] for row in rows if row.get("instrument_id")]


def fetch_kline_bounds(config: PgConfig) -> tuple[dt.date, dt.date]:
    rows = psql_query(
        config,
        """
        SELECT min(trade_date) AS min_trade_date,
               max(trade_date) AS max_trade_date
        FROM public.kline_daily
        WHERE close IS NOT NULL;
        """,
    )
    if not rows or not rows[0].get("min_trade_date") or not rows[0].get("max_trade_date"):
        raise RuntimeError("No kline_daily rows found for date bounds")
    return (
        dt.date.fromisoformat(rows[0]["min_trade_date"]),
        dt.date.fromisoformat(rows[0]["max_trade_date"]),
    )


def write_csv(rows: list[dict[str, str | bool | None]], path: pathlib.Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def sync_rows(config: PgConfig, rows: list[dict[str, str | bool | None]]) -> None:
    if not rows:
        return
    with tempfile.TemporaryDirectory(prefix="stock_realtime_index_daily_") as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        csv_path = tmp_path / "kline_daily.csv"
        sql_path = tmp_path / "kline_daily_upsert.sql"
        write_csv(rows, csv_path)
        sql_path.write_text(build_upsert_sql(csv_path), encoding="utf-8")
        exec_psql_file(config, sql_path)


def run_sync_index_daily(
    config: PgConfig,
    tushare_token: str,
    date_from: dt.date,
    date_to: dt.date,
) -> int:
    ts.set_token(tushare_token)
    pro = ts.pro_api()
    rows: list[dict[str, str | bool | None]] = []
    for instrument_id in fetch_index_ids(config):
        frame = pro.index_daily(
            ts_code=instrument_id,
            start_date=date_from.strftime("%Y%m%d"),
            end_date=date_to.strftime("%Y%m%d"),
        )
        if frame.empty:
            continue
        for raw_row in frame.to_dict(orient="records"):
            trade_date = dt.datetime.strptime(str(raw_row["trade_date"]), "%Y%m%d").date()
            rows.append(
                build_tushare_daily_row(
                    raw_row,
                    trade_date,
                    source="tushare_index_daily",
                )
            )
    sync_rows(config, rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync public.kline_daily index history from Tushare")
    add_pg_args(parser)
    parser.add_argument("--date-from", default=None, help="YYYY-MM-DD")
    parser.add_argument("--date-to", default=None, help="YYYY-MM-DD")
    parser.add_argument("--all-from-kline", action="store_true")
    parser.add_argument("--tushare-token", default="")
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)
    token = resolve_tushare_token(args.tushare_token)

    if args.all_from_kline:
        date_from, date_to = fetch_kline_bounds(config)
    elif args.date_from and args.date_to:
        date_from = dt.date.fromisoformat(args.date_from)
        date_to = dt.date.fromisoformat(args.date_to)
    else:
        raise SystemExit("Provide --date-from/--date-to or --all-from-kline")

    job_run_id = start_job(
        config,
        job_name="sync_index_daily_history",
        job_type="collector",
        run_date=date_to,
    )
    try:
        synced_rows = run_sync_index_daily(config, token, date_from, date_to)
        finish_job(config, job_run_id, status="success", processed_count=synced_rows)
        print(
            "sync_index_daily_history completed",
            f"date_from={date_from.isoformat()}",
            f"date_to={date_to.isoformat()}",
            f"rows={synced_rows}",
        )
        return 0
    except Exception as exc:  # pragma: no cover
        finish_job(config, job_run_id, status="error", processed_count=0, error_message=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
