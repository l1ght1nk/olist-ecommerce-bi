-- ============================================================================
-- 04_advanced.sql  ——  窗口函数 / 同期群 / 漏斗进阶分析
-- ----------------------------------------------------------------------------
-- 这一层覆盖进阶分析能力（窗口函数、同期群留存、漏斗转化等）：
--   ROW_NUMBER 分组取 TopN   LAG/LEAD 环比同比   RANK/DENSE_RANK 排名
--   SUM() OVER 累计（帕累托） ROWS BETWEEN 移动平均   NTILE 分箱（RFM）
--   自连接 + 月份差（同期群留存）   漏斗转化
-- ============================================================================

-- ---------------------------------------------------------------- 1. 品类帕累托
-- 累计求和窗口：SUM(gmv) OVER (ORDER BY gmv DESC ROWS UNBOUNDED PRECEDING)
CREATE OR REPLACE TABLE analysis.pareto_category AS
WITH cat AS (
    SELECT
        p.product_category_name_english AS category,
        SUM(i.price) AS gmv
    FROM clean.fact_order_items i
    JOIN clean.dim_product p ON p.product_id = i.product_id
    WHERE i.is_delivered
    GROUP BY 1
),
calc AS (
    SELECT
        category,
        gmv,
        SUM(gmv) OVER (ORDER BY gmv DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_gmv,
        SUM(gmv) OVER () AS total_gmv,
        ROW_NUMBER() OVER (ORDER BY gmv DESC) AS rank_no
    FROM cat
)
SELECT
    rank_no,
    category,
    ROUND(gmv, 2) AS gmv,
    ROUND(cum_gmv, 2) AS cum_gmv,
    ROUND(cum_gmv / total_gmv * 100, 2) AS cum_pct
FROM calc
ORDER BY rank_no;

-- ---------------------------------------------------------------- 2. 每个品类 TOP3 商品
-- 分组排名窗口：ROW_NUMBER() OVER (PARTITION BY category ORDER BY gmv DESC)
CREATE OR REPLACE TABLE analysis.top3_product_per_category AS
WITH prod AS (
    SELECT
        p.product_category_name_english AS category,
        i.product_id,
        SUM(i.price) AS gmv,
        COUNT(*)     AS qty
    FROM clean.fact_order_items i
    JOIN clean.dim_product p ON p.product_id = i.product_id
    WHERE i.is_delivered
    GROUP BY 1, 2
)
SELECT category, product_id, ROUND(gmv, 2) AS gmv, qty, rn AS rank_in_category
FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY category ORDER BY gmv DESC) AS rn
    FROM prod
) t
WHERE rn <= 3
ORDER BY category, rn;

-- ---------------------------------------------------------------- 3. 月度 GMV 环比 / 同比
-- 前后行取值窗口：LAG / LEAD
CREATE OR REPLACE TABLE analysis.monthly_gmv_mom AS
WITH m AS (
    SELECT
        d.year_month,
        SUM(f.gmv_total) AS gmv,
        COUNT(*)         AS orders
    FROM clean.fact_orders f
    JOIN clean.dim_date d ON d.date_id = f.date_id
    WHERE f.is_delivered AND d.is_complete_month
    GROUP BY 1
)
SELECT
    year_month,
    ROUND(gmv, 2)    AS gmv,
    orders,
    ROUND(LAG(gmv)    OVER (ORDER BY year_month), 2) AS prev_month_gmv,
    ROUND((gmv - LAG(gmv) OVER (ORDER BY year_month))
          / LAG(gmv) OVER (ORDER BY year_month) * 100, 2) AS mom_pct,
    ROUND(LAG(gmv, 12) OVER (ORDER BY year_month), 2) AS same_month_last_year,
    ROUND(AVG(gmv) OVER (ORDER BY year_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS ma3
FROM m
ORDER BY year_month;

-- ---------------------------------------------------------------- 4. 州 GMV 排名
CREATE OR REPLACE TABLE analysis.state_rank AS
WITH s AS (
    SELECT
        c.customer_state,
        SUM(f.gmv_total) AS gmv
    FROM clean.fact_orders f
    JOIN clean.dim_customer c ON c.customer_unique_id = f.customer_unique_id
    WHERE f.is_delivered
    GROUP BY 1
)
SELECT
    customer_state,
    ROUND(gmv, 2) AS gmv,
    RANK()       OVER (ORDER BY gmv DESC) AS rnk,
    DENSE_RANK() OVER (ORDER BY gmv DESC) AS dense_rnk,
    ROUND(PERCENT_RANK() OVER (ORDER BY gmv) * 100, 1) AS pct_rank,
    RANK() OVER (ORDER BY gmv DESC) = 1 AS is_top1
FROM s
ORDER BY rnk;

-- ---------------------------------------------------------------- 5. RFM 分群
-- NTILE 分箱 + 业务映射（复购率仅 3%，F 用等频分位会错分，改业务规则）
CREATE OR REPLACE TABLE analysis.rfm_segment AS
WITH cust AS (
    SELECT
        f.customer_unique_id,
        date_diff('day', MAX(f.order_date), DATE '2018-10-17')            AS recency,
        COUNT(*)                                                          AS frequency,
        SUM(f.gmv_total)                                                  AS monetary
    FROM clean.fact_orders f
    WHERE f.is_delivered
    GROUP BY 1
),
scored AS (
    SELECT
        *,
        NTILE(5) OVER (ORDER BY recency DESC)  AS r_score,   -- 越近分越高
        CASE WHEN frequency = 1 THEN 1
             WHEN frequency = 2 THEN 3
             ELSE 5 END                        AS f_score,   -- 业务映射，非等频分位
        NTILE(5) OVER (ORDER BY monetary)      AS m_score
    FROM cust
)
SELECT
    customer_unique_id,
    recency, frequency, ROUND(monetary, 2) AS monetary,
    r_score, f_score, m_score,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 THEN '01 冠军客户'
        WHEN r_score >= 4 AND f_score <= 2 THEN '02 新客'
        WHEN r_score <= 2 AND f_score >= 4 THEN '03 高价值流失'
        WHEN r_score <= 2 AND f_score <= 2 THEN '04 流失低价值'
        WHEN f_score >= 4                  THEN '05 高频忠诚'
        ELSE '06 一般维持'
    END AS rfm_segment
FROM scored
ORDER BY monetary DESC;

-- ---------------------------------------------------------------- 6. 同期群留存
-- 自连接 + 月份差算 cohort_index，再看每个 cohort 在第 N 月的留存率
CREATE OR REPLACE TABLE analysis.cohort_retention AS
WITH first_month AS (
    SELECT
        f.customer_unique_id,
        MIN(CAST(YEAR(f.order_date) * 12 + MONTH(f.order_date) AS INTEGER)) AS cohort_m
    FROM clean.fact_orders f
    WHERE f.is_delivered
    GROUP BY 1
),
activity AS (
    SELECT DISTINCT
        f.customer_unique_id,
        CAST(YEAR(f.order_date) * 12 + MONTH(f.order_date) AS INTEGER) AS activity_m
    FROM clean.fact_orders f
    WHERE f.is_delivered
),
joined AS (
    SELECT
        fm.cohort_m,
        fm.customer_unique_id,
        a.activity_m - fm.cohort_m AS cohort_index
    FROM first_month fm
    JOIN activity a ON a.customer_unique_id = fm.customer_unique_id
),
sized AS (
    SELECT cohort_m, cohort_index, COUNT(DISTINCT customer_unique_id) AS users
    FROM joined
    GROUP BY 1, 2
)
SELECT
    -- cohort_m 是 YEAR*12+MONTH 的整数编码，还原成可读的年月
    CAST(CASE WHEN cohort_m % 12 = 0 THEN cohort_m // 12 - 1
              ELSE cohort_m // 12 END AS VARCHAR)
        || '-' || printf('%02d', CASE WHEN cohort_m % 12 = 0 THEN 12
                                      ELSE cohort_m % 12 END)      AS cohort_month,
    cohort_index,
    users,
    MAX(users) OVER (PARTITION BY cohort_m)                           AS cohort_size,
    ROUND(users * 100.0 / MAX(users) OVER (PARTITION BY cohort_m), 2) AS retention_pct
FROM sized
ORDER BY cohort_m, cohort_index;

-- ---------------------------------------------------------------- 7. 复购漏斗
CREATE OR REPLACE TABLE analysis.repurchase_funnel AS
WITH cust AS (
    SELECT customer_unique_id, COUNT(*) AS orders
    FROM clean.fact_orders
    WHERE is_delivered
    GROUP BY 1
)
SELECT
    step_no,
    step_name,
    users,
    ROUND(users * 100.0 / MAX(users) OVER (), 2) AS pct_of_total
FROM (
    SELECT 1 AS step_no, '下单客户' AS step_name, COUNT(*) AS users FROM cust
    UNION ALL
    SELECT 2, '购买 2 单及以上', COUNT(*) FROM cust WHERE orders >= 2
    UNION ALL
    SELECT 3, '购买 3 单及以上', COUNT(*) FROM cust WHERE orders >= 3
    UNION ALL
    SELECT 4, '购买 5 单及以上', COUNT(*) FROM cust WHERE orders >= 5
) t
ORDER BY step_no;

-- ---------------------------------------------------------------- 8. 卖家集中度（帕累托变体）
CREATE OR REPLACE TABLE analysis.seller_concentration AS
WITH seller AS (
    SELECT i.seller_id, SUM(i.price) AS gmv
    FROM clean.fact_order_items i
    WHERE i.is_delivered
    GROUP BY 1
),
ranked AS (
    SELECT
        seller_id,
        gmv,
        ROW_NUMBER() OVER (ORDER BY gmv DESC) AS rn,
        COUNT(*)    OVER ()                   AS seller_cnt,
        SUM(gmv)    OVER ()                   AS total_gmv
    FROM seller
)
SELECT
    MAX(seller_cnt)                                                      AS active_sellers,
    CAST(FLOOR(MAX(seller_cnt) * 0.1) AS INTEGER)                        AS top10pct_sellers,
    ROUND(SUM(CASE WHEN rn <= FLOOR(seller_cnt * 0.1) THEN gmv ELSE 0 END), 2) AS top10pct_gmv,
    ROUND(MAX(total_gmv), 2)                                             AS total_gmv,
    ROUND(SUM(CASE WHEN rn <= FLOOR(seller_cnt * 0.1) THEN gmv ELSE 0 END)
          / MAX(total_gmv) * 100, 2)                                     AS top10pct_share_pct
FROM ranked;

-- ---------------------------------------------------------------- 9. 每日订单 7 日移动平均
CREATE OR REPLACE TABLE analysis.daily_orders_ma7 AS
WITH d AS (
    SELECT f.order_date, COUNT(*) AS orders
    FROM clean.fact_orders f
    WHERE f.is_delivered
    GROUP BY 1
)
SELECT
    order_date,
    orders,
    ROUND(AVG(orders) OVER (ORDER BY order_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 1) AS ma7
FROM d
ORDER BY order_date;
