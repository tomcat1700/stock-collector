WITH latest_trade_date AS (
  SELECT max(trade_date) AS trade_date
  FROM public.kline_minute
  WHERE period IN (5, 15, 30, 60)
)
SELECT period, min(bar_time AT TIME ZONE 'Asia/Shanghai') AS min_bar_time, max(bar_time AT TIME ZONE 'Asia/Shanghai') AS max_bar_time, count(*)
FROM public.kline_minute, latest_trade_date
WHERE kline_minute.trade_date = latest_trade_date.trade_date
  AND period IN (5, 15, 30, 60)
GROUP BY period
ORDER BY period;

WITH latest_trade_date AS (
  SELECT max(trade_date) AS trade_date
  FROM public.kline_minute
  WHERE period IN (5, 15, 30, 60)
)
SELECT period, count(*) AS unexpected_rows
FROM public.kline_minute, latest_trade_date
WHERE kline_minute.trade_date = latest_trade_date.trade_date
  AND (
    (period IN (5, 15, 30, 60) AND (bar_time AT TIME ZONE 'Asia/Shanghai')::time IN (TIME '09:30:00', TIME '13:00:00'))
    OR (period = 15 AND (bar_time AT TIME ZONE 'Asia/Shanghai')::time = TIME '09:15:00')
    OR (period = 30 AND (bar_time AT TIME ZONE 'Asia/Shanghai')::time = TIME '09:00:00')
    OR (period = 60 AND (bar_time AT TIME ZONE 'Asia/Shanghai')::time = TIME '08:30:00')
  )
GROUP BY period
ORDER BY period;

WITH latest_trade_date AS (
  SELECT max(trade_date) AS trade_date
  FROM public.kline_minute
  WHERE period IN (5, 15, 30, 60)
)
SELECT period, (bar_time AT TIME ZONE 'Asia/Shanghai')::time AS bar_close_time, count(*) AS rows
FROM public.kline_minute, latest_trade_date
WHERE kline_minute.trade_date = latest_trade_date.trade_date
  AND period IN (5, 15, 30, 60)
  AND (
    (period = 5 AND (bar_time AT TIME ZONE 'Asia/Shanghai')::time IN (TIME '09:35:00', TIME '11:30:00', TIME '13:05:00', TIME '15:00:00'))
    OR (period = 15 AND (bar_time AT TIME ZONE 'Asia/Shanghai')::time IN (TIME '09:45:00', TIME '11:30:00', TIME '13:15:00', TIME '15:00:00'))
    OR (period = 30 AND (bar_time AT TIME ZONE 'Asia/Shanghai')::time IN (TIME '10:00:00', TIME '11:30:00', TIME '13:30:00', TIME '15:00:00'))
    OR (period = 60 AND (bar_time AT TIME ZONE 'Asia/Shanghai')::time IN (TIME '10:30:00', TIME '11:30:00', TIME '14:00:00', TIME '15:00:00'))
  )
GROUP BY period, bar_close_time
ORDER BY period, bar_close_time;
