-- 028_create_daily_adj_factor_indicator.sql
-- Store internally calculated daily MA indicators.  Stock indicators use
-- Tushare adj_factor to derive qfq_close; index indicators use raw close.

\set ON_ERROR_STOP on

create extension if not exists timescaledb;

create table if not exists public.daily_adj_factor (
    instrument_id character varying(30) not null,
    trade_date date not null,
    adj_factor numeric(18,6) not null,
    source character varying(32) not null default 'tushare_adj_factor',
    updated_at timestamp with time zone not null default now(),
    constraint daily_adj_factor_pkey primary key (instrument_id, trade_date)
);

create index if not exists idx_daily_adj_factor_trade_date
    on public.daily_adj_factor (trade_date desc, instrument_id);

select create_hypertable(
    'public.daily_adj_factor',
    'trade_date',
    chunk_time_interval => interval '365 days',
    if_not_exists => true,
    create_default_indexes => false
);

create table if not exists public.daily_indicator (
    instrument_id character varying(30) not null,
    trade_date date not null,
    price_basis character varying(20) not null,
    adjustment_anchor_date date,
    ma5 numeric(18,6),
    ma10 numeric(18,6),
    ma20 numeric(18,6),
    ma55 numeric(18,6),
    ma233 numeric(18,6),
    is_final boolean not null default true,
    source character varying(32) not null default 'system',
    version integer not null default 1,
    calculated_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now(),
    constraint daily_indicator_pkey primary key (instrument_id, trade_date, price_basis)
);

create index if not exists idx_daily_indicator_trade_date_basis
    on public.daily_indicator (trade_date desc, price_basis, instrument_id);

create index if not exists idx_daily_indicator_instrument_basis_date
    on public.daily_indicator (instrument_id, price_basis, trade_date desc);

select create_hypertable(
    'public.daily_indicator',
    'trade_date',
    chunk_time_interval => interval '365 days',
    if_not_exists => true,
    create_default_indexes => false
);

comment on table public.daily_adj_factor is
    'Daily stock adjustment factors used by system-owned qfq calculations.';

comment on table public.daily_indicator is
    'System-owned daily moving averages calculated from kline_daily and daily_adj_factor.';

comment on column public.daily_indicator.price_basis is
    'qfq_close for stocks, close for indices.';

comment on column public.daily_indicator.adjustment_anchor_date is
    'Latest adj_factor date used as the qfq anchor for stock calculations.';
