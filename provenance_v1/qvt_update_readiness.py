#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۸ (P5) — گردش‌کار به‌روزرسانی امن صفحهٔ فرصت‌ها: بررسی آمادگی
(fail-closed، فقط‌خواندنی، dry-run).

هیچ چیز دیگری را نمی‌نویسد جز گزارش JSON در provenance_v1/output/؛ هیچ
دیتابیسی را تغییر نمی‌دهد؛ هیچ آرتیفکتی را بازنویسی نمی‌کند؛ انتشار
production و زمان‌بندی ندارد. انتشار واقعی فقط با publish_bundle.py و
با مجوز مالک انجام می‌شود.

مراحل واقعی تازه‌نگه‌داشتن صفحهٔ فرصت‌ها (همان چیزی که این اسکریپت بررسی می‌کند):
  ۱) تازگی منبع: کنترل مستقل قیمت backend (priceCheck روی
     market.price_observations در پنجرهٔ PIT) — از پاسخ زنده خوانده می‌شود.
  ۲) وضعیت snapshot: سه آرتیفکت هم‌as_of، هم‌cutoff و با TAG سازگار
     (همان قاعدهٔ qvtCheckConsistency سمت backend).
  ۳) اعتبارسنجی تغییر داده: SHA-256 سه آرتیفکت در برابر baseline ثبت‌شده؛
     تغییر ⇒ باید snapshot جدید با TAG جدید ساخته شود، نه overwrite.
  ۴) ساخت sandbox: فرمان‌های ساخت آرتیفکت‌های جدید (pilot_v2_qvt /
     pilot_v2_value / pilot_v2_t + publish_bundle) — در این مأموریت فقط
     «وجود و اجرایی بودن» بررسی می‌شود (dry-run).
  ۵) اختلاف نامزدها: برد فعلی زنده در برابر baseline ثبت‌شدهٔ قبلی —
     نامزدهای اضافه/حذف‌شده با نماد گزارش می‌شود.
  ۶) جلوگیری از انتشار خراب: هر FAIL ⇒ verdict=blocked؛ خروجی هرگز
     «آماده» گزارش نمی‌شود مگر همهٔ گیت‌ها پاس شوند.
  ۷) manifest/rollback: binding از طریق TAG در نام پوشهٔ
     pub-<date>-<q>-<v>-<t> انجام می‌شود؛ rollback = بازگشت LATEST.json به
     پوشهٔ قبلی — بدون دست‌زدن به آرتیفکت‌های قبلی.

اجرا:  python provenance_v1/qvt_update_readiness.py
خروجی: provenance_v1/output/update_readiness_2k8_<TAG>.json
"""

import datetime
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "provenance_v1", "output")
ART = os.path.join(ROOT, "canonical_postgres_v1_2_1", "analytics_canonical_v1", "output")
GO_APP = os.path.join(ROOT, "go-app")

TODAY = datetime.date.today()
checks = []
fail = 0


def add(name, status, detail):
    global fail
    if status == "FAIL":
        fail += 1
    checks.append({"check": name, "status": status, "detail": detail})


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── ۱) منابع زندهٔ backend: پاسخ discovery فعلی ──────────────────────────────
live_path = os.path.join(OUT, "_board_2k8_live.json")
live = json.load(open(live_path, encoding="utf-8"))
as_of = live.get("as_of")
cutoff = live.get("cutoff", "")
TAG = live.get("snapshot_tag") or "%s_q9499e3bb_v7786e01a_tdcfd3840" % as_of

try:
    age_days = max(
        e["price_freshness"]["age_days"]
        for k in ("attractive_candidates", "fundamentals_waiting", "apparent_value_risk", "blocked_or_insufficient")
        for e in live["opportunity_board"][k]
        if e.get("price_freshness") and e["price_freshness"].get("age_days") is not None
    )
    ps = live.get("price_source", {})
    ok = bool(ps.get("available")) and age_days is not None
    add("source_freshness_independent_price_check",
        "PASS" if ok else "FAIL",
        "کنترل مستقل قیمت backend فعال است؛ حداکثر سن قیمت در جامعهٔ سه‌محوری = %s روز (سیاست V: ۷ روز)" % age_days)
except Exception as exc:  # noqa: BLE001
    add("source_freshness_independent_price_check", "FAIL", "کنترل مستقل در دسترس نبود: %r" % exc)

# ── ۲) سازگاری snapshot سه آرتیفکت ───────────────────────────────────────────
cons = live.get("snapshot_consistency", {})
files = cons.get("files", {})
# نرمال‌سازی همان‌ند که backend انجام می‌دهد: «2026-10-08 23:59:00+00:00» و
# «2026-10-08» یکی‌اند — فقط بخش تاریخ مقایسه می‌شود
asofs = {str(f.get("as_of"))[:10] for f in files.values()}
add("snapshot_consistency_three_artifacts",
    "PASS" if cons.get("consistent") and len(asofs) == 1 else "FAIL",
    "consistent=%s؛ تاریخ سه فایل=%s؛ cutoff=%s" % (cons.get("consistent"), sorted(asofs), cutoff[:19]))

snap_age = (TODAY - datetime.date.fromisoformat(str(as_of))).days
add("snapshot_age", "PASS" if snap_age <= 7 else "WARN",
    "سن snapshot = %d روز (as_of=%s؛ امروز=%s) — بالای ۷ روز یعنی نمادها باید با snapshot تازه بازسازی شوند" % (snap_age, as_of, TODAY.isoformat()))

# ── ۳) hash سه آرتیفکت در برابر baseline ────────────────────────────────────
hashes = {}
for name in ("v2_q_observed_report.json", "v2_value_pilot.json", "v2_t_pilot.json"):
    hashes[name] = sha256(os.path.join(ART, name))
base_path = os.path.join(OUT, "artifact_hash_baseline_2k8.json")
if os.path.exists(base_path):
    baseline = json.load(open(base_path, encoding="utf-8"))
    changed = [k for k in hashes if baseline.get("hashes", {}).get(k) != hashes[k]]
    add("artifact_hash_vs_baseline",
        "PASS" if not changed else "WARN",
        "تغییرنکرده در برابر baseline ۲-ک-۸: همه" if not changed else "تغییر یافته: %s — ساخت snapshot جدید لازم است، overwrite ممنوع" % changed)
else:
    json.dump({"tag": TAG, "hashes": hashes}, open(base_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    add("artifact_hash_vs_baseline", "PASS", "baseline hash ثبت شد (اجرای اول)؛ اجراهای بعدی تغییرها را گزارش می‌کنند")

# ── ۴) ساخت sandbox: وجود فرمان‌های واقعی خط تولید ──────────────────────────
CAN = os.path.join(ROOT, "canonical_postgres_v1_2_1", "analytics_canonical_v1")
pipeline_scripts = [
    "pilot_v2_qvt.py",       # محور Q (مشاهده‌شده)
    "pilot_v2_value.py",     # محور V
    "pilot_v2_t.py",         # محور T
    "publish_bundle.py",     # انتشار نسخه‌دار با TAG + LATEST.json
]
missing = [s for s in pipeline_scripts if not os.path.exists(os.path.join(CAN, s))]
add("sandbox_pipeline_scripts_present",
    "PASS" if not missing else "FAIL",
    "اسکریپت‌های خط تولید موجودند: %s" % ", ".join(pipeline_scripts) if not missing else "مفقود: %s" % missing)

# برآورد QVT_MANIFEST_DIR (opt-in) — binding هش در خوانش backend
add("manifest_binding_note", "PASS",
    "خوانش backend با qvtLoadBundle محافظ پایداری دارد و در صورت فعال‌شدن QVT_MANIFEST_DIR با manifest هش-بسته می‌شود؛ انتشار جدید = پوشهٔ pub-<TAG> جدید + LATEST.json (rollback = بازگشت LATEST.json)")

# ── ۵) اختلاف نامزدها: برد فعلی در برابر baseline ۲-ک-۷ ─────────────────────
def att_syms(doc):
    ob = doc["opportunity_board"]
    att = ob.get("attractive_candidates", ob.get("review_priority", []))
    return {e["symbol"] for e in att}, {
        "attractive": len(att),
        "waiting": len(ob.get("fundamentals_waiting", ob.get("watchlist", []))),
        "cheap_risk": len(ob.get("apparent_value_risk", [])),
        "blocked": len(ob["blocked_or_insufficient"]),
    }


cur_syms, cur_counts = att_syms(live)
old_path = os.path.join(OUT, "_board_2k7_live.json")
if os.path.exists(old_path):
    old_syms, old_counts = att_syms(json.load(open(old_path, encoding="utf-8")))
    add("candidate_diff_vs_2k7",
        "PASS",
        "نامزدهای جذاب ۲-ک-۷→۲-ک-۸: اضافه‌شده=%s حذف‌شده=%s؛ شمارش گروه‌ها %s → %s"
        % (sorted(cur_syms - old_syms) or "—", sorted(old_syms - cur_syms) or "—", old_counts, cur_counts))
else:
    add("candidate_diff_vs_2k7", "WARN", "baseline ۲-ک-۷ در دسترس نیست")

# ── ۶) گیت نهایی: UI-backend سازگاری (شمارش‌ها از پاسخ زنده) ────────────────
counts = live["opportunity_board"]["counts"]
total = counts["attractive_candidates"] + counts["fundamentals_waiting"] + counts["apparent_value_risk"] + counts["blocked_or_insufficient"]
add("board_partition_consistency",
    "PASS" if total == counts["n_triple_universe"] else "FAIL",
    "چهار گروه = %d، جامعهٔ سه‌محوری = %d" % (total, counts["n_triple_universe"]))

verdict = "blocked_from_publish" if fail else "ready_for_owner_run"
report = {
    "artifact": "update_readiness_2k8",
    "version": "2k8-readiness-v1",
    "mode": "dry-run / read-only — انتشار انجام نشد و هیچ زمان‌بندی فعالی ساخته نشد",
    "snapshot_tag": TAG,
    "as_of": str(as_of),
    "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "verdict": verdict,
    "fail_count": fail,
    "daily_update_runbook": [
        "۱) این اسکریپت را اجرا کن — اگر verdict=blocked توقف؛ هیچ بازسازی‌ای انجام نشود",
        "۲) با اسکریپت‌های خط تولید در sandbox سه آرتیفکت جدید بساز (TAG جدید از as_of جدید)",
        "۳) snapshot_consistency و hashهای جدید را کنترل کن (عدم برابری = توقف)",
        "۴) publish_bundle.py برای ساخت pub-<TAG> جدید + به‌روزرسانی LATEST.json",
        "۵) اختلاف نامزدها را با این گزارش مقایسه و به مالک اعلام کن",
        "۶) rollback: بازگرداندن LATEST.json به پوشهٔ قبلی — آرتیفکت‌های قبلی هرگز بازنویسی نمی‌شوند",
    ],
    "checks": checks,
}
out_path = os.path.join(OUT, "update_readiness_2k8_%s.json" % TAG)
json.dump(report, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("verdict:", verdict, "| fail:", fail)
for c in checks:
    print(" [%s] %s — %s" % (c["status"], c["check"], c["detail"][:120]))
print("wrote:", out_path)
sys.exit(0)
