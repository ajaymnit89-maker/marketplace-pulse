{% docs metrics %}
# Metric definitions

Every dashboard, notebook and the AI analyst use these definitions. All are computed from `fct_orders`
unless noted, and exclude canceled orders (`is_canceled = false`) unless noted.

| Metric | Definition |
|---|---|
| **GMV** | `sum(order_value)`: item price + freight, in BRL |
| **Orders** | `count(order_id)` |
| **AOV** | GMV / Orders |
| **On-time rate** | delivered orders with `is_late = false` / delivered orders (`is_delivered = true`) |
| **Late rate** | 1 - on-time rate |
| **Avg delay (late orders)** | `avg(delay_days)` where `is_late` |
| **Avg review score** | `avg(review_score)` over orders that have a review |
| **Repeat customer rate** | `dim_customer`: customers with `is_repeat_customer` / all customers |
| **Seller late-ship rate** | `fct_order_items`: items with `seller_shipped_late` / items with a ship date |
{% enddocs %}
