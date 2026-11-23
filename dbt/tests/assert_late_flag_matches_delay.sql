-- is_late and delay_days must agree for every delivered order.
select order_id from {{ ref('fct_orders') }}
where is_delivered and (is_late != (delay_days > 0))
