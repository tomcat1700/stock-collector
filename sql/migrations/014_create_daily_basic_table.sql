\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS public.daily_basic (
    instrument_id varchar(30) NOT NULL,
    trade_date date NOT NULL,
    turnover_rate numeric(12,4),
    total_share numeric(20,4),
    float_share numeric(20,4),
    free_share numeric(20,4),
    total_market_cap numeric(20,4),
    circulating_market_cap numeric(20,4),
    source varchar(32) NOT NULL DEFAULT 'tushare_daily_basic',
    version integer NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT daily_basic_pkey PRIMARY KEY (instrument_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_basic_trade_date
    ON public.daily_basic (trade_date DESC, instrument_id);

COMMENT ON TABLE public.daily_basic IS 'Tushare daily_basic 每日指标快照；share 字段单位为万股，market_cap 字段单位为万元。';
COMMENT ON COLUMN public.daily_basic.turnover_rate IS '换手率，单位：百分比';
COMMENT ON COLUMN public.daily_basic.total_share IS '总股本，单位：万股';
COMMENT ON COLUMN public.daily_basic.float_share IS '流通股本，单位：万股';
COMMENT ON COLUMN public.daily_basic.free_share IS '自由流通股本，单位：万股';
COMMENT ON COLUMN public.daily_basic.total_market_cap IS '总市值，单位：万元';
COMMENT ON COLUMN public.daily_basic.circulating_market_cap IS '流通市值，单位：万元';
