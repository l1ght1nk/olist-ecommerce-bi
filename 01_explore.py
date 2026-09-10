# -*- coding: utf-8 -*-
"""Olist 数据集探索性分析：摸清每张表的结构、粒度、缺失与主键"""
import pandas as pd, os, io, sys

SRC = r"D:\迅雷下载\archive"
out = io.StringIO()
pd.set_option('display.width', 200)

files = {
    'customers': 'olist_customers_dataset.csv',
    'geolocation': 'olist_geolocation_dataset.csv',
    'order_items': 'olist_order_items_dataset.csv',
    'payments': 'olist_order_payments_dataset.csv',
    'reviews': 'olist_order_reviews_dataset.csv',
    'orders': 'olist_orders_dataset.csv',
    'products': 'olist_products_dataset.csv',
    'sellers': 'olist_sellers_dataset.csv',
    'category_tr': 'product_category_name_translation.csv',
}

dfs = {}
for k, f in files.items():
    df = pd.read_csv(os.path.join(SRC, f))
    dfs[k] = df
    print(f"\n{'='*70}\n### {k}  shape={df.shape}", file=out)
    print("columns:", list(df.columns), file=out)
    miss = df.isna().mean().round(4) * 100
    print("missing%:\n", miss[miss > 0] if miss.sum() > 0 else "  无缺失", file=out)
    print(df.head(3).to_string(), file=out)

print(f"\n{'='*70}\n### 主键唯一性检查", file=out)
keys = {
    'customers': ['customer_id'],
    'orders': ['order_id'],
    'order_items': ['order_id', 'order_item_id'],
    'products': ['product_id'],
    'sellers': ['seller_id'],
    'geolocation': ['geolocation_zip_code_prefix'],
}
for t, ks in keys.items():
    n = len(dfs[t])
    u = dfs[t][ks].drop_duplicates().shape[0]
    print(f"{t}: {ks}  行数={n}  唯一组合={u}  重复={n-u}", file=out)

print(f"\n{'='*70}\n### orders 订单状态分布", file=out)
print(dfs['orders']['order_status'].value_counts(), file=out)

print(f"\n{'='*70}\n### orders 日期字段范围与缺失", file=out)
for c in [c for c in dfs['orders'].columns if 'date' in c or 'timestamp' in c]:
    s = pd.to_datetime(dfs['orders'][c], errors='coerce')
    print(f"{c}: 缺失={s.isna().sum()}  范围={s.min()} ~ {s.max()}", file=out)

print(f"\n{'='*70}\n### order_items 数值分布", file=out)
print(dfs['order_items'][['price', 'freight_value']].describe().to_string(), file=out)

print(f"\n{'='*70}\n### payments", file=out)
print(dfs['payments']['payment_type'].value_counts(), file=out)
print("每订单付款记录数分布:", dfs['payments'].groupby('order_id').size().value_counts().head().to_dict(), file=out)
print("payment_sequential 唯一性(用于检查同订单多笔):", dfs['payments'].duplicated(['order_id', 'payment_sequential']).sum(), file=out)

print(f"\n{'='*70}\n### reviews", file=out)
print(dfs['reviews']['review_score'].value_counts().sort_index(), file=out)
print("每订单评论数:", dfs['reviews'].groupby('order_id').size().value_counts().head().to_dict(), file=out)

print(f"\n{'='*70}\n### products 品类", file=out)
print("product_category_name 唯一数:", dfs['products']['product_category_name'].nunique(), file=out)
print(dfs['products'][['product_weight_g', 'product_length_cm', 'product_height_cm', 'product_width_cm']].describe().to_string(), file=out)

print(f"\n{'='*70}\n### customers 地理", file=out)
print("customer_state 分布:\n", dfs['customers']['customer_state'].value_counts().head(10), file=out)
print("customer_city 唯一:", dfs['customers']['customer_city'].nunique(), file=out)

print(f"\n{'='*70}\n### sellers 地理", file=out)
print("seller_state 分布:\n", dfs['sellers']['seller_state'].value_counts().head(10), file=out)

print(f"\n{'='*70}\n### geolocation", file=out)
g = dfs['geolocation']
print("zip prefix 唯一:", g['geolocation_zip_code_prefix'].nunique(), "行数:", len(g), file=out)
print(g['geolocation_state'].value_counts().head(10), file=out)

# 关联完整性
print(f"\n{'='*70}\n### 关联完整性", file=out)
oi = dfs['order_items']
o = dfs['orders']
print("order_items.order_id 在 orders 中缺失:", (~oi['order_id'].isin(o['order_id'])).sum(), file=out)
print("orders.order_id 在 order_items 中缺失:", (~o['order_id'].isin(oi['order_id'])).sum(), file=out)
print("orders.customer_id 在 customers 中缺失:", (~o['customer_id'].isin(dfs['customers']['customer_id'])).sum(), file=out)
print("order_items.product_id 在 products 中缺失:", (~oi['product_id'].isin(dfs['products']['product_id'])).sum(), file=out)
print("order_items.seller_id 在 sellers 中缺失:", (~oi['seller_id'].isin(dfs['sellers']['seller_id'])).sum(), file=out)

# 已交付订单时间跨度
d = pd.to_datetime(o['order_purchase_timestamp'], errors='coerce')
print("\n订单成交时间范围:", d.min(), "~", d.max(), file=out)
print("按月订单量(前12月):\n", d.dt.to_period('M').value_counts().sort_index().head(12), file=out)

open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '01_探查结果.txt'), 'w', encoding='utf-8').write(out.getvalue())
print(out.getvalue()[:3000])
print("...\n已写入 01_探查结果.txt")
