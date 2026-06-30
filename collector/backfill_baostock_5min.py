#!/usr/bin/env python3
"""Backfill public.kline_5min from Baostock 5-minute K-line data."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import pathlib
import tempfile
import time

try:
    import baostock as bs
except ImportError as exc:  # pragma: no cover
    raise SystemExit("baostock is required. Install collector/requirements.txt") from exc

from db import (
    PgConfig,
    add_pg_args,
    exec_psql_file,
    finish_job,
    log_quality,
    psql_execute,
    psql_query,
    require_password,
    sql_quote,
    start_job,
)


FIELDNAMES = [
    "instrument_id",
    "bar_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "trade_date",
    "source",
    "is_complete",
    "bar_status",
    "version",
    "created_at",
    "updated_at",
]

BAOSTOCK_FIELDS = "date,time,code,open,high,low,close,volume,amount,adjustflag"
CN_TZ = dt.timezone(dt.timedelta(hours=8))
SUPPORTED_MARKETS = {"SH": "sh", "SZ": "sz"}


def to_baostock_code(instrument_id: str) -> str:
    code, market = instrument_id.upper().split(".", 1)
    if market not in SUPPORTED_MARKETS:
        raise ValueError(f"Baostock 5min unsupported market for {instrument_id}")
    return f"{SUPPORTED_MARKETS[market]}.{code}"


def from_baostock_code(code: str) -> str:
    market, raw_code = code.lower().split(".", 1)
    suffix = {"sh": "SH", "sz": "SZ"}[market]
    return f"{raw_code}.{suffix}"


def parse_baostock_time(raw_time: str) -> dt.datetime:
    # Example: 20260520093500000
    naive = dt.datetime.strptime(raw_time[:14], "%Y%m%d%H%M%S")
    return naive.replace(tzinfo=CN_TZ)


def to_decimal_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def to_bigint_text(value: str | None) -> str | None:
    text = to_decimal_text(value)
    if text is None:
        return None
    return str(int(float(text)))


def fetch_instrument_ids(
    config: PgConfig,
    explicit_ids: list[str],
    instrument_file: str | None,
    limit: int | None,
    start_after: str | None,
) -> list[str]:
    instrument_ids = [item.strip().upper() for item in explicit_ids if item.strip()]
    if instrument_file:
        with pathlib.Path(instrument_file).open(encoding="utf-8") as handle:
            instrument_ids.extend(line.strip().upper() for line in handle if line.strip())
    if instrument_ids:
        if start_after:
            start_after = start_after.upper()
            instrument_ids = [instrument_id for instrument_id in instrument_ids if instrument_id > start_after]
        return instrument_ids
    limit_sql = f"LIMIT {limit}" if limit else ""
    start_after_sql = f"AND instrument_id > {sql_quote(start_after.upper())}" if start_after else ""
    rows = psql_query(
        config,
        f"""
        SELECT instrument_id
        FROM public.instruments
        WHERE type = 'stock'
          AND status = 'active'
          AND market IN ('SH', 'SZ')
          {start_after_sql}
        ORDER BY instrument_id
        {limit_sql};
        """,
    )
    return [row["instrument_id"] for row in rows]


def fetch_baostock_rows(
    instrument_id: str,
    date_from: dt.date,
    date_to: dt.date,
    adjustflag: str,
    source_retries: int,
    retry_sleep_seconds: float,
) -> list[dict[str, str]]:
    last_error: Exception | None = None
    for attempt in range(1, source_retries + 2):
        try:
            rs = bs.query_history_k_data_plus(
                to_baostock_code(instrument_id),
                BAOSTOCK_FIELDS,
                start_date=date_from.isoformat(),
                end_date=date_to.isoformat(),
                frequency="5",
                adjustflag=adjustflag,
            )
            if rs.error_code != "0":
                raise RuntimeError(f"baostock error {rs.error_code}: {rs.error_msg}")

            rows: list[dict[str, str]] = []
            while rs.next():
                rows.append(dict(zip(rs.fields, rs.get_row_data(), strict=True)))
            return rows
        except Exception as exc:  # pragma: no cover
            last_error = exc
            if attempt > source_retries:
                break
            print(
                "backfill_baostock_5min retry",
                f"instrument_id={instrument_id}",
                f"attempt={attempt}/{source_retries}",
                f"message={exc}",
                flush=True,
            )
            time.sleep(retry_sleep_seconds)
            reconnect_baostock()

    raise RuntimeError(str(last_error))


def login_baostock() -> None:
    login = bs.login()
    if login.error_code != "0":
        raise SystemExit(f"Baostock login failed {login.error_code}: {login.error_msg}")


def reconnect_baostock() -> None:
    try:
        bs.logout()
    except Exception:
        pass
    login_baostock()


def normalize_rows(raw_rows: list[dict[str, str]]) -> list[dict[str, str | None]]:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rows: list[dict[str, str | None]] = []
    for raw_row in raw_rows:
        bar_time = parse_baostock_time(raw_row["time"])
        rows.append(
            {
                "instrument_id": from_baostock_code(raw_row["code"]),
                "bar_time": bar_time.isoformat(),
                "open": to_decimal_text(raw_row.get("open")),
                "high": to_decimal_text(raw_row.get("high")),
                "low": to_decimal_text(raw_row.get("low")),
                "close": to_decimal_text(raw_row.get("close")),
                "volume": to_bigint_text(raw_row.get("volume")),
                "amount": to_decimal_text(raw_row.get("amount")),
                "trade_date": bar_time.date().isoformat(),
                "source": "baostock_5min",
                "is_complete": "true",
                "bar_status": "closed",
                "version": "1",
                "created_at": now,
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

CREATE TEMP TABLE tmp_kline_5min (
    instrument_id varchar(30),
    bar_time timestamptz,
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    volume bigint,
    amount numeric,
    trade_date date,
    source varchar(32),
    is_complete boolean,
    bar_status varchar(20),
    version integer,
    created_at timestamptz,
    updated_at timestamptz
) ON COMMIT DROP;

\\copy tmp_kline_5min FROM '{escaped_csv}' WITH (FORMAT csv, HEADER true)

INSERT INTO public.kline_5min (
    instrument_id,
    bar_time,
    open,
    high,
    low,
    close,
    volume,
    amount,
    created_at,
    is_complete,
    update_count,
    updated_at,
    trade_date,
    source,
    bar_status,
    version
)
SELECT
    instrument_id,
    bar_time,
    open,
    high,
    low,
    close,
    volume,
    amount,
    created_at,
    is_complete,
    1,
    updated_at,
    trade_date,
    source,
    bar_status,
    version
FROM tmp_kline_5min
WHERE open IS NOT NULL
  AND high IS NOT NULL
  AND low IS NOT NULL
  AND close IS NOT NULL
ON CONFLICT (instrument_id, bar_time) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    amount = EXCLUDED.amount,
    is_complete = EXCLUDED.is_complete,
    update_count = public.kline_5min.update_count + 1,
    updated_at = EXCLUDED.updated_at,
    trade_date = EXCLUDED.trade_date,
    source = EXCLUDED.source,
    bar_status = EXCLUDED.bar_status,
    version = EXCLUDED.version;

COMMIT;
"""


def upsert_rows(config: PgConfig, rows: list[dict[str, str | None]]) -> None:
    if not rows:
        return
    with tempfile.TemporaryDirectory(prefix="stock_realtime_bs_5min_") as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        csv_path = tmp_path / "kline_5min.csv"
        sql_path = tmp_path / "kline_5min_upsert.sql"
        write_csv(rows, csv_path)
        sql_path.write_text(build_upsert_sql(csv_path), encoding="utf-8")
        exec_psql_file(config, sql_path)


def update_job_progress(config: PgConfig, job_run_id: int, processed_count: int, errors: int) -> None:
    psql_execute(
        config,
        f"""
        UPDATE public.job_runs
        SET processed_count = {processed_count},
            error_message = {'NULL' if errors == 0 else "'errors=" + str(errors) + "'"}
        WHERE job_run_id = {job_run_id};
        """,
    )


def log_backfill_error(
    config: PgConfig,
    instrument_id: str,
    message: str,
    date_from: dt.date,
    date_to: dt.date,
) -> None:
    log_quality(
        config,
        data_domain="kline_5min_backfill",
        ref_key=instrument_id,
        issue_type="source_error",
        issue_message=message,
        issue_level="warn",
        payload={
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "source": "baostock",
        },
    )


def flush_batch(
    config: PgConfig,
    batch: list[tuple[str, list[dict[str, str | None]]]],
    date_from: dt.date,
    date_to: dt.date,
) -> tuple[int, int]:
    if not batch:
        return 0, 0

    rows = [row for _, item_rows in batch for row in item_rows]
    if not rows:
        return 0, 0

    try:
        upsert_rows(config, rows)
        return len(rows), 0
    except Exception as exc:  # pragma: no cover
        print("backfill_baostock_5min batch_error", f"message={exc}", flush=True)

    written_rows = 0
    errors = 0
    for instrument_id, item_rows in batch:
        try:
            upsert_rows(config, item_rows)
            written_rows += len(item_rows)
        except Exception as exc:  # pragma: no cover
            errors += 1
            log_backfill_error(config, instrument_id, str(exc), date_from, date_to)
            print("backfill_baostock_5min error", f"instrument_id={instrument_id}", f"message={exc}", flush=True)
    return written_rows, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill public.kline_5min from Baostock")
    add_pg_args(parser)
    parser.add_argument("--instrument-id", action="append", default=[], help="Instrument id, repeatable")
    parser.add_argument("--instrument-file", default=None, help="One instrument_id per line")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-after", default=None, help="Resume with instrument_id greater than this value")
    parser.add_argument("--date-from", default=None, help="YYYY-MM-DD; defaults to date-to minus 365 days")
    parser.add_argument("--date-to", default=None, help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    parser.add_argument("--source-retries", type=int, default=3, help="Baostock retries per instrument")
    parser.add_argument("--retry-sleep-seconds", type=float, default=5.0)
    parser.add_argument("--batch-instruments", type=int, default=20, help="Number of instruments per database upsert")
    parser.add_argument("--adjustflag", default="3", choices=["1", "2", "3"], help="1 后复权, 2 前复权, 3 不复权")
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)

    date_to = dt.date.fromisoformat(args.date_to) if args.date_to else dt.datetime.now(CN_TZ).date()
    date_from = dt.date.fromisoformat(args.date_from) if args.date_from else date_to - dt.timedelta(days=365)
    instrument_ids = fetch_instrument_ids(config, args.instrument_id, args.instrument_file, args.limit, args.start_after)
    if not instrument_ids:
        raise SystemExit("No SH/SZ active stock instruments to backfill")

    login_baostock()

    job_run_id = start_job(config, job_name="backfill_baostock_5min", job_type="collector", run_date=date_to)
    total_rows = 0
    errors = 0
    batch: list[tuple[str, list[dict[str, str | None]]]] = []
    try:
        for index, instrument_id in enumerate(instrument_ids, start=1):
            if index > 1 and args.sleep_seconds > 0:
                time.sleep(args.sleep_seconds)
            try:
                raw_rows = fetch_baostock_rows(
                    instrument_id,
                    date_from,
                    date_to,
                    args.adjustflag,
                    args.source_retries,
                    args.retry_sleep_seconds,
                )
                rows = normalize_rows(raw_rows)
                batch.append((instrument_id, rows))
                print(
                    "backfill_baostock_5min fetched",
                    f"instrument_id={instrument_id}",
                    f"rows={len(rows)}",
                    f"progress={index}/{len(instrument_ids)}",
                    flush=True,
                )
                if len(batch) >= args.batch_instruments:
                    written_rows, batch_errors = flush_batch(config, batch, date_from, date_to)
                    total_rows += written_rows
                    errors += batch_errors
                    update_job_progress(config, job_run_id, total_rows, errors)
                    print(
                        "backfill_baostock_5min batch_flushed",
                        f"instruments={len(batch)}",
                        f"written_rows={written_rows}",
                        f"total_rows={total_rows}",
                        f"errors={errors}",
                        flush=True,
                    )
                    batch.clear()
            except Exception as exc:  # pragma: no cover
                errors += 1
                log_backfill_error(config, instrument_id, str(exc), date_from, date_to)
                print("backfill_baostock_5min error", f"instrument_id={instrument_id}", f"message={exc}", flush=True)

        written_rows, batch_errors = flush_batch(config, batch, date_from, date_to)
        total_rows += written_rows
        errors += batch_errors
        update_job_progress(config, job_run_id, total_rows, errors)
        if batch:
            print(
                "backfill_baostock_5min batch_flushed",
                f"instruments={len(batch)}",
                f"written_rows={written_rows}",
                f"total_rows={total_rows}",
                f"errors={errors}",
                flush=True,
            )

        status = "success" if errors == 0 else "partial"
        finish_job(config, job_run_id, status=status, processed_count=total_rows, error_message=None if errors == 0 else f"errors={errors}")
        print("backfill_baostock_5min completed", f"codes={len(instrument_ids)}", f"rows={total_rows}", f"errors={errors}")
        return 0 if errors == 0 else 1
    except Exception as exc:  # pragma: no cover
        finish_job(config, job_run_id, status="error", processed_count=total_rows, error_message=str(exc))
        raise
    finally:
        bs.logout()


if __name__ == "__main__":
    raise SystemExit(main())
