-- 024_rename_collector_watchlist.sql
-- Rename the collector watchlist table and keep only the fields required by
-- the collector: instrument id and display name.

alter table if exists public.pool_members_current
    rename to collector_watchlist;

alter table if exists public.collector_watchlist
    drop constraint if exists pool_members_current_instrument_id_fkey;

alter table if exists public.collector_watchlist
    drop constraint if exists pool_members_current_pkey;

alter table if exists public.collector_watchlist
    drop column if exists entered_at,
    drop column if exists entered_reason,
    drop column if exists updated_at;

alter table if exists public.collector_watchlist
    add column if not exists name varchar(100);

update public.collector_watchlist cw
set name = coalesce(i.name, cw.instrument_id)
from public.instruments i
where i.instrument_id = cw.instrument_id
  and (cw.name is null or cw.name = '');

alter table if exists public.collector_watchlist
    alter column name set not null;

alter table if exists public.collector_watchlist
    add constraint collector_watchlist_pkey primary key (instrument_id);

alter table if exists public.collector_watchlist
    add constraint collector_watchlist_instrument_id_fkey
    foreign key (instrument_id) references public.instruments(instrument_id);
