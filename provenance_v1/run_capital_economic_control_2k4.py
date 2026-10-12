# -*- coding: utf-8 -*-
"""گام ۲-ک-۴ P1 — کنترل اقتصادی نهایی بوعلی و کرماشا (فقط-خواندنی).

ورودی‌ها (بدون تحقیق مجدد از صفر):
  * capital_root_cause_{TAG}.json — شواهد رویداد سرمایه‌ای ۲-ک-۳
    (share_intervals، corporate_actions تأییدشده، سناریوها)
  * _p0_share_evidence_{TAG}.json — تایم‌لاین گزارش‌ها و واحدها
  * v2_value_pilot.json — نسبت‌های منتشرشدهٔ موتور + هشدارهای خود موتور
  * DB (read-only): equity/سپرسازمان گزارش برنده برای تایم‌لاین دقیق

خروجی: طبقه‌بندی هر نسبت (P/E، P/B، P/S) در چهار حالت
  verified / verified_with_limitation / requires_review / insufficient_evidence
+ اثر حسابداری افزایش سرمایه بر حقوق صاحبان سهام + متن پیشنهادی پرونده تصمیم‌یار.
هیچ امتیاز/رتبه‌ای تغییر نمی‌کند و هیچ هشداری حذف نمی‌شود.
"""
import json
import os
import re
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psycopg  # noqa: E402

TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
ART = "canonical_postgres_v1_2_1/analytics_canonical_v1/output"
TARGETS = {
    "بوعلی": "c78433dc-e873-4bc9-85c4-794f755e5637",
    "کرماشا": "89bfa0d8-db72-4298-b7cb-166c0304b58d",
}


def build_dsn():
    txt = open("go-app/.env", encoding="utf-8").read()
    d = re.search(r'^DATABASE_URL\s*=\s*"?([^"\n#]+)"?', txt, re.M).group(1).strip()
    d = d.replace("postgresql+psycopg://", "postgresql://")
    ov = re.search(r'^CDF_CANONICAL_DB\s*=\s*"?([^"\n#]+)"?', txt, re.M)
    if ov:
        d = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$",
                   r"postgresql://\g<1>/" + ov.group(1).strip() + r"\g<2>", d)
    return d


def main():
    rc = json.load(open(f"{OUT}/capital_root_cause_{TAG}.json", encoding="utf-8"))
    val = json.load(open(f"{ART}/v2_value_pilot.json", encoding="utf-8"))
    vcomps = val["v_observed_report"]["companies"]
    val_by_sym = {}
    for cid, c in vcomps.items():
        if c.get("symbol") in TARGETS:
            val_by_sym[c["symbol"]] = c

    conn = psycopg.connect(build_dsn(), connect_timeout=15)
    conn.execute("SET default_transaction_read_only = on")
    cur = conn.cursor()

    results = {}
    for sym, cid in TARGETS.items():
        cause = rc["companies"][sym]
        vc = val_by_sym[sym]
        ev = cause["evidence_chain"]
        action = ev["confirmed_rights_issue"]
        md = action["metadata"]
        old_s, new_s = float(md["old_shares"]), float(md["new_shares"])
        ratio = new_s / old_s

        # گزارش برنده: آخرین سلول موتور (period_end از ۲-ک-۳)
        wpe = cause["eps_cross_check_from_2k2"]["winner_period_end"]
        cur.execute(
            """
            SELECT r.id::text, r.source_report_id, r.published_at,
                   r.period_end_date, rv.version_no, r.supersedes_report_id
            FROM fundamentals.financial_statements st
            JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
            JOIN ingestion.reports r ON r.id = st.report_id
            WHERE st.company_id::text = %s AND st.period_end_date = %s::date
              AND r.supersedes_report_id IS NULL
            ORDER BY rv.version_no DESC LIMIT 1
            """, (cid, wpe))
        wrow = cur.fetchone()

        # equity order-1 و سرمایهٔ اعلامی همان سلول (موتور: latest version)
        cur.execute(
            """
            SELECT f.metric_code, f.period_order, f.canonical_value,
                   st.period_end_date, rv.version_no
            FROM fundamentals.financial_facts f
            JOIN fundamentals.financial_statements st ON st.id = f.statement_id
            JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
            JOIN ingestion.reports r ON r.id = st.report_id
            WHERE st.company_id::text = %s
              AND f.metric_code IN ('total_equity', 'capital', 'net_profit',
                                    'eps', 'revenue')
              AND f.period_order = 1
              AND r.supersedes_report_id IS NULL
            ORDER BY st.period_end_date DESC, rv.version_no DESC, f.metric_code
            LIMIT 40
            """, (cid,))
        facts = {}
        for mc, po, cv, ped, vn in cur.fetchall():
            facts.setdefault(mc, {"value": float(cv) if cv is not None else None,
                                  "period_end": str(ped), "version_no": vn})

        # نسبت‌های منتشرشدهٔ موتور + هشدارها
        ratios = {}
        for fid in ("pe", "pb", "ps"):
            f = (vc.get("factors") or {}).get(fid) or {}
            ratios[fid] = {
                "raw_value": f.get("raw_value"),
                "raw_status": f.get("raw_status"),
                "engine_warnings": f.get("warnings") or [],
                "included": f.get("included"),
            }

        # mcap موتور از IV (بازتولید مستقل ۲-ک-۲)
        iv = json.load(open(f"{OUT}/independent_validation_{TAG}.json",
                            encoding="utf-8"))
        ivc = iv["companies"].get(cid) or {}
        mkt = (ivc.get("checks") or {}).get("independent_market") or {}
        mcap = mkt.get("market_cap")
        equity = (facts.get("total_equity") or {}).get("value")

        # طبقه‌بندی هر نسبت
        # P/E و P/S: تجمیعی (mcap ÷ جریان مطلق) — از تغییر تعداد سهام
        # بی‌تأثیر؛ جریان TTM هم از گزارش‌ها به rial مطلق می‌آید.
        # P/B: صورت کسر post-event، مخرج equity گزارش پیش از واریز آورده
        # (حق‌تقدم نقدی) و پیش از ثبت افزایش → گران‌نمایی محافظه‌کارانه.
        pb_limit = {
            "direction": "published_pb_overstates_expensiveness",
            "reason": "mcap با سهام پس از افزایش و equity گزارش پیش از "
                      "واریز آوردهٔ حق‌تقدم/ثبت افزایش است؛ با واریز آورده، "
                      "equity بالا می‌رود و P/B پایین می‌آید (جهت "
                      "محافظه‌کارانه). سهم bonus_reserves در equity خنثی است "
                      "(انتقال درونی) و فقط rights_cash آن را بالا می‌برد.",
            "magnitude": "تا انتشار ترازنامهٔ بعدی قابل کمّی‌سازی نیست "
                         "(سهم حق‌تقدم نقدی از سهام جدید در شواهد موجود "
                         "تفکیک‌نشده است)",
            "inequality": "P/B_true(پس از واریز) <= P/B_published",
        }
        cls = {
            "pe": {"status": "verified",
                   "basis": "mcap/TTM تجمیعی است؛ تعداد سهام در صورت و مخرج "
                            "خنثی می‌شود و EPS گزارش در محاسبه وارد نمی‌شود"},
            "ps": {"status": "verified",
                   "basis": "mcap/فروش TTM تجمیعی؛ فروش جریان مطلق است و از "
                            "رویداد سرمایه‌ای متأثر نمی‌شود"},
            "pb": {"status": "verified_with_limitation", "limitation": pb_limit},
        }

        results[sym] = {
            "company_id": cid,
            "outcome_2k3": cause["outcome"],
            "capital_event": {
                "ex_date": md["ex_date"],
                "old_shares": old_s, "new_shares": new_s,
                "share_ratio": ratio,
                "adjustment_factor": action["adjustment_factor"],
                "funding_tags": md["lt28_funding_tags"],
                "reference_price_before": md["reference_price_before"],
                "reference_price_after": md["reference_price_after"],
                "confirmed": action["is_confirmed"],
                "source": action["source"],
            },
            "winner_report": {
                "report_id": wrow[0] if wrow else None,
                "tracing_no": wrow[1] if wrow else None,
                "published_at": str(wrow[2]) if wrow else None,
                "period_end": str(wrow[3]) if wrow else None,
                "version_no": wrow[4] if wrow else None,
                "declared_capital_rial": (facts.get("capital") or {}).get("value"),
                "total_equity_rial": equity,
                "equity_period_end": (facts.get("total_equity") or {}).get("period_end"),
                "note_capital_base": (
                    "سرمایهٔ اعلامی گزارش = پایهٔ پیش از افزایش؛ یعنی ثبت "
                    "افزایش تا تاریخ ترازنامه در دفاتر شرکت درج نشده است"
                    if (facts.get("capital") or {}).get("value") and
                    abs((facts.get("capital") or {}).get("value", 0) / 1000.0
                        - old_s) / old_s < 0.01 else
                    "سرمایهٔ اعلامی گزارش با پایهٔ پیش از افزایش یکی نیست — "
                    "بررسی دستی لازم"),
            },
            "timeline_control": {
                "ex_date_vs_report_period_end":
                    "پیش از پایان دورهٔ گزارش" if sym == "بوعلی"
                    else "پس از پایان دورهٔ گزارش (تمیز)",
                "ex_date_vs_publish": None,
                "eps_base": "میانگین موزون پیش از افزایش (implied ≈ سرمایهٔ اعلامی)",
                "period_end_economic_shares": new_s,
                "price_basis": "قیمت PIT موتور پس از رویداد (تعدیل‌شدهٔ TSETMC)",
            },
            "accounting_effect_on_equity": {
                "bonus_reserves": "انتقال اندوخته → سرمایه؛ جمع حقوق صاحبان "
                                  "سهام تغییری نمی‌کند؛ فقط تعداد سهام زیاد "
                                  "می‌شود",
                "rights_cash": "با واریز آورده، حقوق صاحبان سهام به اندازهٔ "
                               "مبلغ دریافتی بالا می‌رود؛ تا ثبت/واریز در "
                               "ترازنامهٔ بعدی، مخرج P/B قدیمی است",
                "net_effect": "equity_پس_از_ثبت = equity_گزارش + آوردهٔ نقدی "
                              "(جزء rights_cash)؛ جزء bonus_reserves اثر صفر",
            },
            "published_ratios": ratios,
            "independent_mcap_rial": mcap,
            "implied_equity_from_pb": (mcap / ratios["pb"]["raw_value"]
                                       if mcap and ratios["pb"]["raw_value"]
                                       else None),
            "ratio_classification": cls,
            "kept_warnings": [
                "هشدار خود موتور (share_snapshot_older_than_price) حفظ می‌شود: "
                "فاصلهٔ ۳روزهٔ snapshot سهام و قیمت و عدم اثبات سازگاری "
                "رویداد سرمایه‌ای بین دو تاریخ",
                "هشدار ۲-ک-۲ (ناسازگاری EPS/سهام) توضیح داده شد ولی حذف "
                "نمی‌شود؛ تا نامهٔ فصلی بعدی به‌صورت پایشی می‌ماند",
            ],
            "diagnostic_display": {
                "pe_ps": "بدون اعوجاج از رویداد سرمایه‌ای — قابلیت اتکای "
                         "مقایسه‌ای مثل بقیهٔ همتاها",
                "pb": "گران‌نمایی محافظه‌کارانه با کف نامعلوم؛ برای مقایسهٔ "
                      "درون‌گروهی تا ترازنامهٔ بعدی با احتیاط",
                "eps_mixing_trap": "نمایش «قیمت امروز ÷ EPS گزارش (پایهٔ "
                                   "قدیم)» معتبر نیست؛ در UI هرگز محاسبه "
                                   "نمی‌شود (سناریو C ۲-ک-۳)",
            },
        }

    conn.rollback()
    conn.close()

    out = {
        "mission": "گام ۲-ک-۴ P1 — کنترل اقتصادی نهایی بوعلی/کرماشا (read-only)",
        "binding": rc.get("binding"),
        "summary": {
            "pe": "verified برای هر دو شرکت — نسبت تجمیعی از تغییر پایهٔ سهام "
                  "بی‌تأثیر است",
            "ps": "verified برای هر دو شرکت — فروش جریان مطلق است",
            "pb": "verified_with_limitation برای هر دو شرکت — مخرج پیش از "
                  "واریز آورده است؛ جهت گران‌نمایی محافظه‌کارانه؛ بزرگی تا "
                  "ترازنامهٔ بعدی کمّی نمی‌شود",
            "no_score_change": True,
            "no_warning_removed": True,
        },
        "companies": results,
    }
    jp = os.path.join(OUT, f"_p1_economic_control_{TAG}.json")
    json.dump(out, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("wrote", jp)

    # خلاصهٔ متنی
    for sym, r in results.items():
        wr = r["winner_report"]
        print(f"== {sym}: ex={r['capital_event']['ex_date']} "
              f"{r['capital_event']['old_shares']/1e9:.2f}B→"
              f"{r['capital_event']['new_shares']/1e9:.2f}B "
              f"report {wr['period_end']} capital="
              f"{(wr['declared_capital_rial'] or 0)/1e9:.1f}B rial "
              f"equity={(wr['total_equity_rial'] or 0)/1e12:.2f}T "
              f"({wr['equity_period_end']})")
        for fid in ("pe", "pb", "ps"):
            print(f"   {fid}={r['published_ratios'][fid]['raw_value']:.3f} "
                  f"→ {r['ratio_classification'][fid]['status']}")


if __name__ == "__main__":
    main()
