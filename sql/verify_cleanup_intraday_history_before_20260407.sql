SELECT count(*) AS old_realtime_quotes_rows
FROM public.realtime_quotes
WHERE trade_date < DATE '2026-04-07'
   OR trade_date IS NULL;

SELECT count(*) AS old_kline_minute_rows
FROM public.kline_minute
WHERE trade_date < DATE '2026-04-07'
   OR trade_date IS NULL;

SELECT trade_date, count(*) AS realtime_rows
FROM public.realtime_quotes
GROUP BY trade_date
ORDER BY trade_date DESC NULLS LAST
LIMIT 10;

SELECT trade_date, count(*) AS kline_minute_rows
FROM public.kline_minute
GROUP BY trade_date
ORDER BY trade_date DESC NULLS LAST
LIMIT 10;
