SELECT conname, pg_get_constraintdef(oid) AS def
FROM pg_constraint
WHERE conrelid = 'public.realtime_quotes'::regclass
  AND conname = 'ck_realtime_quotes_source_timestamp';

SELECT count(*) AS invalid_source_timestamp_rows
FROM public.realtime_quotes
WHERE trade_date IS NOT NULL
  AND trade_time IS NOT NULL
  AND quote_time <> ((trade_date::text || ' ' || trade_time::text || '+08')::timestamptz);
