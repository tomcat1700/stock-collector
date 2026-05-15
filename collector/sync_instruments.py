#!/usr/bin/env python3
"""Sync active A-share instrument master data from Tushare stock_basic."""

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

from db import PgConfig, add_pg_args, exec_psql_file, finish_job, require_password, start_job
from reconcile_daily import resolve_tushare_token


FIELDNAMES = [
    "instrument_id",
    "code",
    "name",
    "type",
    "market",
    "industry",
    "list_date",
    "status",
    "updated_at",
]

TUSHARE_STOCK_BASIC_FIELDS = "ts_code,symbol,name,industry,list_date,list_status"


def parse_tushare_date(value: object) -> str | None:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return dt.datetime.strptime(text, "%Y%m%d").date().isoformat()


def market_from_ts_code(ts_code: str) -> str:
    return ts_code.rsplit(".", 1)[-1].upper()


def normalize_stock_basic(frame: pd.DataFrame) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for raw_row in frame.to_dict(orient="records"):
        ts_code = str(raw_row["ts_code"]).strip().upper()
        code = str(raw_row["symbol"]).strip()
        market = market_from_ts_code(ts_code)
        list_status = str(raw_row.get("list_status") or "L").strip().upper()
        status = "active" if list_status == "L" else "inactive"
        rows.append(
            {
                "instrument_id": ts_code,
                "code": code,
                "name": str(raw_row["name"]).strip(),
                "type": "stock",
                "market": market,
                "industry": str(raw_row.get("industry") or "").strip() or None,
                "list_date": parse_tushare_date(raw_row.get("list_date")),
                "status": status,
                "updated_at": dt.datetime.now(dt.UTC).isoformat(),
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
CREATE TEMP TABLE tmp_instruments (
    instrument_id varchar(30),
    code varchar(30),
    name varchar(100),
    type varchar(20),
    market varchar(10),
    industry varchar(50),
    list_date date,
    status varchar(20),
    updated_at timestamptz
);

\\copy tmp_instruments FROM '{escaped_csv}' WITH (FORMAT csv, HEADER true)

INSERT INTO public.instruments (
    instrument_id,
    code,
    name,
    type,
    market,
    industry,
    list_date,
    status,
    updated_at
)
SELECT
    instrument_id,
    code,
    name,
    type,
    market,
    NULLIF(industry, ''),
    list_date,
    status,
    updated_at
FROM tmp_instruments
ON CONFLICT (instrument_id) DO UPDATE SET
    code = EXCLUDED.code,
    name = EXCLUDED.name,
    type = EXCLUDED.type,
    market = EXCLUDED.market,
    industry = COALESCE(EXCLUDED.industry, public.instruments.industry),
    list_date = COALESCE(EXCLUDED.list_date, public.instruments.list_date),
    status = EXCLUDED.status,
    updated_at = EXCLUDED.updated_at;
"""


def run_sync_instruments(config: PgConfig, tushare_token: str) -> int:
    ts.set_token(tushare_token)
    pro = ts.pro_api()
    frame = pro.stock_basic(
        exchange="",
        list_status="L",
        fields=TUSHARE_STOCK_BASIC_FIELDS,
    )
    if frame.empty:
        raise RuntimeError("Tushare stock_basic returned 0 rows")

    rows = normalize_stock_basic(frame)
    with tempfile.TemporaryDirectory(prefix="stock_realtime_instruments_") as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        csv_path = tmp_path / "instruments.csv"
        sql_path = tmp_path / "instruments_upsert.sql"
        write_csv(rows, csv_path)
        sql_path.write_text(build_upsert_sql(csv_path), encoding="utf-8")
        exec_psql_file(config, sql_path)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync public.instruments from Tushare stock_basic")
    add_pg_args(parser)
    parser.add_argument("--tushare-token", default="")
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)
    token = resolve_tushare_token(args.tushare_token)

    job_run_id = start_job(config, job_name="sync_instruments", job_type="collector")
    try:
        synced_rows = run_sync_instruments(config, token)
        finish_job(config, job_run_id, status="success", processed_count=synced_rows)
        print("sync_instruments completed", f"rows={synced_rows}")
        return 0
    except Exception as exc:  # pragma: no cover
        finish_job(config, job_run_id, status="error", processed_count=0, error_message=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
