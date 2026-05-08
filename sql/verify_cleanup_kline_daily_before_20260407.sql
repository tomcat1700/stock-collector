SELECT count(*) AS old_kline_daily_rows
FROM public.kline_daily
WHERE trade_date < DATE '2026-04-07';

SELECT trade_date, count(*) AS kline_daily_rows
FROM public.kline_daily
GROUP BY trade_date
ORDER BY trade_date DESC
LIMIT 10;
