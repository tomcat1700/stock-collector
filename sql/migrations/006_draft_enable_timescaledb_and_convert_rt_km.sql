-- 006_draft_enable_timescaledb_and_convert_rt_km.sql
-- 目标：
-- 1) 启用 timescaledb 扩展（若尚未启用）
-- 2) 将 realtime_quotes / kline_minute 转为 hypertable（首轮仅时间分区）
--
-- 重要：
-- - 本文件是“执行草案”，默认不自动执行
-- - 执行前请先做 pg_dump 备份与维护窗口确认
-- - 建议先在测试库完整演练

\set ON_ERROR_STOP on

-- Step 0: 启用扩展（幂等）
create extension if not exists timescaledb;

-- Step 1: realtime_quotes -> hypertable
select create_hypertable(
  'public.realtime_quotes',
  'quote_time',
  chunk_time_interval => interval '1 day',
  migrate_data => true,
  if_not_exists => true,
  create_default_indexes => false
);

-- Step 2: kline_minute -> hypertable
select create_hypertable(
  'public.kline_minute',
  'bar_time',
  chunk_time_interval => interval '30 days',
  migrate_data => true,
  if_not_exists => true,
  create_default_indexes => false
);

-- Step 3: 可选（建议二阶段评估后再开）instrument_id 空间分区
-- 注意：请先确认当前 create_hypertable/add_dimension 函数签名，再执行。
-- select add_dimension('public.realtime_quotes', 'instrument_id', number_partitions => 8);
-- select add_dimension('public.kline_minute', 'instrument_id', number_partitions => 8);

-- Step 4: 执行后建议
-- analyze public.realtime_quotes;
-- analyze public.kline_minute;
