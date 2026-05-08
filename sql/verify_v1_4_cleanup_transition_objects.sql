SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('realtime_quotes', 'kline_minute', 'kline_daily')
ORDER BY table_name;

SELECT count(*) AS transition_tables_exist
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('kline_second', 'bar_3s', 'bar_1m', 'bar_30m');

SELECT count(*) AS transition_views_exist
FROM information_schema.views
WHERE table_schema = 'public'
  AND table_name IN ('v_bar_5m', 'v_bar_15m', 'v_bar_60m');

SELECT 'realtime_quotes_rows' AS check_name, count(*)::text AS check_value
FROM public.realtime_quotes
UNION ALL
SELECT 'kline_minute_rows', count(*)::text
FROM public.kline_minute
UNION ALL
SELECT 'kline_daily_rows', count(*)::text
FROM public.kline_daily;
