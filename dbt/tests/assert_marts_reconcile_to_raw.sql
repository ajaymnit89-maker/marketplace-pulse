-- Marts must keep every order and every real of GMV from the raw files. Returns a row on mismatch.
with mart as (
    select count(*) as orders, round(sum(order_value), 2) as gmv from {{ ref('fct_orders') }}
), raw as (
    select
        (select count(*) from {{ source('raw', 'orders') }}) as orders,
        (select round(sum(price + freight_value), 2) from {{ source('raw', 'order_items') }}) as gmv
)
select * from mart, raw
where mart.orders != raw.orders or abs(mart.gmv - raw.gmv) > 0.01
