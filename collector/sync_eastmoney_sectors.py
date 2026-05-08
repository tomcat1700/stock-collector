#!/usr/bin/env python3
"""Sync Eastmoney sector catalog data into PostgreSQL.

This script syncs Eastmoney industry/concept board catalog data into:
- public.standard_sectors

Task lifecycle is tracked in public.job_runs and failures are logged into
public.data_quality_log. The runtime here can reach Eastmoney's sidemenu
catalog JSON more reliably than the push2 quote endpoints, so we first sync
the stable board dictionary and preserve any pre-existing snapshot fields
already stored in the database.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile

from db import (
    PgConfig,
    add_pg_args,
    finish_job,
    log_quality,
    require_password,
    start_job,
)

SIDEMENU_URL = "https://quote.eastmoney.com/center/api/sidemenu_new.json"
EASTMONEY_HEADERS = [
    "User-Agent: Mozilla/5.0",
    "Referer: https://quote.eastmoney.com/center/boardlist.html",
    "Accept: application/json,text/plain,*/*",
]


def run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, env=env)


def fetch_sector_catalog() -> list[dict]:
    cmd = ["curl", "--http1.1", "-L", "--silent", "--show-error", "--max-time", "30"]
    for header in EASTMONEY_HEADERS:
        cmd.extend(["-H", header])
    cmd.append(SIDEMENU_URL)
    result = run(cmd)
    payload = json.loads(result.stdout)
    return payload.get("bklist") or []


def normalize_rows(raw_rows: list[dict], sector_type: str) -> list[dict]:
    type_code = 2 if sector_type == "industry" else 3
    rows: list[dict] = []
    for row in raw_rows:
        if row.get("type") != type_code:
            continue
        sector_code = row.get("code")
        sector_name = row.get("name")
        if not sector_code or not sector_name:
            continue
        rows.append(
            {
                "sector_code": str(sector_code),
                "sector_name": str(sector_name),
                "sector_type": sector_type,
                "change_pct": None,
                "leading_stock": None,
                "leading_stock_name": None,
                "leading_pct": None,
                "falling_stock": None,
                "falling_stock_name": None,
                "falling_pct": None,
                "stock_count": 0,
                "total_market_cap": None,
            }
        )
    return rows


def write_csv(rows: list[dict], path: pathlib.Path) -> None:
    fieldnames = [
        "sector_code",
        "sector_name",
        "sector_type",
        "change_pct",
        "leading_stock",
        "leading_stock_name",
        "leading_pct",
        "falling_stock",
        "falling_stock_name",
        "falling_pct",
        "stock_count",
        "total_market_cap",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_sql(csv_path: pathlib.Path, sector_type: str, sync_source: str) -> str:
    escaped_csv = str(csv_path).replace("'", "''")
    escaped_type = sector_type.replace("'", "''")
    escaped_source = sync_source.replace("'", "''")
    return f"""
BEGIN;

CREATE TEMP TABLE tmp_standard_sectors (
    sector_code varchar(50),
    sector_name varchar(100),
    sector_type varchar(20),
    change_pct numeric(8,4),
    leading_stock varchar(30),
    leading_stock_name varchar(50),
    leading_pct numeric(8,4),
    falling_stock varchar(30),
    falling_stock_name varchar(50),
    falling_pct numeric(8,4),
    stock_count integer,
    total_market_cap numeric(20,2)
) ON COMMIT DROP;

\\copy tmp_standard_sectors FROM '{escaped_csv}' WITH (FORMAT csv, HEADER true)

INSERT INTO public.standard_sectors (
    sector_code,
    sector_name,
    sector_type,
    change_pct,
    leading_stock,
    leading_stock_name,
    leading_pct,
    falling_stock,
    falling_stock_name,
    falling_pct,
    stock_count,
    total_market_cap,
    source,
    sync_status,
    last_sync_at,
    sync_error,
    updated_at
)
SELECT
    t.sector_code,
    t.sector_name,
    t.sector_type,
    t.change_pct,
    t.leading_stock,
    t.leading_stock_name,
    t.leading_pct,
    t.falling_stock,
    t.falling_stock_name,
    t.falling_pct,
    COALESCE(t.stock_count, 0),
    t.total_market_cap,
    '{escaped_source}',
    'completed',
    now(),
    NULL,
    now()
FROM tmp_standard_sectors t
ON CONFLICT (sector_code) DO UPDATE SET
    sector_name = EXCLUDED.sector_name,
    sector_type = EXCLUDED.sector_type,
    change_pct = COALESCE(EXCLUDED.change_pct, public.standard_sectors.change_pct),
    leading_stock = COALESCE(EXCLUDED.leading_stock, public.standard_sectors.leading_stock),
    leading_stock_name = COALESCE(EXCLUDED.leading_stock_name, public.standard_sectors.leading_stock_name),
    leading_pct = COALESCE(EXCLUDED.leading_pct, public.standard_sectors.leading_pct),
    falling_stock = COALESCE(EXCLUDED.falling_stock, public.standard_sectors.falling_stock),
    falling_stock_name = COALESCE(EXCLUDED.falling_stock_name, public.standard_sectors.falling_stock_name),
    falling_pct = COALESCE(EXCLUDED.falling_pct, public.standard_sectors.falling_pct),
    stock_count = GREATEST(COALESCE(EXCLUDED.stock_count, 0), COALESCE(public.standard_sectors.stock_count, 0)),
    total_market_cap = COALESCE(EXCLUDED.total_market_cap, public.standard_sectors.total_market_cap),
    source = EXCLUDED.source,
    sync_status = EXCLUDED.sync_status,
    last_sync_at = EXCLUDED.last_sync_at,
    sync_error = NULL,
    updated_at = now();

COMMIT;
"""


def exec_psql(
    host: str,
    port: int,
    user: str,
    password: str,
    dbname: str,
    sql_file: pathlib.Path,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    cmd = [
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        dbname,
        "-f",
        str(sql_file),
    ]
    return run(cmd, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Eastmoney sector catalog data")
    add_pg_args(parser)
    parser.add_argument("--sync-source", default="eastmoney")
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)
    job_run_id = start_job(config, job_name="sync_eastmoney_sectors", job_type="collector")
    started_at = dt.datetime.now(dt.timezone.utc)
    sync_summaries: list[str] = []

    try:
        with tempfile.TemporaryDirectory(prefix="stockx_sector_sync_") as tmp_dir:
            tmp_path = pathlib.Path(tmp_dir)

            raw_rows = fetch_sector_catalog()

            for sector_type in ("industry", "concept"):
                rows = normalize_rows(raw_rows, sector_type)
                csv_path = tmp_path / f"{sector_type}_sectors.csv"
                sql_path = tmp_path / f"{sector_type}_sync.sql"
                write_csv(rows, csv_path)
                sql_path.write_text(
                    build_sql(csv_path, sector_type, args.sync_source),
                    encoding="utf-8",
                )
                exec_psql(
                    host=config.host,
                    port=config.port,
                    user=config.user,
                    password=config.password,
                    dbname=config.dbname,
                    sql_file=sql_path,
                )
                sync_summaries.append(f"{sector_type}={len(rows)}")

        finished_at = dt.datetime.now(dt.timezone.utc)
        duration = (finished_at - started_at).total_seconds()
        print(
            "sector sync completed",
            f"source={args.sync_source}",
            " ".join(sync_summaries),
            f"duration_seconds={duration:.2f}",
        )
        finish_job(
            config,
            job_run_id=job_run_id,
            status="success",
            processed_count=sum(int(item.split("=")[1]) for item in sync_summaries),
        )
        return 0
    except Exception as exc:  # pragma: no cover
        log_quality(
            config,
            data_domain="sector_sync",
            issue_type="source_error",
            issue_message=str(exc),
            issue_level="error",
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
