#!/usr/bin/env python3
"""Shared PostgreSQL helpers for collector scripts."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import pathlib
import subprocess
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PgConfig:
    host: str
    port: int
    user: str
    password: str
    dbname: str

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "PgConfig":
        return cls(
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            dbname=args.dbname,
        )


def add_pg_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=os.getenv("PGHOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--user", default=os.getenv("PGUSER", "wt"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD", ""))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "stockx"))


def require_password(config: PgConfig) -> None:
    if not config.password:
        raise SystemExit("PG password is required via --password or PGPASSWORD")


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def json_literal(payload: dict | list | None) -> str:
    if payload is None:
        return "NULL::jsonb"
    return f"{sql_quote(json.dumps(payload, ensure_ascii=False))}::jsonb"


def _env(config: PgConfig) -> dict[str, str]:
    env = os.environ.copy()
    env["PGPASSWORD"] = config.password
    return env


def run(cmd: list[str], config: PgConfig) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            check=True,
            text=True,
            capture_output=True,
            env=_env(config),
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise RuntimeError(message) from exc


def psql_query(config: PgConfig, sql: str) -> list[dict[str, str]]:
    cmd = [
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "--csv",
        "-h",
        config.host,
        "-p",
        str(config.port),
        "-U",
        config.user,
        "-d",
        config.dbname,
        "-c",
        sql,
    ]
    result = run(cmd, config)
    return list(csv.DictReader(io.StringIO(result.stdout)))


def psql_execute(config: PgConfig, sql: str) -> subprocess.CompletedProcess:
    cmd = [
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        config.host,
        "-p",
        str(config.port),
        "-U",
        config.user,
        "-d",
        config.dbname,
        "-c",
        sql,
    ]
    return run(cmd, config)


def exec_psql_file(config: PgConfig, sql_file: pathlib.Path) -> subprocess.CompletedProcess:
    cmd = [
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        config.host,
        "-p",
        str(config.port),
        "-U",
        config.user,
        "-d",
        config.dbname,
        "-f",
        str(sql_file),
    ]
    return run(cmd, config)


def to_decimal(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(value)


def to_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def start_job(
    config: PgConfig,
    job_name: str,
    job_type: str,
    run_date: dt.date | None = None,
) -> int:
    run_date_sql = sql_quote(run_date.isoformat()) if run_date else "NULL"
    rows = psql_query(
        config,
        f"""
        INSERT INTO public.job_runs (job_name, job_type, run_date, status)
        VALUES ({sql_quote(job_name)}, {sql_quote(job_type)}, {run_date_sql}, 'running')
        RETURNING job_run_id;
        """,
    )
    return int(rows[0]["job_run_id"])


def finish_job(
    config: PgConfig,
    job_run_id: int,
    status: str,
    processed_count: int,
    error_message: str | None = None,
) -> None:
    error_sql = sql_quote(error_message) if error_message else "NULL"
    psql_execute(
        config,
        f"""
        UPDATE public.job_runs
        SET status = {sql_quote(status)},
            processed_count = {processed_count},
            error_message = {error_sql},
            finished_at = now()
        WHERE job_run_id = {job_run_id};
        """,
    )


def log_quality(
    config: PgConfig,
    data_domain: str,
    issue_type: str,
    issue_message: str,
    issue_level: str = "warn",
    ref_key: str | None = None,
    payload: dict | list | None = None,
) -> None:
    ref_key_sql = sql_quote(ref_key) if ref_key else "NULL"
    psql_execute(
        config,
        f"""
        INSERT INTO public.data_quality_log (
            data_domain,
            ref_key,
            issue_type,
            issue_level,
            issue_message,
            payload_json
        )
        VALUES (
            {sql_quote(data_domain)},
            {ref_key_sql},
            {sql_quote(issue_type)},
            {sql_quote(issue_level)},
            {sql_quote(issue_message)},
            {json_literal(payload)}
        );
        """,
    )


def fetch_watchlist(config: PgConfig, limit: int | None = None) -> list[dict[str, str]]:
    limit_sql = f"LIMIT {limit}" if limit else ""
    return psql_query(
        config,
        f"""
        SELECT
            pm.instrument_id,
            COALESCE(i.code, split_part(pm.instrument_id, '.', 1)) AS code,
            COALESCE(i.name, '') AS name
        FROM public.pool_members_current pm
        LEFT JOIN public.instruments i
            ON i.instrument_id = pm.instrument_id
        ORDER BY pm.updated_at DESC, pm.instrument_id
        {limit_sql};
        """,
    )


def fetch_latest_quote_state(
    config: PgConfig,
    instrument_ids: list[str],
) -> dict[str, dict[str, Decimal | int | None]]:
    if not instrument_ids:
        return {}
    literals = ", ".join(sql_quote(item) for item in instrument_ids)
    rows = psql_query(
        config,
        f"""
        SELECT DISTINCT ON (instrument_id)
            instrument_id,
            volume,
            amount,
            quote_time
        FROM public.realtime_quotes
        WHERE instrument_id IN ({literals})
        ORDER BY instrument_id, quote_time DESC;
        """,
    )
    state: dict[str, dict[str, Decimal | int | None]] = {}
    for row in rows:
        state[row["instrument_id"]] = {
            "volume": to_int(row["volume"]),
            "amount": to_decimal(row["amount"]),
        }
    return state


def fetch_previous_trade_date(
    config: PgConfig,
    anchor_date: dt.date | None = None,
) -> dt.date:
    anchor = anchor_date or dt.date.today()
    candidate = anchor - dt.timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= dt.timedelta(days=1)
    return candidate
