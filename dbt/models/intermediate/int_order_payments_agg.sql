select
    order_id,
    sum(payment_value)          as payment_value,
    max(payment_installments)   as max_installments,
    -- the payment that covered most of the order
    arg_max(payment_type, payment_value) as main_payment_type
from {{ ref('stg_order_payments') }}
group by order_id
