-- 025_drop_trading_calendar.sql
-- The collector runtime now uses Tushare trade_cal in launch scripts or simple
-- previous-workday fallback in code. The local trading calendar cache is no
-- longer part of the collector database scope.

drop function if exists public.count_trading_days(date, date);
drop function if exists public.get_trading_days_ago(integer);

drop table if exists public.trading_calendar;
