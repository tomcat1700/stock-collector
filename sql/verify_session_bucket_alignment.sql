SELECT period, min(bar_time AT TIME ZONE 'Asia/Shanghai') AS min_bar_time, max(bar_time AT TIME ZONE 'Asia/Shanghai') AS max_bar_time, count(*)
FROM public.kline_minute
WHERE trade_date = DATE '2026-04-10'
  AND period IN (15, 30, 60)
GROUP BY period
ORDER BY period;

SELECT period, count(*) AS unexpected_rows
FROM public.kline_minute
WHERE trade_date = DATE '2026-04-10'
  AND (
    (period = 15 AND (bar_time AT TIME ZONE 'Asia/Shanghai')::time = TIME '09:15:00')
    OR (period = 30 AND (bar_time AT TIME ZONE 'Asia/Shanghai')::time = TIME '09:00:00')
    OR (period = 60 AND (bar_time AT TIME ZONE 'Asia/Shanghai')::time = TIME '08:30:00')
  )
GROUP BY period
ORDER BY period;
