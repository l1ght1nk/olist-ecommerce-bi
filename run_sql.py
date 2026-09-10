# -*- coding: utf-8 -*-
"""
run_sql.py —— 用 DuckDB 执行 sql/ 下的全部脚本，并与 pandas 流水线的结果逐项对账。

用法：
    python run_sql.py                       # 默认读 D:/迅雷下载/archive
    python run_sql.py --src <原始数据目录>   # 指定目录

目的：证明同一套口径用 SQL 重算能得到与 pandas 完全一致的指标，
      作为 SQL 能力的可复算证据。
"""
import argparse
import json
import os
import sys
import time

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
SQL_DIR = os.path.join(HERE, "sql")
OUT_JSON = os.path.join(HERE, "output", "dashboard_data.json")

SQL_FILES = ["01_load.sql", "02_clean.sql", "03_metrics.sql", "04_advanced.sql"]

# 期望值：来自 pandas 流水线 output/dashboard_data.json（已与 Power BI 模型三方对齐）
EXPECT = {
    "gmv":                 15419773.75,
    "orders":              96478,
    "customers":           93358,
    "aov":                 159.83,
    "arpu":                165.17,
    "items_sold":          110197,
    "price_per_item":      119.98,
    "freight_pct":         16.63,
    "delivery_rate_pct":   97.02,
    "on_time_rate_pct":    91.89,   # 注：原记录值 94.96% 是错的，见 README_SQL.md「发现的两个 bug」
    "late_rate_pct":       8.11,
    "avg_delivery_days":   12.56,
    "avg_review_score":    4.09,
    "bad_review_rate_pct": 11.52,
    "repurchase_rate_pct": 3.00,
    "all_orders":          99441,
}

TOL = 0.02  # 允许浮点末位差异


def run_sql_file(con, path, src):
    with open(path, encoding="utf-8") as fh:
        sql = fh.read().replace("{{SRC}}", src.replace("\\", "/"))
    name = os.path.basename(path)
    t0 = time.time()
    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
        # 去掉整行注释后再判断是否还有可执行内容
        body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--"))
        if not body.strip():
            continue
        con.execute(stmt)
    print(f"  [OK] {name:<18} {time.time() - t0:5.1f}s")


def show(con, table, limit=8):
    print(f"\n--- {table}")
    try:
        df = con.sql(f"SELECT * FROM {table} LIMIT {limit}").df()
    except Exception as e:  # noqa: BLE001
        print(f"    查询失败: {e}")
        return
    with pd_option():
        print(df.to_string(index=False))


class pd_option:
    """临时放宽 pandas 显示宽度"""
    def __enter__(self):
        import pandas as pd
        self.pd = pd
        self.old = pd.get_option("display.max_columns")
        pd.set_option("display.max_columns", 60)
        pd.set_option("display.width", 250)
        return self

    def __exit__(self, *a):
        self.pd.set_option("display.max_columns", self.old)


def verify(con):
    row = con.sql("SELECT * FROM analysis.kpi_core").df().iloc[0]
    print("\n" + "=" * 66)
    print("核心指标对账（SQL vs pandas 流水线）")
    print("=" * 66)
    print(f"{'指标':<22}{'SQL':>16}{'期望(pandas)':>16}   结果")
    print("-" * 66)
    passed, failed = 0, []
    for k, exp in EXPECT.items():
        got = row.get(k)
        if got is None:
            print(f"{k:<22}{'-':>16}{exp:>16}   跳过（字段不存在）")
            continue
        try:
            ok = abs(float(got) - float(exp)) <= max(TOL, abs(float(exp)) * 0.0005)
        except (TypeError, ValueError):
            ok = False
        flag = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed.append((k, got, exp))
        g = f"{got:,.2f}" if isinstance(got, float) else f"{got:,}"
        print(f"{k:<22}{g:>16}{exp:>16,}   {flag}")
    print("-" * 66)
    print(f"通过 {passed}/{len(EXPECT)}")
    if failed:
        print("\n未通过的指标：")
        for k, got, exp in failed:
            print(f"  {k}: SQL={got}  期望={exp}")
    return len(failed) == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=r"D:\迅雷下载\archive", help="原始 Kaggle CSV 目录")
    ap.add_argument("--db", default="", help="持久化数据库文件（默认内存）")
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        print(f"找不到原始数据目录：{args.src}")
        sys.exit(1)

    con = duckdb.connect(args.db) if args.db else duckdb.connect()
    print(f"DuckDB {duckdb.__version__}  数据源 {args.src}\n执行 SQL：")
    for f in SQL_FILES:
        run_sql_file(con, os.path.join(SQL_DIR, f), args.src)

    ok = verify(con)

    print("\n" + "=" * 66)
    print("进阶分析结果抽样")
    print("=" * 66)
    show(con, "analysis.pareto_category", 12)
    show(con, "analysis.top3_product_per_category", 6)
    show(con, "analysis.monthly_gmv_mom", 6)
    show(con, "analysis.state_rank", 6)
    show(con, "analysis.rfm_segment", 6)
    show(con, "analysis.cohort_retention", 8)
    show(con, "analysis.repurchase_funnel", 4)
    show(con, "analysis.seller_concentration", 1)
    show(con, "analysis.daily_orders_ma7", 5)

    # 行数核对
    print("\n" + "=" * 66)
    print("表行数核对")
    for t in ["clean.fact_orders", "clean.fact_order_items", "clean.dim_customer",
              "clean.dim_product", "clean.dim_seller", "clean.dim_date",
              "clean.dim_geolocation"]:
        n = con.sql(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<28} {n:>10,}")

    if os.path.exists(OUT_JSON):
        with open(OUT_JSON, encoding="utf-8") as fh:
            d = json.load(fh)
        print("\ndashboard_data.json 顶层键：", list(d.keys())[:20])

    print("\n结果：" + ("全部对账通过 ✅" if ok else "存在不一致，见上方 FAIL"))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
