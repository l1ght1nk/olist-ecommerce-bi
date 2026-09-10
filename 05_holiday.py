# -*- coding: utf-8 -*-
"""
Olist 电商分析 —— 阶段五：节假日与黑色星期五专项分析
方法：
  1. 定义数据覆盖期内的巴西主要节假日 / 电商大促节点
  2. 对每个节点计算「节前 7 天 / 节日当天 / 节后 7 天」的日均订单与 GMV
  3. 基线 = 该节日所在月份中，不属于任何节日窗口的日期的日均值（排除窗口污染）
  4. 黑五做专项：周维度对比 + 品类结构 + 客单价 + 是否透支后续消费
输出：追加到 output/dashboard_data.json
"""
import pandas as pd, numpy as np, json, os

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, 'output')

fo = pd.read_csv(f"{OUT}/fact_orders.csv", parse_dates=['order_date'])
foi = pd.read_csv(f"{OUT}/fact_order_items.csv", parse_dates=['order_date'])
dp = pd.read_csv(f"{OUT}/dim_product.csv")
D = json.load(open(f"{OUT}/dashboard_data.json", encoding='utf-8'))

def L(*a): print(*a)

d = fo[fo['is_delivered']].copy()   # 主口径：已交付订单

# ---------------------------------------------------------------- 1. 节日表
# 仅保留数据覆盖区间内的节点（2016-09 ~ 2018-10）
HOLIDAYS = [
    ('2016-10-12', '儿童节/圣母显现日'), ('2016-11-02', '亡人节'), ('2016-11-15', '共和国宣言日'),
    ('2017-01-01', '元旦'), ('2017-02-28', '狂欢节'), ('2017-04-14', '耶稣受难日'),
    ('2017-04-21', '蒂拉登特斯日'), ('2017-05-01', '劳动节'), ('2017-05-14', '母亲节'),
    ('2017-06-15', '圣体节'), ('2017-09-07', '独立日'), ('2017-10-12', '儿童节/圣母显现日'),
    ('2017-11-02', '亡人节'), ('2017-11-15', '共和国宣言日'), ('2017-11-24', '黑色星期五'),
    ('2017-12-25', '圣诞节'),
    ('2018-01-01', '元旦'), ('2018-02-13', '狂欢节'), ('2018-03-30', '耶稣受难日'),
    ('2018-04-21', '蒂拉登特斯日'), ('2018-05-01', '劳动节'), ('2018-05-13', '母亲节'),
    ('2018-05-31', '圣体节'), ('2018-08-12', '父亲节'), ('2018-09-07', '独立日'),
    ('2018-10-12', '儿童节/圣母显现日'),
]
hol = pd.DataFrame(HOLIDAYS, columns=['date', 'name'])
hol['date'] = pd.to_datetime(hol['date'])

# ---------------------------------------------------------------- 2. 日聚合
daily = (d.groupby('order_date')
           .agg(orders=('order_id', 'nunique'), gmv=('gmv_total', 'sum'),
                customers=('customer_unique_id', 'nunique')).reset_index())
daily['aov'] = daily['gmv'] / daily['orders']
daily = daily.set_index('order_date')

# 所有节日窗口日期（用于排除基线污染）
win_dates = set()
for _, r in hol.iterrows():
    for k in range(-7, 8):
        win_dates.add(r['date'] + pd.Timedelta(days=k))

def safe(dt):
    """返回该日的 (orders, gmv)，无数据返回 0"""
    if dt in daily.index:
        return float(daily.loc[dt, 'orders']), float(daily.loc[dt, 'gmv'])
    return 0.0, 0.0

rows = []
for _, r in hol.iterrows():
    dt = r['date']
    ym = dt.to_period('M')
    # 基线：优先用同月内不属于任何节日窗口的日期
    month_days = [x for x in daily.index if x.to_period('M') == ym]
    base_days = [x for x in month_days if x not in win_dates]
    base_src = '同月非窗口日'
    if len(base_days) < 10:
        # 节日密集的月份（如 2017-11 有亡人节/共和国日/黑五，全月无干净日）
        # 退回到「节前 45~8 天」内的非窗口日，兼顾时效性与样本量
        base_days = [x for x in daily.index
                     if (dt - pd.Timedelta(days=45)) <= x <= (dt - pd.Timedelta(days=8))
                     and x not in win_dates]
        base_src = '节前45-8日非窗口'
    if len(base_days) < 5:      # 仍不足（2016 年数据稀疏），跳过
        continue
    # 对照：同月全月日均（含窗口日），用于判断基线是否被月度内趋势扭曲
    month_all = daily.loc[month_days, 'orders'].mean() if month_days else b_ord
    b_ord = daily.loc[base_days, 'orders'].mean()
    b_gmv = daily.loc[base_days, 'gmv'].mean()
    if b_ord <= 0:
        continue

    pre = [dt - pd.Timedelta(days=k) for k in range(1, 8)]
    post = [dt + pd.Timedelta(days=k) for k in range(1, 8)]
    pre_ord = np.mean([safe(x)[0] for x in pre])
    day_ord, day_gmv = safe(dt)
    post_ord = np.mean([safe(x)[0] for x in post])
    pre_gmv = np.mean([safe(x)[1] for x in pre])
    post_gmv = np.mean([safe(x)[1] for x in post])

    if day_ord == 0 and pre_ord == 0 and post_ord == 0:
        continue   # 该时段无数据（如 2018-09 起数据截断），剔除以免产生 -100% 的假结论

    rows.append({
        'name': r['name'], 'date': dt.strftime('%Y-%m-%d'),
        'baseline_orders': round(b_ord, 1), 'month_all_orders': round(month_all, 1),
        'pre7_orders': round(pre_ord, 1), 'day_orders': round(day_ord, 1), 'post7_orders': round(post_ord, 1),
        'uplift_pre': round((pre_ord - b_ord) / b_ord * 100, 1),
        'uplift_day': round((day_ord - b_ord) / b_ord * 100, 1),
        'uplift_post': round((post_ord - b_ord) / b_ord * 100, 1),
        'baseline_gmv': round(b_gmv, 0), 'day_gmv': round(day_gmv, 0),
        'uplift_gmv_day': round((day_gmv - b_gmv) / b_gmv * 100, 1) if b_gmv > 0 else None,
        'base_days': len(base_days), 'base_src': base_src,
    })

hol_res = pd.DataFrame(rows).sort_values('uplift_day', ascending=False)
D['holidays'] = hol_res.to_dict('records')
L("=" * 70)
L("[节假日效应] 节日当天订单量相对基线的 uplift")
L(hol_res[['name', 'date', 'baseline_orders', 'pre7_orders', 'day_orders', 'post7_orders',
           'uplift_pre', 'uplift_day', 'uplift_post']].to_string(index=False))

# ---------------------------------------------------------------- 3. 黑五专项
L("\n" + "=" * 70)
L("[黑五专项] 2017-11-24")
BF = pd.Timestamp('2017-11-24')

def win_stats(start, end, label):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    m = (d['order_date'] >= start) & (d['order_date'] <= end)
    s = d[m]
    return {
        'label': label, 'range': f"{start.date()} ~ {end.date()}",
        'orders': int(len(s)),
        'gmv': round(float(s['gmv_total'].sum()), 0),
        'aov': round(float(s['gmv_total'].mean()), 2),
        'customers': int(s['customer_unique_id'].nunique()),
        'daily_orders': round(len(s) / ((end - start).days + 1), 1),
        'daily_gmv': round(float(s['gmv_total'].sum()) / ((end - start).days + 1), 0),
        'new_cust_pct': round(float(s['is_new_customer'].mean() * 100), 1),
        'avg_installments': round(float(s['main_payment_installments'].mean()), 2),
    }

bf = [
    win_stats('2017-11-13', '2017-11-19', '黑五前一周'),
    win_stats('2017-11-20', '2017-11-26', '黑五当周'),
    win_stats('2017-11-27', '2017-12-03', '黑五后一周'),
    win_stats('2017-12-04', '2017-12-10', '黑五后第二周'),
]
D['bf_weeks'] = bf
L(pd.DataFrame(bf)[['label', 'range', 'orders', 'daily_orders', 'gmv', 'daily_gmv', 'aov',
                    'new_cust_pct', 'avg_installments']].to_string(index=False))

# 黑五当天 vs 11月日常（排除黑五周）
nov = d[(d['order_date'] >= '2017-11-01') & (d['order_date'] <= '2017-11-30')]
bfw = (nov['order_date'] >= '2017-11-20') & (nov['order_date'] <= '2017-11-26')
normal = nov[~bfw]
bfday = d[d['order_date'] == BF]
D['bf_day_vs_normal'] = {
    'bf_day': {'orders': int(len(bfday)), 'gmv': round(float(bfday['gmv_total'].sum()), 0),
               'aov': round(float(bfday['gmv_total'].mean()), 2),
               'avg_installments': round(float(bfday['main_payment_installments'].mean()), 2),
               'new_cust_pct': round(float(bfday['is_new_customer'].mean() * 100), 1),
               'credit_card_pct': round(float((bfday['main_payment_type'] == 'credit_card').mean() * 100), 1)},
    'normal_day': {'orders': round(len(normal) / normal['order_date'].nunique(), 1),
                   'gmv': round(float(normal['gmv_total'].sum()) / normal['order_date'].nunique(), 0),
                   'aov': round(float(normal['gmv_total'].mean()), 2),
                   'avg_installments': round(float(normal['main_payment_installments'].mean()), 2),
                   'new_cust_pct': round(float(normal['is_new_customer'].mean() * 100), 1),
                   'credit_card_pct': round(float((normal['main_payment_type'] == 'credit_card').mean() * 100), 1)},
}
L(f"\n黑五当天 vs 11 月日常（排除黑五周）：")
L(f"  单日订单 {D['bf_day_vs_normal']['bf_day']['orders']} vs {D['bf_day_vs_normal']['normal_day']['orders']} 单")
L(f"  客单价 R$ {D['bf_day_vs_normal']['bf_day']['aov']} vs R$ {D['bf_day_vs_normal']['normal_day']['aov']}")
L(f"  信用卡占比 {D['bf_day_vs_normal']['bf_day']['credit_card_pct']}% vs {D['bf_day_vs_normal']['normal_day']['credit_card_pct']}%")
L(f"  平均分期 {D['bf_day_vs_normal']['bf_day']['avg_installments']} vs {D['bf_day_vs_normal']['normal_day']['avg_installments']} 期")

# 品类结构：黑五当周 vs 11 月其他周
def cat_struct(start, end):
    s = foi[(foi['order_date'] >= start) & (foi['order_date'] <= end) & (foi['is_delivered'])]
    g = (s.merge(dp[['product_id', 'product_category_name_english']], on='product_id', how='left')
           .groupby('product_category_name_english')
           .agg(gmv=('price', 'sum'), qty=('order_item_id', 'count')).reset_index())
    g['share'] = g['gmv'] / g['gmv'].sum() * 100
    return g.sort_values('gmv', ascending=False)

bf_cat = cat_struct('2017-11-20', '2017-11-26')
nm_cat = pd.concat([cat_struct('2017-11-01', '2017-11-19'), cat_struct('2017-11-27', '2017-11-30')]) \
           .groupby('product_category_name_english').agg(gmv=('gmv', 'sum'), qty=('qty', 'sum')).reset_index()
nm_cat['share'] = nm_cat['gmv'] / nm_cat['gmv'].sum() * 100
cmp = (bf_cat[['product_category_name_english', 'gmv', 'share', 'qty']].head(15)
       .merge(nm_cat[['product_category_name_english', 'share', 'gmv']],
              on='product_category_name_english', how='left', suffixes=('_bf', '_nm')))
cmp['share_diff'] = cmp['share_bf'] - cmp['share_nm']
cmp = cmp.sort_values('share_diff', ascending=False)
D['bf_category'] = cmp.round(2).to_dict('records')
L("\n黑五当周品类结构变化（share_diff > 0 表示黑五占比提升）：")
L(cmp[['product_category_name_english', 'share_bf', 'share_nm', 'share_diff']].head(8).to_string(index=False))
L(cmp[['product_category_name_english', 'share_bf', 'share_nm', 'share_diff']].tail(5).to_string(index=False))

# 是否透支后续消费：黑五后 2 周 vs 黑五前基线
post2 = win_stats('2017-11-27', '2017-12-10', '黑五后两周')
pre1 = bf[0]
D['bf_cannibalization'] = {
    'pre_week_daily_orders': pre1['daily_orders'],
    'post_two_weeks_daily_orders': post2['daily_orders'],
    'delta_pct': round((post2['daily_orders'] - pre1['daily_orders']) / pre1['daily_orders'] * 100, 1),
}
L(f"\n透支检验：黑五前一周日均 {pre1['daily_orders']} 单 → 黑五后两周日均 {post2['daily_orders']} 单 "
  f"({D['bf_cannibalization']['delta_pct']:+}%)")

# 黑五窗口日订单序列（用于画图，11/01 ~ 12/15）
bf_series = []
for i in range(-20, 22):
    dt = BF + pd.Timedelta(days=i)
    o, g = safe(dt)
    bf_series.append({'date': dt.strftime('%Y-%m-%d'), 'orders': o, 'gmv': g,
                      'is_bf': int(dt == BF)})
D['bf_series'] = bf_series

# 全期日订单带节日标记（供时间轴使用）
D['holiday_marks'] = [{'name': r['name'], 'date': r['date'].strftime('%Y-%m-%d')}
                      for _, r in hol.iterrows()
                      if pd.Timestamp('2017-01-01') <= r['date'] <= pd.Timestamp('2018-10-17')]

# 母亲节对比（巴西第二大电商节点）
for y, md in [(2017, '2017-05-14'), (2018, '2018-05-13')]:
    m = pd.Timestamp(md)
    o, g = safe(m)
    L(f"\n母亲节 {md} 当天：{int(o)} 单（全期排名靠前）")

# ---------------------------------------------------------------- 4. 导出节日维度表（供 Power BI）
dim_holiday = hol.copy()
dim_holiday['year'] = dim_holiday['date'].dt.year
dim_holiday['is_black_friday'] = dim_holiday['name'] == '黑色星期五'
dim_holiday['is_gift_festival'] = dim_holiday['name'].isin(['母亲节', '父亲节', '儿童节/圣母显现日', '圣诞节'])
dim_holiday['is_public_holiday'] = ~dim_holiday['is_black_friday'] & ~dim_holiday['is_gift_festival']
dim_holiday['date'] = dim_holiday['date'].dt.strftime('%Y-%m-%d')
dim_holiday.to_csv(f"{OUT}/dim_holiday.csv", index=False, encoding='utf-8-sig')
L(f"\n已导出 dim_holiday.csv（{len(dim_holiday)} 个节点）")

json.dump(D, open(f"{OUT}/dashboard_data.json", 'w', encoding='utf-8'),
          ensure_ascii=False, separators=(',', ':'))
L(f"\n已更新 dashboard_data.json（{os.path.getsize(f'{OUT}/dashboard_data.json')/1024:.0f} KB）")
