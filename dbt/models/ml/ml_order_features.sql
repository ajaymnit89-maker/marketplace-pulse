-- One row per non-canceled order with items. Every feature is known at purchase time; is_late is the label
-- (null until delivered). Multi-seller orders (~1%) use the seller of the most expensive item.
with items as (
    select i.*, p.category, p.weight_g, p.length_cm * p.height_cm * p.width_cm as volume_cm3
    from {{ ref('stg_order_items') }} i
    left join {{ ref('stg_products') }} p using (product_id)
),

order_items as (
    select
        order_id,
        arg_max(seller_id, price)   as seller_id,
        arg_max(category, price)    as main_category,
        sum(weight_g)               as total_weight_g,
        sum(volume_cm3)             as total_volume_cm3,
        max(shipping_limit_at)      as shipping_limit_at
    from items
    group by 1
),

orders as (
    select f.*, oi.seller_id, oi.main_category, oi.total_weight_g, oi.total_volume_cm3, oi.shipping_limit_at
    from {{ ref('fct_orders') }} f
    join order_items oi using (order_id)
    where not f.is_canceled
),

-- Seller track record as of purchase time: only earlier orders whose promised date had already passed,
-- so their outcome was known. Undelivered past the promise counts as late.
seller_history as (
    select
        o.order_id,
        count(p.order_id) as seller_prior_orders,
        avg((p.delivered_at is null or p.delivered_at::date > p.estimated_delivery_date)::int)
            filter (where p.estimated_delivery_date < o.purchased_at::date) as seller_prior_late_rate
    from orders o
    left join orders p on p.seller_id = o.seller_id and p.purchased_at < o.purchased_at
    group by 1
)

select
    o.order_id,
    o.purchased_at,
    o.is_late,
    o.customer_state,
    s.state                                             as seller_state,
    o.customer_state = s.state                          as same_state,
    -- haversine distance between customer and seller zip prefixes
    2 * 6371 * asin(sqrt(
        pow(sin(radians(cg.lat - sg.lat) / 2), 2)
        + cos(radians(sg.lat)) * cos(radians(cg.lat)) * pow(sin(radians(cg.lng - sg.lng) / 2), 2)
    ))                                                  as distance_km,
    o.promised_days,
    month(o.purchased_at)                               as purchase_month,
    dayofweek(o.purchased_at)                           as purchase_dow,
    hour(o.purchased_at)                                as purchase_hour,
    date_diff('hour', o.purchased_at, o.shipping_limit_at) / 24.0 as days_to_ship_limit,
    o.item_count,
    o.seller_count,
    o.order_value,
    o.freight_value,
    o.freight_value / nullif(o.order_value, 0)          as freight_ratio,
    o.total_weight_g,
    o.total_volume_cm3,
    o.main_category,
    o.main_payment_type,
    o.max_installments,
    h.seller_prior_orders,
    h.seller_prior_late_rate
from orders o
join seller_history h using (order_id)
join {{ ref('stg_sellers') }} s on s.seller_id = o.seller_id
left join {{ ref('stg_customers') }} c on c.customer_id = o.customer_id
left join {{ ref('stg_geolocation') }} cg on cg.zip_code_prefix = c.zip_code_prefix
left join {{ ref('stg_geolocation') }} sg on sg.zip_code_prefix = s.zip_code_prefix
