# -*- coding: utf-8 -*-
"""构建紧凑事实表，供前端切片器实时重算所有图表。

输出 output/fact_compact.json:
  {
    "dim": {
        "states":  [code, ...],
        "cats":    [english, ...],
        "pays":    [type, ...],
        "statuses":[status, ...],
        "cities":  [city, ...],
        "sellers": [seller_id, ...],
        "products":[product_id, ...],
        "ym":      [[ym_int, year_int, is_complete], ...]   # 按月升序
    },
    "rows": [[date_id,state,cat,uid,oid,price_c, freight_c, delivered,
              deliv_dx10, is_late, delay_dx10, review, pay, inst,
              hour, wday0, is_new, status, city, seller, product], ...]
  }
字段均为整数（price/freight 用分，deliv/delay 用 ×10），便于紧凑 JSON 与前端快速聚合。
"""
import csv, json, os

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, 'output')

def load_csv(p):
    with open(p, encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            yield row

# ---------- 维度索引 ----------
product_cat = {}          # product_id -> english
for r in load_csv(os.path.join(OUT, 'dim_product.csv')):
    product_cat[r['product_id']] = r['product_category_name_english']

seller_state_map = {}     # seller_id -> state
for r in load_csv(os.path.join(OUT, 'dim_seller.csv')):
    seller_state_map[r['seller_id']] = r['seller_state']

cust_loc = {}             # customer_unique_id -> (state, city, r, f, m, rfm_seg)
segments = []
seg_idx = {}
for r in load_csv(os.path.join(OUT, 'dim_customer.csv')):
    seg = r['RFM_segment']
    if seg not in seg_idx:
        seg_idx[seg] = len(segments); segments.append(seg)
    cust_loc[r['customer_unique_id']] = (
        r['customer_state'], r['customer_city'],
        int(float(r['R_score'] or 0)), int(float(r['F_score'] or 0)),
        int(float(r['M_score'] or 0)), seg_idx[seg])

# 维度列表（有序）
states, cats, pays, statuses, cities, sellers, products = [], [], [], [], [], [], []
state_idx, cat_idx, pay_idx, status_idx, city_idx, seller_idx, product_idx = (
    {}, {}, {}, {}, {}, {}, {})
PAY_ORDER = ['credit_card', 'boleto', 'voucher', 'debit_card', 'not_defined']
STATUS_ORDER = ['approved', 'canceled', 'created', 'delivered', 'invoiced',
                'processing', 'shipped', 'unavailable']
for i, p in enumerate(PAY_ORDER): pay_idx[p] = i
for i, s in enumerate(STATUS_ORDER): status_idx[s] = i
pays = list(PAY_ORDER); statuses = list(STATUS_ORDER)

uid_map, oid_map = {}, {}
def get_idx(table, idx_map, val):
    if val not in idx_map:
        idx_map[val] = len(table); table.append(val)
    return idx_map[val]

# ---------- 订单级属性 ----------
# order_id -> 订单级字段（用于关联到每个 item）
order_attr = {}
for r in load_csv(os.path.join(OUT, 'fact_orders.csv')):
    oid = r['order_id']
    cu = r['customer_unique_id']
    st, ci, _, _, _, _ = cust_loc.get(cu, ('UNK', 'unknown', 0, 0, 0, 0))
    date = r['order_date'][:10]
    date_id = int(date.replace('-', ''))
    ym = int(date[:4] + date[5:7])
    order_attr[oid] = {
        'date_id': date_id, 'ym': ym,
        'state': get_idx(states, state_idx, st),
        'city': get_idx(cities, city_idx, ci),
        'status': status_idx.get(r['order_status'], 7),
        'delivered': 1 if r['is_delivered'] == 'True' else 0,
        'deliv_d': int(round(float(r['delivery_days'] or 0) * 10)),
        'is_late': 1 if r['is_late'] == 'True' else 0,
        'delay': int(round(float(r['delay_days'] or 0) * 10)),
        'review': int(float(r['review_score'])) if r['review_score'] not in ('', '0', None) else 0,
        'pay': pay_idx.get(r['main_payment_type'] or 'not_defined', 4),
        'inst': int(float(r['main_payment_installments'] or 0)),
        'hour': int(float(r['purchase_hour'] or 0)),
        'wday': int(float(r['purchase_weekday'] or 1)) - 1,  # 1..7 -> 0..6
        'is_new': 1 if r['is_new_customer'] == 'True' else 0,
        'cu': cu,
    }

# uid 在 item 循环中统一建索引（customer_unique_id -> int）
def uid(cu):
    if cu not in uid_map:
        uid_map[cu] = len(uid_map)
    return uid_map[cu]

# ---------- 逐 item 输出 ----------
rows = []
empty = 0
for r in load_csv(os.path.join(OUT, 'fact_order_items.csv')):
    oid = r['order_id']
    a = order_attr.get(oid)
    if a is None:
        empty += 1; continue
    pid = r['product_id']
    if pid not in product_idx:
        product_idx[pid] = len(products); products.append(pid)
    cat = product_cat.get(pid, 'unknown')
    if cat not in cat_idx:
        cat_idx[cat] = len(cats); cats.append(cat)
    sid = r['seller_id']
    if sid not in seller_idx:
        seller_idx[sid] = len(sellers); sellers.append(sid)
    st, ci, rsc, fsc, msc, rfseg = cust_loc.get(a['cu'], ('UNK', 'unknown', 0, 0, 0, 0))
    price_c = int(round(float(r['price'] or 0) * 100))
    freight_c = int(round(float(r['freight_value'] or 0) * 100))
    deliv = 1 if r['is_delivered'] == 'True' else 0
    if oid not in oid_map:
        oid_map[oid] = len(oid_map)
    rows.append([
        a['date_id'], a['state'], cat_idx[cat], uid(a['cu']), oid_map[oid],
        price_c, freight_c, deliv, a['deliv_d'], a['is_late'], a['delay'],
        a['review'], a['pay'], a['inst'], a['hour'], a['wday'], a['is_new'],
        a['status'], a['city'], seller_idx[sid], product_idx[pid],
        rfseg, rsc, fsc, msc,
    ])

# ---------- 补齐「无商品明细行」的订单 ----------
# fact_order_items 里没有任何记录的订单（下单即取消 / 不可用等），如果只按 item 循环
# 输出，这些订单会整单丢失，导致**基于订单数**的指标分母偏小：
#   交付完成率 = 96,478 / 98,666 = 97.78%   ← 错误（与 SQL / Power BI 的 97.02% 不一致）
#   正确       = 96,478 / 99,441 = 97.02%
# 订单状态构成、各州交付率同样会少算这部分订单。
# 补一条无商品、无金额的占位记录，让订单级去重计数与 fact_orders 对齐。
# 说明：这些订单全部未交付（已交付的 96,478 单都有明细行），所以不会污染
#       「已交付口径」的任何金额 / 明细 / 客户指标（那些聚合都走 del / delOrders）。
#       品类、卖家、商品三列填 -1 占位——无明细即无法归属，按品类筛选时自然被排除。
items_oid = set(oid_map.keys())
orphan = 0
for oid, a in order_attr.items():
    if oid in items_oid:
        continue
    oid_map[oid] = len(oid_map)
    _, _, rsc, fsc, msc, rfseg = cust_loc.get(a['cu'], ('UNK', 'unknown', 0, 0, 0, 0))
    rows.append([
        a['date_id'], a['state'], -1, uid(a['cu']), oid_map[oid],
        0, 0, a['delivered'], a['deliv_d'], a['is_late'], a['delay'],
        a['review'], a['pay'], a['inst'], a['hour'], a['wday'], a['is_new'],
        a['status'], a['city'], -1, -1,
        rfseg, rsc, fsc, msc,
    ])
    orphan += 1

# ---------- 月份维度（含完整性标记）----------
yms = sorted({a['ym'] for a in order_attr.values()})
ym_info = []
for ym in yms:
    y = ym // 100
    m = ym % 100
    # 不完整：2016-09~12 爬坡期；2018-09~10 数据截断
    complete = not ((y == 2016 and m >= 9) or (y == 2018 and m >= 9))
    ym_info.append([ym, y, 1 if complete else 0])

# 卖家 -> 州 对齐到 sellers 列表顺序
seller_states = [seller_state_map.get(s, 'UNK') for s in sellers]

dim = {
    'states': states, 'cats': cats, 'pays': pays, 'statuses': statuses,
    'cities': cities, 'sellers': sellers, 'seller_states': seller_states,
    'products': products, 'segments': segments, 'ym': ym_info,
}
out = {'dim': dim, 'rows': rows}
with open(os.path.join(OUT, 'fact_compact.json'), 'w', encoding='utf-8') as f:
    json.dump(out, f, separators=(',', ':'), ensure_ascii=False)

sz = os.path.getsize(os.path.join(OUT, 'fact_compact.json')) / 1024 / 1024
print(f"行数(明细): {len(rows) - orphan}  补齐无明细订单: {orphan}  跳过: {empty}")
print(f"维度: states={len(states)} cats={len(cats)} pays={len(pays)} "
      f"statuses={len(statuses)} cities={len(cities)} sellers={len(sellers)} products={len(products)} segments={len(segments)}")
print(f"uid={len(uid_map)} oid={len(oid_map)}")
print(f"fact_compact.json: {sz:.2f} MB")
