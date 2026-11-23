select
    s.seller_id,
    s.city,
    s.state,
    min(o.purchased_at)::date   as first_sale_date,
    count(distinct i.order_id)  as order_count
from {{ ref('stg_sellers') }} s
left join {{ ref('stg_order_items') }} i using (seller_id)
left join {{ ref('stg_orders') }} o using (order_id)
group by all
