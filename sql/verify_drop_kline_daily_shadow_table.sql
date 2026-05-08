SELECT to_regclass('public.kline_daily_pre_timescale_20260407') AS dropped_table_should_be_null;

SELECT count(*) AS kline_daily_rows
FROM public.kline_daily;
