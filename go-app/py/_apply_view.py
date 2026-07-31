import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
import importlib.util

spec = importlib.util.spec_from_file_location("brs", "py/brs_prices.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

conn = m.get_db_connection()
cur = conn.cursor()

sql_text = Path("sql/vw_AIStockMetrics.sql").read_text(encoding="utf-8-sig")
batches = [b.strip() for b in sql_text.split("\nGO") if b.strip()]
for i, batch in enumerate(batches, 1):
    try:
        cur.execute(batch)
        conn.commit()
    except Exception:
        conn.rollback()

cur.execute("""
    SELECT TOP 5 Symbol,
        ROUND(GrowthScore, 1) AS growth,
        ROUND(ProfitabilityScore, 1) AS profit,
        ROUND(ValuationScore, 1) AS valuation,
        ROUND(MarketScore, 1) AS market,
        ROUND(QuantScore, 1) AS total
    FROM dbo.vw_AIStockMetrics
    ORDER BY QuantScore DESC
""")
print(f"{'نماد':10} | {'رشد/43':>7} | {'سود/28':>7} | {'ارزش/13':>8} | {'بازار/16':>8} | {'کل':>5}")
print("-" * 60)
for r in cur.fetchall():
    print(f"{r[0]:10} | {r[1]:>7} | {r[2]:>7} | {r[3]:>8} | {r[4]:>8} | {r[5]:>5}")

cur.close()
conn.close()
