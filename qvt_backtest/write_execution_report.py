"""Human-readable results and machine-readable progress, derived from artifacts."""
from pathlib import Path
import json
import pandas as pd
from audit_financial_coverage import missing_core

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent


def main():
    research = json.loads((HERE / "output/roadmap_latest.json").read_text(encoding="utf8"))
    run = Path(research["run_path"])
    if research.get("independent_audit", {}).get("status") != "passed":
        raise ValueError("research not published")
    comparisons = pd.read_csv(run / "comparisons.csv")
    stress = pd.read_csv(run / "execution_stress.csv")
    financial_reports = json.loads((Path(research["baseline_run_path"]) / "input_reports.json").read_text(encoding="utf8"))
    archive_stats = {"known_reports": len(financial_reports),
                     "with_facts": sum(bool(r["facts"]) for r in financial_reports),
                     "facts": sum(len(r["facts"]) for r in financial_reports),
                     "missing": sum(r.get("archive_status") == "missing" for r in financial_reports)}
    archive_stats["unusable"] = archive_stats["known_reports"] - archive_stats["with_facts"] - archive_stats["missing"]
    archive_stats["partial"] = sum(bool(r["facts"]) and bool(missing_core(r["facts"])) for r in financial_reports)
    archive_stats["paired_balance_reports"] = sum(Path(r.get("dynamic_manifest_path", "")).name == "manifest_enriched_v6.json" for r in financial_reports)
    classification = json.loads((HERE / "output/financial_history/unusable_classification.json").read_text(encoding="utf8"))
    extended_path = HERE / "output/financial_history/extended_financial_summary.json"
    extended = json.loads(extended_path.read_text(encoding="utf8")) if extended_path.exists() else None
    progress = {
        "version": "investment-roadmap-progress-v1", "real_orders": 0,
        "broker_connection": "disabled_by_owner; Agah; no official API",
        "phases": [
            {"id": "0", "status": "research_contract_implemented", "remaining": ["investable benchmark data", "owner account risk budget before real capital"]},
            {"id": "1", "status": "partial", "remaining": ["report/unit/date gaps", "historical universe/industry", "disclosed dividends/rights", "share-chain recertification"]},
            {"id": "2", "status": "partial", "remaining": ["actual queue and quote evidence", "total-return accounting", "effective-dated verified tariffs/settlement"]},
            {"id": "3", "status": "subset_experiments_completed", "remaining": ["complete historical live-model factors", "specialized families"]},
            {"id": "4", "status": "fixed_model_diagnostics_completed", "remaining": ["truly unseen forward evidence", "full-policy validation"]},
            {"id": "5", "status": "shared_target_engine_implemented", "remaining": ["historical industry/full-policy replay"]},
            {"id": "6", "status": "simple_preview_implemented", "remaining": ["real account views only after owner requests them"]},
            {"id": "7", "status": "audited_pipeline_and_local_journal_recovery_tested", "remaining": ["production backup recovery exercise", "production operational deployment"]},
            {"id": "8", "status": "simulation_journal_implemented_and_tested", "remaining": ["prospective operational observation; daily observer remains disabled"]},
            {"id": "9", "status": "simulation_contract_only", "remaining": ["broker connection intentionally excluded by owner"]},
            {"id": "10", "status": "not_started", "remaining": ["model monitoring after stable operating policy", "advanced factors only with proven benefit"]}
        ], "research_run": str(run), "archive": archive_stats, "promotion_ready": False
    }
    (run / "roadmap_progress.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf8")
    names = {"QVT": "مدل فعلی", "Q": "فقط کیفیت بنیادی", "V": "فقط ارزندگی", "T": "فقط شرایط ورود",
             "QVT_BUFFER": "مدل فعلی با حفظ سهم تا رتبهٔ ۱۵", "MATCHED_EQUAL_WEIGHT": "مرجع همسان"}
    lines = ["# گزارش اجرای نقشهٔ راه سرمایه‌گذاری", "", f"اجرای پژوهش: `{run.name}`.", "",
             "این گزارش فقط خروجی واقعی اجراشده را شرح می‌دهد. کل نقشهٔ راه هنوز تکمیل نشده؛ اتصال کارگزاری طبق درخواست مالک غیرفعال است.", "",
             "## کارهای انجام‌شده", "",
             "- قرارداد پژوهش، مرجع و معیارهای پذیرش قبل از آزمایش ثبت شد؛ مدل زنده تغییر نکرد.",
             f"- ماتریس شکاف برای {research['gaps']['rows']:,} مشاهدهٔ نماد/تاریخ ساخته شد؛ {research['gaps']['report_recovery_candidates']} گزارش نیازمند بازیابی فایل و {research['gaps'].get('partial_statement_candidates', 0)} گزارش نیازمند بررسی پوشش ناقص صورت‌هاست.",
             f"- {research['n_comparisons']} مقایسهٔ ثابت شامل خانواده‌های عوامل، حذف تک‌عامل و سیاست حفظ سهم اجرا شد.",
             f"- کنترل جداگانهٔ خروجی حسابداری روی {research['independent_audit']['checked_scenarios']} سناریو موفق بود.",
             "- سناریوهای تأخیر، سقف مشارکت یک درصد ارزش معاملات روزانه و عدم خریدوفروش در کندل تک‌قیمت بررسی شدند.",
             "- موتور مشترک انتخاب سبد، برنامهٔ فرضی امروز و دفتر تراکنشی اجرای شبیه‌سازی اضافه شد.",
             "- ثبت تکراری، راه‌اندازی مجدد، سفارش ناقص، کمبود نقد/دارایی، قیمت کهنه، سقف قیمت و توقف آزمایش شده‌اند.", "",
             "## آرشیو و اصلاح تازگی اطلاعات", "",
             f"نسخهٔ ثابت ورودی این اجرا شامل {archive_stats['known_reports']:,} گزارش شناخته‌شده، {archive_stats['with_facts']:,} گزارش دارای دادهٔ قابل استخراج و {archive_stats['facts']:,} مقدار مالی است. {archive_stats['missing']:,} گزارش دریافت‌نشده و {archive_stats['unusable']:,} گزارش بدون مقدار اثبات‌شده باقی مانده‌اند.", "",
             f"از گزارش‌های دارای داده، {archive_stats['partial']:,} مورد حداقل یکی از هفت قلم اصلی درآمد، سود خالص، سود عملیاتی، جریان نقد عملیاتی، حقوق مالکانه، دارایی و بدهی را ندارند. داشتن چند مقدار مالی به معنی پوشش کامل صورت‌های مالی یا عوامل امتیازدهی نیست.", "",
             f"ترازنامهٔ {archive_stats['paired_balance_reports']:,} گزارش با تطبیق شناسهٔ همان گزارش در صفحهٔ رسمی و خروجی ذخیره‌شده بازیابی شده است. واحد میلیون ریال از اعلان صریح همان گزارش اثبات می‌شود؛ سرستون دوره، شرکت اصلی، هویتِ دارایی=بدهی+حقوق مالکانه و حفظ تمام مقادیر قبلی کنترل شده‌اند. فایل‌های اصلی تغییر نکرده‌اند.", "",
             "کنترل منابع، نسخهٔ ثابتِ نگه‌داشته‌شده در هر اجرا را بازخوانی می‌کند؛ بازیابی جدید جای شواهدِ یک اجرای قدیمی را نمی‌گیرد. مقادیر مالی ورودی با متن منبع و هش فایل تطبیق داده می‌شوند.", "",
             "وجود گزارش جدیدِ منتشرشده، حتی وقتی دریافت یا استخراج آن ناقص باشد، استفاده از سود دورهٔ قدیمی را متوقف می‌کند. متادیتای این گزارش‌ها در ورودی ثابت نگه داشته می‌شود و کنترل جداگانه همین قاعده را بررسی می‌کند. اعداد اجراهای قبلی با این نسخه قابل جایگزینی خودکار نیستند.", "",
             "## نتیجهٔ مقایسهٔ ثابت", "", "هزینهٔ فرضی ۰٫۵٪ هر سمت؛ زیرمجموعهٔ ۷۶ واحدی و جامعهٔ تاریخی محدود. این ستون‌ها عملکرد واقعی نیستند.", "",
             "| روش | بازده سالانهٔ اسمی | افت روزانه | گردش سالانهٔ معامله نسبت به NAV |", "|---|---:|---:|---:|"]
    for key, name in names.items():
        row = comparisons[comparisons.strategy.eq(key) & comparisons.cost_rate.eq(.005)].iloc[0]
        lines.append(f"| {name} | {row.annualized_return_pct:.2f}٪ | {abs(row.max_drawdown_pct):.2f}٪ | {row.annualized_traded_nav:.2f} برابر |")
    low, high = research["uncertainty"]["interval_95"]
    zero_note = "بازه شامل صفر است." if low <= 0 <= high else "بازه در این نمونه شامل صفر نیست."
    lines += ["", f"بازهٔ بازنمونه‌گیری بلوکی برای اختلاف CAGR مدل فعلی و مرجع: {low:.2f} تا {high:.2f} واحد درصد. {zero_note} این برآورد به‌تنهایی برتری آینده را اثبات نمی‌کند.",
              "این تخمین سوگیری جامعه، انتخاب مدل روی تاریخچهٔ دیده‌شده یا نبود حسابداری کامل رویدادها را اصلاح نمی‌کند.", "",
              "نتایج حذف تک‌عامل صرفاً تشخیص پژوهشی‌اند و دلیل کافی برای تغییر عامل زنده نیستند. همهٔ آزمایش‌های ناموفق نیز ثبت شده‌اند.", "",
              "## حساسیت به ظرفیت سرمایه", "",
              "مبلغ‌ها سناریوی تحقیق‌اند، نه سرمایهٔ پیشنهادی کاربر. پرشدن‌ها بر پایهٔ تقریب روزانه‌اند؛ صف واقعی یا تسویه تأیید نشده است.", "",
              "| سرمایهٔ فرضی | روش | سناریو | بازده سالانه | متوسط نقد |", "|---|---|---|---:|---:|"]
    for row in stress[stress.scenario.eq("capacity_delay")].itertuples():
        lines.append(f"| {row.initial_capital_rial / 10:,.0f} تومان | {names[row.strategy]} | محدودیت حجم + یک جلسه تأخیر | {row.annualized_return_pct:.2f}٪ | {row.avg_cash_pct:.2f}٪ |")
    lines += ["", "تعیین مبلغ و ظرفیت قبل از انتخاب سیاست لازم است؛ نتیجهٔ یک مبلغ به مبلغ دیگر قابل تعمیم نیست.", "",
              "## تشخیص فایل‌های مالی ردشده", "", "| دلیل | تعداد |", "|---|---:|"]
    reasons = {"no_statement_local_unit_evidence": "واحد مالی در محدودهٔ صورت اثبات نشده", "missing_own_period_header": "سرستون دورهٔ خود گزارش تطبیق ندارد",
               "no_identifiable_parent_statement": "صورت شرکت اصلی قابل شناسایی نیست", "unmatched_or_ambiguous_metrics_or_balance": "قالب/عنوان/تراز نیازمند بررسی"}
    for reason, count in classification["reasons"].items():
        lines.append(f"| {reasons[reason]} | {count} |")
    lines += ["", "این دسته‌بندی مربوط به فایل‌های باقی‌مانده در همین اجرای محلی است. وجود واحد میلیون ریال در یک جدول تولید یا فروش، واحد صورت مالی دیگری را اثبات نمی‌کند.", "",
              "## باقی‌مانده‌های مهم", "",
              "جامعه و صنعت تاریخی، افشای سود نقدی و حق‌تقدم، زنجیرهٔ سهام، عوامل کامل مدل و مرجع منفعل قابل سرمایه‌گذاری باید تکمیل شوند. موتور صف/اجرای واقعی با دادهٔ کندل قابل تأیید نیست.",
              "سیاست سبد زنده هنوز به‌طور کامل بازپخش نشده و اجرای آزمایشی روزانهٔ آینده همچنان غیرفعال است. دفتر شبیه‌سازی قابلیت حسابداری دارد، اما بک‌تست فعلی به دفتر مالک یا سفارش کارگزاری متصل نیست.", "",
              "## اجرای مجدد", "", "```powershell", ".venv/Scripts/python.exe qvt_backtest/run_investment_pipeline.py", "```", "",
              "این فرمان فقط مراحل محلی پژوهش و انتشار کنترل‌شده را اجرا می‌کند؛ هیچ اتصال کارگزاری یا سفارش واقعی ندارد.",
              "خروجی‌های تفصیلی در پوشهٔ اجرای پژوهش باقی می‌مانند. فایل `roadmap_progress.json` وضعیت واقعی هر فاز را مشخص می‌کند."]
    if extended:
        lines += ["", "## بازسازی عوامل مالی تکمیلی", "", f"پنل تشخیصی {extended['rows']:,} مشاهده ساخته شد؛ تعداد مقادیر قابل بازسازی:", "",
                  "| عامل | مشاهدهٔ معتبر |", "|---|---:|"]
        factor_names = {"margin_trend": "روند حاشیهٔ سود", "revenue_growth": "رشد فروش هم‌گزارش", "interest_coverage": "پوشش هزینهٔ مالی هم‌دوره", "earnings_quality": "وابستگی به اقلام غیرعملیاتی هم‌دوره"}
        lines.extend(f"| {factor_names[f]} | {n:,} |" for f, n in extended["valid"].items())
        lines += ["", "این عوامل تشخیصی‌اند و هنوز به امتیاز زنده اضافه نشده‌اند. اختلاف پنجرهٔ سود عملیاتی و هزینه، پایهٔ نامعتبر یا نبود شواهد دوره باعث حذف مقدار می‌شود."]
    extended_result_path = HERE / "output/extended_latest.json"
    if extended_result_path.exists():
        compared = json.loads(extended_result_path.read_text(encoding="utf8"))
        if compared.get("baseline_run_path") == research["baseline_run_path"] and compared.get("independent_audit", {}).get("status") == "passed":
            progress["extended_comparison"] = {"run": compared["run_path"], "n_comparisons": compared["n_comparisons"], "n_rows": compared["n_rows"]}
            (run / "roadmap_progress.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf8")
            lines += ["", "## مقایسهٔ مدل ۷۶ و ۸۹ واحدی روی جامعهٔ مشترک", "",
                      f"{compared['n_rows']:,} مشاهده، {compared['n_dates']} تاریخ و {compared['n_symbols']} نماد یکتا با همهٔ عوامل تکمیلی در دسترس بوده‌اند. وزن‌ها همان وزن‌های طراحی موجودند؛ جست‌وجوی وزن انجام نشده است.", "",
                      "| روش | بازده سالانه با هزینهٔ ۰٫۵٪ هر سمت | افت روزانه |", "|---|---:|---:|"]
            labels = {"CORE76_COMMON": "هستهٔ ۷۶ واحدی در جامعهٔ مشترک", "EXTENDED89_COMMON": "هسته + چهار عامل تکمیلی، ۸۹ واحد", "MATCHED_EQUAL_WEIGHT": "مرجع همسان همین جامعه"}
            for row in compared["results"]:
                if row["cost_rate"] == .005:
                    lines.append(f"| {labels[row['strategy']]} | {row['annualized_return_pct']:.2f}٪ | {abs(row['max_drawdown_pct']):.2f}٪ |")
            lines += ["", "جامعه و گاهی دامنهٔ زمانی این مقایسه محدودتر از آزمون اصلی‌اند؛ اعداد آن نباید با بازده جامعهٔ اصلی برای انتخاب برنده مقایسه شوند. مدل ۸۹ واحدی هم صنعت تاریخی و سیاست کامل سبد زنده را ندارد. نتیجهٔ این مقایسه به‌تنهایی مجوز تغییر امتیاز زنده نیست."]
    chronological_path = HERE / "output/walkforward_latest.json"
    if chronological_path.exists():
        chronological = json.loads(chronological_path.read_text(encoding="utf8"))
        if (chronological.get("baseline_run_path") == research["baseline_run_path"] and
                chronological.get("fixed_research_run_path") == research["run_path"] and
                chronological.get("independent_audit", {}).get("status") == "passed" and
                chronological.get("chronology_audit", {}).get("status") == "passed"):
            progress["chronological_comparison"] = {"run": chronological["run_path"], "n_comparisons": chronological["n_comparisons"]}
            progress["phases"][4]["status"] = "chronological_selection_and_continuous_account_replay_checked"
            (run / "roadmap_progress.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf8")
            lines += ["", "## انتخاب روش با ترتیب زمانی", "",
                      "در نخستین تاریخ تصمیم هر سال میلادی، روش سبد فقط با بازده و افتِ ثبت‌شده پیش از همان تاریخ انتخاب می‌شود. حداقل ۳۶۵ روز و ۱۸۰ جلسهٔ سابقه لازم است؛ تا آن زمان روش پیش‌فرض ثابت می‌ماند. معیار و روش‌های کاندیدا پیش از این اجرا ثبت شده‌اند و جست‌وجوی وزن انجام نشده است.", "",
                      "حساب سبد در کل دوره پیوسته است و تغییر روش هم هزینهٔ معامله دارد؛ منحنی‌های مستقل روش‌ها به هم چسبانده نشده‌اند. کنترل جداگانه و آزمون تغییر نتایج آینده، جلوگیری از اثر آینده بر انتخاب‌های قبلی را بررسی می‌کنند.", "",
                      "| روش | بازده سالانه با هزینهٔ ۰٫۵٪ هر سمت | افت روزانه |", "|---|---:|---:|"]
            labels = {"WALKFORWARD": "انتخاب سالانه بر اساس گذشته", "QVT_FIXED": "مدل ثابت", "MATCHED_EQUAL_WEIGHT": "مرجع همسان"}
            for row in chronological["results"]:
                if row["cost_rate"] == .005:
                    lines.append(f"| {labels[row['strategy']]} | {row['annualized_return_pct']:.2f}٪ | {abs(row['max_drawdown_pct']):.2f}٪ |")
            lines += ["", "قواعد این پژوهش بعد از مشاهدهٔ آزمایش‌های قبلی طراحی شده‌اند. ترتیب تصمیم‌ها صحیح است، اما این نتیجه شاهدِ تاریخچهٔ دست‌نخورده و دیده‌نشده نیست و مجوز تغییر مدل زنده نمی‌دهد."]
    (ROOT / "docs/INVESTMENT_ROADMAP_EXECUTION.fa.md").write_text("\n".join(lines) + "\n", encoding="utf8")
    print(json.dumps({"report": "docs/INVESTMENT_ROADMAP_EXECUTION.fa.md", "completed_comparisons": research["n_comparisons"], "full_plan_complete": False}))


if __name__ == "__main__":
    main()
