-- Covers every purchase and promised-delivery date.
with bounds as (
    select min(purchased_at)::date as lo, max(greatest(estimated_delivery_date, coalesce(delivered_at::date, estimated_delivery_date))) as hi
    from {{ ref('stg_orders') }}
)
select
    d::date                         as date_day,
    year(d)                         as year,
    quarter(d)                      as quarter,
    month(d)                        as month,
    strftime(d, '%Y-%m')            as year_month,
    date_trunc('week', d)::date     as week_start,
    dayofweek(d)                    as day_of_week,
    dayname(d)                      as day_name,
    dayofweek(d) in (0, 6)          as is_weekend
from bounds, generate_series(lo, hi, interval 1 day) as t(d)
