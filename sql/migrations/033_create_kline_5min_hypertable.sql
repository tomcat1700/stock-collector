-- 033_create_kline_5min_hypertable.sql
-- Dedicated one-year 5-minute K-line hypertable for backtesting.

\set ON_ERROR_STOP on

create extension if not exists timescaledb;

create table if not exists public.kline_5min (
    instrument_id character varying(30) not null,
    bar_time timestamp with time zone not null,
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    volume bigint,
    amount numeric,
    created_at timestamp with time zone not null default now(),
    is_complete boolean not null default false,
    update_count integer not null default 0,
    updated_at timestamp with time zone not null default now(),
    trade_date date,
    source character varying(32) not null default 'derived',
    bar_status character varying(20) not null default 'closed',
    version integer not null default 1,
    constraint kline_5min_pkey primary key (instrument_id, bar_time)
);

select create_hypertable(
    'public.kline_5min',
    'bar_time',
    chunk_time_interval => interval '30 days',
    if_not_exists => true,
    create_default_indexes => false
);

create index if not exists idx_kline_5min_instrument_time
    on public.kline_5min (instrument_id, bar_time desc);

create index if not exists idx_kline_5min_trade_date_instrument
    on public.kline_5min (trade_date, instrument_id);

create index if not exists idx_kline_5min_bar_time
    on public.kline_5min (bar_time desc);

select add_retention_policy(
    'public.kline_5min'::regclass,
    interval '365 days',
    if_not_exists => true
);

comment on table public.kline_5min is
    'Backtesting 5-minute K-line hypertable; bar_time is interval close timestamp; retains 365 natural days.';

insert into public.kline_5min (
    instrument_id,
    bar_time,
    open,
    high,
    low,
    close,
    volume,
    amount,
    created_at,
    is_complete,
    update_count,
    updated_at,
    trade_date,
    source,
    bar_status,
    version
)
select
    instrument_id,
    bar_time + interval '5 minutes' as bar_time,
    open,
    high,
    low,
    close,
    volume,
    amount,
    created_at,
    is_complete,
    update_count,
    updated_at,
    trade_date,
    source,
    bar_status,
    version
from public.kline_minute
where period = 5
  and (
    ((bar_time at time zone 'Asia/Shanghai')::time >= time '09:30:00'
      and (bar_time at time zone 'Asia/Shanghai')::time < time '11:30:00')
    or
    ((bar_time at time zone 'Asia/Shanghai')::time >= time '13:00:00'
      and (bar_time at time zone 'Asia/Shanghai')::time < time '15:00:00')
  )
on conflict (instrument_id, bar_time) do update set
    open = excluded.open,
    high = excluded.high,
    low = excluded.low,
    close = excluded.close,
    volume = excluded.volume,
    amount = excluded.amount,
    is_complete = excluded.is_complete,
    update_count = public.kline_5min.update_count + 1,
    updated_at = now(),
    trade_date = excluded.trade_date,
    source = excluded.source,
    bar_status = excluded.bar_status,
    version = excluded.version;

create or replace function public.aggregate_5min_kline(lookback_minutes integer default 60)
returns integer
language plpgsql
as $function$
declare
    updated_count integer;
begin
    with aggregated as (
        select
            km.instrument_id,
            date_bin('5 minutes', km.bar_time, '2001-01-01 09:30:00+08'::timestamptz) as bucket_start,
            5 as period,
            (array_agg(km.open order by km.bar_time asc))[1]::numeric as open,
            max(km.high)::numeric as high,
            min(km.low)::numeric as low,
            (array_agg(km.close order by km.bar_time desc))[1]::numeric as close,
            coalesce(sum(km.volume), 0)::bigint as volume,
            coalesce(sum(km.amount), 0)::numeric as amount,
            now() as created_at,
            date_bin('5 minutes', km.bar_time, '2001-01-01 09:30:00+08'::timestamptz)
                + interval '5 minutes' <= date_trunc('minute', now()) as is_complete,
            1 as update_count,
            now() as updated_at,
            min(km.trade_date) as trade_date,
            'derived'::character varying as source,
            case
                when bool_and(coalesce(km.bar_status, 'closed') = 'closed') then 'closed'
                else 'dirty'
            end as bar_status,
            1 as version
        from public.kline_minute km
        where km.period = 1
          and km.bar_time >= now() - make_interval(mins => lookback_minutes)
          and km.open is not null
          and km.high is not null
          and km.low is not null
          and km.close is not null
          and (
            ((km.bar_time at time zone 'Asia/Shanghai')::time >= time '09:30:00'
              and (km.bar_time at time zone 'Asia/Shanghai')::time < time '11:30:00')
            or
            ((km.bar_time at time zone 'Asia/Shanghai')::time >= time '13:00:00'
              and (km.bar_time at time zone 'Asia/Shanghai')::time < time '15:00:00')
          )
        group by
            km.instrument_id,
            date_bin('5 minutes', km.bar_time, '2001-01-01 09:30:00+08'::timestamptz)
    ),
    upsert_kline_minute as (
        insert into public.kline_minute (
            instrument_id,
            bar_time,
            period,
            open,
            high,
            low,
            close,
            volume,
            amount,
            created_at,
            is_complete,
            update_count,
            updated_at,
            trade_date,
            source,
            bar_status,
            version
        )
        select
            instrument_id,
            bucket_start,
            period,
            open,
            high,
            low,
            close,
            volume,
            amount,
            created_at,
            is_complete,
            update_count,
            updated_at,
            trade_date,
            source,
            bar_status,
            version
        from aggregated
        on conflict (instrument_id, bar_time, period) do update set
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume,
            amount = excluded.amount,
            is_complete = excluded.is_complete,
            update_count = public.kline_minute.update_count + 1,
            updated_at = now(),
            trade_date = excluded.trade_date,
            source = excluded.source,
            bar_status = excluded.bar_status,
            version = excluded.version
        returning
            instrument_id,
            bar_time,
            open,
            high,
            low,
            close,
            volume,
            amount,
            created_at,
            is_complete,
            update_count,
            updated_at,
            trade_date,
            source,
            bar_status,
            version
    ),
    upsert_kline_5min as (
        insert into public.kline_5min (
            instrument_id,
            bar_time,
            open,
            high,
            low,
            close,
            volume,
            amount,
            created_at,
            is_complete,
            update_count,
            updated_at,
            trade_date,
            source,
            bar_status,
            version
        )
        select
            instrument_id,
            bar_time + interval '5 minutes' as bar_time,
            open,
            high,
            low,
            close,
            volume,
            amount,
            created_at,
            is_complete,
            update_count,
            updated_at,
            trade_date,
            source,
            bar_status,
            version
        from upsert_kline_minute
        on conflict (instrument_id, bar_time) do update set
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume,
            amount = excluded.amount,
            is_complete = excluded.is_complete,
            update_count = public.kline_5min.update_count + 1,
            updated_at = now(),
            trade_date = excluded.trade_date,
            source = excluded.source,
            bar_status = excluded.bar_status,
            version = excluded.version
        returning 1
    )
    select count(*)::integer
    into updated_count
    from upsert_kline_minute;

    return updated_count;
end;
$function$;
