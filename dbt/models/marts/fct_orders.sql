select
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    c.state                         as customer_state,
    o.order_status,
    o.order_status in ('canceled', 'unavailable') as is_canceled,
    o.purchased_at,
    o.purchased_at::date            as purchase_date,
    o.approved_at,
    o.shipped_at,
    o.delivered_at,
    o.estimated_delivery_date,
    d.is_delivered,
    d.delivery_days,
    d.promised_days,
    d.delay_days,
    d.is_late,
    coalesce(i.item_count, 0)       as item_count,
    coalesce(i.seller_count, 0)     as seller_count,
    coalesce(i.items_value, 0)      as items_value,
    coalesce(i.freight_value, 0)    as freight_value,
    coalesce(i.order_value, 0)      as order_value,
    p.payment_value,
    p.main_payment_type,
    p.max_installments,
    r.review_score,
    r.review_comment_message is not null as has_review_comment,
    -- order rank per person, 1 = first purchase
    row_number() over (partition by c.customer_unique_id order by o.purchased_at, o.order_id) as customer_order_number
from {{ ref('stg_orders') }} o
join {{ ref('stg_customers') }} c using (customer_id)
join {{ ref('int_order_delivery') }} d using (order_id)
left join {{ ref('int_order_items_agg') }} i using (order_id)
left join {{ ref('int_order_payments_agg') }} p using (order_id)
left join {{ ref('stg_order_reviews') }} r using (order_id)
