#!/usr/bin/env python3
"""Apply retention cleanup for collector observability tables."""

from __future__ import annotations

import argparse

from db import PgConfig, add_pg_args, finish_job, psql_execute, psql_query, require_password, start_job


def cleanup_table_by_timestamp(
    config: PgConfig,
    table_name: str,
    timestamp_column: str,
    retention_days: int,
    batch_size: int,
    max_batches: int | None,
    extra_predicate: str = "TRUE",
) -> int:
    total_deleted = 0
    batches = 0

    while True:
        if max_batches is not None and batches >= max_batches:
            break

        rows = psql_query(
            config,
            f"""
            WITH deleted AS (
                DELETE FROM public.{table_name}
                WHERE ctid IN (
                    SELECT ctid
                    FROM public.{table_name}
                    WHERE {timestamp_column} < now() - make_interval(days => {retention_days})
                      AND ({extra_predicate})
                    ORDER BY {timestamp_column}
                    LIMIT {batch_size}
                )
                RETURNING 1
            )
            SELECT count(*) AS deleted_count
            FROM deleted;
            """,
        )
        deleted_count = int(rows[0]["deleted_count"])
        if deleted_count == 0:
            break

        total_deleted += deleted_count
        batches += 1
        print(
            f"cleanup_{table_name} batch",
            f"batch={batches}",
            f"deleted={deleted_count}",
            f"total_deleted={total_deleted}",
        )

    return total_deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup collector observability tables by retention window")
    add_pg_args(parser)
    parser.add_argument("--retention-days", type=int, default=7)
    parser.add_argument("--batch-size", type=int, default=50_000)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--vacuum", action="store_true")
    parser.add_argument(
        "--target",
        choices=["data_quality_log", "job_runs", "all"],
        default="data_quality_log",
    )
    args = parser.parse_args()

    if args.retention_days < 1:
        raise SystemExit("--retention-days must be >= 1")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")

    config = PgConfig.from_args(args)
    require_password(config)

    job_run_id = start_job(
        config,
        job_name="cleanup_data_quality_log",
        job_type="maintenance",
    )
    try:
        deleted_count = 0
        if args.target in ("data_quality_log", "all"):
            deleted_count += cleanup_table_by_timestamp(
                config,
                table_name="data_quality_log",
                timestamp_column="created_at",
                retention_days=args.retention_days,
                batch_size=args.batch_size,
                max_batches=args.max_batches,
            )
        if args.target in ("job_runs", "all"):
            deleted_count += cleanup_table_by_timestamp(
                config,
                table_name="job_runs",
                timestamp_column="started_at",
                retention_days=args.retention_days,
                batch_size=args.batch_size,
                max_batches=args.max_batches,
                extra_predicate="job_name <> 'cleanup_data_quality_log'",
            )
        if args.vacuum:
            if args.target in ("data_quality_log", "all"):
                psql_execute(config, "VACUUM (ANALYZE) public.data_quality_log;")
            if args.target in ("job_runs", "all"):
                psql_execute(config, "VACUUM (ANALYZE) public.job_runs;")
        finish_job(
            config,
            job_run_id=job_run_id,
            status="success",
            processed_count=deleted_count,
        )
        print(
            "cleanup_data_quality_log completed",
            f"target={args.target}",
            f"retention_days={args.retention_days}",
            f"deleted={deleted_count}",
            f"vacuum={args.vacuum}",
        )
        return 0
    except Exception as exc:  # pragma: no cover
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
