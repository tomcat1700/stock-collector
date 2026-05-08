-- 015_cleanup_kline_daily_before_20200101.sql
-- 目标：将 public.kline_daily 裁剪为仅保留 trade_date >= 2020-01-01 的数据。

\set ON_ERROR_STOP on

delete from public.kline_daily
where trade_date < date '2020-01-01';
