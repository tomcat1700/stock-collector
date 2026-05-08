-- Verify collector sector sync runtime and data freshness.

SELECT
    job_name,
    status,
    processed_count,
    started_at,
    finished_at,
    left(coalesce(error_message, ''), 180) AS error_message
FROM public.job_runs
WHERE job_name IN ('sync_eastmoney_sectors', 'sync_eastmoney_sector_stocks')
ORDER BY started_at DESC
LIMIT 20;

SELECT
    data_domain,
    issue_type,
    issue_level,
    created_at,
    left(issue_message, 180) AS issue_message
FROM public.data_quality_log
WHERE data_domain IN ('sector_sync', 'sector_members')
ORDER BY id DESC
LIMIT 20;

SELECT
    sector_type,
    count(*) AS sector_count
FROM public.standard_sectors
GROUP BY 1
ORDER BY 1;

SELECT
    count(*) AS stock_rows,
    count(DISTINCT sector_code) AS sectors,
    count(DISTINCT instrument_id) AS instruments
FROM public.standard_sector_stocks;
