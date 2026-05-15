-- 018_drop_non_collector_business_tables.sql
-- Keep stock_realtime focused on collector-owned market data.
--
-- Retained collector scope:
-- - realtime_quotes, kline_minute, kline_daily, daily_basic
-- - instruments
-- - collector_watchlist
-- - standard_sectors, standard_sector_stocks
-- - job_runs, data_quality_log

drop view if exists public.v_stock_notes_stats;

drop function if exists public.cleanup_preferred_pool();

drop table if exists
    public.account_assets_daily,
    public.accounts,
    public.alerts,
    public.custom_sector_stocks,
    public.custom_sectors,
    public.order_intents,
    public.orders,
    public.positions,
    public.preferred_pool,
    public.risk_events,
    public.risk_rules,
    public.signal_checks,
    public.signals,
    public.sim_equity_curve,
    public.sim_orders,
    public.sim_positions,
    public.sim_trades,
    public.stock_notes,
    public.stock_pool,
    public.stock_scores,
    public.stock_sector_rel,
    public.strategy_config,
    public.trades;
