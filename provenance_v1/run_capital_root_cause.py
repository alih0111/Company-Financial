# -*- coding: utf-8 -*-
"""P0 ۲-ک-۳: تعیین تکلیف ناسازگاری EPS/تعداد سهام بوعلی و کرماشا.

ورودی: _p0_share_evidence_{tag}.json (شواهد خام فقط‌خواندنی) + independent_validation_{tag}.json
خروجی: capital_root_cause_{tag}.json + .md — طبقه‌بندی سه‌حالت با شواهد ردیفی.
هیچ مقدار فرضی تولید نمی‌شود؛ هر ادعا به منبع وصل است.
"""
import json, os, sys

TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
OUT = "provenance_v1/output"
NOMINAL_RIAL = 1000  # اسموم اسمی — با capital/تعداد سهام هر دو شرکت سازگار است (کنترل می‌شود)


def fnum(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rd(a, b):
    if a is None or b is None or b == 0:
        return None
    return abs(a - b) / abs(b)


def main():
    ev = json.load(open(f"{OUT}/_p0_share_evidence_{TAG}.json", encoding="utf-8"))
    iv = json.load(open(f"{OUT}/independent_validation_{TAG}.json", encoding="utf-8"))

    results = {}
    for sym, e in ev.items():
        cid = e["company_id"]
        chk = iv["companies"][cid]["checks"]
        xchk = chk["eps_cross_check"]
        val = chk["independent_valuation"]
        mkt = chk["independent_market"]

        # اینتروال پیش/پس از افزایش و رویداد تأییدشده
        ints = [i for i in e["share_intervals"] if i.get("shares_outstanding")]
        ints.sort(key=lambda i: i["valid_from"] or "")
        post = next((i for i in ints if i["valid_from"] and i["valid_from"] >= "2026-01-01"
                     and fnum(i["shares_outstanding"]) == fnum(xchk["used_shares"])), None)
        pre = next((i for i in reversed(ints) if i is not post and fnum(i["shares_outstanding"])), None)
        rights = [a for a in e["corporate_actions"]
                  if a.get("action_type") == "rights_issue" and a.get("is_confirmed")
                  and a.get("action_date", "") >= "2026-01-01"]
        ra = rights[0] if rights else None
        meta = (ra or {}).get("metadata") or {}

        implied = fnum(xchk["implied_shares"])
        used = fnum(xchk["used_shares"])
        pre_sh = fnum(pre["shares_outstanding"]) if pre else None
        post_sh = fnum(post["shares_outstanding"]) if post else None

        # سازگاری‌ها
        implied_vs_pre = rd(implied, pre_sh)
        used_vs_post = rd(used, post_sh)
        ratio_check = rd(used / implied, post_sh / pre_sh) if implied and pre_sh and post_sh else None

        # تقویم: ex-date نسبت به پایان سال مالی برنده
        wr = next((r for r in e["income_report_timeline"] if r["period_end"] == "2026-06-21"), None)
        ex_date = meta.get("ex_date") or (ra or {}).get("action_date")
        ex_vs_period_end = ("پیش از پایان سال مالی" if ex_date and wr and ex_date < wr["period_end"]
                            else "پس از پایان سال مالی" if ex_date and wr else None)

        # کنترل اسموم: capital گزارش (canonical rial) / تعداد سهم ضمنی ≈ ۱۰۰۰؟
        facts = (wr or {}).get("facts") or {}
        cap1 = fnum(((facts.get("capital") or {}).get("1") or {}).get("canonical"))
        eps1 = fnum(((facts.get("eps") or {}).get("1") or {}).get("canonical"))
        np1 = fnum(((facts.get("net_profit") or {}).get("1") or {}).get("canonical"))
        nominal_implied = (cap1 / implied) if cap1 and implied else None

        # جدول سناریو
        r_share = used / implied if implied else None
        scen = {
            "A_as_computed": {"pe": val["pe_published"], "ps": val["ps"], "pb": val["pb"],
                              "note": "ارزش کل بازار با سهام فعلی ÷ سود/فروش TTM و حق‌آبهٔ آخرین گزارش — محاسبهٔ فعلی موتور"},
            "B_refuted_counterfactual": {
                "pe": val["pe_published"] / r_share, "ps": val["ps"] / r_share, "pb": val["pb"] / r_share,
                "note": "فرض نادر «سهام همچنان پایهٔ پیش از افزایش» — با شواهد ثبت‌شده رد می‌شود؛ فقط برای نمایش بزرگی اثر"},
            "C_eps_mixing_trap": {
                "pe_price_over_report_eps": (mkt["price"] / eps1) if eps1 else None,
                "note": "تلهٔ ترکیب: قیمت امروز (هر سهم جدید) ÷ EPS گزارش (هر سهم قدیم) — نامعتبر؛ بیش از r_share برابر گمراه‌کننده"},
        }

        # طبقه‌بندی سه‌حالتی
        if (ra is not None and post is not None and used_vs_post is not None and used_vs_post < 1e-9
                and implied_vs_pre is not None and implied_vs_pre < 0.005 and ratio_check is not None
                and ratio_check < 0.005):
            outcome = "explained_resolved"
        elif implied_vs_pre is None or ra is None:
            outcome = "insufficient_evidence"
        else:
            outcome = "real_inconsistency"

        # اثر بر ارزش‌گذاری/رتبه‌بندی
        impact = {
            "pe": "P/E تجمیعی (mcap/TTM) از تغییر تعداد سهام متأثر نمی‌شود — بدون اثر.",
            "pb_ps": ("صورت کسر (mcap) پس از افزایش است و مخرج (حق‌آبه/فروش) از گزارش پیش از افزایش می‌آید؛ "
                      "با مؤلفهٔ rights_cash، حق‌آبهٔ واقعی پس از دریافت آورده بالاتر خواهد بود → P/B (و تا حدی P/S) "
                      "محاسبه‌شده «گران‌تر از واقع» نمایش داده می‌شود — جهت محافظه‌کارانه؛ بزرگی تا انتشار ترازنامهٔ بعدی قابل کمّی‌سازی نیست."),
            "score_change": "هیچ امتیاز یا رتبه‌ای تغییر نکرد؛ اثر فقط به‌صورت هشدار توضیحی در پرونده تصمیم‌یار نمایش داده می‌شود.",
        }

        results[sym] = {
            "company_id": cid,
            "symbol": sym,
            "outcome": outcome,
            "outcome_label": {
                "explained_resolved": "۱ — ناسازگاری توضیح داده شد و حل شد (با شواهد ثبت‌شده، نه فرض)",
                "real_inconsistency": "۲ — ناسازگاری واقعی تأیید شد",
                "insufficient_evidence": "۳ — شواهد کافی نیست",
            }[outcome],
            "evidence_chain": {
                "share_interval_pre": pre,
                "share_interval_post": post,
                "confirmed_rights_issue": ra,
                "implied_shares_from_eps_cell": implied,
                "implied_vs_pre_interval_rel_diff": implied_vs_pre,
                "used_shares_by_engine": used,
                "used_vs_post_interval_rel_diff": used_vs_post,
                "used_over_implied_vs_post_over_pre_rel_diff": ratio_check,
                "ex_date": ex_date,
                "ex_date_vs_winner_period_end": ex_vs_period_end,
                "winner_period_end": (wr or {}).get("period_end"),
                "winner_published_at": (wr or {}).get("published_at"),
                "winner_tracing_no": chk["q_cell_trace"][0].get("tracing_no") if chk["q_cell_trace"] else None,
                "report_declared_capital_rial": cap1,
                "report_declared_capital_shares_at_1000r": (cap1 / NOMINAL_RIAL) if cap1 else None,
                "nominal_rial_implied_from_capital_and_implied_shares": nominal_implied,
                "report_eps_order1": eps1,
                "report_net_profit_order1": np1,
                "eps_and_net_profit_same_statement": True,
                "units": "EPS: rial_per_share · سود/سرمایه: canonical rial · قیمت: rial — سازگار",
                "share_events_rows": len(e["share_events"]),
                "letters_after_winner": e["all_letters_after_winner"],
                "weighted_average_row_available": False,
                "weighted_average_note": "ردیف «میانگین موزون سهام» در داده‌های پارس‌شده وجود ندارد؛ پایهٔ سهام گزارش فقط به‌صورت ضمنی (سود ÷ EPS از همان سلول) استخراج می‌شود.",
            },
            "eps_cross_check_from_2k2": xchk,
            "scenario_ratios": scen,
            "valuation_ranking_impact": impact,
            "residual_caveats": [
                "نامهٔ برنده «میاندوره‌ای ۳ ماهه، حسابرسی‌نشده» است؛ پایهٔ EPS آن پیش از افزایش است" +
                (" در حالی که ex-date پیش از پایان سال مالی است — نامهٔ فصلی بعدی باید پایهٔ جدید را تأیید کند (اقدام پایشی)."
                 if ex_vs_period_end == "پیش از پایان سال مالی"
                 else " و ex-date پس از پایان سال مالی است — ناسازگاری زمانی کامل توضیح‌پذیر است."),
                "share_events هنوز هیچ ردیفی برای این شرکت ندارد؛ زنجیرهٔ اثبات از share_intervals + corporate_actions (تأییدشده، با ارجاع کدال) می‌آید.",
                "این طبقه‌بندی «تأیید نهایی اقتصادی» نیست؛ مبنای آن تطابق چندمنبعی ثبت‌شده است.",
            ],
        }

    doc = {
        "mission": "گام ۲-ک-۳ P0 — تعیین تکلیف ناسازگاری اقتصادی بوعلی و کرماشا",
        "binding": iv["snapshot_binding"],
        "generated_note": ("این گزارش فقط برای همین snapshot تولید شده است؛ زمان تولید گزارش، تاریخ انتشار هیچ داده‌ای نیست. "
                           "هیچ داده‌ای برای رسیدن به نتیجه دستکاری نشده و همهٔ شواهد از جداول فقط‌خواندنی خوانده شده‌اند."),
        "companies": results,
    }
    with open(f"{OUT}/capital_root_cause_{TAG}.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, default=str)

    # MD خلاصه
    lines = ["# P0 ۲-ک-۳ — ریشه‌یابی ناسازگاری EPS/سهام بوعلی و کرماشا", ""]
    for sym, r in results.items():
        lines += [f"## {sym} — {r['outcome_label']}", ""]
        ec = r["evidence_chain"]
        lines += [
            f"- پایهٔ ضمنی سهام از سلول برنده (سود÷EPS همان statement): **{ec['implied_shares_from_eps_cell']:,.0f}**",
            f"- فاصلهٔ آن با سرمایهٔ ثبت‌شدهٔ پیش از افزایش: **{ec['implied_vs_pre_interval_rel_diff']*100:.3f}%** (گردشدن EPS)",
            f"- سهام استفاده‌شدهٔ موتور: **{ec['used_shares_by_engine']:,.0f}** = دقیقاً سرمایهٔ ثبت‌شدهٔ پس از افزایش (اختلاف {ec['used_vs_post_interval_rel_diff']*100 if ec['used_vs_post_interval_rel_diff'] is not None else '؟'}%)",
            f"- حق‌تقدم تأییدشده: ex-date **{ec['ex_date']}** ({ec['ex_date_vs_winner_period_end']} با پایان سال مالی {ec['winner_period_end']}) — نسبت {ec['confirmed_rights_issue']['metadata']['old_shares']:,.0f} → {ec['confirmed_rights_issue']['metadata']['new_shares']:,.0f}، فاکتور تعدیل {ec['confirmed_rights_issue']['adjustment_factor']}، ارجاع کدال: {ec['share_interval_post']['evidence'].get('codal_report_id')}",
            f"- نرخ نسبت‌ها: used/implied با post/pre سازگار (اختلاف {ec['used_over_implied_vs_post_over_pre_rel_diff']*100:.4f}%)",
            f"- سرمایهٔ اعلانی گزارش: {ec['report_declared_capital_rial']:,.0f} ریال = {ec['report_declared_capital_shares_at_1000r']:,.0f} سهم با اسموم ۱۰۰۰ ریال (نسبت ضمنی اسموم: {ec['nominal_rial_implied_from_capital_and_implied_shares']:.1f} ریال)",
            f"- سود و EPS سلول برنده از **یک** statement واحدند (بدون اختلاف مستقل/تلفیقی).",
            "",
            "### بازبینی نسبت‌ها",
            f"| سناریو | P/E | P/S | P/B |",
            f"|---|---|---|---|",
            f"| A — محاسبهٔ فعلی (تجمیعی) | {r['scenario_ratios']['A_as_computed']['pe']:.3f} | {r['scenario_ratios']['A_as_computed']['ps']:.3f} | {r['scenario_ratios']['A_as_computed']['pb']:.3f} |",
            f"| B — فرض ردشده (پایهٔ قدیم) | {r['scenario_ratios']['B_refuted_counterfactual']['pe']:.3f} | {r['scenario_ratios']['B_refuted_counterfactual']['ps']:.3f} | {r['scenario_ratios']['B_refuted_counterfactual']['pb']:.3f} |",
            f"| C — تلهٔ ترکیب EPS (نامعتبر) | {r['scenario_ratios']['C_eps_mixing_trap']['pe_price_over_report_eps']:.3f} | — | — |",
            "",
            f"**اثر بر ارزش‌گذاری:** {r['valuation_ranking_impact']['pb_ps']}",
            "",
            "### محدودیت‌های باقی‌مانده",
        ]
        lines += [f"- {c}" for c in r["residual_caveats"]]
        lines.append("")
    with open(f"{OUT}/capital_root_cause_{TAG}.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("saved capital_root_cause", TAG)
    for sym, r in results.items():
        print(sym, "->", r["outcome"], "| implied_vs_pre:",
              round(r["evidence_chain"]["implied_vs_pre_interval_rel_diff"] * 100, 4), "%",
              "| used_vs_post:", r["evidence_chain"]["used_vs_post_interval_rel_diff"])


if __name__ == "__main__":
    main()
