-- ============================================================================
-- Olist 巴西电商运营分析 · SQL 复刻（DuckDB）
-- 01_load.sql  ——  原始数据接入层
-- ----------------------------------------------------------------------------
-- 数据源：Kaggle Olist Public Dataset（9 张原始 CSV，未做任何加工）
-- 目的：把 Python(pandas) 流水线 01~03 的清洗与建模全过程用 SQL 复刻一遍，
--       产出与 pandas 完全一致的指标，作为 SQL 能力的可复算证据。
-- 运行：python run_sql.py   （脚本会把 {{SRC}} 替换为实际数据目录）
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS raw;

-- 订单主表 99,441 行
CREATE OR REPLACE TABLE raw.orders AS
SELECT * FROM read_csv_auto('{{SRC}}/olist_orders_dataset.csv');

-- 订单明细（商品行）112,650 行
CREATE OR REPLACE TABLE raw.order_items AS
SELECT * FROM read_csv_auto('{{SRC}}/olist_order_items_dataset.csv');

-- 支付流水 103,886 行（一个订单可有多笔支付，需聚合到订单粒度）
CREATE OR REPLACE TABLE raw.order_payments AS
SELECT * FROM read_csv_auto('{{SRC}}/olist_order_payments_dataset.csv');

-- 评论 99,224 行（一个订单可能有多条评论，需去重）
CREATE OR REPLACE TABLE raw.order_reviews AS
SELECT * FROM read_csv_auto('{{SRC}}/olist_order_reviews_dataset.csv');

-- 客户 99,441 行（注意：customer_id 是订单级，customer_unique_id 才是真实客户）
CREATE OR REPLACE TABLE raw.customers AS
SELECT * FROM read_csv_auto('{{SRC}}/olist_customers_dataset.csv');

-- 商品 32,951 行
CREATE OR REPLACE TABLE raw.products AS
SELECT * FROM read_csv_auto('{{SRC}}/olist_products_dataset.csv');

-- 卖家 3,095 行
CREATE OR REPLACE TABLE raw.sellers AS
SELECT * FROM read_csv_auto('{{SRC}}/olist_sellers_dataset.csv');

-- 地理坐标 1,000,163 行（同一邮编重复数十次，需聚合压缩）
CREATE OR REPLACE TABLE raw.geolocation AS
SELECT * FROM read_csv_auto('{{SRC}}/olist_geolocation_dataset.csv');

-- 品类葡语 -> 英语翻译 71 行
CREATE OR REPLACE TABLE raw.category_translation AS
SELECT * FROM read_csv_auto('{{SRC}}/product_category_name_translation.csv');
