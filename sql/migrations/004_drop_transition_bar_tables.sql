BEGIN;

DROP VIEW IF EXISTS public.v_bar_5m;
DROP VIEW IF EXISTS public.v_bar_15m;
DROP VIEW IF EXISTS public.v_bar_60m;

DROP TABLE IF EXISTS public.bar_3s;
DROP TABLE IF EXISTS public.bar_1m;
DROP TABLE IF EXISTS public.bar_30m;

COMMIT;
