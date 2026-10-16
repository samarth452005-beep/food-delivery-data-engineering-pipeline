-- Run in BigQuery with your project and dataset identifiers.
-- These views provide read-only business analytics.

CREATE OR REPLACE VIEW
  `intrepid-charge-511709-t8.food_delivery.vw_delivered_sales_by_location`
AS
SELECT
  restaurant_city,
  COUNT(*) AS delivered_orders,
  SUM(sales_amount) AS delivered_sales,
  ROUND(AVG(sales_amount), 2) AS avg_order_value,
  ROUND(AVG(customer_rating), 2) AS avg_customer_rating,
  ROUND(AVG(delivery_time_min), 2) AS avg_delivery_minutes
FROM `intrepid-charge-511709-t8.food_delivery.orders`
WHERE order_status = 'Delivered'
GROUP BY restaurant_city;

CREATE OR REPLACE VIEW
  `intrepid-charge-511709-t8.food_delivery.vw_order_status_by_location`
AS
SELECT
  restaurant_city,
  COUNT(*) AS total_orders,
  COUNTIF(order_status = 'Delivered') AS delivered_orders,
  COUNTIF(order_status = 'Cancelled') AS cancelled_orders,
  COUNTIF(order_status = 'Refunded') AS refunded_orders,
  ROUND(
    100 * SAFE_DIVIDE(COUNTIF(order_status = 'Cancelled'), COUNT(*)), 2
  ) AS cancellation_rate_pct
FROM `intrepid-charge-511709-t8.food_delivery.orders`
GROUP BY restaurant_city;
