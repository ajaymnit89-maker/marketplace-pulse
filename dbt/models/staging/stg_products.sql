-- 610 products have no category and 13 have a category missing from the translation table.
select
    p.product_id,
    coalesce(t.product_category_name_english, p.product_category_name, 'unknown') as category,
    p.product_photos_qty  as photos_qty,
    p.product_weight_g    as weight_g,
    p.product_length_cm   as length_cm,
    p.product_height_cm   as height_cm,
    p.product_width_cm    as width_cm
from {{ source('raw', 'products') }} p
left join {{ source('raw', 'category_translation') }} t using (product_category_name)
