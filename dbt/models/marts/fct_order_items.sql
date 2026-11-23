select
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    o.customer_unique_id,
    o.purchase_date,
    o.order_status,
    o.is_canceled,
    o.is_late,
    o.delay_days,
    o.review_score,
    i.shipping_limit_at,
    -- seller handed to carrier after the deadline it was given
    o.shipped_at > i.shipping_limit_at as seller_shipped_late,
    i.price,
    i.freight_value,
    i.price + i.freight_value as item_value
from {{ ref('stg_order_items') }} i
join {{ ref('fct_orders') }} o using (order_id)
