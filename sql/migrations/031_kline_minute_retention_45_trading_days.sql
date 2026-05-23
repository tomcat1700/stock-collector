-- 031_kline_minute_retention_45_trading_days.sql
-- Goal:
-- - kline_minute retention is controlled by collector/cleanup_kline_minute.py.
-- - Keep the latest 45 trade_date values with actual minute data.
-- - Remove any natural-time Timescale retention policy that would conflict with trading-day retention.

\set ON_ERROR_STOP on

SELECT remove_retention_policy('public.kline_minute'::regclass, if_exists => true);

CREATE INDEX IF NOT EXISTS idx_public_km_trade_date_period
ON public.kline_minute (trade_date, period, instrument_id);

COMMENT ON TABLE public.kline_minute IS
'分钟 K 线统一表（1/5/15/30/60）；由 cleanup_kline_minute.py 保留最近 45 个实际采集交易日';
