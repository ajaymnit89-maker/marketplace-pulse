-- One row per person (customer_unique_id). Location comes from their latest order.
select
    customer_unique_id,
    arg_max(c.city, o.purchased_at)     as city,
    arg_max(c.state, o.purchased_at)    as state,
    min(o.purchased_at)::date           as first_order_date,
    max(o.purchased_at)::date           as last_order_date,
    count(*)                            as order_count,
    count(*) > 1                        as is_repeat_customer
from {{ ref('stg_customers') }} c
join {{ ref('stg_orders') }} o using (customer_id)
group by customer_unique_id
