-- ~550 orders have more than one review; keep the latest answer so the grain is one row per order.
select
    order_id,
    review_id,
    review_score,
    review_comment_title,
    review_comment_message,
    review_creation_date as review_created_at,
    review_answer_timestamp as review_answered_at
from {{ source('raw', 'order_reviews') }}
qualify row_number() over (partition by order_id order by review_answer_timestamp desc, review_id) = 1
