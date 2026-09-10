# -*- coding: utf-8 -*-
"""
Olist 电商数据分析 —— 阶段三：四大模块指标计算
模块1 运营指标 | 模块2 客户行为 | 模块3 商品指标 | 模块4 履约与卖家
输出：output/dashboard_data.json（供 HTML 看板直接使用）
"""
import pandas as pd, numpy as np, json, os

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, 'output')

fo = pd.read_csv(f"{OUT}/fact_orders.csv", parse_dates=['order_date'])
foi = pd.read_csv(f"{OUT}/fact_order_items.csv", parse_dates=['order_date'])
dp = pd.read_csv(f"{OUT}/dim_product.csv")
dc = pd.read_csv(f"{OUT}/dim_customer.csv")
ds = pd.read_csv(f"{OUT}/dim_seller.csv")
dd = pd.read_csv(f"{OUT}/dim_date.csv", parse_dates=['date'])

D = {}   # 结果容器
def L(*a): print(*a)

# 主分析口径：已交付订单
d = fo[fo['is_delivered']].copy()
L(f"分析口径：已交付订单 {len(d):,} 单 / 全量 {len(fo):,} 单")

# ============================================================ 模块1 运营指标
L("\n[模块1] 运营指标")
kpi = {
    'gmv': float(d['gmv_total'].sum()),
    'gmv_items': float(d['gmv_items'].sum()),
    'freight': float(d['gmv_total'].sum() - d['gmv_items'].sum()),
    'orders': int(len(d)),
    'customers': int(d['customer_unique_id'].nunique()),
    'aov': float(d['gmv_total'].mean()),
    'arpu': float(d['gmv_total'].sum() / d['customer_unique_id'].nunique()),
    'items_sold': int(len(foi[foi['is_delivered']])),
    'delivery_rate': float(fo['is_delivered'].mean() * 100),
    'avg_delivery_days': float(d['delivery_days'].mean()),
    # 注意：不能用 (~d['is_late'])——is_late 含 NaN 时是 object dtype，
    # ~ 会退化成按位取反（~True=-2、~False=-1），算出 -108% 这种荒谬值。
    # 必须显式比较：is_late 为 False 即「未晚于承诺日期」
    'on_time_rate': float((d['is_late'] == False).mean() * 100),
    'avg_review': float(d['review_score'].mean()),
    'avg_installments': float(d['main_payment_installments'].mean()),
    'date_min': str(fo['order_date'].min().date()),
    'date_max': str(fo['order_date'].max().date()),
}
L(f"  GMV={kpi['gmv']:,.0f}  AOV={kpi['aov']:.2f}  ARPU={kpi['arpu']:.2f}  交付完成率={kpi['delivery_rate']:.2f}%")
D['kpi'] = kpi

# 1.1 州 GMV（星型模型用法：事实表经 dim_customer 关联州维度）
#     GMV 按州需 join：fact_orders.customer_unique_id -> dim_customer.customer_state
fo_st = d.merge(dc[['customer_unique_id', 'customer_state', 'customer_city']],
                on='customer_unique_id', how='left')
st2 = (fo_st.groupby('customer_state')
         .agg(gmv=('gmv_total', 'sum'), orders=('order_id', 'nunique'),
              customers=('customer_unique_id', 'nunique'), aov=('gmv_total', 'mean'))
         .reset_index().sort_values('gmv', ascending=False))
st2['gmv_share'] = st2['gmv'] / st2['gmv'].sum() * 100
st2['orders_per_customer'] = st2['orders'] / st2['customers']
D['state_gmv'] = st2.round(3).to_dict('records')
L(f"  州 GMV TOP5: {st2.head(5)[['customer_state','gmv']].values.tolist()}")

# 州交付表现
st_dl = (fo.merge(dc[['customer_unique_id', 'customer_state']], on='customer_unique_id', how='left')
           .groupby('customer_state')
           .agg(total_orders=('order_id', 'count'),
                delivered=('is_delivered', 'sum'),
                avg_delivery_days=('delivery_days', 'mean')).reset_index())
st_dl['delivery_rate'] = st_dl['delivered'] / st_dl['total_orders'] * 100
D['state_delivery'] = st_dl.round(2).to_dict('records')

# 1.3 月度趋势（GMV / 订单 / AOV），仅完整月
d['ym'] = d['order_date'].dt.to_period('M').astype(str)
m = (d.groupby('ym').agg(gmv=('gmv_total', 'sum'), orders=('order_id', 'nunique'),
                         customers=('customer_unique_id', 'nunique')).reset_index())
m['aov'] = m['gmv'] / m['orders']
mom = (fo[fo['is_delivered']].groupby(fo['order_date'].dt.to_period('M').astype(str))
        .agg(all_orders=('order_id', 'count')).reset_index())
complete_months = set(dd[dd['is_complete_month']]['year_month'].unique())
m['is_complete'] = m['ym'].isin(complete_months)
D['monthly_trend'] = m.round(2).to_dict('records')
L(f"  完整月数量：{len(complete_months)}（{min(complete_months)} ~ {max(complete_months)}）")

# 1.4 每日订单量（DAU 也基于此）
daily = (d.groupby('order_date')
           .agg(orders=('order_id', 'nunique'), gmv=('gmv_total', 'sum'),
                customers=('customer_unique_id', 'nunique')).reset_index())
daily['date'] = daily['order_date'].dt.strftime('%Y-%m-%d')
daily['ma7'] = daily['orders'].rolling(7).mean()
D['daily_orders'] = daily[['date', 'orders', 'gmv', 'customers', 'ma7']].round(2).to_dict('records')

# 1.5 交付时效分布
bins = [-100, 0, 3, 7, 10, 15, 20, 30, 1000]
labels = ['提前/准时', '1-3天', '4-7天', '8-10天', '11-15天', '16-20天', '21-30天', '30天以上']
d['delay_band'] = pd.cut(d['delay_days'].dropna(), bins=bins, labels=labels)
dl_band = d['delay_band'].value_counts().reindex(labels).fillna(0).astype(int)
D['delay_band'] = [{'band': k, 'cnt': int(v)} for k, v in dl_band.items()]
dd_bins = [0, 3, 5, 7, 10, 14, 21, 30, 1000]
dd_labels = ['0-3天', '4-5天', '6-7天', '8-10天', '11-14天', '15-21天', '22-30天', '30天以上']
d['delivery_band'] = pd.cut(d['delivery_days'].dropna(), bins=dd_bins, labels=dd_labels)
D['delivery_band'] = [{'band': k, 'cnt': int(v)} for k, v in
                      d['delivery_band'].value_counts().reindex(dd_labels).fillna(0).astype(int).items()]

# 1.6 交付时效 vs 评分
rv = d.dropna(subset=['review_score']).copy()
rv['delivery_band2'] = pd.cut(rv['delivery_days'], bins=[0, 5, 10, 15, 20, 1000],
                              labels=['0-5天', '6-10天', '11-15天', '16-20天', '20天以上'])
ds_rv = rv.groupby('delivery_band2', observed=True).agg(
    avg_score=('review_score', 'mean'), cnt=('order_id', 'count'),
    pct_1star=('review_score', lambda s: (s == 1).mean() * 100)).reset_index()
D['delivery_vs_score'] = ds_rv.round(2).rename(columns={'delivery_band2': 'band'}).to_dict('records')
L("  交付时效 vs 评分：")
for r in D['delivery_vs_score']:
    L(f"    {r['band']}: 均分 {r['avg_score']:.2f}, 1星占比 {r['pct_1star']:.1f}%, n={r['cnt']}")

# ============================================================ 模块2 客户行为
L("\n[模块2] 客户行为")
# 2.1 DAU / MAU / 粘性
mau = (d.groupby(d['order_date'].dt.to_period('M').astype(str))['customer_unique_id'].nunique()
        .rename('mau').reset_index().rename(columns={'order_date': 'ym'}))
mau['days'] = pd.PeriodIndex(mau['ym'], freq='M').days_in_month
dau_avg = (d.groupby(d['order_date'].dt.to_period('M').astype(str))
             .apply(lambda g: g.groupby('order_date')['customer_unique_id'].nunique().mean())
             .rename('dau').reset_index().rename(columns={'order_date': 'ym'}))
mau = mau.merge(dau_avg, on='ym')
mau['stickiness'] = mau['dau'] / mau['mau'] * 100
mau['is_complete'] = mau['ym'].isin(complete_months)
D['mau_dau'] = mau.round(2).to_dict('records')
L(f"  最新完整月 DAU/MAU 粘性：{mau[mau['is_complete']].tail(3)[['ym','dau','mau','stickiness']].values.tolist()}")

# 2.2 复购
cust_orders = d.groupby('customer_unique_id')['order_id'].nunique()
dist = cust_orders.value_counts().sort_index()
D['repeat_dist'] = [{'orders': int(k), 'customers': int(v)} for k, v in dist.items()]
D['repeat_stats'] = {
    'total_customers': int(len(cust_orders)),
    'repeat_customers': int((cust_orders >= 2).sum()),
    'repeat_rate': float((cust_orders >= 2).mean() * 100),
    'max_orders': int(cust_orders.max()),
    'avg_orders': float(cust_orders.mean()),
}
L(f"  复购率 {D['repeat_stats']['repeat_rate']:.2f}%（{D['repeat_stats']['repeat_customers']:,} 人复购）")

# 2.3 新老客（按月）
d2 = d.merge(dc[['customer_unique_id', 'first_purchase_date']], on='customer_unique_id', how='left')
d2['first_purchase_date'] = pd.to_datetime(d2['first_purchase_date'])
d2['is_new'] = d2['order_date'].dt.to_period('M') == d2['first_purchase_date'].dt.to_period('M')
nc = d2.groupby('ym').agg(new_orders=('is_new', 'sum'), total_orders=('order_id', 'count')).reset_index()
nc['old_orders'] = nc['total_orders'] - nc['new_orders']
nc['new_pct'] = nc['new_orders'] / nc['total_orders'] * 100
nc['is_complete'] = nc['ym'].isin(complete_months)
D['new_vs_old'] = nc.round(2).to_dict('records')
L(f"  新客订单占比（整体）：{d2['is_new'].mean()*100:.2f}%")

# 2.4 支付方式
pay = (d.groupby('main_payment_type')
         .agg(orders=('order_id', 'count'), gmv=('gmv_total', 'sum')).reset_index())
pay['pct'] = pay['orders'] / pay['orders'].sum() * 100
pay = pay.sort_values('orders', ascending=False)
D['payment'] = pay.round(2).to_dict('records')
inst = d.groupby('main_payment_installments').agg(orders=('order_id', 'count')).reset_index()
inst = inst[inst['main_payment_installments'] <= 12]
D['installments'] = inst.rename(columns={'main_payment_installments': 'n'}).to_dict('records')
L(f"  支付方式：{pay[['main_payment_type','pct']].values.tolist()}")

# 2.5 下单时间分布
hour = d.groupby('purchase_hour').agg(orders=('order_id', 'count'), gmv=('gmv_total', 'sum')).reset_index()
D['hour_dist'] = hour.to_dict('records')
wk_name = {1: '周一', 2: '周二', 3: '周三', 4: '周四', 5: '周五', 6: '周六', 7: '周日'}
wk = d.groupby('purchase_weekday').agg(orders=('order_id', 'count'), gmv=('gmv_total', 'sum')).reset_index()
wk['name'] = wk['purchase_weekday'].map(wk_name)
D['weekday_dist'] = wk.to_dict('records')
slot = d.groupby('purchase_time_slot').agg(orders=('order_id', 'count'), gmv=('gmv_total', 'sum')).reset_index()
D['slot_dist'] = slot.sort_values('purchase_time_slot').to_dict('records')
L(f"  下单高峰时段：{slot.sort_values('orders',ascending=False).iloc[0]['purchase_time_slot']}")

# 2.6 RFM
seg_gmv = (d.merge(dc[['customer_unique_id', 'RFM_segment', 'R_score', 'M_score', 'F_score']],
                   on='customer_unique_id', how='left')
             .groupby('RFM_segment')
             .agg(customers=('customer_unique_id', 'nunique'), gmv=('gmv_total', 'sum'),
                  orders=('order_id', 'nunique'), aov=('gmv_total', 'mean')).reset_index())
seg_gmv['gmv_share'] = seg_gmv['gmv'] / seg_gmv['gmv'].sum() * 100
seg_gmv['cust_share'] = seg_gmv['customers'] / seg_gmv['customers'].sum() * 100
D['rfm_segment'] = seg_gmv.round(2).sort_values('RFM_segment').to_dict('records')
for c in ['R_score', 'M_score', 'F_score']:
    tmp = dc[dc[c] > 0].groupby(c).agg(customers=('customer_unique_id', 'count'),
                                       avg_spend=('total_spend', 'mean')).reset_index()
    D[f'rfm_{c.lower()}_dist'] = tmp.round(2).to_dict('records')
L("  RFM 分群：")
for r in D['rfm_segment']:
    L(f"    {r['RFM_segment']}: {r['customers']:,}人 ({r['cust_share']:.1f}%) GMV占比 {r['gmv_share']:.1f}%")

# 2.7 客户地理分布（城市 TOP15）
city = (d.merge(dc[['customer_unique_id', 'customer_city', 'customer_state']], on='customer_unique_id', how='left')
          .groupby(['customer_city', 'customer_state'])
          .agg(customers=('customer_unique_id', 'nunique'), gmv=('gmv_total', 'sum')).reset_index()
          .sort_values('customers', ascending=False).head(15))
D['city_top'] = city.round(2).to_dict('records')

# ============================================================ 模块3 商品指标
L("\n[模块3] 商品指标")
it = foi[foi['is_delivered']].merge(
    dp[['product_id', 'product_category_name_english', 'product_category_name']], on='product_id', how='left')

# 3.1 品类销量 / 销售额 TOP
cat = (it.groupby('product_category_name_english')
         .agg(qty=('order_item_id', 'count'), gmv=('price', 'sum'),
              avg_price=('price', 'mean'), orders=('order_id', 'nunique'),
              freight=('freight_value', 'sum')).reset_index()
         .sort_values('gmv', ascending=False))
cat['gmv_share'] = cat['gmv'] / cat['gmv'].sum() * 100
cat['freight_pct'] = cat['freight'] / cat['gmv'] * 100
D['category'] = cat.round(2).to_dict('records')
D['category_top_qty'] = cat.sort_values('qty', ascending=False).head(15).round(2).to_dict('records')
D['category_top_gmv'] = cat.head(15).round(2).to_dict('records')
L(f"  品类 GMV TOP5: {cat.head(5)['product_category_name_english'].tolist()}")
L(f"  品类销量 TOP5: {cat.sort_values('qty',ascending=False).head(5)['product_category_name_english'].tolist()}")

# 3.2 商品 TOP
prod_agg = (it.groupby('product_id')
              .agg(qty=('order_item_id', 'count'), gmv=('price', 'sum'),
                   avg_price=('price', 'mean')).reset_index()
              .merge(dp[['product_id', 'product_category_name_english', 'product_photos_qty',
                         'product_description_length', 'product_weight_g']], on='product_id', how='left'))
D['product_top_qty'] = prod_agg.sort_values('qty', ascending=False).head(10).round(2).to_dict('records')
D['product_top_gmv'] = prod_agg.sort_values('gmv', ascending=False).head(10).round(2).to_dict('records')

# 3.3 商品页面内容分析
photo = (prod_agg.dropna(subset=['product_photos_qty'])
         .groupby('product_photos_qty')
         .agg(products=('product_id', 'nunique'), avg_qty=('qty', 'mean'),
              avg_gmv=('gmv', 'mean'), total_qty=('qty', 'sum')).reset_index())
photo = photo[photo['product_photos_qty'] <= 10]
D['photo_analysis'] = photo.round(2).to_dict('records')
L("  商品图片数 vs 平均销量：")
for r in photo.head(7).to_dict('records'):
    L(f"    {int(r['product_photos_qty'])}张: {r['products']}款商品, 平均销量 {r['avg_qty']:.2f}")

prod_agg['desc_band'] = pd.cut(prod_agg['product_description_length'],
                               bins=[-1, 200, 500, 1000, 2000, 100000],
                               labels=['极简(<200)', '简短(200-500)', '中等(500-1k)', '详细(1k-2k)', '非常详细(>2k)'])
desc = (prod_agg.dropna(subset=['desc_band']).groupby('desc_band', observed=True)
        .agg(products=('product_id', 'nunique'), avg_qty=('qty', 'mean'),
             avg_gmv=('gmv', 'mean')).reset_index())
D['desc_analysis'] = desc.round(2).to_dict('records')

# 已售 vs 未售商品的页面内容对比（页面内容是否影响动销）
sold_ids = set(it['product_id'].unique())
prod_all = dp.copy()
prod_all['is_sold'] = prod_all['product_id'].isin(sold_ids)
sold_cmp = (prod_all.groupby('is_sold')
            .agg(products=('product_id', 'count'),
                 avg_photos=('product_photos_qty', 'mean'),
                 avg_desc=('product_description_length', 'mean'),
                 avg_name_len=('product_name_length', 'mean')).reset_index())
sold_cmp['is_sold'] = sold_cmp['is_sold'].map({True: '已售商品', False: '零销量商品'})
D['sold_vs_unsold'] = sold_cmp.round(2).to_dict('records')
L(f"  已售 {int((prod_all['is_sold']).sum())} 款 / 零销量 {int((~prod_all['is_sold']).sum())} 款")

# ============================================================ 模块4 履约与卖家
L("\n[模块4] 履约与卖家")
seller = (it.groupby('seller_id').agg(gmv=('price', 'sum'), qty=('order_item_id', 'count'),
                                      orders=('order_id', 'nunique')).reset_index()
            .merge(ds, on='seller_id', how='left').sort_values('gmv', ascending=False))
seller['cum_share'] = seller['gmv'].cumsum() / seller['gmv'].sum() * 100
D['seller_top'] = seller.head(15).round(2).to_dict('records')
top10pct = int(len(seller) * 0.1)
D['seller_concentration'] = {
    'total_sellers': int(len(seller)),
    'top10pct_sellers': top10pct,
    'top10pct_gmv_share': float(seller.head(top10pct)['gmv'].sum() / seller['gmv'].sum() * 100),
    'top50_gmv_share': float(seller.head(50)['gmv'].sum() / seller['gmv'].sum() * 100),
}
L(f"  卖家集中度：TOP10%({top10pct}家) 贡献 GMV {D['seller_concentration']['top10pct_gmv_share']:.1f}%")

# 卖家地域
seller_state = (seller.groupby('seller_state').agg(sellers=('seller_id', 'nunique'),
                                                   gmv=('gmv', 'sum')).reset_index()
                .sort_values('gmv', ascending=False))
D['seller_state'] = seller_state.round(2).to_dict('records')

# 评分分布
rev_dist = d.dropna(subset=['review_score']).groupby('review_score').agg(
    orders=('order_id', 'count')).reset_index()
rev_dist['pct'] = rev_dist['orders'] / rev_dist['orders'].sum() * 100
D['review_dist'] = rev_dist.round(2).to_dict('records')

# 评分 vs 是否延迟
late_score = (d.dropna(subset=['review_score', 'is_late']).groupby('is_late')
              .agg(avg_score=('review_score', 'mean'), orders=('order_id', 'count'),
                   pct_1star=('review_score', lambda s: (s == 1).mean() * 100)).reset_index())
late_score['is_late'] = late_score['is_late'].map({True: '延迟送达', False: '准时/提前'})
D['late_vs_score'] = late_score.round(2).to_dict('records')
L("  延迟 vs 评分：")
for r in D['late_vs_score']:
    L(f"    {r['is_late']}: 均分 {r['avg_score']:.2f}, 1星 {r['pct_1star']:.1f}%")

# 订单状态分布
status = fo.groupby('order_status').agg(orders=('order_id', 'count')).reset_index()
status['pct'] = status['orders'] / status['orders'].sum() * 100
D['order_status'] = status.round(2).to_dict('records')

json.dump(D, open(f"{OUT}/dashboard_data.json", 'w', encoding='utf-8'),
          ensure_ascii=False, separators=(',', ':'))
L(f"\n已输出 dashboard_data.json（{os.path.getsize(f'{OUT}/dashboard_data.json')/1024:.0f} KB）")
