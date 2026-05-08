SELECT 'kline_daily_rows' AS check_name, count(*)::text AS check_value
FROM public.kline_daily
UNION ALL
SELECT 'kline_minute_1m_rows', count(*)::text
FROM public.kline_minute
WHERE period = 1
UNION ALL
SELECT 'bar_1m_rows', count(*)::text
FROM public.bar_1m
UNION ALL
SELECT 'kline_minute_30m_rows', count(*)::text
FROM public.kline_minute
WHERE period = 30
UNION ALL
SELECT 'bar_30m_rows', count(*)::text
FROM public.bar_30m
UNION ALL
SELECT 'bar_3s_rows', count(*)::text
FROM public.bar_3s;

SELECT 'view_check_5m' AS check_name, count(*) AS rows
FROM public.v_bar_5m
UNION ALL
SELECT 'view_check_15m', count(*)
FROM public.v_bar_15m
UNION ALL
SELECT 'view_check_60m', count(*)
FROM public.v_bar_60m;

SELECT
    km.instrument_id,
    km.bar_time,
    km.open AS old_open,
    b1.open AS new_open,
    km.close AS old_close,
    b1.close AS new_close,
    km.volume AS old_volume,
    b1.volume AS new_volume
FROM public.kline_minute km
JOIN public.bar_1m b1
  ON b1.instrument_id = km.instrument_id
 AND b1.bar_time = km.bar_time
WHERE km.period = 1
ORDER BY km.bar_time DESC
LIMIT 20;
