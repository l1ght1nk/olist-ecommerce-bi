# -*- coding: utf-8 -*-
"""
阶段七：导出 Power BI 页面 5（节假日与大促）所需的预计算静态表
  1. holiday_uplift.csv   节日效应（基线/节前/当天/节后 + uplift）
  2. bf_weeks.csv         黑五周维度对比
  3. bf_day_vs_normal.csv 黑五当天 vs 11 月日常
  4. bf_category.csv      黑五当周品类结构变化
  5. bf_series.csv        黑五前后 41 天日订单序列（含黑五标记）
同时打印页面 2/3/4 的校验值（与 HTML 看板同源），供 Power BI 对答案。
口径与 05_holiday.py / 03_metrics.py 完全一致：已交付订单。
"""
import pandas as pd, numpy as np, json, os

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, 'output')
D = json.load(open(f"{OUT}/dashboard_data.json", encoding='utf-8'))

def L(*a): print(*a)

# ------------------------------------------------ 1. 页面 5 静态表导出
hol = pd.DataFrame(D['holidays'])
hol.to_csv(f"{OUT}/holiday_uplift.csv", index=False, encoding='utf-8-sig')
L(f"[导出] holiday_uplift.csv  {len(hol)} 条")

bfw = pd.DataFrame(D['bf_weeks'])
bfw.to_csv(f"{OUT}/bf_weeks.csv", index=False, encoding='utf-8-sig')
L(f"[导出] bf_weeks.csv  {len(bfw)} 条")

bv = D['bf_day_vs_normal']
cmp_rows = []
for k in ['orders', 'gmv', 'aov', 'avg_installments', 'new_cust_pct', 'credit_card_pct']:
    cmp_rows.append({'metric': k, 'bf_day': bv['bf_day'][k], 'normal_day': bv['normal_day'][k],
                     'diff': bv['bf_day'][k] - bv['normal_day'][k]})
pd.DataFrame(cmp_rows).to_csv(f"{OUT}/bf_day_vs_normal.csv", index=False, encoding='utf-8-sig')
L(f"[导出] bf_day_vs_normal.csv  {len(cmp_rows)} 行")

bfc = pd.DataFrame(D['bf_category'])
bfc.to_csv(f"{OUT}/bf_category.csv", index=False, encoding='utf-8-sig')
L(f"[导出] bf_category.csv  {len(bfc)} 条")

bfs = pd.DataFrame(D['bf_series'])
bfs.to_csv(f"{OUT}/bf_series.csv", index=False, encoding='utf-8-sig')
L(f"[导出] bf_series.csv  {len(bfs)} 条（{bfs['date'].min()} ~ {bfs['date'].max()}）")

L("\n" + "=" * 78)
L("【页面 5 校验值】节日 uplift（按当天 uplift 降序）")
L(hol[['name', 'date', 'baseline_orders', 'pre7_orders', 'day_orders', 'post7_orders',
       'uplift_pre', 'uplift_day', 'uplift_post', 'base_src']].to_string(index=False))
L("\n黑五周对比：")
L(bfw[['label', 'range', 'orders', 'daily_orders', 'gmv', 'daily_gmv', 'aov',
       'new_cust_pct', 'avg_installments']].to_string(index=False))
L("\n黑五当天 vs 11月日常：")
L(pd.DataFrame(cmp_rows).to_string(index=False))
L(f"\n透支检验：{D['bf_cannibalization']}")
L("\n黑五当周品类结构变化（前 5 / 后 3）：")
L(bfc[['product_category_name_english', 'share_bf', 'share_nm', 'share_diff']].head(5).to_string(index=False))
L(bfc[['product_category_name_english', 'share_bf', 'share_nm', 'share_diff']].tail(3).to_string(index=False))

# ------------------------------------------------ 2. 页面 2 校验值
L("\n" + "=" * 78)
L("【页面 2 校验值】")
L("城市 TOP5：")
L(pd.DataFrame(D['city_top']).head(5)[['customer_city', 'customer_state', 'customers', 'gmv']].to_string(index=False))
L("\n复购次数分布（orders=下单次数, customers=人数）：")
L(pd.DataFrame(D['repeat_dist']).to_string(index=False))
L(f"\n复购统计：{D['repeat_stats']}")
L("\n支付方式：")
L(pd.DataFrame(D['payment']).to_string(index=False))
L("\n分期期数 TOP6：")
L(pd.DataFrame(D['installments']).sort_values('orders', ascending=False).head(6).to_string(index=False))
L("\n下单时段：")
L(pd.DataFrame(D['slot_dist']).to_string(index=False))
L("\nRFM 分群：")
L(pd.DataFrame(D['rfm_segment']).to_string(index=False))

# ------------------------------------------------ 3. 页面 3 校验值
L("\n" + "=" * 78)
L("【页面 3 校验值】")
foi = pd.read_csv(f"{OUT}/fact_order_items.csv")
dp = pd.read_csv(f"{OUT}/dim_product.csv")
it = foi[foi['is_delivered']].copy()
sold_sku = it['product_id'].nunique()
L(f"SKU：全量 {len(dp)} ／ 有销量 {sold_sku} ／ 零销量 {len(dp) - sold_sku}")
L(f"品类数：{dp['product_category_name_english'].nunique()}")
L(f"明细 GMV 口径核对 —— sum(item_total)={it['item_total'].sum():,.2f}  sum(price)={it['price'].sum():,.2f}")
cat = pd.DataFrame(D['category'])
L(f"HTML 品类 GMV 合计 = {cat['gmv'].sum():,.2f}  （对比：总GMV 15,419,773.75 / 商品金额 13,221,498.11）")
L("\n品类 GMV TOP10（HTML 口径）：")
L(pd.DataFrame(D['category_top_gmv']).head(10)[['product_category_name_english', 'qty', 'gmv', 'avg_price', 'freight_pct']].to_string(index=False))
L("\n品类销量 TOP10：")
L(pd.DataFrame(D['category_top_qty']).head(10)[['product_category_name_english', 'qty', 'gmv', 'avg_price']].to_string(index=False))
L("\n图片数 vs 销量：")
L(pd.DataFrame(D['photo_analysis']).head(8)[['product_photos_qty', 'products', 'avg_qty']].to_string(index=False))
L("\n描述长度 vs 销量：")
L(pd.DataFrame(D['desc_analysis']).to_string(index=False))
L("\n已售 vs 零销量：")
L(pd.DataFrame(D['sold_vs_unsold']).to_string(index=False))
L("\n商品 GMV TOP5：")
L(pd.DataFrame(D['product_top_gmv']).head(5)[['product_id', 'qty', 'gmv', 'product_category_name_english']].to_string(index=False))

# ------------------------------------------------ 4. 页面 4 校验值
L("\n" + "=" * 78)
L("【页面 4 校验值】")
L("配送时长分档：")
L(pd.DataFrame(D['delivery_band']).to_string(index=False))
L("\n配送时长 vs 评分：")
L(pd.DataFrame(D['delivery_vs_score']).to_string(index=False))
L("\n延误天数分档：")
L(pd.DataFrame(D['delay_band']).to_string(index=False))
L("\n准时 vs 延误评分：")
L(pd.DataFrame(D['late_vs_score']).to_string(index=False))
L("\n评分分布：")
L(pd.DataFrame(D['review_dist']).to_string(index=False))
L("\n卖家 TOP8：")
L(pd.DataFrame(D['seller_top']).head(8)[['seller_id', 'gmv', 'qty', 'orders', 'seller_state', 'cum_share']].to_string(index=False))
L(f"\n卖家集中度：{D['seller_concentration']}")
L("\n卖家地域 TOP6：")
L(pd.DataFrame(D['seller_state']).head(6).to_string(index=False))
