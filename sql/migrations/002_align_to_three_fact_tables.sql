BEGIN;

CREATE TABLE IF NOT EXISTS public.kline_second (
    instrument_id character varying(30) NOT NULL,
    bar_time timestamp with time zone NOT NULL,
    period integer DEFAULT 3 NOT NULL,
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
    quote_count integer DEFAULT 0 NOT NULL,
    source character varying(20) DEFAULT 'derived'::character varying NOT NULL,
    bar_status character varying(20) DEFAULT 'closed'::character varying NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT kline_second_pkey PRIMARY KEY (instrument_id, bar_time, period)
);

COMMENT ON TABLE public.kline_second IS '秒级 K 线事实表，当前默认存储 3 秒聚合结果';

CREATE INDEX IF NOT EXISTS idx_kline_second_trade_date_period
    ON public.kline_second (trade_date, period, instrument_id);

CREATE INDEX IF NOT EXISTS idx_kline_second_instrument_time
    ON public.kline_second (instrument_id, bar_time DESC, period);

INSERT INTO public.kline_second (
    instrument_id,
    bar_time,
    period,
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
    quote_count,
    source,
    bar_status,
    version
)
SELECT
    b.instrument_id,
    b.bar_time,
    3 AS period,
    b.trade_date,
    b.open,
    b.high,
    b.low,
    b.close,
    b.volume,
    b.amount,
    b.created_at,
    b.updated_at,
    true AS is_complete,
    COALESCE(b.quote_count, 0) AS quote_count,
    'bar_3s_migrated'::character varying AS source,
    b.bar_status,
    b.version
FROM public.bar_3s b
ON CONFLICT (instrument_id, bar_time, period) DO UPDATE SET
    trade_date = EXCLUDED.trade_date,
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    amount = EXCLUDED.amount,
    updated_at = EXCLUDED.updated_at,
    is_complete = EXCLUDED.is_complete,
    quote_count = EXCLUDED.quote_count,
    source = EXCLUDED.source,
    bar_status = EXCLUDED.bar_status,
    version = EXCLUDED.version;

COMMIT;
