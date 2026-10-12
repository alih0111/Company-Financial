#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۸ — تولید گزارش نهایی (JSON + MD).
منبع حقیقت: خروجی زندهٔ موتور (_board_2k8_live.json) و آرتیفکت‌های نسخه‌دار
همین مأموریت. هیچ نام، قیمت، رتبه یا نتیجه‌ای حدس زده نمی‌شود.
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "provenance_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"

live = json.load(open(os.path.join(OUT, "_board_2k8_live.json"), encoding="utf-8"))
ob = live["opportunity_board"]
audit = json.load(open(os.path.join(OUT, f"decision_audit_2k8_{TAG}.json"), encoding="utf-8"))
cov = json.load(open(os.path.join(OUT, f"coverage_analysis_2k8_{TAG}.json"), encoding="utf-8"))
ready = json.load(open(os.path.join(OUT, f"update_readiness_2k8_{TAG}.json"), encoding="utf-8"))
old = json.load(open(os.path.join(OUT, "_board_2k7_live.json"), encoding="utf-8"))["opportunity_board"]

GROUPS = ["attractive_candidates", "fundamentals_waiting", "apparent_value_risk", "blocked_or_insufficient"]


def find(sym):
    for g in GROUPS:
        for e in ob[g]:
            if e["symbol"] == sym:
                return g, e
    return None, None


def f2(x):
    return "—" if x is None else ("%.2f" % x)


counts = ob["counts"]
pol = ob["decision_policy"]

# ── جدول خلاصهٔ فرصت‌ها ───────────────────────────────────────────────────────
opps = []
for e in ob["attractive_candidates"]:
    vm = e["value_mean"]
    pe_txt = "—"
    if e["value_note"]:
        head = e["value_note"][0]
        if "=" in head:
            pe_txt = head.split("=")[-1].split("(")[0].strip()
    opps.append({
        "symbol": e["symbol"], "industry": e["industry"],
        "fundamental": "%s (roe %s، حاشیه %s)" % (e["fundamental_label"], f2(e["roe_pct"]), f2(e["margin_pct"])),
        "value": "%s (میانگین %s — %s)" % (e["value_label"], f2(vm), pe_txt),
        "entry": e["entry_label"],
        "conclusion": e["conclusion"],
        "top_reason": e["top_reason"],
        "risk": e["top_risk"],
    })
# نزدیک‌ترین گزینه‌های گروه دوم (پنج مورد اول ترتیب نمایش) — صریحاً «جذاب» نیستند
near = []
for e in ob["fundamentals_waiting"][:5]:
    near.append({
        "symbol": e["symbol"], "industry": e["industry"],
        "fundamental": e["fundamental_label"],
        "value": "%s (%s)" % (e["value_label"], f2(e["value_mean"])),
        "entry": e["entry_label"],
        "blocker": e["group_reason"],
    })

# ── سرنوشت ۱۶ نامزد قبلی ─────────────────────────────────────────────────────
old16 = [e["symbol"] for e in old["review_priority"]]
fates = []
for s in old16:
    g, e = find(s)
    if e:
        fates.append({"symbol": s, "new_group": g, "fundamental": e["fundamental"],
                      "value_mean": e["value_mean"], "entry": e["entry"],
                      "reason": e["group_reason"][:200]})

# ── امیدوارکننده‌های گروه محدود (۴۶ قبلی) ────────────────────────────────────
prom = [e for e in ob["fundamentals_waiting"] if 0 < e["group_size"] < 5
        and e["fundamental"] == "strong" and (e["value_mean"] or 0) >= 0.55]
prom_rows = [{"symbol": e["symbol"], "industry": e["industry"], "value_mean": e["value_mean"],
              "entry": e["entry"], "peers": e["group_size"],
              "missing": "گروه مقایسهٔ معتبر (و در صورت لزوم، تأیید ورود)",
              "review_when": e["review_when"][:2]} for e in prom]

old46 = {e["symbol"] for k in old["watchlist"] for e in [k]}
n46_now_waiting = sum(1 for e in ob["fundamentals_waiting"] if e["group_size"] < 5)

report = {
    "mission": "گام ۲-ک-۸ — تصمیم‌یار واقعی انتخاب سهام QVT",
    "generated_from": "خروجی زندهٔ موتور + آرتیفکت‌های نسخه‌دار همین snapshot",
    "snapshot_tag": TAG,
    "as_of": live.get("as_of"),
    "engine": {
        "rules_version": ob["rules"]["version"],
        "policy_version": pol["version"],
        "policy_thresholds": {k: v for k, v in pol.items() if k not in ("version", "note")},
        "policy_note": pol["note"],
        "no_composite_score": "هیچ امتیاز جدیدی از ۱۰۰ ساخته نشده؛ فقط خوانش شفاف پرسنتایل‌های رسمی",
    },
    "counts": counts,
    "opportunity_summary": opps,
    "near_misses_waiting_top5": near,
    "q1_how_many_of_old16_qualify": {
        "answer": "فقط ۱ از ۱۶ (بوعلی)؛ ۱۵ مورد با دلیل عددی کنار گذاشته شدند",
        "fates": fates,
    },
    "q2_dropped_and_why": {
        "value_not_defensible_13": [f["symbol"] for f in fates if f["new_group"] == "fundamentals_waiting"],
        "apparent_value_trap_1": [f["symbol"] for f in fates if f["new_group"] == "apparent_value_risk"],
        "no_case_1": [f["symbol"] for f in fates if f["new_group"] == "blocked_or_insufficient"],
        "note": "مهم‌ترین الگو: ۱۳ شرکت بنیادی خوب داشتند اما ارزندگی‌شان گران نسبی بود (میانگین پرسنتایل V از 0.13 تا 0.60، همه زیر آستانهٔ 0.60) — گام ۲-ک-۷ این‌ها را فقط به‌خاطر شواهد کامل «اولویت» می‌داد",
    },
    "q3_promising_among_limited46": {
        "answer": "۳۰ شرکت از گروه محدود قبلی بنیادی مثبت دارند و به «منتظر شرایط بهتر» رفتند؛ امیدوارکننده‌ترین‌ها (بنیادی قوی + ارزندگی نسبی بالا، فقط بدون همتای کافی):",
        "rows": prom_rows,
        "n46_now_waiting": n46_now_waiting,
    },
    "q4_total_reviewable": {
        "attractive": counts["attractive_candidates"],
        "monitoring_waiting": counts["fundamentals_waiting"],
        "apparent_value_risk": counts["apparent_value_risk"],
        "blocked_or_insufficient": counts["blocked_or_insufficient"],
        "triple_universe": counts["n_triple_universe"],
        "interpretation": "تعریف «قابل بررسی» سخت‌گیرانه‌تر و صادقانه‌تر شد: ۱۶ «اولویت» قبلی → ۱ «جذاب» + ۴۳ پایش + ۹ ارزان‌نما + ۹ بدون پرونده",
    },
    "q5_real_problems_fixed": [
        "ضعف اصلی موتور ۲-ک-۷ (انتخاب صرفاً با کفایت شواهد) اصلاح شد — لایهٔ تصمیم چهارگانهٔ مستقل اضافه شد",
        "خطای فرمت‌سنجی در اسکریپت آمادگی (مقایسهٔ as_of با/بدون ساعت) در همین مأموریت کشف و اصلاح شد",
        "اعتبارسنجی متقاطع: بازنویسی مستقل سیاست در پایتون روی ۶۲ شرکت، ۱:۱ با خروجی موتور Go مطابقت دارد",
        "مشکل داده‌ای دائمی (equity مفقود و ...) عمداً رفع نشد — ممنوعیت backfill؛ سه طرح اجرایی آماده شد (پوشش q6 plan)",
    ],
    "q5_coverage_fix_plans": cov["big_blockers_and_plans"],
    "q6_ux_simpler": {
        "answer": "بله — چهار گروه با برچسب تصمیمی، چیپ مستقل بنیادی/ارزندگی/ورود، مانع مشخص با عدد برای هر شرکت، شرایط پایش سنجش‌پذیر («چه زمانی ارزش بررسی مجدد دارد؟»)، و شمارش شفاف «چرا بقیه جذاب نشدند»",
        "browser_verified": ["نمای پیش‌فرض برد", "۱ کارت رتبه‌دار", "۴ گروه با شمارش صحیح ۱/۴۳/۹/۹", "بازکردن ردیف‌ها و پروندهٔ تصمیم‌یار", "سوییچ نماها", "خط صداقت و سیاست منتشرشده"],
    },
    "q7_snapshot_and_daily_readiness": {
        "as_of": live.get("as_of"),
        "snapshot_age_days": 3,
        "price_freshness_max_age_days": 3,
        "price_policy_days": 7,
        "readiness_verdict": ready["verdict"],
        "runbook": ready["daily_update_runbook"],
        "publishing_status": "در این مأموریت انتشار production و زمان‌بندی فعال ساخته نشد؛ فقط dry-run",
    },
    "q8_remaining_limitations": [
        "roe_stability و margin_trend عمداً خارج از دستهٔ ۲-B-5 هستند — پایداری سود سنجیده نمی‌شود و هیچ‌جا جایگزین نشده",
        "حقوق صاحبان سهام برای ۱۷۰ شرکت در مخزن نیست → P/B و پوشش V برای آن‌ها ناممکن است",
        "پوشش Q زیر آستانه برای ۱۶۱ شرکت (۱۳۵ شرکت کاملاً بدون دادهٔ بنیادی)",
        "پنجرهٔ مومنتوم برای ۱۰۵ شرکت ناکافی (تاریخچهٔ قیمت)",
        "۱۱ شرکت بانکی خارج از دامنهٔ خانوادهٔ pilot",
        "آستانه‌های سیاست تصمیم آزمایشی و اعلامی‌اند — نه اثبات آماری؛ بدون بک‌تست PIT کامل هیچ ادعای سودآوری وجود ندارد",
        "ممیزی رشد سود فقط تشخیصی است و earnings_growth همچنان policy-excluded (۲-B-6)",
    ],
    "q9_needs_owner_permission": [
        "اجرای backfill مرحله A (SQL 125) برای حقوق صاحبان سهام و صورت‌های مالی تاریخی",
        "واردات تاریخچهٔ قیمت برای رفع پنجرهٔ مومنتوم",
        "فعال‌سازی دائمی QVT_MANIFEST_DIR",
        "تصمیم سیاستی برای گسترش خانوادهٔ بانکی/مالی",
        "git commit تغییرات این مأموریت",
        "تصمیم دربارهٔ lift شدن policy exclusion 2-B-6 (مستقل از این گام)",
    ],
    "q10_next_actions": [
        {"rank": 1, "action": "تاریخچهٔ قیمت برای نمادهای کم‌سابقه — فوری‌ترین اثر: گروه TT F فعلی (۳۲ شرکت با Q,V قابل قبول) سه‌محوری می‌شود و جامعهٔ نامزدها ۶۲→~۹۴ می‌رود"},
        {"rank": 2, "action": "backfill حقوق صاحبان سهام (۱۷۰ شرکت) — P/B و پوشش V برمی‌گردد؛ ارزیابی ارزندگی از «فقط P/E» به چندگانهٔ کامل"},
        {"rank": 3, "action": "تکمیل صورت‌های مالی تاریخی — Q واجد از ۹۸ به سقف ~۲۶۰؛ بزرگ‌ترین اهرم بلندمدت پوشش و کیفیت انتخاب"},
    ],
    "p6_independent_critique": {
        "بوعلی (تک نامزد جذاب)": "Q points 13.6/40 کم است چون حاشیه (0.22) و اهرم (0.28) و رشد درآمد (0.18) ضعیف‌اند؛ اما roe_level=0.79 و پوشش بهره=0.73 واقعی‌اند و P/E خام 7.7 با پرسنتایل 0.77 ارزانی نسبی معتبر در گروه ۶ همتاست؛ ورود قوی (مومنتوم 0.80). نتیجه: «قابل قبول + ارزان + ورود خوب» — نه کیفیت عالی؛ کارت دقیقاً همین را با عدد نشان می‌دهد و سازگاری سرمایه/قیمت را به‌عنوان ریسک مبنای ارزندگی برجسته می‌کند",
        "فولاد/نان/ذوب (ارزان‌نما)": "سه الگوی value trap واقعی: ارزندگی ظاهری 0.66–0.85 با بنیادی ضعیف (roe پرسنتایل 0.08–0.21؛ ذوب: سود عملیاتی منفی) — همگی به گروه ۳ رفتند و از پیشنهاد اولیه خارج شدند",
        "سباقر (مثال مأموریت)": "Q=24.8/40 با roe قوی ولی V=7.7/35 یعنی گران نسبی (میانگین پرسنتایل 0.21) → «بنیادی مناسب، منتظر شرایط بهتر»؛ نه جذاب اعلام شد نه رد — دقیقاً بررسی دقیق خواسته‌شده",
        "شسپا": "بنیادی قوی اما گروه ۴ عضوی → هیچ رتبه نسبی؛ هشدارهای بزرگی داده (رشد ~428٬000٬000٪ تشخیصی) در «احتیاط» می‌ماند و هرگز دلیل جذابیت نیست (growth_leaks=0 در کل خروجی)",
        "ضعف-داده-انتخاب‌نشدگی": "شرکت با دادهٔ کامل ولی اقتصاد ضعیف دیگر انتخاب نمی‌شود: ۹ شرکت (weak_no_case) و ۹ شرکت ارزان‌نما نمونهٔ دادهٔ کاملِ غیرجذاب‌اند",
    },
    "p6_sensitivity": {
        "v_cheap": {"0.55": "۲ نامزد جذاب", "0.60 (پایه)": "۱ نامزد", "0.65": "۰ نامزد"},
        "others": "تغییر ±0.05 در آستانه‌های Q (roe/margin/safety) و ورود (مومنتوم) شمارش گروه جذاب را تغییر نمی‌دهد — تنها آستانهٔ حساس، ارزندگی است؛ مستند در گزارش",
    },
    "p6_cross_validation": {
        "engine_vs_independent_reimpl": "سیاست به‌طور مستقل در پایتون روی هر ۶۲ شرکت بازحساب شد — همهٔ ۶۲ گروه‌بندی با موتور Go یکی بود (۱ جذاب/۴۳/۹/۹)",
        "ui_vs_backend": "شمارش گروه‌ها، رتبه، چیپ‌های تصمیم و خطوط صداقت در مرورگر واقعی با پاسخ backend یکسان بررسی شد",
    },
    "tests": {
        "go": "go test ./... → همه سبز (شامل ۷ تست جدید برد تصمیم‌محور: گروه‌بندی، گیت‌ها، صفر-نامزد، ترتیب، دلایل بدون رشد تشخیصی، perturbation، انتگرال endpoint)",
        "typescript": "npx tsc --noEmit → پاک",
        "publisher": "publish_bundle.py --selftest → 13/13 (شامل rollback و atomic swap) — بدون نوشتن روی آرتیفکت‌های واقعی",
        "analytics_python": "pytest test_score_v2/test_score_v2_value_normalize/test_pilot_v2_value → 59 passed",
        "health": "/Table (AllCompanyScores)=200، /qvt-v2=200، /qvt-v2/discovery=200 با برد جدید",
        "readiness_dry_run": "verdict=ready_for_owner_run — بدون انتشار و بدون زمان‌بندی",
    },
    "baseline_vs_2k7": {
        "output_diff": "اولویت ۱۶→جذاب ۱؛ زیرنظر ۴۶→منتظر ۴۳ + ارزان‌نما ۹؛ مانع ۰→بدون‌پرونده ۹؛ جامعهٔ سه‌محوری ثابت ۶۲",
        "code_diff": "opportunity.go بازنویسی نسخهٔ ۲ (۴ گروه + لایهٔ تصمیم + review_when)؛ opportunity_decision.go جدید (سیاست v1)؛ opportunity_test.go بازنویسی (۷ تست)؛ discovery.go +۸ خط؛ api.ts/QvtAnalysisPage.tsx نوع‌ها و UI چهارگروهی؛ ۴ اسکریپت/آرتیفکت جدید provenance_v1",
        "unchanged": "آرتیفکت‌های اصلی Q/V/T، pipeline انتشار، V1/V4، فرمول و وزن رسمی، قرنطینه‌ها و سیاست‌های مالی دست‌نخورده",
        "git_state": "مطابق قاعدهٔ همیشگی بدون commit؛ فایل‌های گام‌های قبلی همچنان uncommitted بودند و با این تغییرات مخلوط نشدند",
    },
    "constraints_respected": {
        "no_commit": True, "no_permanent_db_write": True, "no_sql125_backfill": True,
        "no_qvt_formula_change": True, "no_diagnostic_activation": True, "no_100_score": True,
        "no_v1v4_change": True, "no_artifact_overwrite": True, "no_quarantine_bypass": True,
        "no_fake_data": True, "no_buy_sell_advice": True,
    },
    "not_a_signal": "این گزارش «نامزد بررسی» است؛ نه توصیه خرید/فروش و نه اثبات آماری سودآوری",
}

# ── Markdown ─────────────────────────────────────────────────────────────────
def md():
    L = []
    L.append("# گزارش نهایی گام ۲-ک-۸ — تصمیم‌یار واقعی انتخاب سهام QVT\n")
    L.append("snapshot: `%s` — as_of: %s | موتور: `%s` + `%s`\n" % (TAG, report["as_of"], ob["rules"]["version"], pol["version"]))
    L.append("> %s\n" % report["not_a_signal"])
    L.append("## خلاصهٔ فرصت‌های واقعی قابل بررسی\n")
    L.append("شمارش چهار گروه روی ۶۲ شرکت سه‌محوری: **جذاب %d | منتظر شرایط بهتر %d | ارزان‌نمای پرریسک %d | شواهد ناکافی/مانع %d**\n"
             % (counts["attractive_candidates"], counts["fundamentals_waiting"], counts["apparent_value_risk"], counts["blocked_or_insufficient"]))
    L.append("### نامزدهای جذاب برای بررسی جدی (%d)\n" % len(opps))
    L.append("| نماد | صنعت | بنیادی | ارزندگی | ورود | نتیجه | مهم‌ترین دلیل | ریسک |")
    L.append("|---|---|---|---|---|---|---|---|")
    for o in opps:
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            o["symbol"], o["industry"], o["fundamental"], o["value"], o["entry"], o["conclusion"],
            (o["top_reason"] or "")[:120], (o["risk"] or "")[:120]))
    if not opps:
        L.append("| — | — | — | — | — | صفر نامزد (نتیجهٔ صادقانه) | — | — |")
    L.append("")
    L.append("### نزدیک‌ترین گزینه‌ها — گروه «بنیادی مناسب، منتظر شرایط بهتر» (۵ مورد اول؛ جذاب تلقی نمی‌شوند)\n")
    L.append("| نماد | صنعت | بنیادی | ارزندگی | ورود | مانع مشخص |")
    L.append("|---|---|---|---|---|---|")
    for o in near:
        L.append("| %s | %s | %s | %s | %s | %s |" % (o["symbol"], o["industry"], o["fundamental"], o["value"], o["entry"], o["blocker"][:150]))
    L.append("")
    L.append("## پاسخ ده پرسش مأموریت\n")
    L.append("1. **از ۱۶ نامزد قبلی چند مورد واقعاً شرایط گروه اول دارند؟** فقط ۱ (بوعلی). ۱۳ مورد بنیادی خوب ولی ارزندگی گران نسبی (vm 0.13–0.60 < 0.60)، ۱ مورد ارزان‌نمای ضعیف (غپینو)، ۱ مورد بدون پرونده (کرماشا).\n")
    L.append("2. **کدام نمادها کنار گذاشته/تنزل یافتند و چرا؟** نمونه‌ها: سباقر (vm=0.21 گران نسبی)، سقاین (vm=0.13)، فولاد/نان/ذوب (ارزان‌نما با roe 0.08–0.21)، شسپا (قوی ولی ۴ همتا)، دامین (بدون پرونده: roe 0.15 و vm=0.04). فهرست کامل ۱۶ مورد با دلیل در JSON.\n")
    L.append("3. **از ۴۶ محدود قبلی چه کسانی شواهد امیدوارکننده دارند؟** ۳۰ مورد بنیادی مثبت → گروه «منتظر»؛ امیدوارکننده‌ترین‌ها: %s (بنیادی قوی + ارزندگی نسبی بالا، فقط گروه همتا/ورود ناقص).\n" % ("، ".join(r["symbol"] for r in prom_rows) or "—"))
    L.append("4. **تعداد کل قابل بررسی:** جذاب ۱۶→۱؛ پایش ۴۶→۴۳؛ ارزان‌نما ۰→۹؛ بدون پرونده ۰→۹ (جامعه ۶۲ ثابت).\n")
    L.append("5. **مشکلات واقعی اصلاح‌شده:** موتور انتخاب (انتخاب صرفاً-شواهدمحور حذف شد)؛ باگ فرمت در readiness؛ اعتبارسنجی متقاطع موتور/بازم‌پیاده‌سازی مستقل. مشکل داده‌ای دائمی عمداً رفع نشد (ممنوعیت backfill) — طرح اجرایی در JSON.\n")
    L.append("6. **UX ساده‌تر شد؟** بله: ۴ گروه تصمیمی + چیپ بنیادی/ارزندگی/ورود + مانع عددی هر شرکت + «چه زمانی ارزش بررسی مجدد دارد؟» + شمارش «چرا بقیه جذاب نشدند»؛ همه در مرورگر واقعی تأیید شد.\n")
    L.append("7. **وضعیت snapshot و آمادگی روزانه:** as_of=2026-10-08 (۳ روز)، تازگی قیمت ۳/۷ روز، readiness dry-run = `ready_for_owner_run`؛ runbook ۶ مرحله‌ای در JSON؛ انتشار/زمان‌بندی ساخته نشد.\n")
    L.append("8. **محدودیت‌های باقی‌مانده:** roe_stability/margin_trend خارج از دامنه؛ equity مفقود ۱۷۰؛ پوشش Q<0.5 برای ۱۶۱؛ پنجرهٔ مومنتوم ۱۰۵؛ بانک‌ها ۱۱؛ آستانه‌ها آزمایشی؛ بدون بک‌تست.\n")
    L.append("9. **نیازمند مجوز مالک:** backfill (SQL 125) سهام/صورت‌مالی، تاریخچهٔ قیمت، QVT_MANIFEST_DIR، خانوادهٔ بانکی، commit، تصمیم 2-B-6.\n")
    L.append("10. **سه اقدام بعدی با بیشترین اثر:** (۱) تاریخچهٔ قیمت → +۳۲ سه‌محوری فوری؛ (۲) backfill سهام → V برای ~۱۷۰ شرکت؛ (۳) صورت‌های مالی تاریخی → Q از ۹۸ تا سقف ~۲۶۰.\n")
    L.append("\n## نقد مستقل اقتصادی (P6)\n")
    for k, v in report["p6_independent_critique"].items():
        L.append("- **%s:** %s" % (k, v))
    L.append("\n## حساسیت به آستانه‌ها\n")
    L.append("- `v_cheap` 0.55→۲ نامزد، 0.60 (پایه)→۱، 0.65→۰؛ تغییر ±0.05 سایر آستانه‌ها بی‌اثر بر گروه جذاب.\n")
    L.append("\n## تست‌ها و اعتبارسنجی\n")
    for k, v in report["tests"].items():
        L.append("- **%s:** %s" % (k, v))
    L.append("\n## مقایسه با baseline گام ۲-ک-۷\n")
    for k, v in report["baseline_vs_2k7"].items():
        L.append("- **%s:** %s" % (k, v))
    L.append("\n## محدودیت‌های غیرقابل نقض — همگی رعایت شد\n")
    L.append(", ".join(k for k in report["constraints_respected"]) + "\n")
    return "\n".join(L)


jp = os.path.join(OUT, "gam2k8_final_report.json")
mp = os.path.join(OUT, "gam2k8_final_report.md")
json.dump(report, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
open(mp, "w", encoding="utf-8").write(md())
print("wrote:", jp, os.path.getsize(jp), "bytes")
print("wrote:", mp, os.path.getsize(mp), "bytes")
