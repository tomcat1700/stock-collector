-- 022_job_runs_retention.sql
-- job_runs is a short-lived observability table.
-- The collector maintenance task keeps only the last 7 days.

create index if not exists idx_job_runs_started_at
    on public.job_runs (started_at);
