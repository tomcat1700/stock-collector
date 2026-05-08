-- Drop obsolete shadow rollback table left from the 2026-04-07 kline_daily
-- Timescale shadow migration. This table is no longer part of the runtime
-- chain and has diverged from public.kline_daily after later daily backfills.

BEGIN;

DROP TABLE IF EXISTS public.kline_daily_pre_timescale_20260407;

COMMIT;
