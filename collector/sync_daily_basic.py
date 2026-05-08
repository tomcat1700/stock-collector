#!/usr/bin/env python3
"""Sync Tushare daily_basic into public.daily_basic by trade_date or date range."""

from __future__ import annotations

import argparse
import datetime as dt

try:
    import pandas as pd
    import tushare as ts
except ImportError as exc:  # pragma: no cover
    raise SystemExit("tushare and pandas are required. Install collector/requirements.txt") from exc

from db import PgConfig, add_pg_args, fetch_previous_trade_date, finish_job, log_quality, require_password, start_job
from reconcile_daily import (
    TUSHARE_DAILY_BASIC_FIELDS,
    build_daily_basic_rows,
    resolve_tushare_token,
    sync_daily_basic_rows,
)


def fetch_trade_dates_from_tushare(
    date_from: dt.date,
    date_to: dt.date,
    tushare_token: str,
) -> list[dt.date]:
    ts.set_token(tushare_token)
    pro = ts.pro_api()
    trade_cal = pro.trade_cal(
        exchange="SSE",
        start_date=date_from.strftime("%Y%m%d"),
        end_date=date_to.strftime("%Y%m%d"),
        fields="cal_date,is_open",
    )
    if trade_cal.empty:
        return []
    open_days = trade_cal[trade_cal["is_open"] == 1]["cal_date"].tolist()
    trade_dates = [dt.datetime.strptime(str(raw_date), "%Y%m%d").date() for raw_date in open_days]
    return sorted(trade_dates)


def run_sync_daily_basic(
    config: PgConfig,
    trade_date: dt.date,
    tushare_token: str,
) -> tuple[str, int, int]:
    ts.set_token(tushare_token)
    pro = ts.pro_api()
    basic_df = pro.daily_basic(
        trade_date=trade_date.strftime("%Y%m%d"),
        fields=TUSHARE_DAILY_BASIC_FIELDS,
    )
    if basic_df.empty:
        log_quality(
            config,
            data_domain="daily_basic_sync",
            issue_type="missing_daily_basic",
            issue_message=f"Tushare daily_basic returned 0 rows for {trade_date.isoformat()}",
            issue_level="warn",
            payload={"trade_date": trade_date.isoformat(), "source": "tushare"},
        )
        return "skipped", 0, 0

    rows, returned_ids = build_daily_basic_rows(basic_df, trade_date)
    sync_daily_basic_rows(config, rows)
    return "success", len(rows), 0 if returned_ids else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync public.daily_basic from Tushare")
    add_pg_args(parser)
    parser.add_argument("--trade-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--date-from", default=None, help="YYYY-MM-DD")
    parser.add_argument("--date-to", default=None, help="YYYY-MM-DD")
    parser.add_argument("--tushare-token", default="")
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)
    tushare_token = resolve_tushare_token(args.tushare_token)

    if args.trade_date:
        trade_dates = [dt.date.fromisoformat(args.trade_date)]
    elif args.date_from and args.date_to:
        trade_dates = fetch_trade_dates_from_tushare(
            dt.date.fromisoformat(args.date_from),
            dt.date.fromisoformat(args.date_to),
            tushare_token,
        )
    else:
        trade_dates = [fetch_previous_trade_date(config)]

    total_rows = 0
    total_errors = 0
    for trade_date in trade_dates:
        job_run_id = start_job(
            config,
            job_name="sync_daily_basic",
            job_type="collector",
            run_date=trade_date,
        )
        try:
            status, synced_rows, errors = run_sync_daily_basic(config, trade_date, tushare_token)
            finish_job(
                config,
                job_run_id=job_run_id,
                status=status,
                processed_count=synced_rows,
                error_message=None if errors == 0 else f"errors={errors}",
            )
            print(
                "sync_daily_basic completed",
                f"trade_date={trade_date.isoformat()}",
                f"status={status}",
                f"rows={synced_rows}",
                f"errors={errors}",
            )
            total_rows += synced_rows
            total_errors += errors
        except Exception as exc:  # pragma: no cover
            finish_job(
                config,
                job_run_id=job_run_id,
                status="error",
                processed_count=0,
                error_message=str(exc),
            )
            log_quality(
                config,
                data_domain="daily_basic_sync",
                issue_type="job_error",
                issue_message=str(exc),
                issue_level="error",
                payload={"trade_date": trade_date.isoformat()},
            )
            raise

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
