-- 019_data_quality_log_retention.sql
-- data_quality_log is a short-lived observability table.
-- The collector maintenance task keeps only the last 7 days.

create index if not exists idx_data_quality_log_created_at
    on public.data_quality_log (created_at);
