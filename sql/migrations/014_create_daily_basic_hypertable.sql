-- 014_create_daily_basic_hypertable.sql
-- 目标：新增 public.daily_basic，并从创建开始即为 Timescale hypertable。

\set ON_ERROR_STOP on

create extension if not exists timescaledb;

create table if not exists public.daily_basic (
    instrument_id character varying(30) not null,
    trade_date date not null,
    turnover_rate numeric(10,4),
    total_share numeric(20,4),
    float_share numeric(20,4),
    free_share numeric(20,4),
    total_market_cap numeric(20,4),
    circulating_market_cap numeric(20,4),
    source character varying(32) not null default 'tushare_daily_basic',
    version integer not null default 1,
    updated_at timestamp with time zone not null default now(),
    constraint daily_basic_pkey primary key (instrument_id, trade_date)
);

create index if not exists idx_daily_basic_trade_date
    on public.daily_basic (trade_date desc, instrument_id);

select create_hypertable(
    'public.daily_basic',
    'trade_date',
    chunk_time_interval => interval '365 days',
    if_not_exists => true,
    create_default_indexes => false
);
