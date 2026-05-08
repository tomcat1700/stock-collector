-- Enforce source-side timestamp consistency for realtime_quotes.
-- On a Timescale hypertable we cannot add a unique index that omits the
-- partitioning column quote_time. The table already has PRIMARY KEY
-- (instrument_id, quote_time), so by enforcing quote_time = trade_date + trade_time
-- for non-null source timestamps we get DB-level protection equivalent to the
-- intended fingerprint.

BEGIN;

ALTER TABLE public.realtime_quotes
ADD CONSTRAINT ck_realtime_quotes_source_timestamp
CHECK (
    trade_date IS NULL
    OR trade_time IS NULL
    OR quote_time = ((trade_date::text || ' ' || trade_time::text || '+08')::timestamptz)
);

COMMIT;
