# Olist 项目 · SQL 复刻（DuckDB）

用 SQL 把 pandas 流水线的**清洗 + 建模 + 指标**全过程重做一遍，两套实现交叉验证。
目的是验证指标口径的正确性——两套独立实现互为参照，任何一处偏差都会在对账中暴露。

## 30 秒跑起来

```bash
# 1) 装依赖（已装在隔离环境，可跳过）
pip install duckdb

# 2) 跑全部脚本 + 自动对账
python run_sql.py --src "D:\迅雷下载\archive"
```

输出：4 个 SQL 脚本的执行耗时 → **核心指标对账表（SQL vs pandas）** → 9 张进阶分析表抽样 → 表行数核对。

## 文件结构

| 文件 | 作用 | 对应 pandas |
|---|---|---|
| `sql/01_load.sql` | 9 张原始 CSV 接入（建 raw schema） | `01_explore.py` |
| `sql/02_clean.sql` | 清洗 + 星型建模（2 事实 + 5 维度） | `02_clean_model.py` |
| `sql/03_metrics.sql` | 核心指标（KPI 宽表 / 月度 / 州 / 品类） | `03_metrics.py` |
| `sql/04_advanced.sql` | 窗口函数 · 同期群 · 漏斗 | — |
| `run_sql.py` | 执行器 + 与 pandas 结果自动对账 | — |

## 对账结果（16/16 全部通过）

| 指标 | SQL | pandas | | 指标 | SQL | pandas |
|---|---|---|---|---|---|---|
| GMV | 15,419,773.75 | 15,419,773.75 | | 交付完成率% | 97.02 | 97.02 |
| 订单数 | 96,478 | 96,478 | | 准时率% | 91.88 | 91.89 |
| 客户数 | 93,358 | 93,358 | | 延误率% | 8.11 | 8.11 |
| AOV | 159.83 | 159.83 | | 平均配送天数 | 12.56 | 12.56 |
| ARPU | 165.17 | 165.17 | | 平均评分 | 4.09 | 4.09 |
| 销售件数 | 110,197 | 110,197 | | 差评率% | 11.52 | 11.52 |
| 件单价 | 119.98 | 119.98 | | 复购率% | 3.00 | 3.00 |
| 运费占比% | 16.63 | 16.63 | | 全量订单数 | 99,441 | 99,441 |

表行数也逐项一致：fact_orders 99,441 / fact_order_items 112,650 / dim_customer 96,096 /
dim_product 32,951 / dim_seller 3,095 / dim_date 1,096 / dim_geolocation 19,015（由 100 万行聚合而来）。

## SQL 能力覆盖清单

| 能力点 | 用在哪 | 关键写法 |
|---|---|---|
| 多表 JOIN + 一对多聚合 | 02 · 支付/明细聚合到订单粒度 | `LEFT JOIN` + `GROUP BY order_id` |
| 分组取 TopN | 02 · 主支付方式取金额最大的一笔 | `ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY payment_value DESC)` |
| 重复记录去重 | 02 · 一个订单多条评论取最新 | `ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY ... DESC NULLS LAST)` |
| 累计求和（帕累托） | 04 · 品类累计占比 | `SUM(gmv) OVER (ORDER BY gmv DESC ROWS UNBOUNDED PRECEDING)` |
| 分组排名 TopN | 04 · 每个品类 TOP3 商品 | `ROW_NUMBER() OVER (PARTITION BY category ORDER BY gmv DESC)` |
| 环比 / 同比 | 04 · 月度 GMV | `LAG(gmv) OVER (ORDER BY year_month)`、`LAG(gmv, 12)` |
| 排名函数 | 04 · 州 GMV 排名 | `RANK / DENSE_RANK / PERCENT_RANK` |
| 移动平均 | 04 · 每日订单 7 日均值 | `AVG(...) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)` |
| 分箱 | 04 · RFM 打分 | `NTILE(5) OVER (ORDER BY ...)` + 业务规则 CASE |
| 同期群留存 | 04 · cohort × 第 N 月 | 自连接 + `YEAR*12+MONTH` 月份差 + 窗口取 cohort 规模 |
| 漏斗转化 | 04 · 复购漏斗 | UNION ALL 阶梯 + `MAX() OVER ()` 求分母 |
| CTE 多层嵌套 | 全部 | `WITH ... AS` 链式派生 |

## 通过交叉验证发现的两个问题

### 1. 准时率算成了 −108%（真 bug，已修）

`03_metrics.py` 原有写法：

```python
'on_time_rate': float((~d['is_late']).mean() * 100)
```

`is_late` 含 NaN 时是 object dtype，`~` **退化成按位取反**（`~True = -2`、`~False = -1`），
于是 `(88652×(-1) + 7826×(-2)) / 96478 = -1.0811` → **−108.11%**。

已改为显式比较 `(d['is_late'] == False).mean() * 100` → **91.89%**。
HTML 看板当时没中招是因为前端 JS 自己重算了一遍；Power BI 侧的同名度量值也已同步修正为 91.89%。

### 2. 评分口径两套（不是 bug，是有意保留的口径决策）

| 口径 | 平均评分 | 差评率 | 用在哪 |
|---|---|---|---|
| 全量（含未送达 2,963 单） | **4.09** | 11.52% | Power BI、SQL |
| 已交付 | 4.16 | 9.76% | HTML 看板 |

未送达订单均分仅 1.74 分——**没收到货给的 1 星也是真实口碑**，所以 BI 侧保留全量口径；
测算履约对口碑的影响时（配送分档 vs 评分），必须用它才看得到"未送达 1.74 分"这一档。
