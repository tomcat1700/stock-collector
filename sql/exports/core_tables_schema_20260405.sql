--
-- PostgreSQL database dump
--

\restrict y1zCd89byLG1hI9CSQoc9sTy7hKTk7o4HhMDVnhfM4aLx9JPRqQQKGQOZ4H5JQ9

-- Dumped from database version 17.9 (Homebrew)
-- Dumped by pg_dump version 17.9 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: data_quality_log; Type: TABLE; Schema: public; Owner: wt
--

CREATE TABLE public.data_quality_log (
    id bigint NOT NULL,
    data_domain character varying(30) NOT NULL,
    ref_key character varying(100),
    issue_type character varying(30) NOT NULL,
    issue_level character varying(20) DEFAULT 'warn'::character varying NOT NULL,
    issue_message text NOT NULL,
    payload_json jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.data_quality_log OWNER TO wt;

--
-- Name: data_quality_log_id_seq; Type: SEQUENCE; Schema: public; Owner: wt
--

CREATE SEQUENCE public.data_quality_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.data_quality_log_id_seq OWNER TO wt;

--
-- Name: data_quality_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: wt
--

ALTER SEQUENCE public.data_quality_log_id_seq OWNED BY public.data_quality_log.id;


--
-- Name: job_runs; Type: TABLE; Schema: public; Owner: wt
--

CREATE TABLE public.job_runs (
    job_run_id bigint NOT NULL,
    job_name character varying(100) NOT NULL,
    job_type character varying(30) NOT NULL,
    run_date date,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    status character varying(20) DEFAULT 'running'::character varying NOT NULL,
    processed_count bigint DEFAULT 0 NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.job_runs OWNER TO wt;

--
-- Name: job_runs_job_run_id_seq; Type: SEQUENCE; Schema: public; Owner: wt
--

CREATE SEQUENCE public.job_runs_job_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.job_runs_job_run_id_seq OWNER TO wt;

--
-- Name: job_runs_job_run_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: wt
--

ALTER SEQUENCE public.job_runs_job_run_id_seq OWNED BY public.job_runs.job_run_id;


--
-- Name: kline_daily; Type: TABLE; Schema: public; Owner: wt
--

CREATE TABLE public.kline_daily (
    instrument_id character varying(30) NOT NULL,
    trade_date date NOT NULL,
    open numeric(12,4),
    high numeric(12,4),
    low numeric(12,4),
    close numeric(12,4),
    volume bigint,
    amount numeric(16,2),
    pct_change numeric(8,4),
    amplitude numeric(8,4),
    change numeric(12,4),
    turnover numeric(8,4),
    created_at timestamp with time zone DEFAULT now(),
    source character varying(20) DEFAULT 'akshare'::character varying NOT NULL,
    is_final boolean DEFAULT true NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.kline_daily OWNER TO wt;

--
-- Name: TABLE kline_daily; Type: COMMENT; Schema: public; Owner: wt
--

COMMENT ON TABLE public.kline_daily IS '日 K 线数据表（hypertable），保留 6 年';


--
-- Name: kline_minute; Type: TABLE; Schema: public; Owner: wt
--

CREATE TABLE public.kline_minute (
    instrument_id character varying(30) NOT NULL,
    bar_time timestamp with time zone NOT NULL,
    period integer NOT NULL,
    open numeric(12,4),
    high numeric(12,4),
    low numeric(12,4),
    close numeric(12,4),
    volume bigint,
    amount numeric(16,2),
    created_at timestamp with time zone DEFAULT now(),
    is_complete boolean DEFAULT false,
    update_count integer DEFAULT 0,
    updated_at timestamp with time zone DEFAULT now(),
    trade_date date,
    source character varying(20) DEFAULT 'derived'::character varying NOT NULL,
    bar_status character varying(20) DEFAULT 'closed'::character varying NOT NULL,
    version integer DEFAULT 1 NOT NULL
);


ALTER TABLE public.kline_minute OWNER TO wt;

--
-- Name: TABLE kline_minute; Type: COMMENT; Schema: public; Owner: wt
--

COMMENT ON TABLE public.kline_minute IS '股票分钟 K 线统一表，1/5/15 分钟保留 20 交易日，30/60 分钟保留 60 交易日';


--
-- Name: pool_members_current; Type: TABLE; Schema: public; Owner: wt
--

CREATE TABLE public.pool_members_current (
    instrument_id character varying(30) NOT NULL,
    pool_id smallint NOT NULL,
    entered_at timestamp with time zone DEFAULT now() NOT NULL,
    entered_reason text,
    source_signal_id bigint,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.pool_members_current OWNER TO wt;

--
-- Name: pools; Type: TABLE; Schema: public; Owner: wt
--

CREATE TABLE public.pools (
    pool_id smallint NOT NULL,
    pool_type character varying(20) NOT NULL,
    pool_name character varying(50) NOT NULL,
    parent_id smallint,
    depth smallint DEFAULT 0,
    description text,
    max_count integer,
    sort_order smallint DEFAULT 0,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.pools OWNER TO wt;

--
-- Name: realtime_quotes; Type: TABLE; Schema: public; Owner: wt
--

CREATE TABLE public.realtime_quotes (
    instrument_id character varying(30) NOT NULL,
    quote_time timestamp with time zone NOT NULL,
    name character varying(100),
    open numeric(12,4),
    pre_close numeric(12,4),
    current numeric(12,4),
    high numeric(12,4),
    low numeric(12,4),
    bid_price numeric(12,4),
    ask_price numeric(12,4),
    volume bigint,
    amount numeric(16,2),
    bid1_volume bigint,
    bid1_price numeric(12,4),
    bid2_volume bigint,
    bid2_price numeric(12,4),
    bid3_volume bigint,
    bid3_price numeric(12,4),
    bid4_volume bigint,
    bid4_price numeric(12,4),
    bid5_volume bigint,
    bid5_price numeric(12,4),
    ask1_volume bigint,
    ask1_price numeric(12,4),
    ask2_volume bigint,
    ask2_price numeric(12,4),
    ask3_volume bigint,
    ask3_price numeric(12,4),
    ask4_volume bigint,
    ask4_price numeric(12,4),
    ask5_volume bigint,
    ask5_price numeric(12,4),
    change numeric(12,4),
    change_pct numeric(8,4),
    amplitude numeric(8,4),
    total_bid_volume bigint,
    total_ask_volume bigint,
    order_ratio numeric(8,4),
    trade_date date,
    trade_time time without time zone,
    created_at timestamp with time zone DEFAULT now(),
    is_closing boolean DEFAULT false,
    source character varying(20) DEFAULT 'sina'::character varying NOT NULL,
    session_phase character varying(20) DEFAULT 'continuous_am'::character varying NOT NULL,
    cum_volume bigint,
    cum_amount numeric(20,2),
    delta_volume bigint DEFAULT 0 NOT NULL,
    delta_amount numeric(20,2) DEFAULT 0 NOT NULL,
    is_valid boolean DEFAULT true NOT NULL,
    ingest_batch_id character varying(50),
    raw_payload jsonb
);


ALTER TABLE public.realtime_quotes OWNER TO wt;

--
-- Name: TABLE realtime_quotes; Type: COMMENT; Schema: public; Owner: wt
--

COMMENT ON TABLE public.realtime_quotes IS '实时行情表（秒级），待交易池保留 3 天';


--
-- Name: COLUMN realtime_quotes.is_closing; Type: COMMENT; Schema: public; Owner: wt
--

COMMENT ON COLUMN public.realtime_quotes.is_closing IS '是否为收盘价记录（15:00 集中撮合产生）';


--
-- Name: data_quality_log id; Type: DEFAULT; Schema: public; Owner: wt
--

ALTER TABLE ONLY public.data_quality_log ALTER COLUMN id SET DEFAULT nextval('public.data_quality_log_id_seq'::regclass);


--
-- Name: job_runs job_run_id; Type: DEFAULT; Schema: public; Owner: wt
--

ALTER TABLE ONLY public.job_runs ALTER COLUMN job_run_id SET DEFAULT nextval('public.job_runs_job_run_id_seq'::regclass);


--
-- Name: data_quality_log data_quality_log_pkey; Type: CONSTRAINT; Schema: public; Owner: wt
--

ALTER TABLE ONLY public.data_quality_log
    ADD CONSTRAINT data_quality_log_pkey PRIMARY KEY (id);


--
-- Name: job_runs job_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: wt
--

ALTER TABLE ONLY public.job_runs
    ADD CONSTRAINT job_runs_pkey PRIMARY KEY (job_run_id);


--
-- Name: kline_daily kline_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: wt
--

ALTER TABLE ONLY public.kline_daily
    ADD CONSTRAINT kline_daily_pkey PRIMARY KEY (instrument_id, trade_date);


--
-- Name: kline_minute kline_minute_pkey; Type: CONSTRAINT; Schema: public; Owner: wt
--

ALTER TABLE ONLY public.kline_minute
    ADD CONSTRAINT kline_minute_pkey PRIMARY KEY (instrument_id, bar_time, period);


--
-- Name: pool_members_current pool_members_current_pkey; Type: CONSTRAINT; Schema: public; Owner: wt
--

ALTER TABLE ONLY public.pool_members_current
    ADD CONSTRAINT pool_members_current_pkey PRIMARY KEY (instrument_id);


--
-- Name: pools pools_pkey; Type: CONSTRAINT; Schema: public; Owner: wt
--

ALTER TABLE ONLY public.pools
    ADD CONSTRAINT pools_pkey PRIMARY KEY (pool_id);


--
-- Name: realtime_quotes realtime_quotes_pkey; Type: CONSTRAINT; Schema: public; Owner: wt
--

ALTER TABLE ONLY public.realtime_quotes
    ADD CONSTRAINT realtime_quotes_pkey PRIMARY KEY (instrument_id, quote_time);


--
-- Name: idx_kline_complete; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_kline_complete ON public.kline_minute USING btree (period, bar_time, is_complete);


--
-- Name: idx_kline_date; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_kline_date ON public.kline_daily USING btree (trade_date DESC);


--
-- Name: idx_kline_instrument; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_kline_instrument ON public.kline_daily USING btree (instrument_id, trade_date DESC);


--
-- Name: idx_kline_min; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_kline_min ON public.kline_minute USING btree (instrument_id, period, bar_time DESC);


--
-- Name: idx_public_dq_domain_created; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_public_dq_domain_created ON public.data_quality_log USING btree (data_domain, created_at DESC);


--
-- Name: idx_public_job_runs_name_started; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_public_job_runs_name_started ON public.job_runs USING btree (job_name, started_at DESC);


--
-- Name: idx_public_kd_trade_date; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_public_kd_trade_date ON public.kline_daily USING btree (trade_date DESC, instrument_id);


--
-- Name: idx_public_km_trade_date_period; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_public_km_trade_date_period ON public.kline_minute USING btree (trade_date, period, instrument_id);


--
-- Name: idx_public_pool_members_current_pool; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_public_pool_members_current_pool ON public.pool_members_current USING btree (pool_id, entered_at DESC);


--
-- Name: idx_public_rt_quote_time; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_public_rt_quote_time ON public.realtime_quotes USING btree (quote_time DESC);


--
-- Name: idx_public_rt_trade_date; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_public_rt_trade_date ON public.realtime_quotes USING btree (trade_date, instrument_id);


--
-- Name: idx_rt_closing; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_rt_closing ON public.realtime_quotes USING btree (is_closing) WHERE (is_closing = true);


--
-- Name: idx_rt_inst_time; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_rt_inst_time ON public.realtime_quotes USING btree (instrument_id, quote_time DESC);


--
-- Name: idx_rt_instrument; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX idx_rt_instrument ON public.realtime_quotes USING btree (instrument_id, quote_time DESC);


--
-- Name: kline_daily_trade_date_idx; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX kline_daily_trade_date_idx ON public.kline_daily USING btree (trade_date DESC);


--
-- Name: kline_minute_bar_time_idx; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX kline_minute_bar_time_idx ON public.kline_minute USING btree (bar_time DESC);


--
-- Name: realtime_quotes_quote_time_idx; Type: INDEX; Schema: public; Owner: wt
--

CREATE INDEX realtime_quotes_quote_time_idx ON public.realtime_quotes USING btree (quote_time DESC);


--
-- Name: pool_members_current pool_members_current_instrument_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: wt
--

ALTER TABLE ONLY public.pool_members_current
    ADD CONSTRAINT pool_members_current_instrument_id_fkey FOREIGN KEY (instrument_id) REFERENCES public.instruments(instrument_id);


--
-- Name: pool_members_current pool_members_current_pool_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: wt
--

ALTER TABLE ONLY public.pool_members_current
    ADD CONSTRAINT pool_members_current_pool_id_fkey FOREIGN KEY (pool_id) REFERENCES public.pools(pool_id);


--
-- Name: pools pools_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: wt
--

ALTER TABLE ONLY public.pools
    ADD CONSTRAINT pools_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.pools(pool_id);


--
-- PostgreSQL database dump complete
--

\unrestrict y1zCd89byLG1hI9CSQoc9sTy7hKTk7o4HhMDVnhfM4aLx9JPRqQQKGQOZ4H5JQ9

