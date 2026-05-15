#!/usr/bin/env python3
"""Fetch previous trading-day daily bars and upsert kline_daily."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import os
import pathlib
import tempfile
import time
from decimal import Decimal

try:
    import akshare as ak
    import pandas as pd
except ImportError as exc:  # pragma: no cover
    raise SystemExit("akshare and pandas are required. Install collector/requirements.txt") from exc

try:
    import tushare as ts
except ImportError:  # pragma: no cover
    ts = None

from db import (
    PgConfig,
    add_pg_args,
    exec_psql_file,
    fetch_previous_trade_date,
    fetch_watchlist,
    finish_job,
    log_quality,
    psql_query,
    require_password,
    start_job,
)


FIELDNAMES = [
    "instrument_id",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "pct_change",
    "amplitude",
    "change",
    "turnover",
    "source",
    "is_final",
    "version",
    "updated_at",
]

DAILY_BASIC_FIELDNAMES = [
    "instrument_id",
    "trade_date",
    "turnover_rate",
    "total_share",
    "float_share",
    "free_share",
    "total_market_cap",
    "circulating_market_cap",
    "source",
    "version",
    "updated_at",
]

TUSHARE_DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,turnover_rate,total_share,float_share,free_share,total_mv,circ_mv"
)

TUSHARE_SECRETS_PATH = pathlib.Path(__file__).resolve().parent / "config" / "tushare.secrets.local.yaml"


def to_decimal_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(Decimal(str(value)))


def normalize_date_column(frame: pd.DataFrame) -> pd.DataFrame:
    copied = frame.copy()
    copied["日期"] = pd.to_datetime(copied["日期"]).dt.date
    return copied


def load_tushare_token_from_secrets_file(path: pathlib.Path = TUSHARE_SECRETS_PATH) -> str:
    if not path.exists():
        return ""

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip() != "tushare_token":
            continue
        token = value.strip().strip("'\"")
        return token
    return ""


def resolve_tushare_token(cli_token: str | None) -> str:
    token = (cli_token or "").strip()
    if token:
        return token

    token = load_tushare_token_from_secrets_file()
    if token:
        return token

    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if token:
        return token

    raise RuntimeError(
        "Missing Tushare token for source=tushare. Provide --tushare-token, "
        f"or set tushare_token in {TUSHARE_SECRETS_PATH}, or export TUSHARE_TOKEN."
    )


def fetch_daily_row(
    code: str,
    trade_date: dt.date,
    max_attempts: int = 3,
    retry_sleep_seconds: float = 1.0,
) -> dict[str, object] | None:
    end_date = (trade_date + dt.timedelta(days=3)).strftime("%Y%m%d")
    start_date = (trade_date - dt.timedelta(days=10)).strftime("%Y%m%d")
    last_error: Exception | None = None
    for attempt in range(1, max(max_attempts, 1) + 1):
        try:
            frame = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="",
            )
            if frame.empty:
                return None
            normalized = normalize_date_column(frame)
            matched = normalized[normalized["日期"] == trade_date]
            if matched.empty:
                return None
            return matched.iloc[-1].to_dict()
        except Exception as exc:  # pragma: no cover
            last_error = exc
            if attempt < max(max_attempts, 1):
                time.sleep(max(retry_sleep_seconds, 0.0) * attempt)
    if last_error is not None:
        raise last_error
    return None


def fetch_active_stock_ids(config: PgConfig) -> set[str]:
    rows = psql_query(
        config,
        """
        SELECT instrument_id
        FROM public.instruments
        WHERE type = 'stock'
          AND COALESCE(status, 'active') = 'active';
        """,
    )
    return {row["instrument_id"] for row in rows if row.get("instrument_id")}


def fetch_watchlist_index_ids(config: PgConfig) -> list[str]:
    rows = psql_query(
        config,
        """
        SELECT cw.instrument_id
        FROM public.collector_watchlist cw
        JOIN public.instruments i
            ON i.instrument_id = cw.instrument_id
        WHERE i.type = 'index'
          AND COALESCE(i.status, 'active') = 'active'
        ORDER BY cw.instrument_id;
        """,
    )
    return [row["instrument_id"] for row in rows if row.get("instrument_id")]


def build_tushare_daily_row(
    raw_row: dict,
    trade_date: dt.date,
    source: str,
) -> dict[str, str | bool | None]:
    pre_close = raw_row.get("pre_close")
    high = raw_row.get("high")
    low = raw_row.get("low")
    amplitude = None
    if pre_close not in (None, 0) and high is not None and low is not None:
        amplitude = (float(high) - float(low)) / float(pre_close) * 100
    volume = raw_row.get("vol")
    volume_value = None if volume is None else int(Decimal(str(volume)))
    amount = raw_row.get("amount")
    amount_yuan = None if amount is None else float(amount) * 1000
    return {
        "instrument_id": str(raw_row["ts_code"]),
        "trade_date": trade_date.isoformat(),
        "open": to_decimal_string(raw_row.get("open")),
        "high": to_decimal_string(high),
        "low": to_decimal_string(low),
        "close": to_decimal_string(raw_row.get("close")),
        "volume": None if volume_value is None else str(volume_value),
        "amount": to_decimal_string(amount_yuan),
        "pct_change": to_decimal_string(raw_row.get("pct_chg")),
        "amplitude": to_decimal_string(amplitude),
        "change": to_decimal_string(raw_row.get("change")),
        "turnover": None,
        "source": source,
        "is_final": True,
        "version": "1",
        "updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(),
    }


def run_reconcile_tushare(
    config: PgConfig,
    trade_date: dt.date,
    tushare_token: str,
) -> tuple[int, int]:
    if ts is None:
        raise RuntimeError("tushare is required for source=tushare")
    ts.set_token(tushare_token)
    pro = ts.pro_api()
    trade_date_str = trade_date.strftime("%Y%m%d")
    daily_df = pro.daily(trade_date=trade_date_str)
    if daily_df.empty:
        raise RuntimeError(f"Tushare daily returned 0 rows for {trade_date.isoformat()}")
    active_stock_ids = fetch_active_stock_ids(config)
    watchlist_index_ids = fetch_watchlist_index_ids(config)
    daily_basic_rows: list[dict[str, str | None]] = []
    returned_basic_ids: set[str] = set()
    daily_basic_error_count = 0

    try:
        basic_df = pro.daily_basic(
            trade_date=trade_date_str,
            fields=TUSHARE_DAILY_BASIC_FIELDS,
        )
    except Exception as exc:  # pragma: no cover
        log_quality(
            config,
            data_domain="daily_reconcile",
            issue_type="daily_basic_source_error",
            issue_message=str(exc),
            issue_level="warn",
            payload={"trade_date": trade_date.isoformat(), "source": "tushare"},
        )
        basic_df = pd.DataFrame()
        daily_basic_error_count += 1

    if basic_df.empty:
        log_quality(
            config,
            data_domain="daily_reconcile",
            issue_type="missing_daily_basic",
            issue_message=f"Tushare daily_basic returned 0 rows for {trade_date.isoformat()}",
            issue_level="warn",
            payload={"trade_date": trade_date.isoformat(), "source": "tushare"},
        )
        daily_basic_error_count += 1
    else:
        daily_basic_rows, returned_basic_ids = build_daily_basic_rows(
            basic_df,
            trade_date,
        )

    success_rows: list[dict[str, str | bool | None]] = []
    returned_ids: set[str] = set()

    for raw_row in daily_df.to_dict(orient="records"):
        instrument_id = str(raw_row["ts_code"])
        returned_ids.add(instrument_id)
        success_rows.append(build_tushare_daily_row(raw_row, trade_date, source="tushare"))

    returned_index_ids: set[str] = set()
    index_error_count = 0
    for instrument_id in watchlist_index_ids:
        try:
            index_df = pro.index_daily(
                ts_code=instrument_id,
                trade_date=trade_date_str,
            )
        except Exception as exc:  # pragma: no cover
            index_error_count += 1
            log_quality(
                config,
                data_domain="daily_reconcile",
                ref_key=instrument_id,
                issue_type="index_daily_source_error",
                issue_message=str(exc),
                issue_level="warn",
                payload={"trade_date": trade_date.isoformat(), "source": "tushare_index_daily"},
            )
            continue
        if index_df.empty:
            index_error_count += 1
            log_quality(
                config,
                data_domain="daily_reconcile",
                ref_key=instrument_id,
                issue_type="missing_index_daily",
                issue_message=f"Tushare index_daily returned 0 rows for {instrument_id} on {trade_date.isoformat()}",
                issue_level="warn",
                payload={"trade_date": trade_date.isoformat(), "source": "tushare_index_daily"},
            )
            continue
        raw_row = index_df.iloc[0].to_dict()
        returned_index_ids.add(str(raw_row["ts_code"]))
        success_rows.append(
            build_tushare_daily_row(raw_row, trade_date, source="tushare_index_daily")
        )

    missing_ids = sorted(active_stock_ids - returned_ids)
    if missing_ids:
        log_quality(
            config,
            data_domain="daily_reconcile",
            issue_type="missing_daily",
            issue_message=f"Tushare missing {len(missing_ids)} rows for {trade_date.isoformat()}",
            issue_level="warn",
            payload={
                "trade_date": trade_date.isoformat(),
                "source": "tushare",
                "missing_count": len(missing_ids),
                "sample_missing": missing_ids[:20],
            },
        )

    if returned_basic_ids:
        missing_basic_ids = sorted(active_stock_ids - returned_basic_ids)
        if missing_basic_ids:
            log_quality(
                config,
                data_domain="daily_reconcile",
                issue_type="missing_daily_basic",
                issue_message=f"Tushare daily_basic missing {len(missing_basic_ids)} rows for {trade_date.isoformat()}",
                issue_level="warn",
                payload={
                    "trade_date": trade_date.isoformat(),
                    "source": "tushare",
                    "missing_count": len(missing_basic_ids),
                    "sample_missing": missing_basic_ids[:20],
                },
            )
            daily_basic_error_count += len(missing_basic_ids)

    if success_rows:
        with tempfile.TemporaryDirectory(prefix="stockx_reconcile_daily_") as tmp_dir:
            tmp_path = pathlib.Path(tmp_dir)
            csv_path = tmp_path / "kline_daily.csv"
            sql_path = tmp_path / "kline_daily_upsert.sql"
            write_csv(success_rows, csv_path)
            sql_path.write_text(build_upsert_sql(csv_path), encoding="utf-8")
            exec_psql_file(config, sql_path)

    if daily_basic_rows:
        try:
            sync_daily_basic_rows(config, daily_basic_rows)
        except Exception as exc:  # pragma: no cover
            log_quality(
                config,
                data_domain="daily_reconcile",
                issue_type="daily_basic_sync_error",
                issue_message=str(exc),
                issue_level="error",
                payload={
                    "trade_date": trade_date.isoformat(),
                    "source": "tushare",
                    "row_count": len(daily_basic_rows),
                },
            )
            daily_basic_error_count += 1

    missing_index_ids = sorted(set(watchlist_index_ids) - returned_index_ids)
    if missing_index_ids:
        log_quality(
            config,
            data_domain="daily_reconcile",
            issue_type="missing_index_daily",
            issue_message=f"Tushare index_daily missing {len(missing_index_ids)} rows for {trade_date.isoformat()}",
            issue_level="warn",
            payload={
                "trade_date": trade_date.isoformat(),
                "source": "tushare_index_daily",
                "missing_count": len(missing_index_ids),
                "sample_missing": missing_index_ids[:20],
            },
        )

    return len(success_rows), len(missing_ids) + daily_basic_error_count + index_error_count


def write_csv(rows: list[dict[str, str | bool | None]], path: pathlib.Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def write_daily_basic_csv(rows: list[dict[str, str | None]], path: pathlib.Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DAILY_BASIC_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def build_upsert_sql(csv_path: pathlib.Path) -> str:
    escaped_csv = str(csv_path).replace("'", "''")
    return f"""
BEGIN;

CREATE TEMP TABLE tmp_kline_daily (
    instrument_id varchar(30),
    trade_date date,
    open numeric(12,4),
    high numeric(12,4),
    low numeric(12,4),
    close numeric(12,4),
    volume bigint,
    amount numeric(16,2),
    pct_change numeric(8,4),
    amplitude numeric(8,4),
    change numeric(12,4),
    turnover numeric(8,4),
    source varchar(20),
    is_final boolean,
    version integer,
    updated_at timestamptz
) ON COMMIT DROP;

\\copy tmp_kline_daily FROM '{escaped_csv}' WITH (FORMAT csv, HEADER true)

INSERT INTO public.kline_daily (
    instrument_id,
    trade_date,
    open,
    high,
    low,
    close,
    volume,
    amount,
    pct_change,
    amplitude,
    change,
    turnover,
    source,
    is_final,
    version,
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
    pct_change,
    amplitude,
    change,
    turnover,
    source,
    is_final,
    version,
    updated_at
FROM tmp_kline_daily
ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    amount = EXCLUDED.amount,
    pct_change = EXCLUDED.pct_change,
    amplitude = EXCLUDED.amplitude,
    change = EXCLUDED.change,
    turnover = COALESCE(EXCLUDED.turnover, public.kline_daily.turnover),
    source = EXCLUDED.source,
    is_final = EXCLUDED.is_final,
    version = EXCLUDED.version,
    updated_at = EXCLUDED.updated_at;

COMMIT;
"""


def build_daily_basic_upsert_sql(csv_path: pathlib.Path) -> str:
    escaped_csv = str(csv_path).replace("'", "''")
    return f"""
BEGIN;

CREATE TEMP TABLE tmp_daily_basic (
    instrument_id varchar(30),
    trade_date date,
    turnover_rate numeric(12,4),
    total_share numeric(20,4),
    float_share numeric(20,4),
    free_share numeric(20,4),
    total_market_cap numeric(20,4),
    circulating_market_cap numeric(20,4),
    source varchar(20),
    version integer,
    updated_at timestamptz
) ON COMMIT DROP;

\\copy tmp_daily_basic FROM '{escaped_csv}' WITH (FORMAT csv, HEADER true)

INSERT INTO public.daily_basic (
    instrument_id,
    trade_date,
    turnover_rate,
    total_share,
    float_share,
    free_share,
    total_market_cap,
    circulating_market_cap,
    source,
    version,
    updated_at
)
SELECT
    instrument_id,
    trade_date,
    turnover_rate,
    total_share,
    float_share,
    free_share,
    total_market_cap,
    circulating_market_cap,
    source,
    version,
    updated_at
FROM tmp_daily_basic
ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
    turnover_rate = EXCLUDED.turnover_rate,
    total_share = EXCLUDED.total_share,
    float_share = EXCLUDED.float_share,
    free_share = EXCLUDED.free_share,
    total_market_cap = EXCLUDED.total_market_cap,
    circulating_market_cap = EXCLUDED.circulating_market_cap,
    source = EXCLUDED.source,
    version = EXCLUDED.version,
    updated_at = EXCLUDED.updated_at;

COMMIT;
"""


def build_daily_basic_rows(
    basic_df: pd.DataFrame,
    trade_date: dt.date,
) -> tuple[list[dict[str, str | None]], set[str]]:
    rows: list[dict[str, str | None]] = []
    returned_ids: set[str] = set()
    updated_at = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()

    for raw_row in basic_df.to_dict(orient="records"):
        instrument_id = str(raw_row["ts_code"])
        returned_ids.add(instrument_id)
        turnover_value = raw_row.get("turnover_rate")
        rows.append(
            {
                "instrument_id": instrument_id,
                "trade_date": trade_date.isoformat(),
                "turnover_rate": to_decimal_string(turnover_value),
                "total_share": to_decimal_string(raw_row.get("total_share")),
                "float_share": to_decimal_string(raw_row.get("float_share")),
                "free_share": to_decimal_string(raw_row.get("free_share")),
                "total_market_cap": to_decimal_string(raw_row.get("total_mv")),
                "circulating_market_cap": to_decimal_string(raw_row.get("circ_mv")),
                "source": "tushare_daily_basic",
                "version": "1",
                "updated_at": updated_at,
            }
        )

    return rows, returned_ids


def sync_daily_basic_rows(
    config: PgConfig,
    rows: list[dict[str, str | None]],
) -> None:
    if not rows:
        return
    with tempfile.TemporaryDirectory(prefix="stockx_daily_basic_") as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        csv_path = tmp_path / "daily_basic.csv"
        sql_path = tmp_path / "daily_basic_upsert.sql"
        write_daily_basic_csv(rows, csv_path)
        sql_path.write_text(build_daily_basic_upsert_sql(csv_path), encoding="utf-8")
        exec_psql_file(config, sql_path)


def run_reconcile(
    config: PgConfig,
    trade_date: dt.date,
    limit: int | None = None,
    fetch_retries: int = 3,
    retry_sleep_seconds: float = 1.0,
    source: str = "tushare",
    tushare_token: str | None = None,
) -> tuple[int, int]:
    if source == "tushare":
        return run_reconcile_tushare(config, trade_date, resolve_tushare_token(tushare_token))

    watchlist = fetch_watchlist(config, limit=limit)
    success_rows: list[dict[str, str | bool | None]] = []
    error_count = 0

    for item in watchlist:
        try:
            raw_row = fetch_daily_row(
                item["code"],
                trade_date,
                max_attempts=fetch_retries,
                retry_sleep_seconds=retry_sleep_seconds,
            )
            if raw_row is None:
                error_count += 1
                log_quality(
                    config,
                    data_domain="daily_reconcile",
                    ref_key=item["instrument_id"],
                    issue_type="missing_daily",
                    issue_message=f"No daily kline returned for {item['instrument_id']} on {trade_date.isoformat()}",
                    issue_level="warn",
                )
                continue

            success_rows.append(
                {
                    "instrument_id": item["instrument_id"],
                    "trade_date": trade_date.isoformat(),
                    "open": to_decimal_string(raw_row.get("开盘")),
                    "high": to_decimal_string(raw_row.get("最高")),
                    "low": to_decimal_string(raw_row.get("最低")),
                    "close": to_decimal_string(raw_row.get("收盘")),
                    "volume": to_decimal_string(raw_row.get("成交量")),
                    "amount": to_decimal_string(raw_row.get("成交额")),
                    "pct_change": to_decimal_string(raw_row.get("涨跌幅")),
                    "amplitude": to_decimal_string(raw_row.get("振幅")),
                    "change": to_decimal_string(raw_row.get("涨跌额")),
                    "turnover": to_decimal_string(raw_row.get("换手率")),
                    "source": "akshare",
                    "is_final": True,
                    "version": "1",
                    "updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(),
                }
            )
        except Exception as exc:  # pragma: no cover
            error_count += 1
            log_quality(
                config,
                data_domain="daily_reconcile",
                ref_key=item["instrument_id"],
                issue_type="source_error",
                issue_message=str(exc),
                issue_level="warn",
                payload={"trade_date": trade_date.isoformat(), "code": item["code"]},
            )

    if success_rows:
        with tempfile.TemporaryDirectory(prefix="stockx_reconcile_daily_") as tmp_dir:
            tmp_path = pathlib.Path(tmp_dir)
            csv_path = tmp_path / "kline_daily.csv"
            sql_path = tmp_path / "kline_daily_upsert.sql"
            write_csv(success_rows, csv_path)
            sql_path.write_text(build_upsert_sql(csv_path), encoding="utf-8")
            exec_psql_file(config, sql_path)

    return len(success_rows), error_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile previous trading-day daily bars")
    add_pg_args(parser)
    parser.add_argument("--trade-date", default=None, help="YYYY-MM-DD; defaults to previous trading day")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--fetch-retries", type=int, default=3)
    parser.add_argument("--retry-sleep-seconds", type=float, default=1.0)
    parser.add_argument("--source", default="tushare", choices=["tushare", "akshare"])
    parser.add_argument("--tushare-token", default="")
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)

    trade_date = dt.date.fromisoformat(args.trade_date) if args.trade_date else fetch_previous_trade_date(config)
    job_run_id = start_job(
        config,
        job_name="reconcile_daily",
        job_type="reconcile",
        run_date=trade_date,
    )
    try:
        success_count, error_count = run_reconcile(
            config,
            trade_date,
            limit=args.limit,
            fetch_retries=args.fetch_retries,
            retry_sleep_seconds=args.retry_sleep_seconds,
            source=args.source,
            tushare_token=args.tushare_token,
        )
        if success_count and error_count:
            status = "partial"
        elif success_count:
            status = "success"
        else:
            status = "error"
        finish_job(
            config,
            job_run_id=job_run_id,
            status=status,
            processed_count=success_count,
            error_message=None if error_count == 0 else f"errors={error_count}",
        )
        print(
            "reconcile_daily completed",
            f"trade_date={trade_date.isoformat()}",
            f"success={success_count}",
            f"errors={error_count}",
        )
        return 0 if status != "error" else 1
    except Exception as exc:  # pragma: no cover
        log_quality(
            config,
            data_domain="daily_reconcile",
            issue_type="job_error",
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
