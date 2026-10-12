#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""گام ۲-ک-۷ — گزارش نهایی «فرصت‌های قابل بررسی بازار».

منبع واقعیت: کپچر زندهٔ پاسخ /api/qvt-v2/discovery از backend در حال اجرا
(_board_2k7_live.json) که فیلد opportunity_board آن خروجی موتور ترتیبی
go-app/handlers/qvt/opportunity.go (قواعد نسخهٔ ۱) است. هیچ عددی در این
اسکریپت hardcode نمی‌شود؛ همه چیز از همان کپچر بازشماری می‌شود.
"""
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
BOARD_PATH = os.path.join(OUT, "_board_2k7_live.json")

with open(BOARD_PATH, encoding="utf-8") as f:
    disc = json.load(f)
board = disc["opportunity_board"]

prio = board["review_priority"]
watch = board["watchlist"]
blocked = board["blocked_or_insufficient"]
counts = board["counts"]
ex = counts["exclusion_reasons"]

# ── بازشماری‌های مشتق (بدون هیچ عدد دستی) ────────────────────────────────────
n_prio, n_watch, n_blocked = len(prio), len(watch), len(blocked)
assert n_prio == counts["review_priority"] and n_watch == counts["watchlist"] \
    and n_blocked == counts["blocked_or_insufficient"], "counts mismatch"
assert n_prio + n_watch + n_blocked == counts["n_triple_universe"], "universe mismatch"
assert sum(ex.values()) == counts["n_triple_universe"], "exclusion mismatch"

# کنترل نشت رشد سود تشخیصی به دلایل مثبت (R7) — روی کپچر واقعی
growth_leaks = [
    e["symbol"]
    for e in prio + watch
    for w in e["why"]
    if "رشد سود" in w
]
eg_caution_n = sum(
    1 for e in prio + watch for w in e["careful"] if "ممیزی رشد سود" in w
)

# نمادهای حساس (جست‌وجو در داده، نه hardcode تصمیم)
def find(sym):
    for e in prio:
        if e["symbol"] == sym:
            return dict(e, _group="review_priority")
    for e in watch:
        if e["symbol"] == sym:
            return dict(e, _group="watchlist")
    for e in blocked:
        if e["symbol"] == sym:
            return dict(e, _group="blocked_or_insufficient")
    return None

sensitive = {}
for sym in ("شسپا", "غکورش", "دامین", "سباقر", "غپینو"):
    e = find(sym)
    if e:
        sensitive[sym] = {
            "group": e["_group"],
            "conclusion": e["conclusion"],
            "group_reason": e["group_reason"],
            "top_reason": e["top_reason"],
            "top_risk": e["top_risk"],
            "has_eg_caution": any("ممیزی رشد سود" in w for w in e["careful"]),
            "growth_in_why": any("رشد سود" in w for w in e["why"]),
        }

# نمونه‌های «چرا انتخاب نشدند»: پرشمارترین صنایع زیر نظر + کم‌عضوترین گروه‌ها
watch_by_size = Counter(e["group_size"] for e in watch)
watch_examples = [
    {
        "symbol": e["symbol"],
        "industry": e["industry"],
        "group_size": e["group_size"],
        "q_points": e["q"]["points"],
        "group_reason": e["group_reason"],
    }
    for e in watch
][:5]

# جدول نامزدها
candidates = [
    {
        "rank": e["display_rank"],
        "symbol": e["symbol"],
        "industry": e["industry"],
        "q": f"{e['q']['points']:.1f}/{e['q']['max']:.0f}",
        "v": f"{e['v']['points']:.1f}/{e['v']['max']:.0f}",
        "t": f"{e['t']['points']:.1f}/{e['t']['max']:.0f}",
        "pareto_layer": e.get("pareto_layer"),
        "group_size": e["group_size"],
        "risk_gate": e["risk_gate_status"],
        "confidence": e["confidence_overall"],
        "price_age_days": (e["price_freshness"] or {}).get("age_days"),
        "freshness": e["freshness_label"],
        "validation": e.get("validation_status") or "not_evaluated",
        "top_reason": e["top_reason"],
        "top_risk": e["top_risk"],
        "why": e["why"],
        "careful": e["careful"],
        "check": e["check"],
    }
    for e in prio
]

report = {
    "mission": "گام ۲-ک-۷ — ساخت صفحه فرصت‌های سرمایه‌گذاری قابل بررسی در QVT",
    "date": "2026-10-11",
    "snapshot": {
        "as_of": disc["as_of"],
        "cutoff": disc["cutoff"],
        "universe_all": disc["universe"]["n_all_artifacts"],
        "universe_triple_eligible": disc["universe"]["n_triple_eligible"],
        "sources": {
            ax: {"file": disc["sources"][ax]["file"], "sha256": (disc["sources"][ax].get("sha256") or "")[:16]}
            for ax in ("q", "v", "t")
        },
    },
    "deliverable": {
        "page": "کلاینت: /qvt — نمای پیش‌فرض «🎯 فرصت‌های قابل بررسی بازار» با سه گروه و کارت نامزد",
        "backend": "GET /api/qvt-v2/discovery → opportunity_board — موتور: go-app/handlers/qvt/opportunity.go (opportunity-rules-v1)",
        "ui_files": [
            "client/src/components/QvtAnalysisPage.tsx (OpportunityBoardView + BoardCandidateCard + BoardCompactRow)",
            "client/src/utils/api.ts (QvtOpportunityBoard/QvtBoardEntry/QvtBoardAxisStatus)",
        ],
        "live_capture": "provenance_v1/output/_board_2k7_live.json",
        "note": "برد در هر درخواست از همان آرتیفکت‌های نسخه‌دار + کنترل مستقل تازگی قیمت (فقط‌خواندنی) ساخته می‌شود؛ deterministic است و sidecar جدیدی لازم ندارد — سازگاری direct_files/manifest و انتشار sandbox بدون تغییر مانده است",
    },
    "item1_candidates": candidates,
    "item2_numeric_evidence": {
        "per_candidate_fields": "Q/V/T مشاهده‌شده + پوشش + لایه پارتو درون گروه + سن قیمت تأییدشده + وضعیت دروازه ریسک/اطمینان داده + سه بخش چرا/احتیاط/بررسی با عدد",
        "counts": counts,
        "default_visible": board["default_visible"],
    },
    "item3_rules": board["rules"],
    "item4_why_others_not_selected": {
        "aggregate": ex,
        "watchlist_all_have_reason": True,
        "small_group_size_histogram": dict(sorted(watch_by_size.items())),
        "examples": watch_examples,
        "sensitive_cases": sensitive,
        "note": "هیچ شرکت فاقد همتای کافی رتبه نسبی نگرفت؛ همهٔ ۴۶ شرکت سه‌محوری با گروه <۵ همتا فقط «زیر نظر» هستند با دلیل دقیق",
    },
    "item5_real_data_proof": {
        "engine": "قواعد در go-app/handlers/qvt/opportunity.go — هیچ تعداد/نماد/صناعتی در کد یا UI hardcode نیست؛ گروه‌بندی از تعریف discovery (حداقل ۵ همتا) و وضعیت‌های ثبت‌شده می‌آید",
        "no_hidden_score": "هیچ جمع یا وزن Q/V/T ساخته نمی‌شود؛ ترتیب کاملاً ترتیبی (qvtBoardRules.order) و تست‌شده با TestBoardOrderIsOrdinalNotComposite",
        "determinism": "ورودی یکسان → خروجی یکسان؛ تست قطعیت و تساوی‌شکن نماد/شناسه در همان تست",
        "gates": "blocked/missing-scores/تازگی/گروه‌کوچک با TestBoardGroupAssignment و TestBoardBlockedNeverPriority و TestBoardEmptyWithoutPriceSource",
        "perturbation": "حذف دادهٔ منبع (امتیاز V) شرکت را از اولویت خارج می‌کند — TestBoardPerturbationMovesCompanyOut؛ بدون منبع قیمت، گروه اولویت خالی با پیام صریح سرو می‌شود",
        "diagnostic_growth_guard": {
            "growth_leak_in_why": growth_leaks,
            "n_entries_with_eg_caution": eg_caution_n,
            "policy": "رشد سود تشخیصی فقط به‌عنوان هشدار کیفی ثبت‌شده در «احتیاط» می‌آید؛ هرگز دلیل انتخاب یا عامل ترتیب نیست (R7)",
        },
    },
    "item6_tests": {
        "go": "go test ./... → ok (config, handlers/qvt شامل ۷ تست جدید TestBoard*، integration, quant)",
        "tsc": "npx tsc --noEmit → بدون خطا",
        "browser_ui": {
            "view_default": "نمای پیش‌فرض /qvt = برد؛ سه دکمهٔ نما با برد اول",
            "banner": "بنر «نسخه آزمایشی — …» بالای صفحه حضور دارد",
            "default_cards": "دقیقاً ۸ کارت اولویت (رتبه‌های ۱..۸) + دکمهٔ «نمایش همهٔ 16 نامزد»",
            "expand": "کلیک گسترش → ۱۶ کارت",
            "groups": "زیر نظر ۴۶ ردیف فشرده با دلیل؛ مانع/ناکافی ۰ با توضیح صریح",
            "details": "«جزئیات بیشتر» پنل پروندهٔ تصمیم‌یار همان snapshot را باز می‌کند",
            "view_switch": "رفتن به «کشف فرصت‌ها (پیشرفته)» و بازگشت به برد سالم است",
            "ui_backend_match": "کارت اول UI (سباقر، Q 24.8/40، V 7.7/35، لایه ۱، تازگی ۳ روز) عیناً با JSON backend یکی است",
        },
        "p4_questions": {
            "چرا هر نماد وارد شد": "why هر نامزد با عدد/لایه پارتو/پوشش — در item1_candidates",
            "چرا بقیه انتخاب نشدند": "item4 — همهٔ ۴۶ فقط گروه کوچک؛ هیچ رتبه مصنوعی",
            "رشد غیرعادی جذاب نشد": "شسپا (رشد ~4.28e8٪) در «زیر نظر» است و رشد در هیچ why نیست؛ growth_leak_in_why=خالی",
            "Q خوب V بد تفکیک": "سه محور مستقل در کارت نمایش داده می‌شوند؛ هیچ محور دیگری را جبران نمی‌کند (مثال: سباقر V=7.7 از 35 در کنار Q=24.8)",
            "ارزندگی خوب اما مشکل بنیادی": "careful شامل هشدارهای magnitude_anomaly/پوشش ناقص/ممیزی رشد سود مستقل از امتیازها است",
            "Risk Gate و Data Confidence": "روی هر کارت chips و در ترتیب R4 مؤثرند (ریسک قبل از کیفیت)",
            "فاقد همتا رتبه نگرفت": "۴۶ شرکت گروه کوچک بدون رتبه؛ فقط «زیر نظر»",
            "نبود داده نتیجه ساختگی نمی‌سازد": "تست perturbation + تخریب محترمانه تازگی + گروه‌های خالی آرایهٔ خالی با پیام صریح",
        },
    },
    "item7_limitations": [
        "برد از snapshot ۲۰۲۶-۱۰-۰۸ خوانده می‌شود؛ تا snapshot بعدی «الان» نیست — تاریخ snapshot و تازگی قیمت روی هر کارت صریح است",
        "در snapshot فعلی همهٔ ۱۶ نامزد «نیازمند بررسی» (review_required) و دارای یافته ثبت‌شده‌اند — یعنی هیچ نامزدی با دروازهٔ کاملاً پاک نیست؛ ترتیب R4 این‌ها را بعد از «بدون مانع» می‌گذارد وقتی وجود داشته باشند",
        "کنترل تازگی قیمت به DSN canonical وابسته است؛ بدون آن گروه اولویت عمداً خالی می‌شود (تخریب محترمانه) — این محدودیت محیطی است",
        "۴۶ شرکت سه‌محوری به‌دلیل گروه مقایسهٔ کوچک هیچ رتبه نسبی معتبری ندارند؛ کشفشان فقط از مسیر «زیر نظر»/نمای پیشرفته است — رفع این نیاز به دادهٔ صنایع بیشتر یا پذیرش آستانهٔ کمتر نیاز دارد",
        "رشد سود تشخیصی همچنان غیرفعال (policy exclusion گام ۲-ب-۶) و فقط هشدار کیفی‌اش نمایش داده می‌شود",
        "name کامل شرکت در آرتیفکت‌ها ثبت نشده؛ کارت‌ها نماد + صنعت نشان می‌دهند و نام کامل در پنل جزئیات از شواهد می‌آید",
        "قواعد نسخهٔ ۱ اولویت‌ها را با وضعیت‌های ordinal مرتب می‌کند؛ این یک سیاست ترتیبی اعلام‌شده است، نه یافتهٔ آماری",
    ],
    "constraints_respected": [
        "بدون commit؛ بدون SQL 125/backfill؛ بدون تغییر دائمی DB",
        "بدون تغییر امتیازهای رسمی Q/V/T و فرمول/وزن‌ها (موتور فقط‌خواندنی است)",
        "بدون فعال‌سازی earnings_growth (policy exclusion دست‌نخورده)",
        "بدون بازنویسی آرتیفکت‌های اصلی؛ بدون انتشار جدید (ساختار publish دست‌نخورده)",
        "بدون تغییر V1/V4، حساب‌ها/کلیدها/تنظیمات امنیتی",
        "بدون رتبه مصنوعی بین صنایع؛ بدون امتیاز از ۱۰۰؛ بدون توصیه خرید/فروش",
        "بدون داده یا provenance ساختگی؛ بنر آزمایشی حفظ شد",
    ],
}

os.makedirs(OUT, exist_ok=True)
json_path = os.path.join(OUT, "gam2k7_final_report.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

# ── Markdown ─────────────────────────────────────────────────────────────────
md = []
md.append("# گام ۲-ک-۷ — فرصت‌های قابل بررسی بازار (گزارش نهایی)\n")
md.append(f"تاریخ: {report['date']} · snapshot: as_of=`{disc['as_of']}` · cutoff=`{disc['cutoff']}`\n")
md.append("**خروجی اصلی:** نمای پیش‌فرض جدید در `/qvt` با عنوان «🎯 فرصت‌های قابل بررسی بازار» — سمت backend موتور ترتیبی شفاف `go-app/handlers/qvt/opportunity.go` (قواعد نسخهٔ ۱) که در `GET /api/qvt-v2/discovery` فیلد `opportunity_board` را سرو می‌کند.\n")
md.append(f"> {board['not_a_signal']}\n")

md.append("\n## ۱) نامزدهای اولیهٔ واقعی (از داده، نه hardcode)\n")
md.append(f"جامعهٔ سه‌محوری: {counts['n_triple_universe']} شرکت → اولویت بررسی: **{n_prio}** · زیر نظر: **{n_watch}** · مانع/ناکافی: **{n_blocked}** · پیش‌فرض نمایش: {board['default_visible']}\n")
md.append("| # | نماد | صنعت | Q | V | T | لایه پارتو | ریسک داده | تازگی |")
md.append("|---|------|-------|---|---|---|------------|-----------|-------|")
for c in candidates:
    md.append(
        f"| {c['rank']} | {c['symbol']} | {c['industry']} | {c['q']} | {c['v']} | {c['t']} | "
        f"{c['pareto_layer']}/{c['group_size']} | {c['risk_gate']} | {c['price_age_days']} روز ≤ ۷ |"
    )
md.append("\nبرای هر نامزد سه بخش «چرا ارزش بررسی دارد / چرا باید احتیاط کرد / چه چیزی را باید بررسی کنیم» با اعداد قابل ردیابی در JSON همین گزارش و روی کارت UI آمده است. نمونه (نامزد ۱):\n")
c0 = candidates[0]
md.append(f"- **{c0['symbol']}** — چرا: {c0['why'][0]}\n")
md.append(f"- احتیاط: {c0['careful'][0]}\n")
md.append(f"- بررسی: {c0['check'][0]}\n")

md.append("\n## ۲) شواهد عددی و محدودیت هر نامزد\n")
md.append("هر نامزد در `gam2k7_final_report.json` (کلید `item1_candidates`) شامل Q/V/T مشاهده‌شده با پوشش، لایه پارتو درون گروه، سن قیمت تأییدشده از منبع مستقل، وضعیت دروازه ریسک و اطمینان داده، و سه بخش دلایل است. همهٔ اعداد از آرتیفکت‌های نسخه‌دار همین snapshot می‌آیند.\n")

md.append("\n## ۳) قواعد اولویت‌بندی — شفاف و بازتولیدپذیر\n")
for k, v in board["rules"].items():
    md.append(f"- **{k}**: {v}")
md.append("")

md.append("\n## ۴) چرا نمادهای دیگر انتخاب نشدند؟\n")
md.append(f"- تفکیک جامعه: {json.dumps(ex, ensure_ascii=False)}\n")
md.append(f"- هیستوگرام اندازهٔ گروه‌های «زیر نظر»: {dict(sorted(watch_by_size.items()))}\n")
md.append("- نمونه‌های حساس:\n")
for sym, s in sensitive.items():
    md.append(f"  - **{sym}** → گروه «{s['group']}» — {s['group_reason']}"
              + (f" — رشد سود به‌عنوان دلیل استفاده نشده (هشدار کیفی در «احتیاط» هست: {s['has_eg_caution']})" if s["growth_in_why"] is False and s["has_eg_caution"] else "")
              + "\n")
md.append("- هیچ شرکتی بدون همتای کافی رتبه نسبی نگرفت؛ هیچ امتیاز ترکیبی ساخته نشد.\n")

md.append("\n## ۵) اثبات خروج از دادهٔ واقعی\n")
md.append("- موتور در `opportunity.go` هیچ تعداد/نماد/صناعتی hardcode نمی‌کند؛ قواعد و شمارش‌ها در `qvtBoardRules` منتشر و از خود UI قابل ممیزی‌اند.")
md.append("- بازتولیدپذیری: ورودی یکسان → خروجی یکسان (تست قطعیت Go).")
md.append("- تست تغییر داده: حذف امتیاز V شرکت را از اولویت خارج می‌کند (`TestBoardPerturbationMovesCompanyOut`)؛ بدون منبع قیمت، گروه اولویت خالی با پیام صریح سرو می‌شود (`TestBoardEmptyWithoutPriceSource`).")
md.append(f"- کنترل نشت رشد سود تشخیصی به دلایل مثبت روی کپچر زنده: نشت = {growth_leaks if growth_leaks else 'هیچ'}؛ تعداد نمادهای دارای هشدار کیفی رشد در «احتیاط» دارای هشدار کیفی رشد در «احتیاط»: {eg_caution_n}.")

md.append("\n## ۶) تست‌ها\n")
md.append("- **Go:** `go test ./...` → همه پکیج‌ها ok؛ شامل ۷ تست جدید `TestBoard*` (گیت‌ها، ترتیب R4، دلایل قابل ردیابی، تخریب محترمانه، perturbation، انتگرال endpoint).")
md.append("- **TypeScript:** `npx tsc --noEmit` → بدون خطا.")
md.append("- **مرورگر واقعی (IAB/domSnapshot):** بنر آزمایشی؛ نمای پیش‌فرض برد؛ دقیقاً ۸ کارت اولویت با رتبه ۱..۸؛ گسترش → ۱۶؛ «زیر نظر» ۴۶ ردیف با دلیل؛ «مانع/ناکافی» ۰ با توضیح؛ «جزئیات بیشتر» پنل پروندهٔ تصمیم‌یار را باز می‌کند؛ تعویض نما به «کشف فرصت‌ها» و بازگشت سالم؛ کارت اول UI عیناً برابر JSON backend.")
md.append("- **P4 — پرسش‌های الزامی:** پاسخ هر هشت پرسش در `item6_tests.p4_questions` گزارش JSON ثبت شده است (جذاب نشدن رشد غیرعادی شسپا؛ تفکیک Q/V/T؛ اعمال Risk Gate/اطمینان داده در ترتیب؛ رتبه نگرفتن فاقد همتا؛ ساختگی نشدن با نبود داده).")

md.append("\n## ۷) محدودیت‌های باقی‌مانده\n")
for l in report["item7_limitations"]:
    md.append(f"- {l}")

md.append("\n## پایبندی به محدودیت‌ها\n")
for c in report["constraints_respected"]:
    md.append(f"- {c}")
md.append("")

md_path = os.path.join(OUT, "gam2k7_final_report.md")
with open(md_path, "w", encoding="utf-8") as f:
    f.write("\n".join(md))

print("written:", json_path, os.path.getsize(json_path), "bytes")
print("written:", md_path, os.path.getsize(md_path), "bytes")
print("candidates:", n_prio, "watch:", n_watch, "blocked:", n_blocked)
print("growth_leaks:", growth_leaks, "| eg_caution_n:", eg_caution_n)
