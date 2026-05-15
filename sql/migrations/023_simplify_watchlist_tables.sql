-- 023_simplify_watchlist_tables.sql
-- stock_realtime no longer classifies collector watchlist entries into pools.
-- public.pool_members_current remains the single collector watchlist table.

alter table if exists public.pool_members_current
    drop constraint if exists pool_members_current_pool_id_fkey;

drop index if exists public.idx_public_pool_members_current_pool;

alter table if exists public.pool_members_current
    drop column if exists pool_id,
    drop column if exists source_signal_id,
    drop column if exists membership_mask;

drop table if exists public.pools;
