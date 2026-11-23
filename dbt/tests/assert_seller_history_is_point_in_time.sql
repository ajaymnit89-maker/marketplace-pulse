-- A seller's first order cannot have any history, and the late rate can only use orders counted as prior.
with ranked as (
    select *, row_number() over (partition by seller_id order by purchased_at, order_id) as n
    from (select f.*, i.seller_id from {{ ref('ml_order_features') }} f
          join (select order_id, arg_max(seller_id, price) as seller_id from {{ ref('stg_order_items') }} group by 1) i
          using (order_id))
)
select order_id from ranked
where (n = 1 and seller_prior_orders != 0)
   or seller_prior_orders > n - 1
   or (seller_prior_late_rate is not null and seller_prior_orders = 0)
