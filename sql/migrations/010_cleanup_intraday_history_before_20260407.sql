-- Cleanup obsolete intraday history before 2026-04-07.
-- Scope:
-- - public.realtime_quotes
-- - public.kline_minute
-- Do not touch public.kline_daily.

BEGIN;

DELETE FROM public.realtime_quotes
WHERE trade_date < DATE '2026-04-07'
   OR trade_date IS NULL;

DELETE FROM public.kline_minute
WHERE trade_date < DATE '2026-04-07'
   OR trade_date IS NULL;

COMMIT;
