-- 016_create_paper_trading_tables.sql
-- 目标：创建 V1.5.2 最小模拟交易骨架对象。

\set ON_ERROR_STOP on

create table if not exists public.order_intents (
    intent_id bigserial primary key,
    account_id character varying(32) not null default 'paper-main',
    instrument_id character varying(30) not null,
    plan_id character varying(64) not null,
    side character varying(8) not null,
    quantity bigint not null,
    intent_price numeric(20,4) not null,
    intent_reason text,
    status character varying(16) not null default 'confirmed',
    plan_snapshot jsonb,
    risk_snapshot jsonb,
    created_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now()
);

create index if not exists idx_order_intents_account_created
    on public.order_intents (account_id, created_at desc);

create table if not exists public.sim_orders (
    sim_order_id bigserial primary key,
    intent_id bigint not null references public.order_intents(intent_id),
    account_id character varying(32) not null default 'paper-main',
    instrument_id character varying(30) not null,
    side character varying(8) not null,
    quantity bigint not null,
    order_price numeric(20,4) not null,
    order_type character varying(16) not null default 'manual_market',
    status character varying(16) not null default 'filled',
    submitted_at timestamp with time zone not null default now(),
    filled_at timestamp with time zone,
    created_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now()
);

create index if not exists idx_sim_orders_account_submitted
    on public.sim_orders (account_id, submitted_at desc);

create table if not exists public.sim_trades (
    sim_trade_id bigserial primary key,
    sim_order_id bigint not null references public.sim_orders(sim_order_id),
    account_id character varying(32) not null default 'paper-main',
    instrument_id character varying(30) not null,
    side character varying(8) not null,
    quantity bigint not null,
    fill_price numeric(20,4) not null,
    fill_amount numeric(20,4) not null,
    fee numeric(20,4) not null default 0,
    trade_time timestamp with time zone not null default now(),
    trade_date date not null default current_date,
    created_at timestamp with time zone not null default now()
);

create index if not exists idx_sim_trades_account_trade_time
    on public.sim_trades (account_id, trade_time desc);

create table if not exists public.sim_positions (
    account_id character varying(32) not null default 'paper-main',
    instrument_id character varying(30) not null,
    quantity bigint not null,
    available_qty bigint not null,
    avg_cost numeric(20,6) not null,
    current_price numeric(20,4) not null,
    market_value numeric(20,4) not null,
    cost_value numeric(20,4) not null,
    unrealized_pnl numeric(20,4) not null,
    unrealized_pnl_pct numeric(20,4) not null,
    last_trade_date date,
    updated_at timestamp with time zone not null default now(),
    primary key (account_id, instrument_id)
);

create index if not exists idx_sim_positions_updated
    on public.sim_positions (account_id, updated_at desc);

create table if not exists public.sim_equity_curve (
    snapshot_id bigserial primary key,
    account_id character varying(32) not null default 'paper-main',
    snapshot_time timestamp with time zone not null default now(),
    trade_date date not null default current_date,
    cash numeric(20,4) not null,
    market_value numeric(20,4) not null,
    equity numeric(20,4) not null,
    realized_pnl numeric(20,4) not null default 0,
    unrealized_pnl numeric(20,4) not null default 0,
    created_at timestamp with time zone not null default now()
);

create index if not exists idx_sim_equity_curve_account_time
    on public.sim_equity_curve (account_id, snapshot_time desc);
