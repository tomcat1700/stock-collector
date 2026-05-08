BEGIN;

CREATE TABLE IF NOT EXISTS public.bar_3s (
    instrument_id character varying(30) NOT NULL,
    bar_time timestamp with time zone NOT NULL,
    trade_date date NOT NULL,
    open numeric(12,4),
    high numeric(12,4),
    low numeric(12,4),
    close numeric(12,4),
    volume bigint,
    amount numeric(20,2),
    quote_count integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    source character varying(20) DEFAULT 'realtime_quotes'::character varying NOT NULL,
    bar_status character varying(20) DEFAULT 'closed'::character varying NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT bar_3s_pkey PRIMARY KEY (instrument_id, bar_time)
);

COMMENT ON TABLE public.bar_3s IS '盘中 3 秒基础事实层，由 realtime_quotes 聚合生成';

CREATE INDEX IF NOT EXISTS idx_bar_3s_trade_date
    ON public.bar_3s (trade_date, instrument_id);

CREATE INDEX IF NOT EXISTS idx_bar_3s_instrument_time
    ON public.bar_3s (instrument_id, bar_time DESC);

CREATE TABLE IF NOT EXISTS public.bar_1m (
    instrument_id character varying(30) NOT NULL,
    bar_time timestamp with time zone NOT NULL,
    trade_date date NOT NULL,
    open numeric(12,4),
    high numeric(12,4),
    low numeric(12,4),
    close numeric(12,4),
    volume bigint,
    amount numeric(20,2),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_complete boolean DEFAULT true NOT NULL,
    source character varying(20) DEFAULT 'derived'::character varying NOT NULL,
    bar_status character varying(20) DEFAULT 'closed'::character varying NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT bar_1m_pkey PRIMARY KEY (instrument_id, bar_time)
);

COMMENT ON TABLE public.bar_1m IS '1 分钟事实层，优先由 bar_3s 聚合生成，兼容从旧 kline_minute(period=1) 回填';

CREATE INDEX IF NOT EXISTS idx_bar_1m_trade_date
    ON public.bar_1m (trade_date, instrument_id);

CREATE INDEX IF NOT EXISTS idx_bar_1m_instrument_time
    ON public.bar_1m (instrument_id, bar_time DESC);

CREATE TABLE IF NOT EXISTS public.bar_30m (
    instrument_id character varying(30) NOT NULL,
    bar_time timestamp with time zone NOT NULL,
    trade_date date NOT NULL,
    open numeric(12,4),
    high numeric(12,4),
    low numeric(12,4),
    close numeric(12,4),
    volume bigint,
    amount numeric(20,2),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_complete boolean DEFAULT true NOT NULL,
    source character varying(20) DEFAULT 'derived'::character varying NOT NULL,
    bar_status character varying(20) DEFAULT 'closed'::character varying NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT bar_30m_pkey PRIMARY KEY (instrument_id, bar_time)
);

COMMENT ON TABLE public.bar_30m IS '30 分钟事实层，优先由 bar_1m 聚合生成，兼容从旧 kline_minute(period=30) 回填';

CREATE INDEX IF NOT EXISTS idx_bar_30m_trade_date
    ON public.bar_30m (trade_date, instrument_id);

CREATE INDEX IF NOT EXISTS idx_bar_30m_instrument_time
    ON public.bar_30m (instrument_id, bar_time DESC);

INSERT INTO public.bar_1m (
    instrument_id,
    bar_time,
    trade_date,
    open,
    high,
    low,
    close,
    volume,
    amount,
    created_at,
    updated_at,
    is_complete,
    source,
    bar_status,
    version
)
SELECT
    km.instrument_id,
    km.bar_time,
    COALESCE(km.trade_date, (km.bar_time AT TIME ZONE 'Asia/Shanghai')::date) AS trade_date,
    km.open,
    km.high,
    km.low,
    km.close,
    km.volume,
    km.amount,
    COALESCE(km.created_at, now()) AS created_at,
    COALESCE(km.updated_at, now()) AS updated_at,
    COALESCE(km.is_complete, true) AS is_complete,
    km.source,
    km.bar_status,
    km.version
FROM public.kline_minute km
WHERE km.period = 1
ON CONFLICT (instrument_id, bar_time) DO UPDATE SET
    trade_date = EXCLUDED.trade_date,
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    amount = EXCLUDED.amount,
    updated_at = EXCLUDED.updated_at,
    is_complete = EXCLUDED.is_complete,
    source = EXCLUDED.source,
    bar_status = EXCLUDED.bar_status,
    version = EXCLUDED.version;

INSERT INTO public.bar_30m (
    instrument_id,
    bar_time,
    trade_date,
    open,
    high,
    low,
    close,
    volume,
    amount,
    created_at,
    updated_at,
    is_complete,
    source,
    bar_status,
    version
)
SELECT
    km.instrument_id,
    km.bar_time,
    COALESCE(km.trade_date, (km.bar_time AT TIME ZONE 'Asia/Shanghai')::date) AS trade_date,
    km.open,
    km.high,
    km.low,
    km.close,
    km.volume,
    km.amount,
    COALESCE(km.created_at, now()) AS created_at,
    COALESCE(km.updated_at, now()) AS updated_at,
    COALESCE(km.is_complete, true) AS is_complete,
    km.source,
    km.bar_status,
    km.version
FROM public.kline_minute km
WHERE km.period = 30
ON CONFLICT (instrument_id, bar_time) DO UPDATE SET
    trade_date = EXCLUDED.trade_date,
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    amount = EXCLUDED.amount,
    updated_at = EXCLUDED.updated_at,
    is_complete = EXCLUDED.is_complete,
    source = EXCLUDED.source,
    bar_status = EXCLUDED.bar_status,
    version = EXCLUDED.version;

WITH rt_3s AS (
    SELECT
        rt.instrument_id,
        date_bin('3 seconds', rt.quote_time, '2001-01-01 09:30:00+08'::timestamp with time zone) AS bar_time,
        COALESCE(rt.trade_date, (rt.quote_time AT TIME ZONE 'Asia/Shanghai')::date) AS trade_date,
        (array_agg(rt.current ORDER BY rt.quote_time ASC))[1] AS open,
        max(rt.current) AS high,
        min(rt.current) AS low,
        (array_agg(rt.current ORDER BY rt.quote_time DESC))[1] AS close,
        sum(COALESCE(rt.delta_volume, 0)) AS volume,
        sum(COALESCE(rt.delta_amount, 0)) AS amount,
        count(*)::integer AS quote_count,
        min(COALESCE(rt.created_at, now())) AS created_at,
        max(COALESCE(rt.created_at, now())) AS updated_at,
        CASE
            WHEN bool_and(COALESCE(rt.is_valid, true)) THEN 'closed'
            ELSE 'dirty'
        END AS bar_status
    FROM public.realtime_quotes rt
    WHERE rt.current IS NOT NULL
    GROUP BY
        rt.instrument_id,
        date_bin('3 seconds', rt.quote_time, '2001-01-01 09:30:00+08'::timestamp with time zone),
        COALESCE(rt.trade_date, (rt.quote_time AT TIME ZONE 'Asia/Shanghai')::date)
)
INSERT INTO public.bar_3s (
    instrument_id,
    bar_time,
    trade_date,
    open,
    high,
    low,
    close,
    volume,
    amount,
    quote_count,
    created_at,
    updated_at,
    source,
    bar_status,
    version
)
SELECT
    instrument_id,
    bar_time,
    trade_date,
    open,
    high,
    low,
    close,
    volume,
    amount,
    quote_count,
    created_at,
    updated_at,
    'realtime_quotes'::character varying,
    bar_status,
    1
FROM rt_3s
ON CONFLICT (instrument_id, bar_time) DO UPDATE SET
    trade_date = EXCLUDED.trade_date,
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    amount = EXCLUDED.amount,
    quote_count = EXCLUDED.quote_count,
    updated_at = EXCLUDED.updated_at,
    bar_status = EXCLUDED.bar_status;

CREATE OR REPLACE VIEW public.v_bar_5m AS
SELECT
    b.instrument_id,
    date_bin('5 minutes', b.bar_time, '2001-01-01 09:30:00+08'::timestamp with time zone) AS bar_time,
    min(b.trade_date) AS trade_date,
    (array_agg(b.open ORDER BY b.bar_time ASC))[1] AS open,
    max(b.high) AS high,
    min(b.low) AS low,
    (array_agg(b.close ORDER BY b.bar_time DESC))[1] AS close,
    sum(COALESCE(b.volume, 0)) AS volume,
    sum(COALESCE(b.amount, 0)) AS amount,
    min(b.created_at) AS created_at,
    max(b.updated_at) AS updated_at,
    bool_and(b.is_complete) AS is_complete,
    'derived_5m'::character varying(20) AS source,
    CASE
        WHEN bool_and(b.bar_status = 'closed') THEN 'closed'
        ELSE 'building'
    END AS bar_status,
    max(b.version) AS version
FROM public.bar_1m b
GROUP BY
    b.instrument_id,
    date_bin('5 minutes', b.bar_time, '2001-01-01 09:30:00+08'::timestamp with time zone);

CREATE OR REPLACE VIEW public.v_bar_15m AS
SELECT
    b.instrument_id,
    date_bin('15 minutes', b.bar_time, '2001-01-01 09:30:00+08'::timestamp with time zone) AS bar_time,
    min(b.trade_date) AS trade_date,
    (array_agg(b.open ORDER BY b.bar_time ASC))[1] AS open,
    max(b.high) AS high,
    min(b.low) AS low,
    (array_agg(b.close ORDER BY b.bar_time DESC))[1] AS close,
    sum(COALESCE(b.volume, 0)) AS volume,
    sum(COALESCE(b.amount, 0)) AS amount,
    min(b.created_at) AS created_at,
    max(b.updated_at) AS updated_at,
    bool_and(b.is_complete) AS is_complete,
    'derived_15m'::character varying(20) AS source,
    CASE
        WHEN bool_and(b.bar_status = 'closed') THEN 'closed'
        ELSE 'building'
    END AS bar_status,
    max(b.version) AS version
FROM public.bar_1m b
GROUP BY
    b.instrument_id,
    date_bin('15 minutes', b.bar_time, '2001-01-01 09:30:00+08'::timestamp with time zone);

CREATE OR REPLACE VIEW public.v_bar_60m AS
SELECT
    b.instrument_id,
    date_bin('60 minutes', b.bar_time, '2001-01-01 09:30:00+08'::timestamp with time zone) AS bar_time,
    min(b.trade_date) AS trade_date,
    (array_agg(b.open ORDER BY b.bar_time ASC))[1] AS open,
    max(b.high) AS high,
    min(b.low) AS low,
    (array_agg(b.close ORDER BY b.bar_time DESC))[1] AS close,
    sum(COALESCE(b.volume, 0)) AS volume,
    sum(COALESCE(b.amount, 0)) AS amount,
    min(b.created_at) AS created_at,
    max(b.updated_at) AS updated_at,
    bool_and(b.is_complete) AS is_complete,
    'derived_60m'::character varying(20) AS source,
    CASE
        WHEN bool_and(b.bar_status = 'closed') THEN 'closed'
        ELSE 'building'
    END AS bar_status,
    max(b.version) AS version
FROM public.bar_30m b
GROUP BY
    b.instrument_id,
    date_bin('60 minutes', b.bar_time, '2001-01-01 09:30:00+08'::timestamp with time zone);

COMMIT;
