-- 036_alter_price_columns_to_2dp.sql
-- 所有价格数据统一为2位小数四舍五入
-- kline_daily: open/high/low/close numeric(12,4) -> numeric(12,2)
-- kline_daily_qfq: open/high/low/close numeric(18,6) -> numeric(12,2),
--   change/pct_change/amplitude -> numeric(X,2)

\set ON_ERROR_STOP on

-- ---- kline_daily ----
-- 注意：这是 TimescaleDB 超表，ALTER 期间需要排他锁，
-- 请在收盘后（realtime loop 停止时）执行。

ALTER TABLE public.kline_daily
  ALTER COLUMN open  TYPE numeric(12,2),
  ALTER COLUMN high  TYPE numeric(12,2),
  ALTER COLUMN low   TYPE numeric(12,2),
  ALTER COLUMN close TYPE numeric(12,2),
  ALTER COLUMN change TYPE numeric(12,2),
  ALTER COLUMN pct_change TYPE numeric(8,2),
  ALTER COLUMN amplitude  TYPE numeric(8,2);

-- ---- kline_daily_qfq ----
ALTER TABLE public.kline_daily_qfq
  ALTER COLUMN open   TYPE numeric(12,2),
  ALTER COLUMN high   TYPE numeric(12,2),
  ALTER COLUMN low    TYPE numeric(12,2),
  ALTER COLUMN close  TYPE numeric(12,2),
  ALTER COLUMN change TYPE numeric(12,2),
  ALTER COLUMN pct_change TYPE numeric(10,2),
  ALTER COLUMN amplitude  TYPE numeric(10,2);
