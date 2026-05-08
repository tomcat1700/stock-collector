#!/usr/bin/env python3
"""Sync Eastmoney sector constituent stocks into PostgreSQL."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import json
import pathlib
import tempfile
import time
from decimal import Decimal

try:
    import akshare as ak
    import efinance as ef
    import pandas as pd
except ImportError as exc:  # pragma: no cover
    raise SystemExit("akshare, efinance and pandas are required. Install collector/requirements.txt") from exc

from db import (
    PgConfig,
    add_pg_args,
    exec_psql_file,
    psql_query,
    finish_job,
    log_quality,
    require_password,
    start_job,
)


FIELDNAMES = [
    "sector_code",
    "instrument_id",
    "stock_code",
    "stock_name",
    "change_pct",
    "is_leading",
    "sync_at",
    "created_at",
]

DEFAULT_STATE_PATH = pathlib.Path(__file__).with_name("runtime") / "sector_member_sync_state.json"


def is_missing(value: object) -> bool:
    try:
        return value is None or pd.isna(value)
    except Exception:
        return value is None


def to_decimal_string(value: object) -> str | None:
    if is_missing(value):
        return None
    return str(Decimal(str(value)))


def normalize_text(value: object) -> str | None:
    if is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def normalize_stock_code(value: object) -> str | None:
    if is_missing(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 6:
        return digits
    if text.isdigit():
        return text.zfill(6)
    return text


def stock_instrument_id(stock_code: str) -> str:
    if stock_code.startswith(("6", "9")):
        return f"{stock_code}.SH"
    if stock_code.startswith(("8", "4")):
        return f"{stock_code}.BJ"
    return f"{stock_code}.SZ"


def sector_member_fn(sector_type: str):
    if sector_type == "industry":
        return ak.stock_board_industry_cons_em
    if sector_type == "concept":
        return ak.stock_board_concept_cons_em
    raise ValueError(f"Unsupported sector_type: {sector_type}")


def fetch_target_sectors(
    config: PgConfig,
    sector_type: str | None = None,
    limit: int | None = None,
) -> list[dict[str, str]]:
    clauses = ["source = 'eastmoney'", "sector_code LIKE 'BK%'"]
    if sector_type:
        clauses.append(f"sector_type = '{sector_type}'")
    limit_sql = f"LIMIT {limit}" if limit else ""
    rows = psql_query(
        config,
        f"""
        SELECT sector_code, sector_name, sector_type
        FROM public.standard_sectors
        WHERE {" AND ".join(clauses)}
        ORDER BY sector_type, sector_code
        {limit_sql};
        """,
    )
    return [
        {
            "sector_code": row["sector_code"],
            "sector_name": row["sector_name"],
            "sector_type": row["sector_type"],
        }
        for row in rows
    ]


def fetch_existing_member_counts(
    config: PgConfig,
    sector_codes: list[str],
) -> dict[str, int]:
    if not sector_codes:
        return {}
    literals = ", ".join("'" + code.replace("'", "''") + "'" for code in sector_codes)
    rows = psql_query(
        config,
        f"""
        SELECT sector_code, count(*) AS member_count
        FROM public.standard_sector_stocks
        WHERE sector_code IN ({literals})
        GROUP BY sector_code;
        """,
    )
    return {row["sector_code"]: int(row["member_count"]) for row in rows}


def fetch_active_stocks(
    config: PgConfig,
) -> list[dict[str, str]]:
    rows = psql_query(
        config,
        """
        SELECT instrument_id, code, COALESCE(name, '') AS name
        FROM public.instruments
        WHERE type = 'stock'
          AND COALESCE(status, 'active') = 'active'
        ORDER BY instrument_id;
        """,
    )
    return [
        {
            "instrument_id": row["instrument_id"],
            "code": row["code"],
            "name": row["name"],
        }
        for row in rows
    ]


def load_sync_state(path: pathlib.Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_sync_state(path: pathlib.Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_sector_members_frame(
    sector_type: str,
    sector_code: str,
    sector_name: str,
    max_attempts: int = 3,
    retry_sleep_seconds: float = 1.0,
) -> tuple[pd.DataFrame, str]:
    fn = sector_member_fn(sector_type)
    last_error: Exception | None = None
    for candidate in (sector_code, sector_name):
        for attempt in range(1, max(max_attempts, 1) + 1):
            try:
                frame = fn(candidate)
                if not frame.empty:
                    return frame, candidate
                last_error = RuntimeError(f"Empty frame for {candidate} attempt={attempt}")
            except Exception as exc:  # pragma: no cover
                last_error = exc
            if attempt < max(max_attempts, 1):
                time.sleep(max(retry_sleep_seconds, 0.0) * attempt)
    raise RuntimeError(f"Failed to fetch members for {sector_code}: {last_error}") from last_error


def fetch_stock_board_rows_efinance(
    stock: dict[str, str],
    allowed_sector_map: dict[str, dict[str, str]],
    as_of: dt.datetime,
    max_attempts: int = 3,
    retry_sleep_seconds: float = 1.0,
) -> list[dict[str, str | bool | None]]:
    last_error: Exception | None = None
    for attempt in range(1, max(max_attempts, 1) + 1):
        try:
            frame = ef.stock.get_belong_board(stock["code"])
            rows: list[dict[str, str | bool | None]] = []
            if frame.empty:
                return rows
            seen: set[tuple[str, str]] = set()
            for raw_row in frame.to_dict(orient="records"):
                sector_code = normalize_text(raw_row.get("板块代码"))
                if not sector_code or sector_code not in allowed_sector_map:
                    continue
                stock_code = normalize_stock_code(raw_row.get("股票代码")) or stock["code"]
                stock_name = normalize_text(raw_row.get("股票名称")) or stock["name"]
                key = (sector_code, stock["instrument_id"])
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "sector_code": sector_code,
                        "instrument_id": stock["instrument_id"],
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                        "change_pct": to_decimal_string(raw_row.get("板块涨幅")),
                        "is_leading": False,
                        "sync_at": as_of.isoformat(),
                        "created_at": as_of.isoformat(),
                    }
                )
            return rows
        except Exception as exc:  # pragma: no cover
            last_error = exc
            if attempt < max(max_attempts, 1):
                time.sleep(max(retry_sleep_seconds, 0.0) * attempt)
    raise RuntimeError(
        f"Failed to fetch eastmoney boards for {stock['instrument_id']}: {last_error}"
    ) from last_error


def normalize_rows(
    frame: pd.DataFrame,
    sector_code: str,
    as_of: dt.datetime,
) -> list[dict[str, str | bool | None]]:
    rows: list[dict[str, str | bool | None]] = []
    for raw_row in frame.to_dict(orient="records"):
        stock_code = normalize_stock_code(raw_row.get("代码") or raw_row.get("股票代码"))
        stock_name = normalize_text(raw_row.get("名称") or raw_row.get("股票简称"))
        if not stock_code or not stock_name:
            continue
        seq = raw_row.get("序号") or raw_row.get("排名")
        try:
            is_leading = int(float(seq)) == 1 if seq is not None and seq != "" else False
        except Exception:
            is_leading = False
        rows.append(
            {
                "sector_code": sector_code,
                "instrument_id": stock_instrument_id(stock_code),
                "stock_code": stock_code,
                "stock_name": stock_name,
                "change_pct": to_decimal_string(raw_row.get("涨跌幅") or raw_row.get("涨跌幅(%)")),
                "is_leading": is_leading,
                "sync_at": as_of.isoformat(),
                "created_at": as_of.isoformat(),
            }
        )
    return rows


def write_csv(rows: list[dict[str, str | bool | None]], path: pathlib.Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def build_upsert_sql(csv_path: pathlib.Path) -> str:
    escaped_csv = str(csv_path).replace("'", "''")
    return f"""
BEGIN;

CREATE TEMP TABLE tmp_standard_sector_stocks (
    sector_code varchar(50),
    instrument_id varchar(30),
    stock_code varchar(10),
    stock_name varchar(50),
    change_pct numeric(8,4),
    is_leading boolean,
    sync_at timestamptz,
    created_at timestamptz
) ON COMMIT DROP;

\\copy tmp_standard_sector_stocks FROM '{escaped_csv}' WITH (FORMAT csv, HEADER true)

DELETE FROM public.standard_sector_stocks s
WHERE s.sector_code IN (
    SELECT DISTINCT sector_code
    FROM tmp_standard_sector_stocks
)
  AND NOT EXISTS (
      SELECT 1
      FROM tmp_standard_sector_stocks keep_rows
      WHERE keep_rows.sector_code = s.sector_code
        AND keep_rows.instrument_id = s.instrument_id
  );

INSERT INTO public.standard_sector_stocks (
    sector_code,
    instrument_id,
    stock_code,
    stock_name,
    change_pct,
    is_leading,
    sync_at,
    created_at
)
SELECT
    sector_code,
    instrument_id,
    stock_code,
    stock_name,
    change_pct,
    is_leading,
    sync_at,
    created_at
FROM tmp_standard_sector_stocks
ON CONFLICT (sector_code, instrument_id) DO UPDATE SET
    stock_code = EXCLUDED.stock_code,
    stock_name = EXCLUDED.stock_name,
    change_pct = EXCLUDED.change_pct,
    is_leading = EXCLUDED.is_leading,
    sync_at = EXCLUDED.sync_at;

COMMIT;
"""


def build_incremental_upsert_sql(csv_path: pathlib.Path) -> str:
    escaped_csv = str(csv_path).replace("'", "''")
    return f"""
BEGIN;

CREATE TEMP TABLE tmp_standard_sector_stocks (
    sector_code varchar(50),
    instrument_id varchar(30),
    stock_code varchar(10),
    stock_name varchar(50),
    change_pct numeric(8,4),
    is_leading boolean,
    sync_at timestamptz,
    created_at timestamptz
) ON COMMIT DROP;

\\copy tmp_standard_sector_stocks FROM '{escaped_csv}' WITH (FORMAT csv, HEADER true)

INSERT INTO public.standard_sector_stocks (
    sector_code,
    instrument_id,
    stock_code,
    stock_name,
    change_pct,
    is_leading,
    sync_at,
    created_at
)
SELECT
    sector_code,
    instrument_id,
    stock_code,
    stock_name,
    change_pct,
    is_leading,
    sync_at,
    created_at
FROM tmp_standard_sector_stocks
ON CONFLICT (sector_code, instrument_id) DO UPDATE SET
    stock_code = EXCLUDED.stock_code,
    stock_name = EXCLUDED.stock_name,
    change_pct = EXCLUDED.change_pct,
    is_leading = EXCLUDED.is_leading,
    sync_at = EXCLUDED.sync_at;

COMMIT;
"""


def run_sync(
    config: PgConfig,
    sector_type: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    min_coverage_ratio: float = 0.7,
    fetch_retries: int = 3,
    retry_sleep_seconds: float = 1.0,
    fetch_backend: str = "efinance",
    max_workers: int = 4,
    state_file: pathlib.Path = DEFAULT_STATE_PATH,
    stocks_per_run: int = 50,
    stock_sleep_seconds: float = 0.0,
) -> dict[str, int]:
    sectors = fetch_target_sectors(config, sector_type=sector_type, limit=limit)
    existing_counts = fetch_existing_member_counts(
        config,
        [sector["sector_code"] for sector in sectors],
    )
    as_of = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    accepted_rows: list[dict[str, str | bool | None]] = []
    failed_sector_count = 0
    skipped_sector_count = 0
    accepted_sector_count = 0
    failed_stock_count = 0

    if fetch_backend == "efinance":
        state = load_sync_state(state_file)
        last_instrument_id = str(state.get("last_instrument_id") or "")
        start_index = 0
        stocks = fetch_active_stocks(config)
        if last_instrument_id:
            for idx, stock in enumerate(stocks):
                if stock["instrument_id"] == last_instrument_id:
                    start_index = idx + 1
                    break
        selected_stocks = stocks[start_index : start_index + max(stocks_per_run, 1)]
        if not selected_stocks and stocks:
            start_index = 0
            selected_stocks = stocks[: max(stocks_per_run, 1)]
        has_more = start_index + len(selected_stocks) < len(stocks)

        allowed_sector_map = {sector["sector_code"]: sector for sector in sectors}
        grouped_rows: dict[str, list[dict[str, str | bool | None]]] = {
            sector["sector_code"]: [] for sector in sectors
        }

        for offset, stock in enumerate(selected_stocks, start=1):
            try:
                stock_rows = fetch_stock_board_rows_efinance(
                    stock,
                    allowed_sector_map=allowed_sector_map,
                    as_of=as_of,
                    max_attempts=fetch_retries,
                    retry_sleep_seconds=retry_sleep_seconds,
                )
                for row in stock_rows:
                    grouped_rows[row["sector_code"]].append(row)
            except Exception as exc:  # pragma: no cover
                failed_stock_count += 1
                log_quality(
                    config,
                    data_domain="sector_members",
                    ref_key=stock["instrument_id"],
                    issue_type="source_error",
                    issue_message=str(exc),
                    issue_level="warn",
                    payload={"stock_code": stock["code"], "backend": "efinance"},
                )
            save_sync_state(
                state_file,
                {
                    "last_instrument_id": stock["instrument_id"],
                    "updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(),
                    "stocks_per_run": stocks_per_run,
                    "processed_offset": offset,
                    "start_index": start_index,
                    "total_stocks": len(stocks),
                    "has_more": has_more,
                },
            )
            if offset < len(selected_stocks):
                time.sleep(max(stock_sleep_seconds, 0.0))

        for sector in sectors:
            rows = grouped_rows.get(sector["sector_code"], [])
            if not rows:
                continue
            existing_count = existing_counts.get(sector["sector_code"], 0)
            min_acceptable_count = (
                max(1, math.ceil(existing_count * max(min_coverage_ratio, 0.0)))
                if existing_count > 0
                else 1
            )
            if existing_count > 0 and len(rows) < min_acceptable_count:
                skipped_sector_count += 1
                coverage_ratio = len(rows) / existing_count if existing_count else 0.0
                log_quality(
                    config,
                    data_domain="sector_members",
                    ref_key=sector["sector_code"],
                    issue_type="suspect_partial_member_frame",
                    issue_message=(
                        f"Skip replace for {sector['sector_code']}: "
                        f"rows={len(rows)} existing={existing_count}"
                    ),
                    issue_level="warn",
                    payload={
                        "sector_name": sector["sector_name"],
                        "sector_type": sector["sector_type"],
                        "rows": len(rows),
                        "existing_count": existing_count,
                        "coverage_ratio": round(coverage_ratio, 4),
                        "min_coverage_ratio": min_coverage_ratio,
                        "backend": "efinance",
                    },
                )
                continue
            accepted_rows.extend(rows)
            accepted_sector_count += 1

        if dry_run or not accepted_rows:
            return {
                "sector_count": len(sectors),
                "accepted_sector_count": accepted_sector_count,
                "skipped_sector_count": skipped_sector_count,
                "row_count": len(accepted_rows),
                "failed_sector_count": failed_sector_count,
                "failed_stock_count": failed_stock_count,
                "processed_stock_count": len(selected_stocks),
                "has_more": has_more,
            }

        with tempfile.TemporaryDirectory(prefix="stockx_sector_members_") as tmp_dir:
            tmp_path = pathlib.Path(tmp_dir)
            csv_path = tmp_path / "standard_sector_stocks.csv"
            sql_path = tmp_path / "standard_sector_stocks_upsert.sql"
            write_csv(accepted_rows, csv_path)
            sql_path.write_text(build_incremental_upsert_sql(csv_path), encoding="utf-8")
            exec_psql_file(config, sql_path)

        return {
            "sector_count": len(sectors),
            "accepted_sector_count": accepted_sector_count,
            "skipped_sector_count": skipped_sector_count,
            "row_count": len(accepted_rows),
            "failed_sector_count": failed_sector_count,
            "failed_stock_count": failed_stock_count,
            "processed_stock_count": len(selected_stocks),
            "has_more": has_more,
        }

    for sector in sectors:
        try:
            frame, resolved = fetch_sector_members_frame(
                sector["sector_type"],
                sector["sector_code"],
                sector["sector_name"],
                max_attempts=fetch_retries,
                retry_sleep_seconds=retry_sleep_seconds,
            )
            rows = normalize_rows(frame, sector["sector_code"], as_of)
            if not rows:
                failed_sector_count += 1
                log_quality(
                    config,
                    data_domain="sector_members",
                    ref_key=sector["sector_code"],
                    issue_type="empty_member_frame",
                    issue_message=f"No members returned for {sector['sector_code']} ({resolved})",
                    issue_level="warn",
                    payload={"sector_name": sector["sector_name"], "sector_type": sector["sector_type"]},
                )
                continue
            existing_count = existing_counts.get(sector["sector_code"], 0)
            min_acceptable_count = (
                max(1, math.ceil(existing_count * max(min_coverage_ratio, 0.0)))
                if existing_count > 0
                else 1
            )
            if existing_count > 0 and len(rows) < min_acceptable_count:
                skipped_sector_count += 1
                coverage_ratio = len(rows) / existing_count if existing_count else 0.0
                log_quality(
                    config,
                    data_domain="sector_members",
                    ref_key=sector["sector_code"],
                    issue_type="suspect_partial_member_frame",
                    issue_message=(
                        f"Skip replace for {sector['sector_code']}: "
                        f"rows={len(rows)} existing={existing_count}"
                    ),
                    issue_level="warn",
                    payload={
                        "sector_name": sector["sector_name"],
                        "sector_type": sector["sector_type"],
                        "resolved_target": resolved,
                        "rows": len(rows),
                        "existing_count": existing_count,
                        "coverage_ratio": round(coverage_ratio, 4),
                        "min_coverage_ratio": min_coverage_ratio,
                    },
                )
                continue
            accepted_rows.extend(rows)
            accepted_sector_count += 1
        except Exception as exc:  # pragma: no cover
            failed_sector_count += 1
            log_quality(
                config,
                data_domain="sector_members",
                ref_key=sector["sector_code"],
                issue_type="source_error",
                issue_message=str(exc),
                issue_level="warn",
                payload={"sector_name": sector["sector_name"], "sector_type": sector["sector_type"]},
            )

    if dry_run or not accepted_rows:
        return {
            "sector_count": len(sectors),
            "accepted_sector_count": accepted_sector_count,
            "skipped_sector_count": skipped_sector_count,
            "row_count": len(accepted_rows),
            "failed_sector_count": failed_sector_count,
        }

    with tempfile.TemporaryDirectory(prefix="stockx_sector_members_") as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        csv_path = tmp_path / "standard_sector_stocks.csv"
        sql_path = tmp_path / "standard_sector_stocks_upsert.sql"
        write_csv(accepted_rows, csv_path)
        sql_path.write_text(build_upsert_sql(csv_path), encoding="utf-8")
        exec_psql_file(config, sql_path)

    return {
        "sector_count": len(sectors),
        "accepted_sector_count": accepted_sector_count,
        "skipped_sector_count": skipped_sector_count,
        "row_count": len(accepted_rows),
        "failed_sector_count": failed_sector_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Eastmoney sector constituent stocks")
    add_pg_args(parser)
    parser.add_argument("--sector-type", choices=("industry", "concept"), default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-coverage-ratio", type=float, default=0.7)
    parser.add_argument("--fetch-retries", type=int, default=3)
    parser.add_argument("--retry-sleep-seconds", type=float, default=1.0)
    parser.add_argument("--fetch-backend", choices=("efinance", "akshare"), default="efinance")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--stocks-per-run", type=int, default=50)
    parser.add_argument("--stock-sleep-seconds", type=float, default=0.0)
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)

    job_run_id = start_job(
        config,
        job_name="sync_eastmoney_sector_stocks",
        job_type="collector",
    )
    try:
        result = run_sync(
            config,
            sector_type=args.sector_type,
            limit=args.limit,
            dry_run=args.dry_run,
            min_coverage_ratio=args.min_coverage_ratio,
            fetch_retries=args.fetch_retries,
            retry_sleep_seconds=args.retry_sleep_seconds,
            fetch_backend=args.fetch_backend,
            max_workers=args.max_workers,
            state_file=pathlib.Path(args.state_file),
            stocks_per_run=args.stocks_per_run,
            stock_sleep_seconds=args.stock_sleep_seconds,
        )
        if args.dry_run:
            status = "dry_run" if result["failed_sector_count"] == 0 else "dry_partial"
        else:
            status = "success" if result["failed_sector_count"] == 0 else "partial"
        finish_job(
            config,
            job_run_id=job_run_id,
            status=status,
            processed_count=result["row_count"],
        )
        print(
            "sector member sync completed",
            f"sectors={result['sector_count']}",
            f"accepted_sectors={result['accepted_sector_count']}",
            f"skipped_sectors={result['skipped_sector_count']}",
            f"processed_stocks={result.get('processed_stock_count', 0)}",
            f"has_more={result.get('has_more', False)}",
            f"rows={result['row_count']}",
            f"failed_sectors={result['failed_sector_count']}",
            f"dry_run={args.dry_run}",
        )
        return 0
    except Exception as exc:  # pragma: no cover
        log_quality(
            config,
            data_domain="sector_members",
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
