-- 026_seed_major_a_share_indices.sql
-- Keep the collector watchlist focused on realtime collection while allowing
-- core A-share indices to be sampled alongside stocks.

INSERT INTO public.instruments (
    instrument_id,
    code,
    name,
    type,
    market,
    status
)
VALUES
    ('000001.SH', '000001', '上证指数', 'index', 'SH', 'active'),
    ('000016.SH', '000016', '上证50', 'index', 'SH', 'active'),
    ('000300.SH', '000300', '沪深300', 'index', 'SH', 'active'),
    ('000688.SH', '000688', '科创50', 'index', 'SH', 'active'),
    ('000905.SH', '000905', '中证500', 'index', 'SH', 'active'),
    ('000852.SH', '000852', '中证1000', 'index', 'SH', 'active'),
    ('399001.SZ', '399001', '深证成指', 'index', 'SZ', 'active'),
    ('399006.SZ', '399006', '创业板指', 'index', 'SZ', 'active'),
    ('899050.BJ', '899050', '北证50', 'index', 'BJ', 'active')
ON CONFLICT (instrument_id) DO UPDATE SET
    code = EXCLUDED.code,
    name = EXCLUDED.name,
    type = EXCLUDED.type,
    market = EXCLUDED.market,
    status = EXCLUDED.status,
    updated_at = now();

INSERT INTO public.collector_watchlist (
    instrument_id,
    name,
    instrument_type
)
SELECT
    instrument_id,
    name,
    type
FROM public.instruments
WHERE instrument_id IN (
    '000001.SH',
    '000016.SH',
    '000300.SH',
    '000688.SH',
    '000905.SH',
    '000852.SH',
    '399001.SZ',
    '399006.SZ',
    '899050.BJ'
)
ON CONFLICT (instrument_id) DO UPDATE SET
    name = EXCLUDED.name,
    instrument_type = EXCLUDED.instrument_type;
