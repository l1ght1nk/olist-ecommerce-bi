-- ============================================================================
-- 02_clean.sql  ——  清洗与建模层（对应 pandas 的 02_clean_model.py）
-- ----------------------------------------------------------------------------
-- 关键清洗决策（逐条说明）：
--   1. 送达日期缺失不填补、不删除 —— 那是「订单未送达」的业务状态，
--      派生 is_delivered 标志位区分，而不是当成脏数据 drop 掉
--   2. 支付流水一对多：按订单聚合金额 SUM，主支付方式取「金额最大的那一笔」
--   3. 评论一对多：取 review_answer_timestamp 最新的一条，避免评分重复计数
--   4. 客户身份用 customer_unique_id，不用 customer_id（后者是订单级）
--   5. 地理表 100 万行按邮编聚合取中心点，压缩到 1.9 万行（去掉 98% 冗余）
--   6. 完整月标志 is_complete_month：只保留订单量 ≥500 的连续月份区间，
--      排除平台爬坡期与数据截断月，避免趋势分析误判为业务下滑
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS clean;

-- ---------------------------------------------------------------- 1. 订单级聚合
-- 支付：一个订单多笔 -> 总支付额
CREATE OR REPLACE TABLE clean.order_payment_agg AS
SELECT order_id,
       SUM(payment_value) AS order_payment
FROM raw.order_payments
GROUP BY order_id;

-- 主支付方式：金额最大的那一笔（窗口函数 ROW_NUMBER 取每组 Top1）
CREATE OR REPLACE TABLE clean.order_main_payment AS
SELECT order_id,
       payment_type        AS main_payment_type,
       payment_installments AS main_payment_installments
FROM (
    SELECT order_id, payment_type, payment_installments,
           ROW_NUMBER() OVER (
               PARTITION BY order_id
               ORDER BY payment_value DESC, payment_sequential
           ) AS rn
    FROM raw.order_payments
) t
WHERE rn = 1;

-- 明细：一个订单多行商品 -> 商品金额 / 运费 / 件数
CREATE OR REPLACE TABLE clean.order_item_agg AS
SELECT order_id,
       SUM(price)         AS order_gmv_items,
       SUM(freight_value) AS order_freight,
       COUNT(order_item_id) AS order_qty
FROM raw.order_items
GROUP BY order_id;

-- 评论：一个订单多条 -> 取最新一条的评分
CREATE OR REPLACE TABLE clean.order_review_one AS
SELECT order_id, review_score
FROM (
    SELECT order_id, review_score,
           ROW_NUMBER() OVER (
               PARTITION BY order_id
               ORDER BY review_answer_timestamp DESC NULLS LAST
           ) AS rn
    FROM raw.order_reviews
) t
WHERE rn = 1;

-- 客户首单日期（用于新老客判定 & 同期群）
CREATE OR REPLACE TABLE clean.customer_first_purchase AS
SELECT c.customer_unique_id,
       MIN(o.order_purchase_timestamp) AS first_purchase_date
FROM raw.customers c
JOIN raw.orders o ON o.customer_id = c.customer_id
GROUP BY c.customer_unique_id;

-- ---------------------------------------------------------------- 2. 完整月区间
CREATE OR REPLACE TABLE clean.complete_month_range AS
WITH monthly AS (
    SELECT date_trunc('month', order_purchase_timestamp) AS ym,
           COUNT(*) AS order_cnt
    FROM raw.orders
    GROUP BY 1
)
SELECT MIN(ym) AS ym_start, MAX(ym) AS ym_end
FROM monthly
WHERE order_cnt >= 500;   -- 样本量过小的月份视为爬坡期 / 截断月

-- ---------------------------------------------------------------- 3. 日期维度
CREATE OR REPLACE TABLE clean.dim_date AS
WITH r AS (SELECT * FROM clean.complete_month_range)
SELECT
    CAST(d AS DATE)                                  AS date,
    CAST(strftime(d, '%Y%m%d') AS INTEGER)           AS date_id,
    YEAR(d)                                          AS year,
    QUARTER(d)                                       AS quarter,
    MONTH(d)                                         AS month,
    strftime(d, '%b')                                AS month_name,
    strftime(d, '%Y-%m')                             AS year_month,
    DAY(d)                                           AS day,
    ISODOW(d)                                        AS weekday,
    strftime(d, '%a')                                AS weekday_name,
    ISODOW(d) IN (6, 7)                              AS is_weekend,
    (date_trunc('month', CAST(d AS DATE)) >= (SELECT ym_start FROM r)
     AND date_trunc('month', CAST(d AS DATE)) <= (SELECT ym_end   FROM r))
                                                     AS is_complete_month
FROM generate_series(DATE '2016-01-01', DATE '2018-12-31', INTERVAL 1 DAY) AS g(d);

-- ---------------------------------------------------------------- 4. 客户维度
CREATE OR REPLACE TABLE clean.dim_customer AS
SELECT
    c.customer_unique_id,
    ANY_VALUE(c.customer_state)                        AS customer_state,
    ANY_VALUE(c.customer_city)                         AS customer_city,
    ANY_VALUE(c.customer_zip_code_prefix)              AS customer_zip_code_prefix,
    COUNT(o.order_id)                                  AS order_count,
    MIN(o.order_purchase_timestamp)                    AS first_purchase_date,
    MAX(o.order_purchase_timestamp)                    AS last_purchase_date,
    COUNT(*) FILTER (WHERE o.order_status = 'delivered') AS delivered_orders,
    date_diff('day', MAX(o.order_purchase_timestamp),
              (SELECT MAX(order_purchase_timestamp) FROM raw.orders)) AS recency_days,
    (COUNT(*) FILTER (WHERE o.order_status = 'delivered')) >= 2       AS is_repeat
FROM raw.customers c
JOIN raw.orders o ON o.customer_id = c.customer_id
GROUP BY c.customer_unique_id;

-- ---------------------------------------------------------------- 5. 商品 / 卖家 / 地理维度
CREATE OR REPLACE TABLE clean.dim_product AS
SELECT
    p.product_id,
    p.product_category_name,
    COALESCE(t.product_category_name_english, p.product_category_name) AS product_category_name_english,
    p.product_photos_qty,
    p.product_description_lenght AS product_description_length,
    p.product_weight_g,
    p.product_length_cm * p.product_height_cm * p.product_width_cm AS product_volume_cm3,
    CASE WHEN p.product_photos_qty = 0 THEN '01 无图'
         WHEN p.product_photos_qty <= 2 THEN '02 1-2张'
         WHEN p.product_photos_qty <= 5 THEN '03 3-5张'
         ELSE '04 6张以上' END AS photo_qty_band,
    CASE WHEN p.product_description_lenght < 200 THEN '01 短(<200)'
         WHEN p.product_description_lenght < 800 THEN '02 中(200-800)'
         WHEN p.product_description_lenght < 2000 THEN '03 长(800-2000)'
         ELSE '04 超长(>2000)' END AS desc_len_band
FROM raw.products p
LEFT JOIN raw.category_translation t
       ON t.product_category_name = p.product_category_name;

CREATE OR REPLACE TABLE clean.dim_seller AS
SELECT * FROM raw.sellers;

-- 地理表聚合：100 万行 -> 按邮编取中心点，压缩 98%
CREATE OR REPLACE TABLE clean.dim_geolocation AS
SELECT
    geolocation_zip_code_prefix,
    AVG(geolocation_lat) AS lat,
    AVG(geolocation_lng) AS lng,
    ANY_VALUE(geolocation_city)  AS city,
    ANY_VALUE(geolocation_state) AS state,
    COUNT(*) AS raw_rows
FROM raw.geolocation
GROUP BY geolocation_zip_code_prefix;

-- ---------------------------------------------------------------- 6. 事实表：订单粒度
CREATE OR REPLACE TABLE clean.fact_orders AS
WITH base AS (
    SELECT
        o.order_id,
        o.customer_id,
        c.customer_unique_id,
        o.order_status,
        o.order_purchase_timestamp,
        o.order_delivered_customer_date,
        (o.order_status = 'delivered') AS is_delivered
    FROM raw.orders o
    LEFT JOIN raw.customers c ON c.customer_id = o.customer_id
)
SELECT
    b.order_id,
    b.customer_id,
    b.customer_unique_id,
    CAST(strftime(CAST(b.order_purchase_timestamp AS DATE), '%Y%m%d') AS INTEGER) AS date_id,
    CAST(b.order_purchase_timestamp AS DATE) AS order_date,
    b.order_status,
    b.is_delivered,

    COALESCE(ia.order_gmv_items, 0) AS gmv_items,
    COALESCE(ia.order_freight,   0) AS order_freight,
    COALESCE(ia.order_gmv_items, 0) + COALESCE(ia.order_freight, 0) AS gmv_total,
    COALESCE(pa.order_payment,   0) AS payment_value,
    COALESCE(ia.order_qty,       0) AS order_qty,

    -- 时效派生：缺失不填补，is_delivered=FALSE 时自然为 NULL
    epoch(CAST(o.order_delivered_customer_date AS TIMESTAMP) - b.order_purchase_timestamp) / 86400.0 AS delivery_days,
    epoch(CAST(o.order_estimated_delivery_date AS TIMESTAMP) - b.order_purchase_timestamp) / 86400.0 AS estimated_days,
    (epoch(CAST(o.order_delivered_customer_date AS TIMESTAMP) - b.order_purchase_timestamp) / 86400.0)
      - (epoch(CAST(o.order_estimated_delivery_date AS TIMESTAMP) - b.order_purchase_timestamp) / 86400.0) AS delay_days,
    CASE WHEN b.is_delivered
         THEN (epoch(CAST(o.order_delivered_customer_date AS TIMESTAMP) - b.order_purchase_timestamp) / 86400.0)
            > (epoch(CAST(o.order_estimated_delivery_date AS TIMESTAMP) - b.order_purchase_timestamp) / 86400.0)
         ELSE NULL END AS is_late,

    rv.review_score,
    mp.main_payment_type,
    mp.main_payment_installments,

    EXTRACT(hour FROM b.order_purchase_timestamp) AS purchase_hour,
    ISODOW(b.order_purchase_timestamp)            AS purchase_weekday,
    CASE WHEN EXTRACT(hour FROM b.order_purchase_timestamp) < 6  THEN '00 凌晨(0-6)'
         WHEN EXTRACT(hour FROM b.order_purchase_timestamp) < 12 THEN '01 上午(6-12)'
         WHEN EXTRACT(hour FROM b.order_purchase_timestamp) < 18 THEN '02 下午(12-18)'
         ELSE '03 晚间(18-24)' END AS purchase_time_slot,

    (CAST(b.order_purchase_timestamp AS DATE)
        = CAST(fp.first_purchase_date AS DATE)) AS is_new_customer
FROM base b
JOIN raw.orders o ON o.order_id = b.order_id
LEFT JOIN clean.order_item_agg      ia ON ia.order_id = b.order_id
LEFT JOIN clean.order_payment_agg   pa ON pa.order_id = b.order_id
LEFT JOIN clean.order_main_payment  mp ON mp.order_id = b.order_id
LEFT JOIN clean.order_review_one    rv ON rv.order_id = b.order_id
LEFT JOIN clean.customer_first_purchase fp ON fp.customer_unique_id = b.customer_unique_id;

-- ---------------------------------------------------------------- 7. 事实表：明细粒度
CREATE OR REPLACE TABLE clean.fact_order_items AS
SELECT
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    o.customer_id,
    c.customer_unique_id,
    CAST(strftime(CAST(o.order_purchase_timestamp AS DATE), '%Y%m%d') AS INTEGER) AS date_id,
    CAST(o.order_purchase_timestamp AS DATE) AS order_date,
    (o.order_status = 'delivered') AS is_delivered,
    i.price,
    i.freight_value,
    i.price + i.freight_value AS item_total
FROM raw.order_items i
LEFT JOIN raw.orders o    ON o.order_id    = i.order_id
LEFT JOIN raw.customers c ON c.customer_id = o.customer_id;
