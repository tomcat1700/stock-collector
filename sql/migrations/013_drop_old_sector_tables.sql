-- 013_drop_old_sector_tables.sql
-- 目标：删除已废弃的旧 sector_* 表，保留 standard_sectors / standard_sector_stocks

\set ON_ERROR_STOP on

drop table if exists public.sector_mapping;
drop table if exists public.sector_operation_log;
drop table if exists public.sector_quotes_daily;
drop table if exists public.sector_sync_log;
drop view if exists public.v_custom_sector_stats;
drop view if exists public.v_sector_stats;
drop view if exists public.v_sector_tree;
drop view if exists public.v_stock_all_sectors;
drop view if exists public.v_stock_sectors;
drop table if exists public.sectors cascade;
