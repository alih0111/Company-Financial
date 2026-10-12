# -*- coding: utf-8 -*-
"""تولید SQL مرحله‌ای backfill (بدون اجرا) — گام ۲-ک-۳ P1.

123: مرحلهٔ A — همان ۶٬۴۰۲ ردیف طرح ۲-ک-۲ با گاردهای تراکنشی (baseline برنده‌ها،
پیش‌شرط‌های قابل اندازه‌گیری، RAISE روی هر تغییر برنده → rollback خودکار).
124: مرحلهٔ B (غیرفعال، نیازمند تصمیم) — رفع آرتیفکت ۶۰ دقیقه‌ای timezone
برای ۸۳۵ جفت conflicting با قاعدهٔ ساعت‌دیواری.
"""
import json
from datetime import datetime

TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
OUT = "provenance_v1/output"

plan = json.load(open(f"{OUT}/backfill_plan_{TAG}.json", encoding="utf-8"))
as_of = str(plan["snapshot_binding"]["as_of"])[:10]
cutoff = str(plan["snapshot_binding"]["cutoff"]).replace(" ", "T")
audit = json.load(open(f"{OUT}/backfill_plan_audit_{TAG}.json", encoding="utf-8"))
n_conf_pairs = audit["conflict_deep_dive"]["by_e1_letter_count"]["e1_letters=1"] + \
    audit["conflict_deep_dive"]["by_e1_letter_count"].get("e1_letters=2", 0)

rows = plan["plan_rows"]
values = ",\n".join(
    f"  ('{r['report_id']}'::uuid, '{r['publish_at']}'::timestamptz)" for r in rows)

sql_a = f"""-- =====================================================================
-- 123_publish_at_backfill_staged.sql — پیش‌نویس مرحلهٔ A (اجرا نشده؛ نیازمند مجوز صریح)
-- گام ۲-ک-۳ P1: همان ۶٬۴۰۲ ردیف طرح ۲-ک-۲، این بار transaction-safe با:
--   (۱) پیش‌شرط‌های قابل اندازه‌گیری قبل از UPDATE
--   (۲) جدول موقت برنده‌های پایه (قرارداد موتور) قبل از تغییر
--   (۳) مقایسهٔ برنده‌ها پس از UPDATE داخل همان تراکنش؛ هر تفاوت = RAISE → rollback کامل
-- snapshot: as_of={as_of} cutoff={cutoff} q9499e3bb v7786e01a tdcfd3840
-- idempotent: فقط published_at IS NULL AND source='legacy_sqlserver'
-- =====================================================================

BEGIN;

CREATE TEMP TABLE _backfill_plan(report_id uuid, publish_at timestamptz) ON COMMIT DROP;
INSERT INTO _backfill_plan VALUES
{values};

-- پیش‌شرط ۲: تعداد ردیف‌های هدف = {len(rows)} و همه بدون تاریخ و legacy
DO $$
DECLARE n_rows INT; n_dated INT; n_nonlegacy INT; n_gt_cutoff INT;
BEGIN
  SELECT count(*) INTO n_rows FROM _backfill_plan;
  IF n_rows <> {len(rows)} THEN
    RAISE EXCEPTION 'plan size mismatch: % <> {len(rows)}', n_rows; END IF;
  SELECT count(*) INTO n_dated
    FROM ingestion.reports r JOIN _backfill_plan p ON p.report_id = r.id
   WHERE r.published_at IS NOT NULL;
  IF n_dated <> 0 THEN
    RAISE EXCEPTION '% target rows already dated — plan stale, re-run plan builder', n_dated; END IF;
  SELECT count(*) INTO n_nonlegacy
    FROM ingestion.reports r JOIN _backfill_plan p ON p.report_id = r.id
   WHERE r.source <> 'legacy_sqlserver';
  IF n_nonlegacy <> 0 THEN
    RAISE EXCEPTION '% target rows are not legacy_sqlserver', n_nonlegacy; END IF;
  SELECT count(*) INTO n_gt_cutoff FROM _backfill_plan WHERE publish_at > '{cutoff}'::timestamptz;
  IF n_gt_cutoff <> 0 THEN
    RAISE EXCEPTION '% plan dates exceed cutoff', n_gt_cutoff; END IF;
END $$;

-- گارد ۳: برنده‌های پایه (قرارداد موتور) قبل از تغییر
CREATE TEMP TABLE _baseline_winners(company_id text, period_end date, report_id uuid) ON COMMIT DROP;
INSERT INTO _baseline_winners
SELECT DISTINCT ON (st.company_id::text, st.period_end_date)
       st.company_id::text, st.period_end_date, r.id
FROM fundamentals.financial_statements st
JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
JOIN ingestion.reports r ON r.id = st.report_id
WHERE (r.published_at IS NULL AND st.period_end_date <= '{as_of}'::date)
   OR (r.published_at IS NOT NULL AND r.published_at <= '{cutoff}'::timestamptz)
ORDER BY st.company_id::text, st.period_end_date,
         st.period_end_date DESC, rv.version_no DESC, r.id;

-- گام اصلی (idempotent)
UPDATE ingestion.reports r
   SET published_at = p.publish_at
  FROM _backfill_plan p
 WHERE r.id = p.report_id
   AND r.published_at IS NULL
   AND r.source = 'legacy_sqlserver';

-- گارد ۴ (قطعی): هیچ تغییری در مجموعهٔ ردیف‌های واجد شرایط مجاز نیست
DO $$
DECLARE drift INT;
BEGIN
  CREATE TEMP TABLE _after_winners ON COMMIT DROP AS
  SELECT DISTINCT ON (st.company_id::text, st.period_end_date)
         st.company_id::text, st.period_end_date, r.id
  FROM fundamentals.financial_statements st
  JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
  JOIN ingestion.reports r ON r.id = st.report_id
  WHERE (r.published_at IS NULL AND st.period_end_date <= '{as_of}'::date)
     OR (r.published_at IS NOT NULL AND r.published_at <= '{cutoff}'::timestamptz)
  ORDER BY st.company_id::text, st.period_end_date,
           st.period_end_date DESC, rv.version_no DESC, r.id;

  SELECT count(*) INTO drift FROM (
    (SELECT * FROM _baseline_winners EXCEPT SELECT * FROM _after_winners)
    UNION ALL
    (SELECT * FROM _after_winners EXCEPT SELECT * FROM _baseline_winners)) d;
  IF drift <> 0 THEN
    RAISE EXCEPTION 'eligibility drift after backfill: % pair(s) — rolling back', drift;
  END IF;
END $$;

-- گارد ۵: شمارش ردیف‌های به‌روزشده باید با طرح یکی باشد
DO $$
DECLARE n_updated INT;
BEGIN
  SELECT count(*) INTO n_updated
    FROM ingestion.reports r JOIN _backfill_plan p ON p.report_id = r.id
   WHERE r.published_at = p.publish_at;
  IF n_updated <> {len(rows)} THEN
    RAISE EXCEPTION 'updated % <> plan %', n_updated, {len(rows)};
  END IF;
END $$;

COMMIT;

-- بازگردانی (rollback) پس از commit — فقط در صورت نیاز:
-- UPDATE ingestion.reports r SET published_at = NULL
--   FROM _backfill_plan_saved p WHERE r.id = p.report_id;  (بکاپ پیش از اجرا الزامی است)
"""

sql_b = f"""-- =====================================================================
-- 124_publish_at_tz_artifact_stage_draft.sql — پیش‌نویس مرحلهٔ B (غیرفعال؛ دوباره‌نیاز به تصمیم)
-- یافتهٔ ممیزی ۲-ک-۳ P1: هر ۸۳۹ نامهٔ conflicting (۹۰۷ سطر statement) دقیقاً
-- ۶۰ دقیقه اختلاف برچسب tz دارند و ساعت دیواری‌شان یکسان است — آرتیفکت
-- ناسازگاری DST بین ingestion DB (+04:30 ثابت) و کش کدال (+03:30 ثابت).
-- قاعدهٔ پیشنهادی: اگر |db - cache| = 60min و ساعت دیواری UTC+3.5 برابر بود،
-- همان لحظهٔ کش پذیرفته شود (تاریخ انتشار واقعی همان است).
-- این فایل عمداً COMMENT است: اجرای آن بدون تصمیم صریح ممنوع است.
-- =====================================================================
-- BEGIN;
-- CREATE TEMP TABLE _tz_fix(report_id uuid, publish_at timestamptz) ON COMMIT DROP;
-- INSERT INTO _tz_fix VALUES
--   (…۸۳۹ جفت از خروجی audit…);
-- پیش‌شرط: همهٔ ردیف‌های هدف dateless و legacy؛ مقایسهٔ برنده‌ها مثل مرحلهٔ A
-- UPDATE … ; گاردهای ۳–۵ مثل 123؛ COMMIT;
-- =====================================================================
"""

open("provenance_v1/sql/123_publish_at_backfill_staged.sql", "w", encoding="utf-8").write(sql_a)
open("provenance_v1/sql/124_publish_at_tz_artifact_stage_draft.sql", "w", encoding="utf-8").write(sql_b)
print("wrote 123 (stage A,", len(rows), "rows) and 124 (stage B draft, disabled)")
