# -*- coding: utf-8 -*-
"""把 ECharts、指标数据、紧凑事实表注入模板，生成单文件离线交互看板 HTML"""
import os, json, io

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, 'output')

tpl = io.open(os.path.join(BASE, 'dashboard_template.html'), encoding='utf-8').read()
data = json.load(io.open(os.path.join(OUT, 'dashboard_data.json'), encoding='utf-8'))
fact = io.open(os.path.join(OUT, 'fact_compact.json'), encoding='utf-8').read()
ec = io.open(os.path.join(BASE, 'echarts.min.js'), encoding='utf-8').read()

# 节假日与大促数据：模板里 renderHoliday() 依赖这些字段，必须嵌入
# 这些是 07_export_pbi_static.py 导出的 CSV（值均为字符串），需转成模板期望的结构：
#   holidays          -> 数组，数值列转 number（排序/比较/格式化都依赖数值语义）
#   bf_weeks          -> 数组，[0]=前一周 [1]=当周 [2]=后一周 [3]=后第二周
#   bf_day_vs_normal  -> 对象 {bf_day:{metric:值}, normal_day:{...}, diff:{...}}
import csv

def read_csv(name):
    fpath = os.path.join(OUT, name)
    if not os.path.exists(fpath):
        return None
    return list(csv.DictReader(io.open(fpath, encoding='utf-8-sig')))

def num(v):
    """能转数字就转，否则原样返回（name/date/base_src 等文本列保持字符串）"""
    if v is None or v == '':
        return v
    try:
        f = float(v)
        return int(f) if f == int(f) and '.' not in v else f
    except (ValueError, TypeError):
        return v

def to_records(rows):
    return [{k: num(v) for k, v in r.items()} for r in rows] if rows else []

holidays = read_csv('holiday_uplift.csv')
bf_weeks = read_csv('bf_weeks.csv')
bf_dn = read_csv('bf_day_vs_normal.csv')
bf_cat = read_csv('bf_category.csv')
bf_ser = read_csv('bf_series.csv')
dim_hol = read_csv('dim_holiday.csv')

data['holidays'] = to_records(holidays)
data['bf_weeks'] = to_records(bf_weeks)
data['bf_category'] = to_records(bf_cat)
data['bf_series'] = to_records(bf_ser)
# 节日标记线：只需要 name + date，从 dim_holiday 取（模板内再按名称白名单过滤）
data['holiday_marks'] = [{'name': r['name'], 'date': r['date']} for r in (dim_hol or [])]

# bf_day_vs_normal 是「长表」（每行一个 metric），模板按列取用，转成宽表对象
bf_wide = {'bf_day': {}, 'normal_day': {}, 'diff': {}}
for r in (bf_dn or []):
    m = r.get('metric')
    for side in ('bf_day', 'normal_day', 'diff'):
        bf_wide[side][m] = num(r.get(side))
data['bf_day_vs_normal'] = bf_wide

# 兜底断言：模板 renderHoliday() 直接取 bf_weeks[1]，长度不足会在浏览器里抛
# "Cannot read properties of undefined (reading '1')"，生成阶段就拦下来
assert len(data['bf_weeks']) >= 2, 'bf_weeks 至少需要 2 行（前一周 / 当周）'
assert data['holidays'], 'holidays 不能为空'
assert data['bf_day_vs_normal']['bf_day'].get('orders'), 'bf_day_vs_normal 缺少 orders'
assert data['bf_category'], 'bf_category 不能为空'
assert data['bf_series'], 'bf_series 不能为空'

assert '/*__DATA__*/' in tpl, '模板缺少 /*__DATA__*/ 占位符'
assert '/*__FACT__*/' in tpl, '模板缺少 /*__FACT__*/ 占位符'

html = tpl.replace('/*__ECHARTS__*/', ec).replace('/*__DATA__*/', json.dumps(data, ensure_ascii=False)).replace('/*__FACT__*/', fact)

dst = os.path.join(BASE, 'Olist电商运营分析看板.html')
with io.open(dst, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"生成：{dst}  ({os.path.getsize(dst)/1024/1024:.2f} MB)")

# 同步产出 index.html，作为 GitHub Pages 的入口（内容与上者完全一致）
idx = os.path.join(BASE, 'index.html')
with io.open(idx, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"同步：{idx}  (GitHub Pages 入口)")
