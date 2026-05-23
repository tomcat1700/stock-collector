-- 030_realtime_quotes_retention_10_trading_days.sql
-- Goal:
-- - realtime_quotes retention is controlled by collector/cleanup_realtime_quotes.py.
-- - Keep the latest 10 trade_date values with actual realtime data.
-- - Remove any natural-time Timescale retention policy that would conflict with trading-day retention.

\set ON_ERROR_STOP on

SELECT remove_retention_policy('public.realtime_quotes'::regclass, if_exists => true);

CREATE INDEX IF NOT EXISTS idx_public_rt_trade_date
ON public.realtime_quotes (trade_date, instrument_id);

COMMENT ON TABLE public.realtime_quotes IS
'实时行情表（秒级）；由 cleanup_realtime_quotes.py 保留最近 10 个实际采集交易日';
