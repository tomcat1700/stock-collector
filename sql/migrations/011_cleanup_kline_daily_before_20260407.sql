-- Cleanup obsolete daily history before 2026-04-07.
-- Preserve table structure and keep 2026-04-07 onward only.

BEGIN;

DELETE FROM public.kline_daily
WHERE trade_date < DATE '2026-04-07';

COMMIT;
