-- 007_draft_convert_kd_to_hypertable_shadow.sql
-- 目标：
-- 采用“影子表 + 校验 + 切换”方式迁移 kline_daily，最大化保护历史真值层。
--
-- 重要：
-- - 本文件是“执行草案”，默认不自动执行
-- - 执行前必须完成全量备份，并确认回滚负责人
-- - 切换前需暂停写入 kline_daily（collector 盘后校准作业）

\set ON_ERROR_STOP on

-- Step 0: 前置（扩展）
create extension if not exists timescaledb;

-- Step 1: 创建影子表（保留结构/约束/索引）
drop table if exists public.kline_daily_ht_shadow;
create table public.kline_daily_ht_shadow (like public.kline_daily including all);

-- Step 2: 全量复制数据
insert into public.kline_daily_ht_shadow
select *
from public.kline_daily
order by trade_date, instrument_id;

-- Step 3: 将影子表转换为 hypertable
select create_hypertable(
  'public.kline_daily_ht_shadow',
  'trade_date',
  chunk_time_interval => interval '365 days',
  migrate_data => false,
  if_not_exists => true,
  create_default_indexes => false
);

-- Step 4: 切换前校验（行数与时间边界）
-- 期望两侧一致后再切换
select 'kline_daily' as table_name, count(*) as row_count, min(trade_date) as min_trade_date, max(trade_date) as max_trade_date
from public.kline_daily
union all
select 'kline_daily_ht_shadow' as table_name, count(*) as row_count, min(trade_date) as min_trade_date, max(trade_date) as max_trade_date
from public.kline_daily_ht_shadow;

-- Step 5: 切换（请在低峰窗口执行）
-- 注意：backup 表名可按执行日期调整
begin;
lock table public.kline_daily in access exclusive mode;
lock table public.kline_daily_ht_shadow in access exclusive mode;

alter table public.kline_daily rename to kline_daily_pre_timescale_20260407;
alter table public.kline_daily_ht_shadow rename to kline_daily;

commit;

-- Step 6: 回滚（仅示例，按实际窗口执行）
-- begin;
-- lock table public.kline_daily in access exclusive mode;
-- lock table public.kline_daily_pre_timescale_20260407 in access exclusive mode;
-- alter table public.kline_daily rename to kline_daily_failed_20260407;
-- alter table public.kline_daily_pre_timescale_20260407 rename to kline_daily;
-- commit;
