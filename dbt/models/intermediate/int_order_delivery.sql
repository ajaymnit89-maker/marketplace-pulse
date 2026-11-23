-- Delivery timing per order. Lateness is judged on calendar dates because the promised date has no time part.
select
    order_id,
    delivered_at is not null as is_delivered,
    date_diff('day', purchased_at::date, delivered_at::date)        as delivery_days,
    date_diff('day', purchased_at::date, estimated_delivery_date)   as promised_days,
    date_diff('day', estimated_delivery_date, delivered_at::date)   as delay_days,
    case when delivered_at is not null
         then delivered_at::date > estimated_delivery_date end      as is_late
from {{ ref('stg_orders') }}
