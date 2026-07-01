#!/usr/bin/env python3
"""Fetch realtime watchlist quotes and upsert them into public.realtime_quotes."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import pathlib
import subprocess
import tempfile
import time
from decimal import Decimal

try:
    import akshare as ak
    import pandas as pd
except ImportError as exc:  # pragma: no cover
    raise SystemExit("akshare and pandas are required. Install collector/requirements.txt") from exc

from db import (
    PgConfig,
    add_pg_args,
    exec_psql_file,
    fetch_latest_quote_state,
    fetch_watchlist,
    finish_job,
    log_quality,
    require_password,
    start_job,
)
from runtime_control import normalize_source, source_preference_order


TRADE_DAY_PROBE_WATCHLIST = [
    {
        "instrument_id": "000001.SH",
        "code": "000001",
        "name": "上证指数",
        "instrument_type": "index",
    }
]


FIELDNAMES = [
    "instrument_id",
    "quote_time",
    "name",
    "open",
    "pre_close",
    "current",
    "high",
    "low",
    "volume",
    "amount",
    "change",
    "change_pct",
    "amplitude",
    "trade_date",
    "trade_time",
    "created_at",
    "is_closing",
    "source",
    "session_phase",
    "cum_volume",
    "cum_amount",
    "delta_volume",
    "delta_amount",
    "is_valid",
    "ingest_batch_id",
    "raw_payload",
]

def pick_value(row: dict, *candidates: str):
    for candidate in candidates:
        if candidate in row:
            value = row[candidate]
            if value is not None and not (isinstance(value, float) and math.isnan(value)):
                return value
    return None


def normalize_code(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return text.zfill(6)
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 6:
        return digits
    return text


def to_decimal_string(value: object, decimals: int = 2) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(Decimal(str(round(float(value), decimals))))


def to_int_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(int(Decimal(str(value))))


def compute_session_phase(ts: dt.datetime) -> tuple[str, bool]:
    local_time = ts.timetz().replace(tzinfo=None)
    if local_time < dt.time(9, 29, 58):
        return "pre_open", False
    if local_time <= dt.time(11, 30, 2):
        return "continuous_am", False
    if local_time < dt.time(13, 0):
        return "lunch_break", False
    if local_time < dt.time(14, 57, 2):
        return "continuous_pm", False
    if local_time < dt.time(15, 0, 1):
        return "close_auction_pause", True
    if local_time <= dt.time(15, 0, 59):
        return "close_call", True
    return "closed", True


def should_persist_realtime_timestamp(ts: dt.datetime) -> bool:
    local_time = ts.timetz().replace(tzinfo=None)
    return (
        dt.time(9, 29, 58) <= local_time <= dt.time(11, 30, 2)
        or dt.time(13, 0, 0) <= local_time < dt.time(14, 57, 2)
        or dt.time(15, 0, 1) <= local_time <= dt.time(15, 0, 59)
    )


def parse_source_timestamp(raw_row: dict) -> dt.datetime | None:
    trade_date = pick_value(raw_row, "日期")
    trade_time = pick_value(raw_row, "时间")
    if not trade_date or not trade_time:
        return None
    try:
        return dt.datetime.fromisoformat(f"{trade_date}T{trade_time}+08:00")
    except ValueError:
        return None


def sina_symbol(instrument_id: str, code: str) -> str:
    market_suffix = instrument_id.split(".")[-1].lower() if "." in instrument_id else ""
    normalized = normalize_code(code) or normalize_code(instrument_id) or code
    if market_suffix in {"sz", "sh", "bj"}:
        return f"{market_suffix}{normalized}"
    if normalized and normalized.startswith(("6", "9")):
        return f"sh{normalized}"
    return f"sz{normalized}"


def fetch_sina_watchlist_frame(watchlist: list[dict[str, str]]) -> pd.DataFrame:
    symbols = [sina_symbol(item["instrument_id"], item["code"]) for item in watchlist]
    url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
    result = subprocess.run(
        [
            "curl",
            "--http1.1",
            "-L",
            "--silent",
            "--show-error",
            "--max-time",
            "20",
            "-H",
            "Referer: https://finance.sina.com.cn",
            "-H",
            "User-Agent: Mozilla/5.0",
            url,
        ],
        check=True,
        capture_output=True,
    )
    payload = result.stdout.decode("gbk", errors="ignore")
    rows: list[dict[str, object]] = []
    for line in payload.splitlines():
        if not line.startswith("var hq_str_") or '="' not in line:
            continue
        symbol, quoted = line.split('="', 1)
        body = quoted.rsplit('";', 1)[0]
        fields = body.split(",")
        if len(fields) < 32:
            continue
        rows.append(
            {
                "symbol": symbol.replace("var hq_str_", ""),
                "代码": symbol.replace("var hq_str_", "")[-6:],
                "名称": fields[0],
                "今开": fields[1],
                "昨收": fields[2],
                "最新价": fields[3],
                "最高": fields[4],
                "最低": fields[5],
                "买一": fields[6],
                "卖一": fields[7],
                "成交量": fields[8],
                "成交额": fields[9],
                "买一量": fields[10],
                "买一价": fields[11],
                "买二量": fields[12],
                "买二价": fields[13],
                "买三量": fields[14],
                "买三价": fields[15],
                "买四量": fields[16],
                "买四价": fields[17],
                "买五量": fields[18],
                "买五价": fields[19],
                "卖一量": fields[20],
                "卖一价": fields[21],
                "卖二量": fields[22],
                "卖二价": fields[23],
                "卖三量": fields[24],
                "卖三价": fields[25],
                "卖四量": fields[26],
                "卖四价": fields[27],
                "卖五量": fields[28],
                "卖五价": fields[29],
                "日期": fields[30],
                "时间": fields[31],
            }
        )
    return pd.DataFrame(rows)


def fetch_source_frame(watchlist: list[dict[str, str]], source: str) -> pd.DataFrame:
    normalized_source = normalize_source(source)
    if normalized_source == "eastmoney":
        return ak.stock_zh_a_spot_em()
    if normalized_source == "sina":
        return fetch_sina_watchlist_frame(watchlist)
    return pd.DataFrame()


def fetch_spot_frame(
    watchlist: list[dict[str, str]],
    preferred_source: str | None = None,
    allow_fallback: bool = True,
) -> tuple[pd.DataFrame, str]:
    sources = (
        source_preference_order(preferred_source)
        if allow_fallback
        else [normalize_source(preferred_source)]
    )
    for source in sources:
        try:
            frame = fetch_source_frame(watchlist, source)
            if not frame.empty:
                return frame, source
        except Exception:
            continue
    raise RuntimeError("No realtime source returned a usable snapshot")


def probe_source_trade_date(
    config: PgConfig,
    preferred_source: str,
    limit: int | None = 1,
) -> dict[str, str | None]:
    del config, limit
    watchlist = TRADE_DAY_PROBE_WATCHLIST
    frame, resolved_source = fetch_spot_frame(
        watchlist,
        preferred_source=normalize_source(preferred_source),
        allow_fallback=False,
    )
    latest_trade_date: dt.date | None = None
    for raw_row in frame.to_dict(orient="records"):
        row_timestamp = parse_source_timestamp(raw_row)
        if row_timestamp is None:
            continue
        row_trade_date = row_timestamp.date()
        if latest_trade_date is None or row_trade_date > latest_trade_date:
            latest_trade_date = row_trade_date
    return {
        "status": "success" if latest_trade_date is not None else "missing_trade_date",
        "source": resolved_source,
        "trade_date": latest_trade_date.isoformat() if latest_trade_date else None,
    }


def normalize_rows(
    frame: pd.DataFrame,
    watchlist: list[dict[str, str]],
    previous_state: dict[str, dict[str, Decimal | int | None]],
    as_of: dt.datetime,
    source: str,
    ingest_batch_id: str,
) -> list[dict[str, str | bool | None]]:
    code_to_instruments: dict[str, list[str]] = {}
    symbol_to_instrument = {
        sina_symbol(item["instrument_id"], item["code"]): item["instrument_id"]
        for item in watchlist
    }
    for item in watchlist:
        code = normalize_code(item["code"])
        if code:
            code_to_instruments.setdefault(code, []).append(item["instrument_id"])
    code_to_instrument = {
        code: instruments[0]
        for code, instruments in code_to_instruments.items()
        if len(instruments) == 1
    }
    watch_codes = set(code_to_instrument)
    rows: list[dict[str, str | bool | None]] = []

    for raw_row in frame.to_dict(orient="records"):
        raw_symbol = str(pick_value(raw_row, "symbol") or "").strip()
        instrument_id = symbol_to_instrument.get(raw_symbol) if source == "sina" else None
        code = normalize_code(pick_value(raw_row, "代码", "symbol", "code"))
        if instrument_id is None:
            if code not in watch_codes:
                continue
            instrument_id = code_to_instrument[code]
        if instrument_id is None:
            continue

        row_timestamp = parse_source_timestamp(raw_row)
        if row_timestamp is None:
            if source == "sina":
                # Sina rows must carry source-side date/time; do not fall back to system time.
                continue
            row_timestamp = as_of
        if not should_persist_realtime_timestamp(row_timestamp):
            continue
        session_phase, is_closing = compute_session_phase(row_timestamp)
        cum_volume = Decimal(to_int_string(pick_value(raw_row, "成交量", "总手")) or "0")
        cum_amount = Decimal(to_decimal_string(pick_value(raw_row, "成交额")) or "0")
        previous = previous_state.get(instrument_id, {})
        previous_volume = previous.get("volume")
        previous_amount = previous.get("amount")

        if previous_volume is None or cum_volume < previous_volume:
            delta_volume = 0
        else:
            delta_volume = int(cum_volume - Decimal(previous_volume))

        if previous_amount is None or cum_amount < previous_amount:
            delta_amount = Decimal("0")
        else:
            delta_amount = cum_amount - Decimal(previous_amount)

        payload = {
            key: (
                None
                if value is None or (isinstance(value, float) and math.isnan(value))
                else value
            )
            for key, value in raw_row.items()
        }
        current_value = to_decimal_string(pick_value(raw_row, "最新价", "最新", "现价"))

        rows.append(
            {
                "instrument_id": instrument_id,
                "quote_time": row_timestamp.isoformat(),
                "name": str(pick_value(raw_row, "名称", "name") or ""),
                "open": to_decimal_string(pick_value(raw_row, "今开", "开盘")),
                "pre_close": to_decimal_string(pick_value(raw_row, "昨收")),
                "current": current_value,
                "high": to_decimal_string(pick_value(raw_row, "最高")),
                "low": to_decimal_string(pick_value(raw_row, "最低")),
                "volume": str(int(cum_volume)),
                "amount": str(cum_amount),
                "change": to_decimal_string(pick_value(raw_row, "涨跌额")),
                "change_pct": to_decimal_string(pick_value(raw_row, "涨跌幅")),
                "amplitude": to_decimal_string(pick_value(raw_row, "振幅")),
                "trade_date": row_timestamp.date().isoformat(),
                "trade_time": row_timestamp.strftime("%H:%M:%S"),
                "created_at": as_of.isoformat(),
                "is_closing": is_closing,
                "source": source,
                "session_phase": session_phase,
                "cum_volume": str(int(cum_volume)),
                "cum_amount": str(cum_amount),
                "delta_volume": str(delta_volume),
                "delta_amount": str(delta_amount),
                "is_valid": current_value is not None,
                "ingest_batch_id": ingest_batch_id,
                "raw_payload": json.dumps(payload, ensure_ascii=False),
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

CREATE TEMP TABLE tmp_realtime_quotes (
    instrument_id varchar(30),
    quote_time timestamptz,
    name varchar(100),
    open numeric(12,4),
    pre_close numeric(12,4),
    current numeric(12,4),
    high numeric(12,4),
    low numeric(12,4),
    volume bigint,
    amount numeric(16,2),
    change numeric(12,4),
    change_pct numeric(8,4),
    amplitude numeric(8,4),
    trade_date date,
    trade_time time,
    created_at timestamptz,
    is_closing boolean,
    source varchar(20),
    session_phase varchar(20),
    cum_volume bigint,
    cum_amount numeric(20,2),
    delta_volume bigint,
    delta_amount numeric(20,2),
    is_valid boolean,
    ingest_batch_id varchar(50),
    raw_payload jsonb
) ON COMMIT DROP;

\\copy tmp_realtime_quotes FROM '{escaped_csv}' WITH (FORMAT csv, HEADER true)

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
    src.instrument_id,
    src.quote_time,
    NULLIF(src.name, ''),
    src.open,
    src.pre_close,
    src.current,
    src.high,
    src.low,
    src.volume,
    src.amount,
    src.change,
    src.change_pct,
    src.amplitude,
    src.trade_date,
    src.trade_time,
    src.created_at,
    src.is_closing,
    src.source,
    src.session_phase,
    src.cum_volume,
    src.cum_amount,
    src.delta_volume,
    src.delta_amount,
    src.is_valid,
    src.ingest_batch_id,
    src.raw_payload
FROM tmp_realtime_quotes AS src
ON CONFLICT (instrument_id, quote_time) DO NOTHING;

COMMIT;
"""


def run_collection(
    config: PgConfig,
    source: str,
    limit: int | None = None,
    ingest_batch_id: str | None = None,
    allow_fallback: bool = True,
) -> dict[str, int | str | float]:
    total_started_at = time.perf_counter()
    fetch_watchlist_started_at = time.perf_counter()
    watchlist = fetch_watchlist(config, limit=limit)
    fetch_watchlist_seconds = time.perf_counter() - fetch_watchlist_started_at
    if not watchlist:
        log_quality(
            config,
            data_domain="realtime_collect",
            issue_type="empty_watchlist",
            issue_message="No instruments found in collector_watchlist",
            issue_level="warn",
        )
        return {
            "status": "empty_watchlist",
            "row_count": 0,
            "batch_id": ingest_batch_id or "",
            "source": normalize_source(source),
            "fetch_watchlist_seconds": round(fetch_watchlist_seconds, 3),
            "latest_state_seconds": 0.0,
            "fetch_source_seconds": 0.0,
            "normalize_seconds": 0.0,
            "upsert_realtime_quotes_seconds": 0.0,
            "total_seconds": round(time.perf_counter() - total_started_at, 3),
        }

    as_of = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    batch_id = ingest_batch_id or as_of.strftime("%Y%m%d%H%M%S%f")
    latest_state_started_at = time.perf_counter()
    previous_state = fetch_latest_quote_state(
        config,
        [item["instrument_id"] for item in watchlist],
    )
    latest_state_seconds = time.perf_counter() - latest_state_started_at
    sources = (
        source_preference_order(source)
        if allow_fallback
        else [normalize_source(source)]
    )
    rows: list[dict[str, str | bool | None]] = []
    resolved_source = normalize_source(source)
    saw_non_empty_frame = False
    fetch_source_seconds = 0.0
    normalize_seconds = 0.0
    for candidate_source in sources:
        fetch_source_started_at = time.perf_counter()
        try:
            frame = fetch_source_frame(watchlist, candidate_source)
        except Exception:
            fetch_source_seconds += time.perf_counter() - fetch_source_started_at
            if not allow_fallback:
                raise
            continue
        fetch_source_seconds += time.perf_counter() - fetch_source_started_at
        if frame.empty:
            continue
        saw_non_empty_frame = True
        normalize_started_at = time.perf_counter()
        candidate_rows = normalize_rows(
            frame,
            watchlist,
            previous_state,
            as_of,
            candidate_source,
            batch_id,
        )
        normalize_seconds += time.perf_counter() - normalize_started_at
        if candidate_rows:
            rows = candidate_rows
            resolved_source = candidate_source
            break

    if not saw_non_empty_frame:
        raise RuntimeError("No realtime source returned a usable snapshot")

    if not rows:
        log_quality(
            config,
            data_domain="realtime_collect",
            issue_type="empty_payload",
            issue_message="AkShare returned no rows for current watchlist",
            issue_level="warn",
            payload={"watchlist_size": len(watchlist)},
        )
        return {
            "status": "empty_payload",
            "row_count": 0,
            "batch_id": batch_id,
            "source": resolved_source,
            "fetch_watchlist_seconds": round(fetch_watchlist_seconds, 3),
            "latest_state_seconds": round(latest_state_seconds, 3),
            "fetch_source_seconds": round(fetch_source_seconds, 3),
            "normalize_seconds": round(normalize_seconds, 3),
            "upsert_realtime_quotes_seconds": 0.0,
            "total_seconds": round(time.perf_counter() - total_started_at, 3),
        }

    latest_trade_date = max(dt.date.fromisoformat(str(row["trade_date"])) for row in rows if row["trade_date"])
    if latest_trade_date < as_of.date():
        log_quality(
            config,
            data_domain="realtime_collect",
            issue_type="stale_snapshot",
            issue_message=f"Source returned stale snapshot trade_date={latest_trade_date.isoformat()}",
            issue_level="warn",
            payload={"batch_id": batch_id, "source": resolved_source},
        )
        return {
            "status": "stale_snapshot",
            "row_count": 0,
            "batch_id": batch_id,
            "source": resolved_source,
            "fetch_watchlist_seconds": round(fetch_watchlist_seconds, 3),
            "latest_state_seconds": round(latest_state_seconds, 3),
            "fetch_source_seconds": round(fetch_source_seconds, 3),
            "normalize_seconds": round(normalize_seconds, 3),
            "upsert_realtime_quotes_seconds": 0.0,
            "total_seconds": round(time.perf_counter() - total_started_at, 3),
        }

    upsert_started_at = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="stockx_collect_realtime_") as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        csv_path = tmp_path / "realtime_quotes.csv"
        sql_path = tmp_path / "realtime_quotes_upsert.sql"
        write_csv(rows, csv_path)
        sql_path.write_text(build_upsert_sql(csv_path), encoding="utf-8")
        exec_psql_file(config, sql_path)
    upsert_realtime_quotes_seconds = time.perf_counter() - upsert_started_at

    total_seconds = time.perf_counter() - total_started_at

    if total_seconds >= 5:
        log_quality(
            config,
            data_domain="realtime_collect",
            issue_type="slow_cycle",
            issue_message=f"collect_realtime slow cycle total_seconds={total_seconds:.3f}",
            issue_level="warn",
            payload={
                "watchlist_size": len(watchlist),
                "row_count": len(rows),
                "source": resolved_source,
                "batch_id": batch_id,
                "fetch_watchlist_seconds": round(fetch_watchlist_seconds, 3),
                "latest_state_seconds": round(latest_state_seconds, 3),
                "fetch_source_seconds": round(fetch_source_seconds, 3),
                "normalize_seconds": round(normalize_seconds, 3),
                "upsert_realtime_quotes_seconds": round(upsert_realtime_quotes_seconds, 3),
                "total_seconds": round(total_seconds, 3),
            },
        )

    return {
        "status": "success",
        "row_count": len(rows),
        "batch_id": batch_id,
        "source": resolved_source,
        "fetch_watchlist_seconds": round(fetch_watchlist_seconds, 3),
        "latest_state_seconds": round(latest_state_seconds, 3),
        "fetch_source_seconds": round(fetch_source_seconds, 3),
        "normalize_seconds": round(normalize_seconds, 3),
        "upsert_realtime_quotes_seconds": round(upsert_realtime_quotes_seconds, 3),
        "total_seconds": round(total_seconds, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect realtime watchlist quotes")
    add_pg_args(parser)
    parser.add_argument("--source", default="eastmoney")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ingest-batch-id", default=None)
    args = parser.parse_args()

    config = PgConfig.from_args(args)
    require_password(config)

    job_run_id = start_job(config, job_name="collect_realtime", job_type="collector")
    try:
        result = run_collection(
            config,
            source=args.source,
            limit=args.limit,
            ingest_batch_id=args.ingest_batch_id,
            allow_fallback=True,
        )
        status = "success" if result["status"] == "success" else "partial"
        error_message = None if status == "success" else str(result["status"])
        finish_job(
            config,
            job_run_id=job_run_id,
            status=status,
            processed_count=int(result["row_count"]),
            error_message=error_message,
        )
        print(
            "collect_realtime completed",
            f"status={result['status']}",
            f"rows={result['row_count']}",
            f"batch_id={result['batch_id']}",
            f"source={result['source']}",
            f"fetch_watchlist_seconds={result.get('fetch_watchlist_seconds', 0.0)}",
            f"latest_state_seconds={result.get('latest_state_seconds', 0.0)}",
            f"fetch_source_seconds={result.get('fetch_source_seconds', 0.0)}",
            f"normalize_seconds={result.get('normalize_seconds', 0.0)}",
            f"upsert_realtime_quotes_seconds={result.get('upsert_realtime_quotes_seconds', 0.0)}",
            f"total_seconds={result.get('total_seconds', 0.0)}",
        )
        return 0
    except Exception as exc:  # pragma: no cover
        log_quality(
            config,
            data_domain="realtime_collect",
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
