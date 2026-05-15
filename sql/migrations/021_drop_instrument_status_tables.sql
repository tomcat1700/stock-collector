-- 021_drop_instrument_status_tables.sql
-- stock_realtime is scoped to collector-required data.
-- Keep public.instruments as the collector instrument master and remove
-- application/status-management objects that are not read by collectors.

drop view if exists public.v_active_stocks;
drop view if exists public.v_delisted_stocks;
drop view if exists public.v_new_stocks;
drop view if exists public.v_stock_status_stats;
drop view if exists public.v_suspended_stocks;

drop function if exists public.cleanup_delisted_stocks();
drop function if exists public.get_active_instruments();
drop function if exists public.update_new_stock_status();

drop table if exists public.instrument_status_log;
drop table if exists public.instrument_status;
