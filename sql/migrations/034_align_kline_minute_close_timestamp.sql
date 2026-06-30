-- 034_align_kline_minute_close_timestamp.sql
-- Align derived minute bars to interval close timestamps.
--
-- Convention:
-- - period=5 first morning bar closes at 09:35, not 09:30.
-- - period=15 first morning bar closes at 09:45, not 09:30.
-- - period=30 first morning bar closes at 10:00, not 09:30.
-- - period=60 first morning bar closes at 10:30, not 09:30.

\set ON_ERROR_STOP on

begin;

comment on table public.kline_minute is
    '分钟 K 线统一表；period=5/15/30/60 的 bar_time 为区间结束时间；1 分钟保留最近 45 个实际采集交易日，5/15/30/60 分钟保留最近 120 个实际采集交易日';

comment on table public.kline_5min is
    'Backtesting 5-minute K-line hypertable; bar_time is interval close timestamp; retains 365 natural days.';

create temp table tmp_kline_minute_close_timestamp on commit drop as
select
    instrument_id,
    bar_time + make_interval(mins => period) as bar_time,
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
from public.kline_minute
where period in (5, 15, 30, 60)
  and (
    ((bar_time at time zone 'Asia/Shanghai')::time >= time '09:30:00'
      and (bar_time at time zone 'Asia/Shanghai')::time < time '11:30:00')
    or
    ((bar_time at time zone 'Asia/Shanghai')::time >= time '13:00:00'
      and (bar_time at time zone 'Asia/Shanghai')::time < time '15:00:00')
  );

delete from public.kline_minute
where period in (5, 15, 30, 60);

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
from tmp_kline_minute_close_timestamp
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
    version = excluded.version;

delete from public.kline_5min;

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
from public.kline_minute
where period = 5
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
            date_bin('5 minutes', km.bar_time, '2001-01-01 09:30:00+08'::timestamptz)
                + interval '5 minutes' as bucket_close,
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
                + interval '5 minutes'
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
            bucket_close,
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

create or replace function public.aggregate_15min_kline(lookback_minutes integer default 180)
returns integer
language plpgsql
as $function$
declare
    updated_count integer;
begin
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
        km.instrument_id,
        case
            when (km.bar_time at time zone 'Asia/Shanghai')::time > time '13:00:00'
                then date_bin('15 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 13:00:00+08')::timestamptz)) + interval '15 minutes'
            else date_bin('15 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 09:30:00+08')::timestamptz)) + interval '15 minutes'
        end as bar_time,
        15 as period,
        (array_agg(km.open order by km.bar_time asc))[1]::numeric as open,
        max(km.high)::numeric as high,
        min(km.low)::numeric as low,
        (array_agg(km.close order by km.bar_time desc))[1]::numeric as close,
        coalesce(sum(km.volume), 0)::bigint as volume,
        coalesce(sum(km.amount), 0)::numeric as amount,
        now(),
        (
            case
                when (km.bar_time at time zone 'Asia/Shanghai')::time > time '13:00:00'
                    then date_bin('15 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 13:00:00+08')::timestamptz)) + interval '15 minutes'
                else date_bin('15 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 09:30:00+08')::timestamptz)) + interval '15 minutes'
            end
        ) <= date_trunc('minute', now()) as is_complete,
        1,
        now(),
        min(km.trade_date) as trade_date,
        'derived'::character varying,
        case
            when bool_and(coalesce(km.bar_status, 'closed') = 'closed') then 'closed'
            else 'dirty'
        end as bar_status,
        1
    from public.kline_minute km
    where km.period = 5
      and km.bar_time >= now() - make_interval(mins => lookback_minutes)
      and (
        ((km.bar_time at time zone 'Asia/Shanghai')::time > time '09:30:00'
          and (km.bar_time at time zone 'Asia/Shanghai')::time <= time '11:30:00')
        or
        ((km.bar_time at time zone 'Asia/Shanghai')::time > time '13:00:00'
          and (km.bar_time at time zone 'Asia/Shanghai')::time <= time '15:00:00')
      )
      and km.open is not null
      and km.high is not null
      and km.low is not null
      and km.close is not null
    group by
        km.instrument_id,
        case
            when (km.bar_time at time zone 'Asia/Shanghai')::time > time '13:00:00'
                then date_bin('15 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 13:00:00+08')::timestamptz)) + interval '15 minutes'
            else date_bin('15 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 09:30:00+08')::timestamptz)) + interval '15 minutes'
        end
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
        version = excluded.version;

    get diagnostics updated_count = row_count;
    return updated_count;
end;
$function$;

create or replace function public.aggregate_30min_kline(lookback_minutes integer default 240)
returns integer
language plpgsql
as $function$
declare
    updated_count integer;
begin
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
        km.instrument_id,
        case
            when (km.bar_time at time zone 'Asia/Shanghai')::time > time '13:00:00'
                then date_bin('30 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 13:00:00+08')::timestamptz)) + interval '30 minutes'
            else date_bin('30 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 09:30:00+08')::timestamptz)) + interval '30 minutes'
        end as bar_time,
        30 as period,
        (array_agg(km.open order by km.bar_time asc))[1]::numeric as open,
        max(km.high)::numeric as high,
        min(km.low)::numeric as low,
        (array_agg(km.close order by km.bar_time desc))[1]::numeric as close,
        coalesce(sum(km.volume), 0)::bigint as volume,
        coalesce(sum(km.amount), 0)::numeric as amount,
        now(),
        (
            case
                when (km.bar_time at time zone 'Asia/Shanghai')::time > time '13:00:00'
                    then date_bin('30 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 13:00:00+08')::timestamptz)) + interval '30 minutes'
                else date_bin('30 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 09:30:00+08')::timestamptz)) + interval '30 minutes'
            end
        ) <= date_trunc('minute', now()) as is_complete,
        1,
        now(),
        min(km.trade_date) as trade_date,
        'derived'::character varying,
        case
            when bool_and(coalesce(km.bar_status, 'closed') = 'closed') then 'closed'
            else 'dirty'
        end as bar_status,
        1
    from public.kline_minute km
    where km.period = 15
      and km.bar_time >= now() - make_interval(mins => lookback_minutes)
      and (
        ((km.bar_time at time zone 'Asia/Shanghai')::time > time '09:30:00'
          and (km.bar_time at time zone 'Asia/Shanghai')::time <= time '11:30:00')
        or
        ((km.bar_time at time zone 'Asia/Shanghai')::time > time '13:00:00'
          and (km.bar_time at time zone 'Asia/Shanghai')::time <= time '15:00:00')
      )
      and km.open is not null
      and km.high is not null
      and km.low is not null
      and km.close is not null
    group by
        km.instrument_id,
        case
            when (km.bar_time at time zone 'Asia/Shanghai')::time > time '13:00:00'
                then date_bin('30 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 13:00:00+08')::timestamptz)) + interval '30 minutes'
            else date_bin('30 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 09:30:00+08')::timestamptz)) + interval '30 minutes'
        end
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
        version = excluded.version;

    get diagnostics updated_count = row_count;
    return updated_count;
end;
$function$;

create or replace function public.aggregate_60min_kline(lookback_minutes integer default 480)
returns integer
language plpgsql
as $function$
declare
    updated_count integer;
begin
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
        km.instrument_id,
        case
            when (km.bar_time at time zone 'Asia/Shanghai')::time > time '13:00:00'
                then date_bin('60 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 13:00:00+08')::timestamptz)) + interval '60 minutes'
            else date_bin('60 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 09:30:00+08')::timestamptz)) + interval '60 minutes'
        end as bar_time,
        60 as period,
        (array_agg(km.open order by km.bar_time asc))[1]::numeric as open,
        max(km.high)::numeric as high,
        min(km.low)::numeric as low,
        (array_agg(km.close order by km.bar_time desc))[1]::numeric as close,
        coalesce(sum(km.volume), 0)::bigint as volume,
        coalesce(sum(km.amount), 0)::numeric as amount,
        now(),
        (
            case
                when (km.bar_time at time zone 'Asia/Shanghai')::time > time '13:00:00'
                    then date_bin('60 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 13:00:00+08')::timestamptz)) + interval '60 minutes'
                else date_bin('60 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 09:30:00+08')::timestamptz)) + interval '60 minutes'
            end
        ) <= date_trunc('minute', now()) as is_complete,
        1,
        now(),
        min(km.trade_date) as trade_date,
        'derived'::character varying,
        case
            when bool_and(coalesce(km.bar_status, 'closed') = 'closed') then 'closed'
            else 'dirty'
        end as bar_status,
        1
    from public.kline_minute km
    where km.period = 30
      and km.bar_time >= now() - make_interval(mins => lookback_minutes)
      and (
        ((km.bar_time at time zone 'Asia/Shanghai')::time > time '09:30:00'
          and (km.bar_time at time zone 'Asia/Shanghai')::time <= time '11:30:00')
        or
        ((km.bar_time at time zone 'Asia/Shanghai')::time > time '13:00:00'
          and (km.bar_time at time zone 'Asia/Shanghai')::time <= time '15:00:00')
      )
      and km.open is not null
      and km.high is not null
      and km.low is not null
      and km.close is not null
    group by
        km.instrument_id,
        case
            when (km.bar_time at time zone 'Asia/Shanghai')::time > time '13:00:00'
                then date_bin('60 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 13:00:00+08')::timestamptz)) + interval '60 minutes'
            else date_bin('60 minutes', km.bar_time - interval '1 microsecond', ((km.trade_date::text || ' 09:30:00+08')::timestamptz)) + interval '60 minutes'
        end
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
        version = excluded.version;

    get diagnostics updated_count = row_count;
    return updated_count;
end;
$function$;

commit;
