SELECT to_regclass('public.daily_basic') AS daily_basic_table;

SELECT
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'daily_basic'
ORDER BY ordinal_position;

SELECT
    trade_date,
    COUNT(*) AS row_count
FROM public.daily_basic
GROUP BY trade_date
ORDER BY trade_date DESC
LIMIT 10;
