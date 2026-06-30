-- 035_create_kline_daily_qfq.sql
-- Precomputed forward-adjusted daily K-line table for analysis/backtesting.
-- Source of truth remains public.kline_daily (raw, unadjusted) + public.daily_adj_factor.

\set ON_ERROR_STOP on

create extension if not exists timescaledb;

create table if not exists public.kline_daily_qfq (
    instrument_id character varying(30) not null,
    trade_date date not null,
    open numeric(18,6),
    high numeric(18,6),
    low numeric(18,6),
    close numeric(18,6),
    volume bigint,
    amount numeric(16,2),
    change numeric(18,6),
    pct_change numeric(10,6),
    amplitude numeric(10,6),
    adj_factor numeric(18,6) not null,
    anchor_trade_date date not null,
    anchor_factor numeric(18,6) not null,
    is_final boolean not null default true,
    source character varying(32) not null default 'system_qfq',
    version integer not null default 1,
    calculated_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now(),
    constraint kline_daily_qfq_pkey primary key (instrument_id, trade_date)
);

select create_hypertable(
    'public.kline_daily_qfq',
    'trade_date',
    chunk_time_interval => interval '365 days',
    if_not_exists => true,
    create_default_indexes => false
);

create index if not exists idx_kline_daily_qfq_trade_date
    on public.kline_daily_qfq (trade_date desc, instrument_id);

create index if not exists idx_kline_daily_qfq_instrument_date
    on public.kline_daily_qfq (instrument_id, trade_date desc);

create index if not exists idx_kline_daily_qfq_anchor_factor
    on public.kline_daily_qfq (instrument_id, anchor_factor);

comment on table public.kline_daily_qfq is
    'Precomputed forward-adjusted daily stock K-line table. Derived from raw kline_daily and daily_adj_factor; rebuild when latest adj_factor anchor changes.';

comment on column public.kline_daily_qfq.close is
    'Forward-adjusted close: raw close * row adj_factor / latest anchor_factor.';

comment on column public.kline_daily_qfq.anchor_factor is
    'Latest adj_factor for the instrument at calculation time. If this changes, all historical qfq prices for that instrument must be recalculated.';

comment on column public.kline_daily_qfq.pct_change is
    'Percentage change calculated from precomputed qfq close versus previous qfq close.';
