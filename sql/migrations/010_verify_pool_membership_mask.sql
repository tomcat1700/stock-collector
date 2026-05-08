-- 010_verify_pool_membership_mask.sql
-- 目标：验证 membership_mask 已存在并按当前 pool_id 完成回填。

\set ON_ERROR_STOP on

select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name = 'pool_members_current'
  and column_name = 'membership_mask';

select
    pool_id,
    count(*) as row_count,
    min(membership_mask) as min_mask,
    max(membership_mask) as max_mask
from public.pool_members_current
group by pool_id
order by pool_id;

select
    instrument_id,
    pool_id,
    membership_mask,
    entered_reason,
    updated_at
from public.pool_members_current
order by updated_at desc
limit 20;
