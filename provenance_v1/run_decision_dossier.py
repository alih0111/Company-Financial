# -*- coding: utf-8 -*-
"""P2 ۲-ک-۵: پرونده تصمیم‌یار سهم برای ۶۲ شرکت واجد شرایط سه‌محور.

گسترش نسخهٔ ۲-ک-۳ (۱۶ نامزد) به کل جمعیت سه‌محور واجد شرایط (q∪v∪t
pilot_eligible): ۱۶ نامزد مقایسه‌پذیر + شرکت‌های دارای محدودیت گروه همتا
(۴۶ شرکت در snapshot فعلی). برای غیرنامزدها، بخش اعتبارسنجی مستقل به‌صورت
«خارج از دامنهٔ نامزدی» صادقانه نمایش داده می‌شود و هیچ شاهدی ساختگی
نمی‌شود. همهٔ اعداد فقط از آرتیفکت‌های نسخه‌دار همین snapshot + خروجی‌های
ممیزی ۲-ک-۲ تا ۲-ک-۵ می‌آیند. هیچ امتیاز ترکیبی، وزن پنهان یا متن
تبلیغاتی تولید نمی‌شود؛ خروجی sidecar نسخه‌دار (overlay) است.
"""
import json, os, sys
from datetime import date, datetime

TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
OUT = "provenance_v1/output"
ART = "canonical_postgres_v1_2_1/analytics_canonical_v1/output"

Q_FA = {
    "roe_level": "سطح بازده حقوق صاحبان سهام (ROE)",
    "margins": "حاشیه سود",
    "interest_coverage": "پوشش هزینهٔ مالی",
    "leverage": "اهرم مالی",
    "cash_conversion": "تبدیل سود به نقد",
    "earnings_quality": "کیفیت سود (نسبت تعهدی)",
    "revenue_growth": "رشد فروش",
    "margin_trend": "روند حاشیهٔ سود",
    "earnings_growth": "رشد سود",
    "roe_stability": "پایداری ROE",
}
V_FA = {"pe": "نسبت قیمت به سود (P/E)", "pb": "نسبت قیمت به حق‌آبه (P/B)",
        "ps": "نسبت قیمت به فروش (P/S)"}
T_FA = {
    "momentum_6m_rel": "بازده ۶ماههٔ نسبی به میانگین هم‌وزن بازار",
    "momentum_3m_rel": "بازده ۳ماههٔ نسبی به میانگین هم‌وزن بازار",
    "relative_strength_6m_sector": "بازده ۶ماههٔ نسبی به میانگین صنعت",
    "low_volatility": "نوسان روزانه (انحراف معیار بازده)",
    "liquidity": "نقدشوندگی (میانگین ارزش معاملات روزانه)",
}

DISCLAIMER = ("این پرونده ابزار بررسی و مقایسه است؛ هیچ توصیهٔ خرید/فروش، هدف قیمتی یا "
              "امتیاز نهایی از ۱۰۰ نیست. همهٔ اعداد از آرتیفکت‌های همین snapshot می‌آیند "
              "و «ارزندگی» هرگز از پایین‌بودن یک نسبت به‌تنهایی استنباط نمی‌شود.")


def fnum(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    q_doc = json.load(open(f"{ART}/v2_q_observed_report.json", encoding="utf-8"))
    v_doc = json.load(open(f"{ART}/v2_value_pilot.json", encoding="utf-8"))
    t_doc = json.load(open(f"{ART}/v2_t_pilot.json", encoding="utf-8"))
    q_comps = q_doc["companies"]
    v_comps = v_doc["v_observed_report"]["companies"]
    t_rep = t_doc.get("t_observed_report", t_doc)
    t_comps = t_rep["companies"]
    iv = json.load(open(f"{OUT}/independent_validation_{TAG}.json", encoding="utf-8"))
    crc = json.load(open(f"{OUT}/capital_root_cause_{TAG}.json", encoding="utf-8"))
    crc_by_cid = {v["company_id"]: v for v in crc["companies"].values()}
    # کنترل اقتصادی ۲-ک-۴ (P1): طبقه‌بندی هر نسبت برای شرکت‌های دارای رویداد سرمایه‌ای
    econ_path = os.path.join(OUT, f"_p1_economic_control_{TAG}.json")
    econ_by_sym = {}
    if os.path.isfile(econ_path):
        econ_by_sym = json.load(open(econ_path, encoding="utf-8")).get("companies", {})

    binding = iv["snapshot_binding"]
    as_of = str(binding["as_of"])[:10]

    # گام ۲-ک-۵: هدف = ۱۶ نامزد IV + کل جمعیت سه‌محور واجد شرایط (۶۲).
    # برای غیرنامزدها IV نداریم → stub صادقانه «خارج از دامنهٔ نامزدی».
    triple_ids = sorted(
        cid for cid in q_comps
        if cid in v_comps and cid in t_comps
        and q_comps[cid].get("pilot_eligible")
        and v_comps[cid].get("pilot_eligible")
        and t_comps[cid].get("pilot_eligible"))
    iv_ids = list(iv["companies"].keys())
    target_cids = sorted(set(iv_ids) | set(triple_ids))
    n_shortlist = sum(1 for c in iv["companies"].values() if c.get("shortlist"))
    print(f"dossier population: {len(target_cids)} "
          f"(iv {len(iv_ids)} / triple {len(triple_ids)})")

    def iv_stub(cid):
        qc0 = q_comps.get(cid) or {}
        return {"symbol": qc0.get("symbol") or (v_comps.get(cid) or {}).get("symbol"),
                "display_name": None, "shortlist": False,
                "status": "not_in_shortlist_scope",
                "status_label": "خارج از فهرست کوتاه این snapshot",
                "status_definition": (
                    "این شرکت واجد شرایط سه‌محور است اما عضو فهرست کوتاه "
                    "مقایسه‌پذیر این snapshot نیست؛ اعتبارسنجی مستقل ۲-ک-۲ فقط "
                    "روی نامزدها اجرا شده و برای این شرکت شاهدی وجود ندارد — "
                    "هیچ وضعیتی به آن نسبت داده نمی‌شود."),
                "reasons": [], "checks": {}}

    # همتایان ارزش‌گذاری: هم‌صنعت + هم‌خانواده + نسبتِ معتبر — از خود آرتیفکت V
    def value_peers(cid):
        me = v_comps[cid]
        out = {}
        for other_id, oc in v_comps.items():
            if other_id == cid or oc.get("model_family") != me.get("model_family") \
                    or oc.get("industry") != me.get("industry"):
                continue
            for fn in ("pe", "pb", "ps"):
                f = (oc.get("factors") or {}).get(fn)
                if f and f.get("included") and f.get("raw_status") == "valid":
                    out.setdefault(fn, []).append(
                        {"symbol": oc.get("symbol"), "company_id": other_id,
                         "value": fnum(f.get("raw_value"))})
        return out

    dossiers = {}
    for cid in target_cids:
        ivc = iv["companies"].get(cid) or iv_stub(cid)
        qc, vc, tc = q_comps[cid], v_comps[cid], t_comps.get(cid, {})
        checks = ivc.get("checks") or {}
        mkt = checks.get("independent_market") or {}
        trace = checks.get("q_cell_trace") or []
        winner = next((t for t in trace if t.get("cell") == "winner"), None)

        # ── بخش ۱: کیفیت (Q) ────────────────────────────────────────────────
        strengths, weaknesses, excluded = [], [], []
        for fn, f in (qc.get("factors") or {}).items():
            if not f.get("in_aggregation_scope") or not f.get("included"):
                reason = f.get("not_included_reason") or (
                    (qc.get("data_confidence", {}).get("missing_reasons") or {}).get(fn)) \
                    or "خارج از دامنهٔ تجمیع"
                excluded.append({"factor": fn, "fa": Q_FA.get(fn, fn), "reason": str(reason)[:200]})
                continue
            row = {"factor": fn, "fa": Q_FA.get(fn, fn), "direction": f.get("direction"),
                   "score": fnum(f.get("score")), "contribution": fnum(f.get("contribution_points")),
                   "weight": f.get("weight"), "warnings": f.get("warnings") or []}
            (strengths if fnum(f.get("score")) is not None and f["score"] >= 0.55
             else weaknesses).append(row)
        strengths.sort(key=lambda r: -(r["contribution"] or 0))
        weaknesses.sort(key=lambda r: (r["score"] if r["score"] is not None else 1))
        quality = {
            "strengths": strengths[:4], "weaknesses": weaknesses[:4],
            "excluded_diagnostic": excluded,
            "coverage": {"covered_weight": fnum(qc.get("covered_weight")),
                         "missing_weight": fnum(qc.get("missing_weight")),
                         "coverage_ratio": fnum(qc.get("coverage_ratio"))},
            "evidence_note": ("همهٔ اعداد Q صدکِ درون‌خانواده از خود آرتیفکت نسخه‌دار است؛ "
                              "مقدار خام فاکتورهای Q در آرتیفکت منتشر نشده و اینجا از هیچ "
                              "منبع دیگری (از جمله موتور قدیمی V1) استفاده نشده است."),
        }

        # ── بخش ۲: ارزندگی (V) ──────────────────────────────────────────────
        peers = value_peers(cid)
        ratios = []
        for fn in ("pe", "pb", "ps"):
            f = (vc.get("factors") or {}).get(fn)
            if not f:
                continue
            pl = sorted(peers.get(fn, []), key=lambda x: x["value"])
            raw = fnum(f.get("raw_value"))
            # جایگاه در میان همتایان معتبر، با جهت فاکتور (lower = کوچک‌تر بهتر)
            rank = None
            if raw is not None and pl:
                if f.get("direction") == "lower":
                    better = [p for p in pl if p["value"] < raw]
                else:
                    better = [p for p in pl if p["value"] > raw]
                rank = 1 + len(better)
            warnings = f.get("warnings") or []
            if f.get("raw_status") != "valid" or raw is None:
                rel = "missing"
            elif warnings:
                rel = "time_limited"
            else:
                rel = "reliable"
            ratios.append({
                "name": fn, "fa": V_FA[fn], "raw_value": raw, "direction": f.get("direction"),
                "score": fnum(f.get("score")), "contribution": fnum(f.get("contribution_points")),
                "weight": f.get("weight"), "essential": f.get("essential"),
                "included": bool(f.get("included")),
                "n_peers_sector": f.get("n_valid_sector"), "n_peers_family": f.get("n_valid_market_family"),
                "peer_rank": rank, "n_peers": len(pl),
                "peer_values": pl[:8],
                "reliability": rel,
                "reliability_fa": {"reliable": "نسبت معتبر (هم‌زمانی سهام/قیمت در پنجرهٔ آرتیفکت)",
                                   "time_limited": "محدودیت زمانی: هشدار هم‌زمانی snapshot سهام و قیمت ثبت شده",
                                   "missing": "فاقد دادهٔ معتبر"}[rel],
                "warnings": [str(w)[:200] for w in warnings],
            })
        value = {
            "ratios": ratios,
            "caveats": [
                "پایین‌بودن یک نسبت به‌تنهایی معادل ارزندگی قطعی نیست؛ نسبت‌ها در بستر سودآوری، رشد و ریسک همین پرونده باید خوانده شوند.",
            ],
            "points": fnum(vc.get("v_observed_points")),
            "covered_weight": fnum(vc.get("covered_weight")),
            "missing_weight": fnum(vc.get("missing_weight")),
        }
        crc = crc_by_cid.get(cid)
        econ = econ_by_sym.get(ivc["symbol"]) or {}
        if crc and crc.get("outcome") == "explained_resolved":
            if econ:
                # نتیجهٔ اثبات‌شدهٔ ۲-ک-۴ P1: فقط P/B محدودیت دارد؛ P/E و P/S
                # تجمیعی‌اند و از تغییر پایهٔ سهام بی‌تأثیرند.
                value["caveats"].append(
                    "کنترل اقتصادی ۲-ک-۴: P/E و P/S تجمیعی (mcap ÷ جریان مطلق) از رویداد "
                    "افزایش سرمایه بی‌تأثیرند (verified)؛ فقط P/B محدودیت زمانی دارد: "
                    "مخرج آن حقوق صاحبان سهامِ گزارش پیش از واریز آوردهٔ حق‌تقدم است، "
                    "پس P/B منتشرشده «گران‌تر از واقع» نمایش داده می‌شود (جهت محافظه‌کارانه) "
                    "و بزرگی آن تا انتشار ترازنامهٔ بعدی قابل کمّی‌سازی نیست. "
                    + "منبع: _p1_economic_control همین snapshot.")
            else:
                value["caveats"].append(
                    "پس از افزایش سرمایهٔ ثبت‌شده، مخرج P/B و P/S از گزارش پیش از افزایش می‌آید؛ "
                    "با مؤلفهٔ آوردهٔ حق‌تقدم، این نسبت‌ها «گران‌تر از واقع» نمایش داده می‌شوند (جهت محافظه‌کارانه). "
                    + "منبع: capital_root_cause همین snapshot.")
            value["caveats"].append(
                "هشدار عمومی موتور دربارهٔ «اثبات‌نشدن هم‌زمانی سهام و قیمت» برای این شرکت با شواهد "
                "ثبت‌شدهٔ حق‌تقدم (corporate_actions تأییدشده) روشن‌تر شده است؛ هشدار موتور دست‌نخورده "
                "در بخش شواهد حفظ شده است.")

        # ── بخش ۳: وضعیت بازار و ورود (T) ───────────────────────────────────
        t_rows = []
        for fn, f in (tc.get("factors") or {}).items():
            if not f.get("included"):
                continue
            raw = fnum(f.get("raw_value"))
            if fn in ("momentum_6m_rel", "momentum_3m_rel", "relative_strength_6m_sector"):
                plain = f"{raw * 100:+.1f} واحد درصد نسبت به میانگین" if raw is not None else None
            elif fn == "low_volatility":
                plain = f"انحراف معیار روزانه {raw:.2%}" if raw is not None else None
            elif fn == "liquidity":
                plain = f"میانگین ارزش معاملات {raw / 1e9:,.1f} میلیارد ریال" if raw is not None else None
            else:
                plain = None
            t_rows.append({"factor": fn, "fa": T_FA.get(fn, fn), "raw_value": raw,
                           "direction": f.get("direction"), "score": fnum(f.get("score")),
                           "contribution": fnum(f.get("contribution_points")),
                           "weight": f.get("weight"), "plain": plain,
                           "warnings": [str(w)[:200] for w in (f.get("warnings") or [])]})
        t_rows.sort(key=lambda r: -(r["contribution"] or 0))
        market = {
            "factors": t_rows,
            "points": fnum(tc.get("t_observed_points")),
            "price": {"price_rial": fnum(mkt.get("price")), "trade_date": mkt.get("trade_date"),
                      "shares": fnum(mkt.get("shares")),
                      "market_cap_rial": fnum(mkt.get("market_cap")),
                      "share_source": mkt.get("share_source"),
                      "note": "قیمت از منبع مستقل market.price_observations در پنجرهٔ PIT آرتیفکت؛ سری قیمت vendor-adjusted است و تعدیل‌های اقتصادیِ تأییدشده فقط رویدادهای is_confirmed جدول corporate_actions هستند."},
            "adjustment_status": (
                "برای این شرکت حق‌تقدم تأییدشده در corporate_actions ثبت شده است (تعدیل اقتصادی تأییدشده)."
                if crc and crc.get("outcome") == "explained_resolved"
                else "هیچ رویداد سرمایه‌ای تأییدشده‌ای برای این شرکت ثبت نشده؛ تعدیل vendor تأیید اقتصادی مستقل نشده است."),
        }

        # ── بخش ۴: شواهد و ریسک ─────────────────────────────────────────────
        warn_fin = []
        for ax, cdoc in (("q", qc), ("v", vc), ("t", tc)):
            rgx = cdoc.get("risk_gate") or {}
            for w in (rgx.get("financial_warnings") or []):
                warn_fin.append(f"[{ax.upper()}] {w}")
        evidence = {
            "data_confidence": {"status": (qc.get("data_confidence") or {}).get("status"),
                                "covered_weight": fnum((qc.get("data_confidence") or {}).get("covered_weight")),
                                "pit_status_counts": (qc.get("data_confidence") or {}).get("pit_status_counts"),
                                "missing_reasons": {k: str(v)[:160] for k, v in
                                                    ((qc.get("data_confidence") or {}).get("missing_reasons") or {}).items()}},
            "risk_gate": {"status": (qc.get("risk_gate") or {}).get("status"),
                          "financial_warnings": warn_fin,
                          "note": (qc.get("risk_gate") or {}).get("note")},
            "independent_validation": {
                "status": ivc["status"], "status_label": ivc["status_label"],
                "status_definition": ivc.get("status_definition"),
                "reasons": ivc.get("reasons")},
            "capital_events": ([] if not crc or crc.get("outcome") != "explained_resolved" else [{
                "outcome": crc["outcome_label"],
                "ex_date": crc["evidence_chain"]["ex_date"],
                "old_shares": crc["evidence_chain"]["confirmed_rights_issue"]["metadata"]["old_shares"],
                "new_shares": crc["evidence_chain"]["confirmed_rights_issue"]["metadata"]["new_shares"],
                "funding_tags": crc["evidence_chain"]["confirmed_rights_issue"]["metadata"].get("lt28_funding_tags"),
                "codal_reference": crc["evidence_chain"]["share_interval_post"]["evidence"].get("codal_report_id"),
                "implied_vs_recorded_rel_diff": crc["evidence_chain"]["implied_vs_pre_interval_rel_diff"],
                "ratio_classification": {
                    "pe": "verified — نسبت تجمیعی از تغییر پایهٔ سهام بی‌تأثیر است",
                    "ps": "verified — فروش جریان مطلق است",
                    "pb": "verified_with_limitation — مخرج پیش از واریز آورده؛ "
                          "گران‌نمایی محافظه‌کارانه با کف نامعلوم",
                } if econ else None,
                "accounting_effect": (econ.get("accounting_effect_on_equity")
                                      if econ else None),
                "caveat": "هیچ رویداد ثبت‌نشده‌ای «اثبات نبود تغییر» تلقی نمی‌شود؛ این مورد با شواهد ثبت‌شده توضیح داده شد، نه فرض.",
            }]),
            "effective_dates": {
                "as_of": as_of, "cutoff": str(binding["cutoff"]),
                "winner_period_end": (winner or {}).get("period_end"),
                "winner_publish_at": (winner or {}).get("publish_at"),
                "winner_tracing_no": (winner or {}).get("tracing_no"),
                "price_trade_date": mkt.get("trade_date")},
        }

        # ── بخش ۵: جمع‌بندی توضیح‌پذیر (قاعده‌محور، هر جمله به عدد وصل) ──────
        why, risks, needs = [], [], []
        # برچسب گروه، همان فرمت discovery بک‌اند است: صنعت «X» / خانواده Y
        glabel = f"صنعت «{qc.get('industry')}» / خانواده {qc.get('model_family')}"
        if ivc.get("shortlist"):
            why.append(f"عضو فهرست کوتاه گروه مقایسه‌پذیر «{glabel}» — مقایسه فقط داخل همین گروه معتبر است.")
        else:
            why.append(f"واجد شرایط سه‌محور (Q/V/T) است اما گروه همتای معتبرِ به حداقل‌عضو ندارد یا در فهرست کوتاه این snapshot نیست — "
                       f"نمایش به‌صورت «قابل بررسی با محدودیت مقایسه» است و هیچ رتبهٔ نسبی مصنوعی برای آن ساخته نشده. گروه: {glabel}.")
        if strengths:
            s0 = strengths[0]
            why.append(f"قوی‌ترین فاکتور کیفیت: {s0['fa']} با صدک {s0['score']:.0%} خانواده "
                       f"({s0['contribution']:.1f} امتیاز از {s0['weight']}).")
        for r in ratios:
            if r["peer_rank"] and r["raw_value"] is not None and r["n_peers"] and r["peer_rank"] <= 2:
                why.append(f"{r['fa']} = {r['raw_value']:.2f} — رتبهٔ {r['peer_rank']} از "
                           f"{r['n_peers']} هم‌صنعت/هم‌خانوادهٔ دارای نسبت معتبر.")
        for r in market["factors"]:
            if r["factor"] == "momentum_6m_rel" and (r["score"] or 0) >= 0.6:
                why.append(f"مومنتوم ۶ماههٔ نسبی مثبت ({r['plain']}).")
        if not why:
            why.append("نامزد بودن این شرکت فقط از لایه‌بندی پارتو داخل گروهش می‌آید؛ فاکتور برجسته‌ای ثبت نشده است.")

        if weaknesses:
            w0 = weaknesses[0]
            risks.append(f"ضعیف‌ترین فاکتور کیفیت: {w0['fa']} با صدک {w0['score']:.0%}.")
        # هشدارهای نسبت‌ها بدون تکرار: متن یکسان یک‌بار با نام نسبت‌ها می‌آید
        warn_map = {}
        for r in ratios:
            for w in r["warnings"]:
                warn_map.setdefault(str(w)[:200], []).append(r["fa"])
        for w, rn in warn_map.items():
            risks.append(f"{'، '.join(rn)}: {w}")
        if ivc["status"] != "independently_checked":
            if not ivc.get("shortlist"):
                risks.append(
                    "اعتبارسنجی مستقل ۲-ک-۲ فقط روی فهرست کوتاه اجرا شده؛ برای این شرکت "
                    "هیچ شاهد مستقلی ثبت نشده و هیچ وضعیت اعتبارسنجی‌ای به آن نسبت داده نمی‌شود "
                    "(نبود شاهد ≠ تأیید).")
            elif crc and crc.get("outcome") == "explained_resolved":
                # دلیل اصلی ۲-ک-۲ (ابهام سهام/EPS) با شواهد ثبت‌شدهٔ P0 توضیح داده
                # شد — جای تکرار همان دلیل، پیوند به رفع آن می‌آید.
                risks.append(
                    "وضعیت اعتبارسنجی مستقل «سازگار اما مستقل نه» است؛ دلیل آن (ابهام پایهٔ سهام/EPS) "
                    "در همین snapshot با شواهد ثبت‌شدهٔ corporate_actions و share_intervals توضیح داده شد "
                    "(بخش رویداد سرمایه) — آن ابهام دیگر باز است، ولی حلقه‌های اثبات مستقل ناقص می‌ماند.")
                if econ:
                    # نتیجهٔ کمّی ۲-ک-۴: اثر رویداد روی هر نسبت، تفکیک‌شده
                    risks.append(
                        "اثر رویداد سرمایه‌ای روی نسبت‌ها تفکیک شد: P/E و P/S تجمیعی بدون اعوجاج "
                        "(verified)؛ فقط P/B با محدودیت «مخرج پیش از واریز آورده» گران‌نمایی "
                        "محافظه‌کارانه دارد — هشدارهای موتور حذف نشده‌اند.")
            else:
                for rs in ivc.get("reasons") or []:
                    risks.append(rs)
        if crc and crc.get("outcome") == "explained_resolved":
            ec = crc["evidence_chain"]
            risks.append(
                "پایهٔ EPS نامهٔ منتشرشده هنوز پیش از افزایش سرمایه است"
                + (" (ex-date پس از پایان سال مالی — انتظار می‌رود نامهٔ فصلی بعدی پایهٔ جدید را نشان دهد)."
                   if ec["ex_date_vs_winner_period_end"] == "پس از پایان سال مالی"
                   else " (ex-date داخل سال مالی — نامهٔ فصلی بعدی باید پایهٔ جدید را تأیید کند)."))
        pit_counts = (qc.get("data_confidence") or {}).get("pit_status_counts") or {}
        if pit_counts.get("unverified_no_publication_date"):
            risks.append(f"{pit_counts['unverified_no_publication_date']} سلول Q بدون تاریخ انتشار تأییدشده است "
                         "(برنامهٔ backfill آماده است؛ اجرا نشده).")
        if not risks:
            risks.append("هیچ ریسک ثبت‌شده‌ای در شواهد این snapshot نیست؛ «بی‌هشدار» هرگز به معنای «بی‌ریسک» نیست.")

        if ivc["status"] != "independently_checked":
            needs.append("تکمیل حلقه‌های اثبات‌نشدهٔ اعتبارسنجی مستقل (طبق اقدامات پیشنهادی همین پرونده).")
        if crc and crc.get("outcome") == "explained_resolved":
            needs.append("نامهٔ فصلی بعدی برای تأیید پایهٔ سهام جدید و به‌روز شدن مخرج P/B و P/S.")
        for fn, reason in ((qc.get("data_confidence") or {}).get("missing_reasons") or {}).items():
            needs.append(f"فاکتور {Q_FA.get(fn, fn)}: {str(reason)[:120]}")
        if not needs:
            needs.append("در حال حاضر اقدام بازدارنده‌ای ثبت نشده؛ پایش گزارش‌های بعدی کافی است.")

        dossiers[cid] = {
            "company_id": cid, "symbol": ivc["symbol"],
            "display_name": ivc.get("display_name"),
            "industry": qc.get("industry"), "model_family": qc.get("model_family"),
            "sections": {"quality": quality, "value": value, "market": market,
                         "evidence": evidence,
                         "summary": {"why_review": why, "main_risk": risks,
                                     "needed_evidence": needs}},
        }

    doc = {
        "mission": "گام ۲-ک-۳ P2 — پرونده تصمیم‌یار سهم (فقط شواهد نسخه‌دار همین snapshot)",
        "snapshot_binding": binding,
        "generated_note": ("زمان تولید این گزارش، تاریخ انتشار هیچ داده‌ای نیست. هیچ امتیاز ترکیبی، "
                           "وزن پنهان یا بازتوزیع وزن مفقود ساخته نشده؛ مقایسه فقط داخل هم‌صنعت/هم‌خانواده است."),
        "disclaimer": DISCLAIMER,
        "companies": dossiers,
    }
    path = f"{OUT}/decision_dossier_{TAG}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, default=str)
    print(f"saved {path} — {len(dossiers)} dossiers")
    s0 = dossiers[target_cids[0]]
    print(json.dumps(s0["sections"]["summary"], ensure_ascii=False, indent=1)[:900])


if __name__ == "__main__":
    main()
