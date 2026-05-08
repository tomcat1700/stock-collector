#!/usr/bin/env python3
"""Probe AkShare source availability for realtime and daily collector jobs."""

from __future__ import annotations

import argparse
import datetime as dt
import time

try:
    import akshare as ak
except ImportError as exc:  # pragma: no cover
    raise SystemExit("akshare is required. Install collector/requirements.txt") from exc

from collect_realtime import fetch_sina_watchlist_frame
from db import (
    PgConfig,
    add_pg_args,
    fetch_previous_trade_date,
    fetch_watchlist,
    finish_job,
    log_quality,
    require_password,
    start_job,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe collector source availability")
    add_pg_args(parser)
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)

    watchlist = fetch_watchlist(config, limit=1)
    sample = watchlist[0] if watchlist else {"instrument_id": "000001.SZ", "code": "000001"}
    trade_date = fetch_previous_trade_date(config)
    job_run_id = start_job(
        config,
        job_name="source_probe",
        job_type="collector",
        run_date=trade_date,
    )

    try:
        realtime_source = None
        realtime_rows = 0
        realtime_elapsed = 0.0
        realtime_error = None
        started = time.perf_counter()
        try:
            spot = ak.stock_zh_a_spot_em()
            realtime_source = "eastmoney"
        except Exception as exc:
            realtime_error = str(exc)
            try:
                spot = fetch_sina_watchlist_frame(watchlist or [sample])
                realtime_source = "sina"
            except Exception as fallback_exc:
                realtime_error = f"eastmoney={exc}; sina={fallback_exc}"
                spot = None
        realtime_elapsed = time.perf_counter() - started
        realtime_rows = len(spot) if spot is not None else 0

        daily_rows = 0
        daily_elapsed = 0.0
        daily_error = None

        started = time.perf_counter()
        try:
            hist = ak.stock_zh_a_hist(
                symbol=sample["code"],
                period="daily",
                start_date=(trade_date - dt.timedelta(days=10)).strftime("%Y%m%d"),
                end_date=(trade_date + dt.timedelta(days=3)).strftime("%Y%m%d"),
                adjust="",
            )
            daily_rows = len(hist)
        except Exception as exc:
            daily_error = str(exc)
            hist = None
        daily_elapsed = time.perf_counter() - started

        if realtime_error:
            log_quality(
                config,
                data_domain="collector_probe",
                ref_key=sample["instrument_id"],
                issue_type="realtime_source_error",
                issue_message=realtime_error,
                issue_level="warn",
                payload={"trade_date": trade_date.isoformat()},
            )
        if daily_error:
            log_quality(
                config,
                data_domain="collector_probe",
                ref_key=sample["instrument_id"],
                issue_type="daily_source_error",
                issue_message=daily_error,
                issue_level="warn",
                payload={"trade_date": trade_date.isoformat()},
            )

        ok_count = int(realtime_rows > 0) + int(daily_rows > 0)
        if ok_count == 2:
            status = "success"
        elif ok_count == 1:
            status = "partial"
        else:
            status = "error"
        finish_job(
            config,
            job_run_id=job_run_id,
            status=status,
            processed_count=ok_count,
            error_message="; ".join(
                message for message in (realtime_error, daily_error) if message
            )
            or None,
        )

        print(
            "source_probe completed",
            f"realtime_source={realtime_source}",
            f"spot_rows={realtime_rows}",
            f"spot_seconds={realtime_elapsed:.2f}",
            f"daily_rows={daily_rows}",
            f"daily_seconds={daily_elapsed:.2f}",
            f"sample={sample['instrument_id']}",
            f"trade_date={trade_date.isoformat()}",
            f"status={status}",
        )
        return 0 if status != "error" else 1
    except Exception as exc:  # pragma: no cover
        log_quality(
            config,
            data_domain="collector_probe",
            ref_key=sample["instrument_id"],
            issue_type="source_error",
            issue_message=str(exc),
            issue_level="error",
            payload={"trade_date": trade_date.isoformat()},
        )
        finish_job(
            config,
            job_run_id=job_run_id,
            status="error",
            processed_count=0,
            error_message=str(exc),
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
