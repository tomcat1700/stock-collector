\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION public.aggregate_15min_kline(lookback_minutes integer DEFAULT 180)
RETURNS integer
LANGUAGE plpgsql
AS $function$
DECLARE
    updated_count integer;
BEGIN
    INSERT INTO public.kline_minute (
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
    SELECT
        km.instrument_id,
        CASE
            WHEN (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '13:00:00'
                THEN date_bin('15 minutes', km.bar_time, ((km.trade_date::text || ' 13:00:00+08')::timestamptz))
            ELSE date_bin('15 minutes', km.bar_time, ((km.trade_date::text || ' 09:30:00+08')::timestamptz))
        END AS bar_time,
        15 AS period,
        (array_agg(km.open ORDER BY km.bar_time ASC))[1]::numeric AS open,
        max(km.high)::numeric AS high,
        min(km.low)::numeric AS low,
        (array_agg(km.close ORDER BY km.bar_time DESC))[1]::numeric AS close,
        coalesce(sum(km.volume), 0)::bigint AS volume,
        coalesce(sum(km.amount), 0)::numeric AS amount,
        now(),
        (
            CASE
                WHEN (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '13:00:00'
                    THEN date_bin('15 minutes', km.bar_time, ((km.trade_date::text || ' 13:00:00+08')::timestamptz))
                ELSE date_bin('15 minutes', km.bar_time, ((km.trade_date::text || ' 09:30:00+08')::timestamptz))
            END
        ) + interval '15 minutes' <= date_trunc('minute', now()) AS is_complete,
        1,
        now(),
        min(km.trade_date) AS trade_date,
        'derived'::character varying,
        CASE
            WHEN bool_and(coalesce(km.bar_status, 'closed') = 'closed') THEN 'closed'
            ELSE 'dirty'
        END AS bar_status,
        1
    FROM public.kline_minute km
    WHERE km.period = 5
      AND km.bar_time >= now() - make_interval(mins => lookback_minutes)
      AND (
        ((km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '09:30:00'
          AND (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time <= time '11:30:00')
        OR
        ((km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '13:00:00'
          AND (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time <= time '15:00:00')
      )
      AND km.open IS NOT NULL
      AND km.high IS NOT NULL
      AND km.low IS NOT NULL
      AND km.close IS NOT NULL
    GROUP BY
        km.instrument_id,
        CASE
            WHEN (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '13:00:00'
                THEN date_bin('15 minutes', km.bar_time, ((km.trade_date::text || ' 13:00:00+08')::timestamptz))
            ELSE date_bin('15 minutes', km.bar_time, ((km.trade_date::text || ' 09:30:00+08')::timestamptz))
        END
    ON CONFLICT (instrument_id, bar_time, period) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        amount = EXCLUDED.amount,
        is_complete = EXCLUDED.is_complete,
        update_count = public.kline_minute.update_count + 1,
        updated_at = now(),
        trade_date = EXCLUDED.trade_date,
        source = EXCLUDED.source,
        bar_status = EXCLUDED.bar_status,
        version = EXCLUDED.version;

    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count;
END;
$function$;

CREATE OR REPLACE FUNCTION public.aggregate_30min_kline(lookback_minutes integer DEFAULT 240)
RETURNS integer
LANGUAGE plpgsql
AS $function$
DECLARE
    updated_count integer;
BEGIN
    INSERT INTO public.kline_minute (
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
    SELECT
        km.instrument_id,
        CASE
            WHEN (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '13:00:00'
                THEN date_bin('30 minutes', km.bar_time, ((km.trade_date::text || ' 13:00:00+08')::timestamptz))
            ELSE date_bin('30 minutes', km.bar_time, ((km.trade_date::text || ' 09:30:00+08')::timestamptz))
        END AS bar_time,
        30 AS period,
        (array_agg(km.open ORDER BY km.bar_time ASC))[1]::numeric AS open,
        max(km.high)::numeric AS high,
        min(km.low)::numeric AS low,
        (array_agg(km.close ORDER BY km.bar_time DESC))[1]::numeric AS close,
        coalesce(sum(km.volume), 0)::bigint AS volume,
        coalesce(sum(km.amount), 0)::numeric AS amount,
        now(),
        (
            CASE
                WHEN (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '13:00:00'
                    THEN date_bin('30 minutes', km.bar_time, ((km.trade_date::text || ' 13:00:00+08')::timestamptz))
                ELSE date_bin('30 minutes', km.bar_time, ((km.trade_date::text || ' 09:30:00+08')::timestamptz))
            END
        ) + interval '30 minutes' <= date_trunc('minute', now()) AS is_complete,
        1,
        now(),
        min(km.trade_date) AS trade_date,
        'derived'::character varying,
        CASE
            WHEN bool_and(coalesce(km.bar_status, 'closed') = 'closed') THEN 'closed'
            ELSE 'dirty'
        END AS bar_status,
        1
    FROM public.kline_minute km
    WHERE km.period = 15
      AND km.bar_time >= now() - make_interval(mins => lookback_minutes)
      AND (
        ((km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '09:30:00'
          AND (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time <= time '11:30:00')
        OR
        ((km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '13:00:00'
          AND (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time <= time '15:00:00')
      )
      AND km.open IS NOT NULL
      AND km.high IS NOT NULL
      AND km.low IS NOT NULL
      AND km.close IS NOT NULL
    GROUP BY
        km.instrument_id,
        CASE
            WHEN (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '13:00:00'
                THEN date_bin('30 minutes', km.bar_time, ((km.trade_date::text || ' 13:00:00+08')::timestamptz))
            ELSE date_bin('30 minutes', km.bar_time, ((km.trade_date::text || ' 09:30:00+08')::timestamptz))
        END
    ON CONFLICT (instrument_id, bar_time, period) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        amount = EXCLUDED.amount,
        is_complete = EXCLUDED.is_complete,
        update_count = public.kline_minute.update_count + 1,
        updated_at = now(),
        trade_date = EXCLUDED.trade_date,
        source = EXCLUDED.source,
        bar_status = EXCLUDED.bar_status,
        version = EXCLUDED.version;

    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count;
END;
$function$;

CREATE OR REPLACE FUNCTION public.aggregate_60min_kline(lookback_minutes integer DEFAULT 480)
RETURNS integer
LANGUAGE plpgsql
AS $function$
DECLARE
    updated_count integer;
BEGIN
    INSERT INTO public.kline_minute (
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
    SELECT
        km.instrument_id,
        CASE
            WHEN (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '13:00:00'
                THEN date_bin('60 minutes', km.bar_time, ((km.trade_date::text || ' 13:00:00+08')::timestamptz))
            ELSE date_bin('60 minutes', km.bar_time, ((km.trade_date::text || ' 09:30:00+08')::timestamptz))
        END AS bar_time,
        60 AS period,
        (array_agg(km.open ORDER BY km.bar_time ASC))[1]::numeric AS open,
        max(km.high)::numeric AS high,
        min(km.low)::numeric AS low,
        (array_agg(km.close ORDER BY km.bar_time DESC))[1]::numeric AS close,
        coalesce(sum(km.volume), 0)::bigint AS volume,
        coalesce(sum(km.amount), 0)::numeric AS amount,
        now(),
        (
            CASE
                WHEN (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '13:00:00'
                    THEN date_bin('60 minutes', km.bar_time, ((km.trade_date::text || ' 13:00:00+08')::timestamptz))
                ELSE date_bin('60 minutes', km.bar_time, ((km.trade_date::text || ' 09:30:00+08')::timestamptz))
            END
        ) + interval '60 minutes' <= date_trunc('minute', now()) AS is_complete,
        1,
        now(),
        min(km.trade_date) AS trade_date,
        'derived'::character varying,
        CASE
            WHEN bool_and(coalesce(km.bar_status, 'closed') = 'closed') THEN 'closed'
            ELSE 'dirty'
        END AS bar_status,
        1
    FROM public.kline_minute km
    WHERE km.period = 30
      AND km.bar_time >= now() - make_interval(mins => lookback_minutes)
      AND (
        ((km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '09:30:00'
          AND (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time <= time '11:30:00')
        OR
        ((km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '13:00:00'
          AND (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time <= time '15:00:00')
      )
      AND km.open IS NOT NULL
      AND km.high IS NOT NULL
      AND km.low IS NOT NULL
      AND km.close IS NOT NULL
    GROUP BY
        km.instrument_id,
        CASE
            WHEN (km.bar_time AT TIME ZONE 'Asia/Shanghai')::time >= time '13:00:00'
                THEN date_bin('60 minutes', km.bar_time, ((km.trade_date::text || ' 13:00:00+08')::timestamptz))
            ELSE date_bin('60 minutes', km.bar_time, ((km.trade_date::text || ' 09:30:00+08')::timestamptz))
        END
    ON CONFLICT (instrument_id, bar_time, period) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        amount = EXCLUDED.amount,
        is_complete = EXCLUDED.is_complete,
        update_count = public.kline_minute.update_count + 1,
        updated_at = now(),
        trade_date = EXCLUDED.trade_date,
        source = EXCLUDED.source,
        bar_status = EXCLUDED.bar_status,
        version = EXCLUDED.version;

    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count;
END;
$function$;
