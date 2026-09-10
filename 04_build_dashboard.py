# -*- coding: utf-8 -*-
"""把 ECharts、指标数据、紧凑事实表注入模板，生成单文件离线交互看板 HTML"""
import os, json, io

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, 'output')

tpl = io.open(os.path.join(BASE, 'dashboard_template.html'), encoding='utf-8').read()
data = io.open(os.path.join(OUT, 'dashboard_data.json'), encoding='utf-8').read()
fact = io.open(os.path.join(OUT, 'fact_compact.json'), encoding='utf-8').read()
ec = io.open(os.path.join(BASE, 'echarts.min.js'), encoding='utf-8').read()

assert '/*__DATA__*/' in tpl, '模板缺少 /*__DATA__*/ 占位符'
assert '/*__FACT__*/' in tpl, '模板缺少 /*__FACT__*/ 占位符'

html = tpl.replace('/*__ECHARTS__*/', ec).replace('/*__DATA__*/', data).replace('/*__FACT__*/', fact)

dst = os.path.join(BASE, 'Olist电商运营分析看板.html')
with io.open(dst, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"生成：{dst}  ({os.path.getsize(dst)/1024/1024:.2f} MB)")
