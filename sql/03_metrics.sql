-- ============================================================================
-- 03_metrics.sql  ——  核心指标层（对应 pandas 的 03_metrics.py）
-- ----------------------------------------------------------------------------
-- 口径说明（必须与 Power BI / HTML 看板一致，否则三处数字打架）：
--   · GMV = 商品金额 + 运费，且【只统计 is_delivered = TRUE】
--   · 客户数用 COUNT(DISTINCT customer_unique_id)，不用 customer_id
--   · 评分类指标（平均评分 / 差评率）用全量口径：没收到货的 1 星也是真实口碑
--   · 趋势类指标必须过滤 is_complete_month，否则首尾残缺月会被误读为暴跌
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS analysis;

-- ---------------------------------------------------------------- 核心 KPI 宽表
CREATE OR REPLACE TABLE analysis.kpi_core AS
WITH delivered AS (
    SELECT * FROM clean.fact_orders WHERE is_delivered
),
all_orders AS (
    SELECT * FROM clean.fact_orders
),
items_d AS (
    SELECT * FROM clean.fact_order_items WHERE is_delivered
),
cust_orders AS (
    SELECT customer_unique_id, COUNT(*) AS delivered_orders
    FROM clean.fact_orders WHERE is_delivered
    GROUP BY customer_unique_id
),
scaler AS (
    SELECT
        SUM(gmv_total)                       AS gmv,
        COUNT(*)                             AS orders,
        COUNT(DISTINCT customer_unique_id)   AS customers,
        SUM(gmv_items)                       AS gmv_items_amt,
        SUM(order_freight)                   AS freight_amt,
        AVG(gmv_total)                       AS aov,
        AVG(delivery_days)                   AS avg_delivery_days,
        COUNT(*) FILTER (WHERE is_late = FALSE) AS on_time_orders,
        COUNT(*) FILTER (WHERE is_late)         AS late_orders,
        COUNT(*) FILTER (WHERE is_new_customer) AS new_customer_orders
    FROM delivered
),
rep AS (
    SELECT
        COUNT(*)                                        AS repurchase_customers,
        COUNT(*) FILTER (WHERE delivered_orders >= 2)   AS repeat_customers
    FROM cust_orders
),
itm AS (
    SELECT COUNT(*) AS qty, SUM(price) AS price_amt FROM items_d
),
ful AS (
    SELECT
        COUNT(*)                                    AS all_orders,
        COUNT(*) FILTER (WHERE is_delivered)        AS delivered_orders,
        COUNT(DISTINCT customer_unique_id)          AS all_customers,
        AVG(review_score)                           AS avg_review_score,
        COUNT(*) FILTER (WHERE review_score = 1)    AS bad_review_orders,
        COUNT(*) FILTER (WHERE review_score IS NOT NULL) AS scored_orders
    FROM all_orders
)
SELECT
    ROUND(s.gmv, 2)                                                   AS gmv,
    s.orders                                                          AS orders,
    s.customers                                                       AS customers,
    ROUND(s.aov, 2)                                                   AS aov,
    ROUND(s.gmv / s.customers, 2)                                     AS arpu,
    ROUND(s.orders * 1.0 / s.customers, 4)                            AS orders_per_customer,
    itm.qty                                                           AS items_sold,
    ROUND(itm.price_amt / itm.qty, 2)                                 AS price_per_item,
    ROUND(s.freight_amt / s.gmv_items_amt * 100, 2)                   AS freight_pct,
    ROUND(f.delivered_orders * 100.0 / f.all_orders, 2)               AS delivery_rate_pct,
    ROUND(s.on_time_orders * 100.0 / s.orders, 2)                     AS on_time_rate_pct,
    ROUND(s.late_orders   * 100.0 / s.orders, 2)                      AS late_rate_pct,
    ROUND(s.avg_delivery_days, 2)                                     AS avg_delivery_days,
    ROUND(f.avg_review_score, 2)                                      AS avg_review_score,
    ROUND(f.bad_review_orders * 100.0 / f.scored_orders, 2)           AS bad_review_rate_pct,
    ROUND(r.repeat_customers * 100.0 / r.repurchase_customers, 2)     AS repurchase_rate_pct,
    r.repeat_customers                                                AS repeat_customers,
    ROUND(s.new_customer_orders * 100.0 / s.orders, 2)                AS new_customer_order_pct,
    f.all_orders                                                      AS all_orders,
    f.all_customers                                                   AS all_customers
FROM scaler s CROSS JOIN rep r CROSS JOIN itm CROSS JOIN ful f;

-- ---------------------------------------------------------------- 月度趋势
CREATE OR REPLACE TABLE analysis.monthly_trend AS
SELECT
    d.year_month,
    d.is_complete_month,
    SUM(f.gmv_total)                    AS gmv,
    COUNT(*)                            AS orders,
    COUNT(DISTINCT f.customer_unique_id) AS customers,
    ROUND(AVG(f.gmv_total), 2)          AS aov
FROM clean.fact_orders f
JOIN clean.dim_date d ON d.date_id = f.date_id
WHERE f.is_delivered
GROUP BY d.year_month, d.is_complete_month
ORDER BY d.year_month;

-- ---------------------------------------------------------------- 州维度
CREATE OR REPLACE TABLE analysis.state_performance AS
SELECT
    c.customer_state,
    SUM(f.gmv_total)                     AS gmv,
    COUNT(*)                             AS orders,
    COUNT(DISTINCT f.customer_unique_id) AS customers,
    ROUND(AVG(f.gmv_total), 2)           AS aov,
    ROUND(AVG(f.delivery_days), 2)       AS avg_delivery_days
FROM clean.fact_orders f
JOIN clean.dim_customer c ON c.customer_unique_id = f.customer_unique_id
WHERE f.is_delivered
GROUP BY c.customer_state
ORDER BY gmv DESC;

-- ---------------------------------------------------------------- 品类维度
CREATE OR REPLACE TABLE analysis.category_performance AS
SELECT
    p.product_category_name_english AS category,
    SUM(i.price)                    AS gmv_items,
    SUM(i.freight_value)            AS freight,
    SUM(i.item_total)               AS gmv_with_freight,
    COUNT(*)                        AS items_sold,
    COUNT(DISTINCT i.order_id)      AS orders,
    ROUND(AVG(i.price), 2)          AS avg_price,
    ROUND(SUM(i.freight_value) / SUM(i.price) * 100, 2) AS freight_pct
FROM clean.fact_order_items i
JOIN clean.dim_product p ON p.product_id = i.product_id
WHERE i.is_delivered
GROUP BY p.product_category_name_english
ORDER BY gmv_items DESC;
