SELECT 'realtime_quotes_rows' AS check_name, count(*)::text AS check_value
FROM public.realtime_quotes
UNION ALL
SELECT 'kline_minute_rows', count(*)::text
FROM public.kline_minute
UNION ALL
SELECT 'kline_daily_rows', count(*)::text
FROM public.kline_daily;

SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('realtime_quotes', 'kline_minute', 'kline_daily')
ORDER BY table_name;

SELECT count(*) AS kline_second_exists
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name = 'kline_second';
