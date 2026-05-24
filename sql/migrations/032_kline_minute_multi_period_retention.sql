-- 032_kline_minute_multi_period_retention.sql
-- Goal:
-- - Keep 1-minute bars for 45 observed trading days.
-- - Keep 5/15/30/60-minute bars for 120 observed trading days, roughly half a trading year.
-- - Retention is period-aware and controlled by collector/cleanup_kline_minute.py.

\set ON_ERROR_STOP on

COMMENT ON TABLE public.kline_minute IS
'分钟 K 线统一表；1 分钟保留最近 45 个实际采集交易日，5/15/30/60 分钟保留最近 120 个实际采集交易日';
