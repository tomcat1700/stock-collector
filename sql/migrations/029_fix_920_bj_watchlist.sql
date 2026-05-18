-- 029_fix_920_bj_watchlist.sql
-- Correct selected Beijing Stock Exchange watchlist entries that were imported
-- with an SH suffix. The canonical instrument rows already use .BJ.

\set ON_ERROR_STOP on

begin;

with mapping(old_id, new_id) as (
    values
        ('920092.SH', '920092.BJ'),
        ('920493.SH', '920493.BJ'),
        ('920522.SH', '920522.BJ')
)
insert into public.collector_watchlist (
    instrument_id,
    name,
    instrument_type
)
select
    mapping.new_id,
    coalesce(correct.name, old_watchlist.name),
    old_watchlist.instrument_type
from mapping
join public.collector_watchlist old_watchlist
    on old_watchlist.instrument_id = mapping.old_id
left join public.instruments correct
    on correct.instrument_id = mapping.new_id
on conflict (instrument_id) do update set
    name = excluded.name,
    instrument_type = excluded.instrument_type;

with mapping(old_id, new_id) as (
    values
        ('920092.SH', '920092.BJ'),
        ('920493.SH', '920493.BJ'),
        ('920522.SH', '920522.BJ')
)
delete from public.collector_watchlist old_watchlist
using mapping
where old_watchlist.instrument_id = mapping.old_id;

delete from public.instruments
where instrument_id in ('920092.SH', '920493.SH', '920522.SH')
  and not exists (
      select 1
      from public.collector_watchlist
      where collector_watchlist.instrument_id = instruments.instrument_id
  );

commit;
