-- 008_draft_verify_timescale_hypertables.sql
-- 目标：迁移后最小验证（扩展、hypertable、行数、时间边界）
-- 重要：本脚本为“验证草案”，不做结构改动。

\set ON_ERROR_STOP on

-- 1) 扩展状态
select extname, extversion
from pg_extension
where extname = 'timescaledb';

-- 2) 三张表是否已成为 hypertable
select hypertable_schema, hypertable_name
from timescaledb_information.hypertables
where hypertable_schema = 'public'
  and hypertable_name in ('realtime_quotes', 'kline_minute', 'kline_daily')
order by hypertable_name;

-- 3) 维度与 chunk interval
select hypertable_schema, hypertable_name, dimension_number, column_name, dimension_type, time_interval, integer_interval
from timescaledb_information.dimensions
where hypertable_schema = 'public'
  and hypertable_name in ('realtime_quotes', 'kline_minute', 'kline_daily')
order by hypertable_name, dimension_number;

-- 4) 数据行数与时间边界
select 'realtime_quotes' as table_name, count(*)::bigint as row_count, min(quote_time) as min_time, max(quote_time) as max_time
from public.realtime_quotes
union all
select 'kline_minute' as table_name, count(*)::bigint as row_count, min(bar_time) as min_time, max(bar_time) as max_time
from public.kline_minute
union all
select 'kline_daily' as table_name, count(*)::bigint as row_count, min(trade_date::timestamptz) as min_time, max(trade_date::timestamptz) as max_time
from public.kline_daily;

