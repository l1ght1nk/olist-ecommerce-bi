# -*- coding: utf-8 -*-
"""
Olist 电商数据分析 —— 阶段二：数据清洗与星型模型构建
输出：output/ 下可直接导入 Power BI 的维度表与事实表 CSV + 数据质量报告

模型设计：
  fact_orders        订单粒度（1 行 = 1 订单）       —— AOV/ARPU/交付/复购/DAU 等指标口径
  fact_order_items   订单明细粒度（1 行 = 1 商品行） —— 商品/品类/卖家指标口径
  dim_date           日期维度（2016-01-01 ~ 2018-12-31）
  dim_customer       客户维度（真实客户 customer_unique_id 粒度，含 RFM 与新客首单属性）
  dim_product        产品维度（含品类英文名翻译）
  dim_seller         卖家维度
  dim_geolocation    地理维度（邮编前缀聚合，用于地图）
"""
import pandas as pd
import numpy as np
import os, json, io

SRC = r"D:\迅雷下载\archive"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
os.makedirs(OUT, exist_ok=True)

log = io.StringIO()
def P(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    print(s, file=log)

# ---------------------------------------------------------------- 1. 读取原始数据
P("=" * 70)
P("1. 读取原始数据")
customers  = pd.read_csv(f"{SRC}/olist_customers_dataset.csv")
geo        = pd.read_csv(f"{SRC}/olist_geolocation_dataset.csv")
items      = pd.read_csv(f"{SRC}/olist_order_items_dataset.csv")
payments   = pd.read_csv(f"{SRC}/olist_order_payments_dataset.csv")
reviews    = pd.read_csv(f"{SRC}/olist_order_reviews_dataset.csv")
orders     = pd.read_csv(f"{SRC}/olist_orders_dataset.csv")
products   = pd.read_csv(f"{SRC}/olist_products_dataset.csv")
sellers    = pd.read_csv(f"{SRC}/olist_sellers_dataset.csv")
cat_tr     = pd.read_csv(f"{SRC}/product_category_name_translation.csv")
P(f"原始行数：orders={len(orders)} items={len(items)} customers={len(customers)} "
  f"products={len(products)} sellers={len(sellers)} reviews={len(reviews)} payments={len(payments)} geo={len(geo)}")

qc = []   # 数据质量记录
def note(step, issue, rows, action):
    qc.append({'环节': step, '问题': issue, '影响行数': int(rows), '处理方式': action})

# ---------------------------------------------------------------- 2. 字段类型与命名规范化
P("\n" + "=" * 70)
P("2. 字段类型与命名规范化")

# 2.1 列名去 BOM / 首尾空格（原表存在 product_description_lenght 等拼写错误，保留原样但重命名）
for df in [customers, geo, items, payments, reviews, orders, products, sellers, cat_tr]:
    df.columns = [c.strip().lstrip('﻿') for c in df.columns]
products = products.rename(columns={
    'product_name_lenght': 'product_name_length',
    'product_description_lenght': 'product_description_length',
})
P("  列名规范化完成（修正 product_name_lenght / product_description_lenght 拼写）")

# 2.2 日期字段转 datetime
date_cols = ['order_purchase_timestamp', 'order_approved_at', 'order_delivered_carrier_date',
             'order_delivered_customer_date', 'order_estimated_delivery_date']
for c in date_cols:
    orders[c] = pd.to_datetime(orders[c], errors='coerce')
items['shipping_limit_date'] = pd.to_datetime(items['shipping_limit_date'], errors='coerce')
reviews['review_creation_date'] = pd.to_datetime(reviews['review_creation_date'], errors='coerce')
reviews['review_answer_timestamp'] = pd.to_datetime(reviews['review_answer_timestamp'], errors='coerce')
P("  日期字段转 datetime 完成")

# ---------------------------------------------------------------- 3. 数据质量检查与清洗
P("\n" + "=" * 70)
P("3. 数据质量检查与清洗")

# 3.1 缺失值
P("\n-- 3.1 缺失值检查")
miss_summary = []
for name, df in [('orders', orders), ('items', items), ('customers', customers), ('products', products),
                 ('sellers', sellers), ('reviews', reviews), ('payments', payments)]:
    m = df.isna().sum()
    m = m[m > 0]
    for col, v in m.items():
        miss_summary.append(f"{name}.{col}: {v} 行缺失 ({v/len(df)*100:.2f}%)")
        P(f"  {name}.{col}: {v} 行缺失 ({v/len(df)*100:.2f}%)")
if not miss_summary:
    P("  无缺失")

# 3.2 订单交付日期缺失 —— 属于业务状态（未送达），不填补，用状态标记
undelivered_missing = orders['order_delivered_customer_date'].isna().sum()
note('订单表', 'order_delivered_customer_date 缺失', undelivered_missing,
     '不填补：非数据错误，是订单未送达的业务状态；派生 is_delivered 标志位区分')

# 3.3 products 品类缺失
prod_miss = products['product_category_name'].isna().sum()
products['product_category_name'] = products['product_category_name'].fillna('unknown')
note('商品表', 'product_category_name 缺失', prod_miss, '填充为 unknown，避免品类分析时静默丢行')

# 3.4 products 尺寸/重量异常（0 值）
for c in ['product_weight_g', 'product_length_cm', 'product_height_cm', 'product_width_cm']:
    products[c] = products[c].fillna(products[c].median())
zero_w = (products['product_weight_g'] == 0).sum()
note('商品表', 'product_weight_g = 0（不可能为 0 的物理量）', zero_w,
     f'保留原值但标记异常，体积/重量分析时过滤；缺失的 {products["product_weight_g"].isna().sum()} 行用中位数填充')

# 3.5 重复值
P("\n-- 3.2 重复值检查")
dup_orders = orders.duplicated(['order_id']).sum()
dup_items = items.duplicated(['order_id', 'order_item_id']).sum()
dup_cust = customers.duplicated(['customer_id']).sum()
P(f"  orders.order_id 重复={dup_orders}  items(order_id+item_id) 重复={dup_items}  customers.customer_id 重复={dup_cust}")
note('主键', '主键重复检查', dup_orders + dup_items + dup_cust, '无重复，主键唯一性成立')

# 3.6 异常值：金额
P("\n-- 3.3 异常值检查（金额）")
P(f"  price: min={items['price'].min()} max={items['price'].max()} "
  f"P99={items['price'].quantile(0.99):.2f}")
P(f"  freight_value: min={items['freight_value'].min()} max={items['freight_value'].max()} "
  f"P99={items['freight_value'].quantile(0.99):.2f}")
zero_price = (items['price'] <= 0).sum()
note('订单明细', 'price <= 0 的异常记录', zero_price, '保留（Olist 存在 0.85 雷亚尔的极低单价商品，属正常长尾，不做截断）')
note('订单明细', 'price 长尾极值（最高 6735 雷亚尔）', (items['price'] > items['price'].quantile(0.99)).sum(),
     '不删除：真实高价商品；建议看板用中位数/均值对比，避免极值扭曲图形')

# 3.7 无明细订单
orders_with_items = set(items['order_id'])
no_item = (~orders['order_id'].isin(orders_with_items)).sum()
note('订单表', '订单存在但无任何商品明细', no_item, '保留在 fact_orders（用于交付完成率分母），明细表自然不包含')

# 3.8 评论：一个订单多条评论
dup_rev = reviews.groupby('order_id').size()
note('评论表', '同一订单存在多条评论', (dup_rev > 1).sum(),
     '按订单聚合：取最新一条评论的评分，避免订单级指标被重复计数')

# 3.9 支付：一个订单多笔支付
dup_pay = payments.groupby('order_id').size()
note('支付表', '同一订单存在多笔支付（分期/混合支付）', (dup_pay > 1).sum(),
     '订单级汇总 payment_value；主支付方式取金额最大的那一笔，避免支付方式占比重复计数')

# 3.10 时间窗完整性
orders['ym'] = orders['order_purchase_timestamp'].dt.to_period('M')
monthly_cnt = orders.groupby('ym').size()
P("\n-- 3.4 时间窗完整性")
P(f"  数据时间跨度：{orders['order_purchase_timestamp'].min()} ~ {orders['order_purchase_timestamp'].max()}")
# 完整月：从第一个月订单量 >=500 的月份，到最后一个月订单量 >=500 的月份之间的区间
valid = monthly_cnt[monthly_cnt >= 500]
m_start, m_end = valid.index.min(), valid.index.max()
complete = set(pd.period_range(m_start, m_end, freq='M'))
thin = monthly_cnt[~monthly_cnt.index.isin(complete)]
P(f"  完整月区间：{m_start} ~ {m_end}")
P(f"  样本量异常月份（平台爬坡期 / 数据截断）：{[f'{i}({monthly_cnt[i]}单)' for i in thin.index]}")
note('时间维度', f'首尾月份样本不完整（{m_start} 之前为爬坡期，{m_end} 之后数据截断）', int(thin.sum()),
     '在 dim_date 增加 is_complete_month 标志，趋势分析默认只看完整月，避免误判为业务下滑')

# ---------------------------------------------------------------- 4. 构建维度表
P("\n" + "=" * 70)
P("4. 构建维度表")

# ---- dim_date：覆盖 2016-01-01 ~ 2018-12-31
d0, d1 = pd.Timestamp('2016-01-01'), pd.Timestamp('2018-12-31')
dim_date = pd.DataFrame({'date': pd.date_range(d0, d1, freq='D')})
dim_date['date_id'] = dim_date['date'].dt.strftime('%Y%m%d').astype(int)
dim_date['year'] = dim_date['date'].dt.year
dim_date['quarter'] = dim_date['date'].dt.quarter
dim_date['month'] = dim_date['date'].dt.month
dim_date['month_name'] = dim_date['date'].dt.strftime('%b')
dim_date['year_month'] = dim_date['date'].dt.strftime('%Y-%m')
dim_date['day'] = dim_date['date'].dt.day
dim_date['weekday'] = dim_date['date'].dt.weekday + 1
dim_date['weekday_name'] = dim_date['date'].dt.strftime('%a')
dim_date['is_weekend'] = dim_date['weekday'].isin([6, 7])
# 完整月标志（由下方时间窗检查确定的 complete 集合填充）
dim_date['ym'] = dim_date['date'].dt.to_period('M')
dim_date['is_complete_month'] = dim_date['ym'].isin(complete)
dim_date = dim_date.drop(columns=['ym'])
P(f"  dim_date: {len(dim_date)} 行 ({d0.date()} ~ {d1.date()})")

# ---- dim_customer：以 customer_unique_id 为真实客户粒度
cust = customers.merge(
    orders[['order_id', 'customer_id', 'order_purchase_timestamp']], on='customer_id', how='left')
cust = cust[cust['order_purchase_timestamp'].notna()]
first_purchase = cust.groupby('customer_unique_id')['order_purchase_timestamp'].min().rename('first_purchase_date')
# RFM 基准日：数据集最后一天
T = orders['order_purchase_timestamp'].max()
P(f"\n  RFM 基准日（数据集最后一天）= {T}")

# 订单级金额先算好，供 RFM 使用
pay_agg = payments.groupby('order_id')['payment_value'].sum().rename('order_payment')
item_agg = items.groupby('order_id').agg(
    order_gmv_items=('price', 'sum'),
    order_freight=('freight_value', 'sum'),
    order_qty=('order_item_id', 'count')).reset_index()
orders = orders.merge(pay_agg, on='order_id', how='left').merge(item_agg, on='order_id', how='left')
# 订单表补上真实客户标识（customer_unique_id）—— 复购 / RFM / 新老客分析必须用它，而非 customer_id
orders = orders.merge(customers[['customer_id', 'customer_unique_id']], on='customer_id', how='left')
orders['order_payment'] = orders['order_payment'].fillna(0)
orders['order_gmv_items'] = orders['order_gmv_items'].fillna(0)
orders['order_freight'] = orders['order_freight'].fillna(0)

# 只保留已交付订单做收入类 RFM（未送达订单不计入消费）
o_del = orders[orders['order_status'] == 'delivered']
rfm = o_del.groupby('customer_unique_id').agg(
    last_purchase_date=('order_purchase_timestamp', 'max'),
    frequency=('order_id', 'nunique'),
    monetary=('order_payment', 'sum')).reset_index()
rfm['recency_days'] = (T - rfm['last_purchase_date']).dt.days
# R / M 用五分位（连续型变量，分位有效）
rfm['R_score'] = pd.qcut(rfm['recency_days'], 5, labels=[5, 4, 3, 2, 1]).astype(int)   # 越近分越高
rfm['M_score'] = pd.qcut(rfm['monetary'].rank(method='first'), 5, labels=[1, 2, 3, 4, 5]).astype(int)
# F 不能用分位：Olist 复购率仅约 3%，frequency 96% 以上为 1，等频切分会把"同样只买 1 单"的客户硬分层
# 改为按业务含义映射：1 单=1 分，2 单=3 分，3 单及以上=5 分
rfm['F_score'] = rfm['frequency'].map(lambda f: 1 if f <= 1 else (3 if f == 2 else 5))
rfm['RFM_cell'] = rfm['R_score'].astype(str) + rfm['F_score'].astype(str) + rfm['M_score'].astype(str)

def seg(r):
    R, M, F = r['R_score'], r['M_score'], r['F_score']
    if R >= 4 and (M >= 4 or F >= 3): return '01 冠军客户'      # 近期有消费 且 金额高/有复购
    if R >= 4: return '02 近期新客'                              # 刚来过但金额一般
    if R == 3 and M >= 4: return '03 需唤醒的高价值客户'
    if R == 3: return '04 稳定客户'
    if R <= 2 and M >= 4: return '05 高价值流失'
    return '06 低价值流失'
rfm['RFM_segment'] = rfm.apply(seg, axis=1)
note('客户维度', 'frequency 高度偏态（复购率仅约 3%，96% 客户只有 1 单）',
     int((rfm['frequency'] <= 1).sum()),
     'RFM 的 F 不使用等频分位（会把同为 1 单的客户错误分层），改为业务映射：1单=1分/2单=3分/3单+=5分；分群以 R 与 M 为主')

dim_customer = (customers[['customer_id', 'customer_unique_id', 'customer_zip_code_prefix',
                           'customer_city', 'customer_state']]
                .merge(first_purchase, on='customer_unique_id', how='left'))
# 客户级属性（唯一客户粒度）
cust_uni = (cust.groupby('customer_unique_id')
            .agg(customer_state=('customer_state', 'first'),
                 customer_city=('customer_city', 'first'),
                 customer_zip_code_prefix=('customer_zip_code_prefix', 'first'),
                 order_count=('order_id', 'nunique')).reset_index())
cust_uni = cust_uni.merge(first_purchase.reset_index(), on='customer_unique_id', how='left')
cust_uni = cust_uni.merge(rfm[['customer_unique_id', 'last_purchase_date', 'frequency', 'monetary',
                               'recency_days', 'R_score', 'F_score', 'M_score', 'RFM_segment']],
                          on='customer_unique_id', how='left')
cust_uni['frequency'] = cust_uni['frequency'].fillna(0).astype(int)
cust_uni['monetary'] = cust_uni['monetary'].fillna(0)
cust_uni['is_repeat'] = cust_uni['frequency'] >= 2
cust_uni['RFM_segment'] = cust_uni['RFM_segment'].fillna('07 无已交付订单')
cust_uni['recency_days'] = cust_uni['recency_days'].fillna(-1)
for c in ['R_score', 'F_score', 'M_score']:
    cust_uni[c] = cust_uni[c].fillna(0).astype(int)
cust_uni = cust_uni.rename(columns={'frequency': 'delivered_orders', 'monetary': 'total_spend'})
P(f"  dim_customer(unique 粒度): {len(cust_uni)} 行，复购客户 {int(cust_uni['is_repeat'].sum())} 人 "
  f"(复购率 {cust_uni['is_repeat'].mean()*100:.2f}%)")

# ---- dim_product
dim_product = products.merge(cat_tr, on='product_category_name', how='left')
dim_product['product_category_name_english'] = dim_product['product_category_name_english'].fillna('unknown')
dim_product['product_volume_cm3'] = (dim_product['product_length_cm'] * dim_product['product_height_cm']
                                     * dim_product['product_width_cm'])
# 页面内容分档（用户要求：商品页面内容分析）
dim_product['photo_qty_band'] = pd.cut(dim_product['product_photos_qty'],
                                       bins=[-1, 1, 2, 3, 5, 100],
                                       labels=['0-1张', '2张', '3张', '4-5张', '6张以上'])
dim_product['desc_len_band'] = pd.cut(dim_product['product_description_length'],
                                      bins=[-1, 200, 500, 1000, 2000, 100000],
                                      labels=['极简(<200)', '简短(200-500)', '中等(500-1k)', '详细(1k-2k)', '非常详细(>2k)'])
P(f"  dim_product: {len(dim_product)} 行，{dim_product['product_category_name_english'].nunique()} 个品类（英文）")

# ---- dim_seller
dim_seller = sellers.rename(columns={'seller_zip_code_prefix': 'seller_zip_code_prefix',
                                     'seller_city': 'seller_city', 'seller_state': 'seller_state'})
P(f"  dim_seller: {len(dim_seller)} 行")

# ---- dim_geolocation：邮编前缀聚合（100 万行 → 1.9 万行）
dim_geo = (geo.groupby('geolocation_zip_code_prefix')
           .agg(geo_lat=('geolocation_lat', 'median'),
                geo_lng=('geolocation_lng', 'median'),
                geo_city=('geolocation_city', lambda s: s.mode().iloc[0] if len(s.mode()) else s.iloc[0]),
                geo_state=('geolocation_state', lambda s: s.mode().iloc[0] if len(s.mode()) else s.iloc[0]))
           .reset_index())
note('地理表', 'geolocation 原始 100 万行，同一邮编前缀存在多个经纬度点（重复 98.1 万行）',
     981148, '按邮编前缀聚合并取经纬度中位数、城市/州取众数，压缩至 1.9 万行')
P(f"  dim_geolocation: {len(dim_geo)} 行（由 1,000,163 行聚合）")

# ---------------------------------------------------------------- 5. 构建事实表
P("\n" + "=" * 70)
P("5. 构建事实表")

# ---- fact_orders（订单粒度）
fo = orders.copy()
# 主支付方式：金额最大的一笔
pay_sorted = payments.sort_values('payment_value', ascending=False)
main_pay = pay_sorted.drop_duplicates('order_id')[['order_id', 'payment_type', 'payment_installments']]
main_pay = main_pay.rename(columns={'payment_type': 'main_payment_type',
                                    'payment_installments': 'main_payment_installments'})
fo = fo.merge(main_pay, on='order_id', how='left')
# 评论：每个订单取最新一条
rev_sorted = reviews.sort_values('review_answer_timestamp', ascending=False)
rev_one = rev_sorted.drop_duplicates('order_id')[['order_id', 'review_score']]
fo = fo.merge(rev_one.rename(columns={'review_score': 'review_score'}), on='order_id', how='left')

# 首单信息（customer_unique_id 已在 orders 中）
fo = fo.merge(first_purchase.rename('first_purchase_date'), on='customer_unique_id', how='left')
fo['is_new_customer'] = (fo['order_purchase_timestamp'].dt.normalize()
                         == fo['first_purchase_date'].dt.normalize())

# 派生：交付与时效
fo['is_delivered'] = fo['order_status'] == 'delivered'
fo['delivery_days'] = (fo['order_delivered_customer_date'] - fo['order_purchase_timestamp']).dt.total_seconds() / 86400
fo['estimated_days'] = (fo['order_estimated_delivery_date'] - fo['order_purchase_timestamp']).dt.total_seconds() / 86400
fo['delay_days'] = fo['delivery_days'] - fo['estimated_days']
fo['is_late'] = fo['delay_days'] > 0
fo['is_late'] = fo['is_late'].where(fo['is_delivered'], np.nan)
fo['purchase_hour'] = fo['order_purchase_timestamp'].dt.hour
fo['purchase_weekday'] = fo['order_purchase_timestamp'].dt.weekday + 1
def tod(h):
    if 0 <= h < 6: return '00 凌晨(0-6)'
    if 6 <= h < 12: return '01 上午(6-12)'
    if 12 <= h < 18: return '02 下午(12-18)'
    return '03 晚间(18-24)'
fo['purchase_time_slot'] = fo['purchase_hour'].apply(tod)

fo['order_date'] = fo['order_purchase_timestamp'].dt.normalize()
fo['date_id'] = fo['order_date'].dt.strftime('%Y%m%d').astype(int)
fo['order_gmv'] = fo['order_gmv_items'] + fo['order_freight']

fact_orders = fo[[
    'order_id', 'customer_id', 'customer_unique_id', 'date_id', 'order_date',
    'order_status', 'is_delivered', 'order_gmv_items', 'order_freight', 'order_gmv',
    'order_payment', 'order_qty', 'delivery_days', 'estimated_days', 'delay_days', 'is_late',
    'review_score', 'main_payment_type', 'main_payment_installments',
    'purchase_hour', 'purchase_weekday', 'purchase_time_slot', 'is_new_customer'
]].rename(columns={'order_gmv_items': 'gmv_items', 'order_gmv': 'gmv_total', 'order_payment': 'payment_value'})
P(f"  fact_orders: {len(fact_orders)} 行，{fact_orders['order_id'].nunique()} 个订单")

# ---- fact_order_items（明细粒度）
foi = items.merge(orders[['order_id', 'customer_id', 'order_purchase_timestamp', 'order_status',
                          'order_delivered_customer_date', 'order_estimated_delivery_date']],
                  on='order_id', how='left')
foi = foi.merge(customers[['customer_id', 'customer_unique_id', 'customer_state', 'customer_city']],
                on='customer_id', how='left')
foi['order_date'] = foi['order_purchase_timestamp'].dt.normalize()
foi['date_id'] = foi['order_date'].dt.strftime('%Y%m%d').astype(int)
foi['is_delivered'] = foi['order_status'] == 'delivered'
foi['item_total'] = foi['price'] + foi['freight_value']
fact_order_items = foi[[
    'order_id', 'order_item_id', 'product_id', 'seller_id', 'customer_id', 'customer_unique_id',
    'date_id', 'order_date', 'is_delivered', 'price', 'freight_value', 'item_total'
]]
P(f"  fact_order_items: {len(fact_order_items)} 行")

# ---------------------------------------------------------------- 6. 导出
P("\n" + "=" * 70)
P("6. 导出 CSV（utf-8-sig，Power BI 中文不乱码）")
tables = {
    'dim_date': dim_date,
    'dim_customer': cust_uni,
    'dim_product': dim_product,
    'dim_seller': dim_seller,
    'dim_geolocation': dim_geo,
    'fact_orders': fact_orders,
    'fact_order_items': fact_order_items,
}
for name, df in tables.items():
    p = os.path.join(OUT, f'{name}.csv')
    df.to_csv(p, index=False, encoding='utf-8-sig')
    P(f"  {name}.csv  {len(df):>8,} 行 × {df.shape[1]} 列  ({os.path.getsize(p)/1024/1024:.1f} MB)")

# 数据质量报告
pd.DataFrame(qc).to_csv(os.path.join(OUT, '数据质量与清洗记录.csv'), index=False, encoding='utf-8-sig')
P("\n  数据质量与清洗记录.csv 已导出")

# 关键口径快照
snap = {
    '数据时间范围': [str(orders['order_purchase_timestamp'].min()), str(orders['order_purchase_timestamp'].max())],
    '总订单数': int(len(fact_orders)),
    '已交付订单数': int(fact_orders['is_delivered'].sum()),
    '交付完成率': round(float(fact_orders['is_delivered'].mean()) * 100, 2),
    '真实客户数(unique)': int(cust_uni.shape[0]),
    '复购率%': round(float(cust_uni['is_repeat'].mean()) * 100, 2),
    '总GMV(已交付,含运费)': round(float(fact_orders[fact_orders['is_delivered']]['gmv_total'].sum()), 2),
    'AOV客单价': round(float(fact_orders[fact_orders['is_delivered']]['gmv_total'].mean()), 2),
    'ARPU': round(float(fact_orders[fact_orders['is_delivered']]['gmv_total'].sum() / cust_uni.shape[0]), 2),
    '平均交付天数': round(float(fact_orders['delivery_days'].mean()), 2),
    '准时率%': round(float((fact_orders[fact_orders['is_delivered']]['is_late'] == False).mean()) * 100, 2),
    '平均评分': round(float(fact_orders['review_score'].mean()), 2),
    '订单明细行数': int(len(fact_order_items)),
    '品类数': int(dim_product['product_category_name_english'].nunique()),
    '卖家数': int(len(dim_seller)),
}
json.dump(snap, open(os.path.join(OUT, '口径快照.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
P("\n-- 关键口径快照")
for k, v in snap.items():
    P(f"  {k}: {v}")

open(os.path.join(os.path.dirname(OUT), '02_清洗建模日志.txt'), 'w', encoding='utf-8').write(log.getvalue())
P("\n完成。")
