-- 020_drop_index_meta.sql
-- stock_realtime is scoped to collector-required data.
-- Index descriptive metadata is not read by the collector pipeline.

drop table if exists public.index_meta;
