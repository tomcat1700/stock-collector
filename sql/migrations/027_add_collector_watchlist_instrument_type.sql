-- 027_add_collector_watchlist_instrument_type.sql
-- Mark each collector watchlist entry by instrument type so stocks and indices
-- can be separated without joining instruments for common operational checks.

ALTER TABLE public.collector_watchlist
    ADD COLUMN IF NOT EXISTS instrument_type varchar(20);

UPDATE public.collector_watchlist cw
SET instrument_type = COALESCE(i.type, 'stock')
FROM public.instruments i
WHERE i.instrument_id = cw.instrument_id
  AND (
      cw.instrument_type IS NULL
      OR cw.instrument_type IS DISTINCT FROM COALESCE(i.type, 'stock')
  );

UPDATE public.collector_watchlist
SET instrument_type = 'stock'
WHERE instrument_type IS NULL;

ALTER TABLE public.collector_watchlist
    ALTER COLUMN instrument_type SET DEFAULT 'stock',
    ALTER COLUMN instrument_type SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_collector_watchlist_instrument_type
    ON public.collector_watchlist (instrument_type, instrument_id);

COMMENT ON COLUMN public.collector_watchlist.instrument_type IS
    'Collector watchlist type marker, usually stock or index.';
