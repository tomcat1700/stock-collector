-- 009_add_membership_mask_to_pool_members_current.sql
-- 目标：
-- 为 public.pool_members_current 增加 membership_mask，
-- 保留 pool_id 作为当前最深主池，并基于当前 pool_id 回填多池归属位。

\set ON_ERROR_STOP on

alter table public.pool_members_current
    add column if not exists membership_mask bigint not null default 0;

update public.pool_members_current
set membership_mask = case pool_id
    when 1 then 1
    when 2 then 3
    when 3 then 5
    when 4 then 13
    when 5 then 29
    when 6 then 61
    else 0
end
where coalesce(membership_mask, 0) = 0;

comment on column public.pool_members_current.membership_mask is
'Multi-pool membership bit mask. pool_id remains the current deepest main pool. Bits: all=1 preferred=2 base=4 observation=8 trade=16 hold=32.';
