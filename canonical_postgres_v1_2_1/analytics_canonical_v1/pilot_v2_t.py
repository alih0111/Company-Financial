"""Observed-T pilot for Score v2 (step 2-D-1) — the first REAL timing/
entry-conditions output. Deliberately NOT a final T and NOT a buy signal:

  * ``t_observed_points`` = Σ (config weight of an available factor × its
    normalized score), computed per company over ITS model family's T weight
    table (all four families: momentum_6m_rel 7 + momentum_3m_rel 5 +
    relative_strength_6m_sector 5 + liquidity 4 + low_volatility 4 = 25).
    The axis target is 25, but no missing weight is ever redistributed and
    the points are NEVER divided by covered_weight — an incomplete company
    keeps an incomplete point total, honestly labeled.
  * A missing/refused factor (insufficient history, stale price, suspected
    unadjusted gap, insufficient peers) has no score share and is never read
    as good or bad timing: it contributes nothing and its absence is named.
  * Companies are NEVER ranked by ``t_observed_points`` — coverage differs
    across companies, so a rank would compare different denominators. And a
    timing percentile is an entry-conditions reading, never a trade signal.
  * There is no timing_score / t_final / Q+V+T combination / QVT total
    anywhere in this pilot; the Q axis output of 2-B-8 and the V axis
    output of 2-J-1 are untouched.
  * Data Confidence and the Risk Gate stay independent, not_evaluated (the
    liquidity stall/halt evidence is preserved as Risk-Gate input, not
    converted into a penalty).

Weight-table control (mission 2-D-1 section 1): every family's T weights
are read live from score_v2_config.FAMILY_WEIGHTS and must sum exactly to
AXIS_WEIGHTS["timing"] (25). Any inconsistency raises TWeightInconsistency
and STOPS. The needs_development factor distance_from_52w_high carries a
target weight (4) in the registry but is in NO family map and is NEVER
computed, scored or redistributed — the config forbids any surrogate.

Market history comes ONLY from the engine's own loaded price rows
(market.price_observations, engine PIT filter; the vendor-adjusted series —
price_series = 'adjusted' on every row). The pilot deduplicates rows to one
per trade date (latest collected_at) and the raw layer drops any
trade_date > as_of in defense in depth. No new SQL, no fabricated calendar
days: missing days are missing, never interpolated.

Q/V overlap reads the saved 2-B-8 / 2-J-1 artifacts (same reproducible
snapshot) — never recomputed, never modified.

Pure aggregation: math.fsum over sorted keys, deterministic, no database
writes, no clock.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (str(HERE), str(HERE.parent.parent / "migration_tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import compute_metrics as CM  # noqa: E402  (read-only metric engine)
import score_v2_config as CFG2  # noqa: E402  (read-only weight registry)
import score_v2_normalize as SN  # noqa: E402
import score_v2_t_normalize as TN  # noqa: E402
import score_v2_t_raw as TRW  # noqa: E402
import score_v4 as S4  # noqa: E402  (PIT sector map, SELECT-only)

import pilot_v2_qvt as QP  # noqa: E402  (meta/provenance helpers, pure)
import pilot_v2_value as PV  # noqa: E402  (display sample, eligibility loader)

STAGE = "pilot_v2_t_exploratory"
AXIS = "timing"

DISCLAIMER = (
    "گام ۲-د-۱ — t_observed_points یک خروجی مشاهده‌شده آزمایشی شرایط ورود است، "
    "نه T کامل از ۲۵ و نه سیگنال خرید. وزن مفقود بازتوزیع نمی‌شود، امتیاز ناقص "
    "بر مبنای پوشش نرمال نمی‌شود، شرکت‌ها بر اساس آن رتبه‌بندی نمی‌شوند و "
    "مومنتوم/نقدشوندگی نسبی، ادعای جهت آینده قیمت نیست. Data Confidence و "
    "Risk Gate مستقل و فعلاً not_evaluated هستند و هیچ ترکیب Q+V+T یا امتیاز "
    "کل QVT ساخته نمی‌شود."
)

FORBIDDEN_AGGREGATE_KEYS = (
    "timing_score", "t_final_score", "t_final", "total_score", "qvt_score",
    "qvt_total", "quality_score", "valuation_score", "quant_score",
    "qv_score", "qt_score", "vt_score", "q_plus_v_plus_t",
)


class TWeightInconsistency(ValueError):
    """A family's T weight table contradicts the config/raw-layer contract —
    aggregation must STOP and the inconsistency be reported, never auto-fixed
    in code."""


def t_weight_table(family: str) -> dict:
    """The family's T-axis weight table, read live from config, with the
    implementation status per factor.

    Raises TWeightInconsistency when the weights do not sum exactly to
    AXIS_WEIGHTS["timing"], a mapped factor is not a READY timing factor, or
    a READY timing factor mapped for this family is missing from the raw
    layer's scope (stale config vs raw contract) — stop, never auto-fix.
    """
    if family not in CFG2.FAMILIES:
        raise ValueError(f"unknown family {family!r}; expected one of "
                         f"{CFG2.FAMILIES}")
    fam_map = CFG2.FAMILY_WEIGHTS[family]
    weights = {fid: w for fid, w in fam_map.items()
               if CFG2.V2_QVT_FACTORS[fid]["axis"] == AXIS}

    rows = {}
    for fid in sorted(weights):
        spec = CFG2.V2_QVT_FACTORS[fid]
        if spec["availability"] != CFG2.READY:
            raise TWeightInconsistency(
                f"{fid}: a needs_development factor must never appear in a "
                "family weight map")
        if fid not in TRW.IN_SCOPE_T_FACTORS:
            raise TWeightInconsistency(
                f"{fid}: mapped for {family} but absent from the T raw "
                "layer's scope — aggregation stops (report the "
                "inconsistency, never auto-fix)")
        rows[fid] = {"weight": weights[fid], "essential": spec["essential"],
                     "direction": spec["direction"],
                     "implementation": "implemented",
                     "in_aggregation_scope": True,
                     "aggregation_note": None}

    total = math.fsum(weights[f] for f in sorted(weights))
    target = CFG2.AXIS_WEIGHTS[AXIS]
    if abs(total - target) > 1e-9:
        raise TWeightInconsistency(
            f"{family} T-axis weights sum to {total}, expected {target} — "
            "aggregation stops; weights are recalibrated in config, never "
            "auto-fixed here")

    not_in_map = {fid: {"target_weight": spec["target_weight"],
                        "availability": spec["availability"],
                        "essential": spec["essential"],
                        "note": spec["note"]}
                  for fid, spec in sorted(CFG2.V2_QVT_FACTORS.items())
                  if spec["axis"] == AXIS and fid not in fam_map}
    return {"family": family, "axis": AXIS,
            "target_weight": target,
            "total_weight": total,
            "weights": dict(sorted(weights.items())),
            "rows": rows,
            "factors_not_in_family_map": not_in_map}


def _scored_factor(rollup) -> tuple:
    """(score, kind) when the rollup carries a usable normalized score —
    single ``ranked`` with a finite percentile_combined in [0, 1]."""
    if not isinstance(rollup, dict):
        return None, None
    if rollup.get("normalization_status") != SN.NR_RANKED:
        return None, None
    val = rollup.get("percentile_combined")
    if (isinstance(val, bool) or not isinstance(val, (int, float))
            or not math.isfinite(val) or not 0.0 <= float(val) <= 1.0):
        return None, None
    return float(val), "percentile_combined"


def _no_score_reason(rollup) -> str:
    st = (rollup or {}).get("normalization_status")
    if st is None:
        return "no normalize rollup for this company/factor"
    if st == SN.NR_RANKED:
        return ("score_refused: the rollup claims ranked but its score is "
                "not a finite number in [0, 1]")
    return {
        SN.NR_INSUFFICIENT_PEERS:
            "insufficient_peers: family peer population below family_min_n",
        SN.NR_NON_FINITE: "not_ranked_non_finite",
        SN.NR_PIT_STRICT: "not_ranked_pit_strict",
        SN.NR_AFTER_AS_OF: "collected_after_as_of",
        "not_ranked_raw_missing":
            "raw_missing: a timing input is absent or the history is too "
            "short — a missing factor has no score share, never a "
            "zero-performance reading",
        "not_ranked_raw_invalid":
            "raw_invalid: the raw layer refused the value (stale price, "
            "suspected unadjusted gap, overlong window)",
        "not_ranked_raw_not_applicable":
            "raw_not_applicable: economically meaningless for this company",
    }.get(st, f"unranked: {st}")


def _diag_bucket(reason: str) -> str:
    for prefix, bucket in (
            ("insufficient_peers", "insufficient_peers"),
            ("raw_missing", "missing"),
            ("raw_invalid", "invalid"),
            ("raw_not_applicable", "not_applicable"),
            ("score_refused", "score_refused"),
            ("no normalize rollup", "other_refusals")):
        if reason.startswith(prefix):
            return bucket
    return "other_refusals"


def build_t_observed_report(normalize_out: dict,
                            raw_by_company: dict,
                            company_meta: dict,
                            *,
                            symbols: dict | None = None,
                            coverage_threshold: float | None = None,
                            display_limit: int = 24) -> dict:
    """Aggregate the observed-T pilot over every model family.

    Per company (under ITS family's table): per-factor weight / raw value /
    score / contribution, t_observed_points over scored factors only,
    covered / missing weight and coverage_ratio against the 25 target, the
    essential gate (momentum_6m_rel and liquidity, per config), and
    pilot_eligible. Companies are never ranked by points.
    """
    thr = (CFG2.SCORING_POLICY["min_axis_coverage"]
           if coverage_threshold is None else float(coverage_threshold))
    if not 0 < thr <= 1:
        raise ValueError(f"coverage_threshold must be in (0, 1], got {thr!r}")

    tables = {fam: t_weight_table(fam) for fam in CFG2.FAMILIES}
    all_rollups = normalize_out.get("factors", {})

    companies: dict = {}
    n_eligible = n_any = n_zero = 0
    valid_by_factor: Counter = Counter()
    scored_by_factor: Counter = Counter()
    refusal_by_factor: dict = {}
    covered_hist: Counter = Counter()

    for cid in sorted(company_meta):
        meta = company_meta[cid] or {}
        fam = meta.get("model_family")
        table = tables[fam]
        weights, rows = table["weights"], table["rows"]
        target = table["target_weight"]
        essentials = sorted(f for f, r in rows.items() if r["essential"])

        rollups = all_rollups.get(cid, {})
        factors: dict = {}
        covered_pairs: list = []
        points_pairs: list = []
        ess_missing: list = []
        diag: Counter = Counter()

        for fid in sorted(weights):
            row = rows[fid]
            ru = rollups.get(fid) or {}
            score, kind = _scored_factor(ru)
            fentry = {"weight": row["weight"],
                      "essential": row["essential"],
                      "direction": row["direction"],
                      "raw_status": ru.get("raw_status"),
                      "raw_value": ru.get("raw_value"),
                      "normalization_status": ru.get("normalization_status"),
                      "n_valid_market_family": None,
                      "n_valid_sector": None,
                      "warnings": list(ru.get("warnings") or [])}
            rec = next((r for r in normalize_out.get("records", [])
                        if r["company_id"] == cid and r["factor_id"] == fid),
                       None)
            if rec:
                fentry["n_valid_market_family"] = rec["n_valid_market_family"]
                fentry["n_valid_sector"] = rec["n_valid_sector"]
            if score is None:
                reason = _no_score_reason(ru)
                fentry.update({"score": None, "score_kind": None,
                               "included": False,
                               "contribution_points": None,
                               "not_included_reason": reason})
                diag[_diag_bucket(reason)] += 1
                refusal_by_factor.setdefault(fid, Counter())[reason] += 1
            else:
                fentry.update({"score": score, "score_kind": kind,
                               "included": True,
                               "contribution_points": row["weight"] * score,
                               "not_included_reason": None})
                covered_pairs.append((fid, row["weight"]))
                points_pairs.append((fid, row["weight"] * score))
                scored_by_factor[fid] += 1
            if ru.get("raw_status") == "valid":
                valid_by_factor[fid] += 1
            if row["essential"] and not fentry["included"]:
                ess_missing.append(fid)
            factors[fid] = fentry

        covered = math.fsum(w for _f, w in sorted(covered_pairs))
        points = (math.fsum(p for _f, p in sorted(points_pairs))
                  if points_pairs else None)
        ratio = covered / target
        ess_ok = not ess_missing
        cov_ok = ratio >= thr - PV.COV_EPS
        eligible = ess_ok and cov_ok

        n_eligible += eligible
        n_any += bool(points_pairs)
        n_zero += not points_pairs
        covered_hist[f"{round(covered, 6):g}"] += 1

        warnings = sorted({w for fid in sorted(raw_by_company.get(cid) or {})
                           for w in (raw_by_company[cid][fid].get("warnings")
                                     or [])})
        entry = {
            "company_id": cid,
            "symbol": (symbols or {}).get(cid),
            "model_family": fam,
            "industry": meta.get("industry"),
            "factors": factors,
            "t_observed_points": points,
            "covered_weight": covered,
            "missing_weight": target - covered,
            "coverage_ratio": ratio,
            "coverage_threshold_met": cov_ok,
            "essential_status": {"required": essentials,
                                 "missing": sorted(ess_missing),
                                 "all_satisfied": ess_ok},
            "pilot_eligible": eligible,
            "diagnostic_counts": dict(sorted(diag.items())),
            "data_confidence": {
                "status": "not_evaluated",
                "covered_weight": covered,
                "coverage_ratio": ratio,
                "missing_reasons": {
                    fid: factors[fid]["not_included_reason"]
                    for fid in sorted(factors)
                    if not factors[fid]["included"]},
                "note": ("diagnostic only — the numeric Data Confidence "
                         "formula is not approved yet; no confidence "
                         "coefficient touches t_observed_points"),
            },
            "risk_gate": {
                "status": "not_evaluated",
                "final_evaluation": "not_evaluated",
                "trading_warnings": warnings,
                "note": ("warnings are preserved evidence only (halts, "
                         "gaps, window composition); absence of warnings "
                         "is never a low-risk or risk-cleared verdict; no "
                         "risk penalty is applied to t_observed_points"),
            },
        }
        companies[cid] = entry

    summary = {
        "n_companies_total": len(companies),
        "n_any_score": n_any,
        "n_zero_coverage": n_zero,
        "n_pilot_eligible": n_eligible,
        "n_raw_valid_by_factor": dict(sorted(valid_by_factor.items())),
        "n_scored_by_factor": dict(sorted(scored_by_factor.items())),
        "refusal_reasons_by_factor": {
            fid: dict(sorted(c.items()))
            for fid, c in sorted(refusal_by_factor.items())},
        "max_covered_weight_observed": max(
            (e["covered_weight"] for e in companies.values()), default=0.0),
        "covered_weight_distribution": dict(sorted(
            covered_hist.items(), key=lambda kv: float(kv[0]))),
        "policy": {
            "coverage_threshold": thr,
            "threshold_source": "score_v2_config.SCORING_POLICY"
                                ".min_axis_coverage",
            "renormalization": ("forbidden — a missing factor's weight is "
                                "never redistributed and t_observed_points "
                                "is never divided by covered_weight"),
            "ranking": ("companies are never ranked by t_observed_points — "
                        "coverage differs across companies; a timing "
                        "percentile is an entry-conditions reading, not a "
                        "trade signal or a direction claim"),
            "independent_systems": ("Data Confidence and Risk Gate stay "
                                    "not_evaluated; no coefficient or "
                                    "penalty touches the points"),
        },
    }
    return {
        "stage": STAGE,
        "score_version": CFG2.SCORE_VERSION,
        "as_of": normalize_out.get("as_of"),
        "pit_policy": normalize_out.get("pit_policy"),
        "disclaimer": DISCLAIMER,
        "purpose": (
            "first observed-T pilot output — an honest partial sum of "
            "entry-conditions readings (relative momentum, relative "
            "strength, liquidity, low volatility) over the factors that "
            "actually scored; NOT a final T out of 25, never renormalized "
            "over covered weight, never a purchase signal"),
        "weight_tables": {fam: tables[fam] for fam in sorted(tables)},
        "companies": companies,
        "summary": summary,
        "display_sample": PV.select_display_sample(companies, display_limit),
    }


# ---------------------------------------------------------------------------
# engine-adjacent inputs — everything from the engine's OWN loaded rows
# ---------------------------------------------------------------------------
def build_histories(eng, as_of: dt.date) -> tuple[dict, dict]:
    """({security_id: day records}, diag) — the engine's flat price rows
    turned into per-security ascending daily series (one row per trade
    date, latest collected_at; TRW.extract_daily_history also drops any
    trade_date > as_of in defense in depth)."""
    prices = getattr(eng, "prices", []) or []
    histories = TRW.extract_daily_history(prices, as_of)
    diag = {"n_price_rows_seen": len(prices),
            "n_securities_with_history": len(histories),
            "n_day_records": sum(len(v) for v in histories.values()),
            "note": ("one record per (security, trade_date), latest "
                     "collected_at wins; trade_date > as_of dropped at "
                     "extraction; missing days stay missing — never "
                     "interpolated")}
    return histories, diag


def engine_cross_check(raw_by_company: dict, eng) -> dict:
    """Compare the T raw layer against the V1 engine's own 30-day market
    metrics on the same loaded rows. liquidity (avg_trade_value_30d) and
    volatility (volatility_30d) share the V1 construction, so agreements
    are expected wherever T's stricter gates (per-day deduplication, price
    floor, min sample, span/gap refusals) do not intervene; divergences are
    listed and attributed, never silently trusted. The V1 engine has NO
    6-month momentum counterpart (its price_momentum_30d is a different
    horizon) — no comparison is claimed for the momentum factors."""
    ok = Counter()
    div: list = []
    n_engine_value = Counter()
    for cid in sorted(raw_by_company):
        m = eng.metrics.get(cid) or {}
        rec = raw_by_company[cid]
        pairs = (("liquidity", "avg_trade_value_30d", 1.0,
                  "engine averages the last 30 raw rows without per-day "
                  "deduplication; T dedupes to one row per trade date"),
                 ("low_volatility", "volatility_30d", 100.0,
                  "the engine's volatility_30d is in PERCENT daily stdev; "
                  "T stores the FRACTION (comparison scales by 100). The "
                  "engine also builds returns from non-deduplicated rows, "
                  "uses no price floor and accepts any sample above 1 "
                  "return; T dedupes, floors, requires >= 10 returns and "
                  "refuses overlong/gap windows"))
        for fid, eng_key, scale, note in pairs:
            eng_v = m.get(eng_key)
            if eng_v is None:
                continue
            n_engine_value[fid] += 1
            rv = rec[fid].get("raw_value")
            if rec[fid]["status"] != "valid" or rv is None:
                div.append({"company_id": cid, "what": fid,
                            "raw_status": rec[fid]["status"],
                            "engine": eng_v,
                            "note": "engine produced a value the T raw "
                                    "layer refused — T's gates are "
                                    "stricter, by design: " + note})
                continue
            if math.isclose(float(rv) * scale, float(eng_v), rel_tol=1e-9,
                            abs_tol=1e-9):
                ok[fid] += 1
            else:
                div.append({"company_id": cid, "what": fid,
                            "raw_fraction": rv, "engine_percent": eng_v
                            if scale == 100.0 else None,
                            "raw_scaled": rv * scale if scale != 1.0
                            else rv,
                            "note": "value divergence: " + note})
    return {"agreements": dict(sorted(ok.items())),
            "n_engine_values_seen": dict(sorted(n_engine_value.items())),
            "n_momentum_comparisons": 0,
            "n_divergences": len(div),
            "divergences": div[:10],
            "note": ("the raw layer recomputes with V2 state semantics; "
                     "the engine's values are the same construction "
                     "without the T gates — a refusal where the engine "
                     "has a value is the raw layer being STRICTER, not a "
                     "disagreement about arithmetic")}


def raw_reason_census(raw_by_company: dict) -> dict:
    """Count the named refusals of the raw layer — the direct answers to
    the mission's coverage questions."""
    c: Counter = Counter()
    for cid, recs in raw_by_company.items():
        reasons = {fid: recs[fid]["validation_reason"] or ""
                   for fid in recs}
        if "no_price_history" in reasons.get("momentum_6m_rel", ""):
            c["n_no_price_history"] += 1
        if "price_stale" in reasons.get("momentum_6m_rel", ""):
            c["n_stale_blocked_all"] += 1
        if "insufficient_history_6m" in reasons.get("momentum_6m_rel", ""):
            c["n_mom6_insufficient_history"] += 1
        if "insufficient_history_3m" in reasons.get("momentum_3m_rel", ""):
            c["n_mom3_insufficient_history"] += 1
        if "suspected_unadjusted_gap_in_window" in \
                reasons.get("momentum_6m_rel", ""):
            c["n_mom6_gap_blocked"] += 1
        if "suspected_unadjusted_gap_in_window" in \
                reasons.get("momentum_3m_rel", ""):
            c["n_mom3_gap_blocked"] += 1
        if "suspected_unadjusted_gap_in_window" in \
                reasons.get("relative_strength_6m_sector", ""):
            c["n_rs6_gap_blocked"] += 1
        if "industry_unclassified" in \
                reasons.get("relative_strength_6m_sector", ""):
            c["n_rs6_industry_unclassified"] += 1
        if "insufficient_sector_benchmark" in \
                reasons.get("relative_strength_6m_sector", ""):
            c["n_rs6_insufficient_sector_benchmark"] += 1
        if "insufficient_history_liquidity" in reasons.get("liquidity", ""):
            c["n_liq_insufficient_history"] += 1
        if "window_span_too_long" in reasons.get("liquidity", ""):
            c["n_liq_span_too_long"] += 1
        if "insufficient_history_volatility" in \
                reasons.get("low_volatility", ""):
            c["n_vol_insufficient_history"] += 1
        if "window_span_too_long" in reasons.get("low_volatility", ""):
            c["n_vol_span_too_long"] += 1
        if "suspected_unadjusted_gap_in_window" in \
                reasons.get("low_volatility", ""):
            c["n_vol_gap_blocked"] += 1
    return dict(sorted(c.items()))


def load_v_eligible(path: Path) -> tuple[set, dict]:
    """The V pilot-eligible companies of step 2-J-1, from the saved
    artifact (same reproducible snapshot) — read-only. The V artifact nests
    its report under "v_observed_report" (the run wrapper), unlike the Q
    artifact whose companies sit at the top level."""
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    src = d.get("v_observed_report") or d
    eligible = {cid for cid, e in (src.get("companies") or {}).items()
                if e.get("pilot_eligible")}
    return eligible, {"path": str(path), "as_of": str(d.get("as_of")),
                      "n_pilot_eligible": len(eligible),
                      "stage": src.get("stage")}


def build_coverage_summary(raw_by_company: dict, t_report: dict,
                           q_eligible: set | None,
                           v_eligible: set | None) -> dict:
    """Direct answers to the mission's coverage questions (section 7)."""
    summary: dict = {}
    summary["raw_reason_census"] = raw_reason_census(raw_by_company)
    summary["n_scored_by_factor"] = {
        fid: t_report["summary"]["n_scored_by_factor"].get(fid, 0)
        for fid in TRW.IN_SCOPE_T_FACTORS}
    summary["n_t_pilot_eligible"] = t_report["summary"]["n_pilot_eligible"]
    if q_eligible is not None:
        summary["n_q_axis_pilot_eligible"] = len(q_eligible)
    if v_eligible is not None:
        summary["n_v_axis_pilot_eligible"] = len(v_eligible)
    if q_eligible is not None and v_eligible is not None:
        companies = t_report["companies"]
        qv = qvt = 0
        for cid in companies:
            in_q = cid in q_eligible
            in_v = cid in v_eligible
            in_t = companies[cid]["pilot_eligible"]
            if in_q and in_v:
                qv += 1
            if in_q and in_v and in_t:
                qvt += 1
        summary["n_q_and_v_eligible"] = qv
        summary["n_q_v_t_all_eligible"] = qvt
    return summary


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def run_t_pilot(as_of: dt.date, cutoff: dt.datetime,
                engine=None, sector_map: dict | None = None,
                q_eligible: set | None = None,
                v_eligible: set | None = None) -> dict:
    """Full read-only T pipeline over the engine population; ``engine``,
    ``sector_map`` and the eligibility sets are injectable for offline
    tests."""
    if engine is None:
        engine = CM.Engine(as_of, cutoff)
    engine.compute()
    if sector_map is None:
        sector_map = S4.load_sector_map(as_of)
    meta, detail = QP.build_company_meta(engine, sector_map)

    histories, hist_diag = build_histories(engine, as_of)
    security_by_company = {cid: (engine.metrics.get(cid) or {})
                           .get("security_id")
                           for cid in sorted(engine.metrics)}

    raw = TRW.build_t_raw(histories, security_by_company, meta, as_of=as_of)
    cross = engine_cross_check(raw, engine)
    norm = TN.normalize_t_cross_section(raw, meta, as_of=cutoff,
                                        pit_policy=SN.PIT_CURRENT_EXPLORATORY)
    t_report = build_t_observed_report(
        norm, raw, meta,
        symbols={cid: detail[cid].get("symbol") for cid in detail})

    coverage_summary = build_coverage_summary(raw, t_report, q_eligible,
                                              v_eligible)

    return {
        "stage": STAGE,
        "score_version": CFG2.SCORE_VERSION,
        "as_of": as_of.isoformat(),
        "cutoff": cutoff.isoformat(),
        "pit_policy": SN.PIT_CURRENT_EXPLORATORY,
        "disclaimer": DISCLAIMER,
        "construction": {
            "price_basis": ("market.price_observations in this store is "
                            "entirely the vendor-adjusted series "
                            "(price_series='adjusted'); momentum windows "
                            "ride the ADJUSTED closes"),
            "formulas": {fid: TRW.DEFINITIONS[fid]
                         for fid in TRW.IN_SCOPE_T_FACTORS},
            "benchmarks": ("market momentum benchmark = equal-weight mean "
                           "return of the valid population (self included); "
                           "sector benchmark = equal-weight mean of the "
                           "company's own industry group — both computed "
                           "from the same price data, no external index "
                           "invented; cross-sectional ordering is invariant "
                           "to any single common benchmark"),
            "thresholds": {
                "price_floor_rial": TRW.PRICE_FLOOR,
                "stale_days": TRW.STALE_DAYS,
                "jump_band": TRW.JUMP_BAND,
                "vol_window_closes": TRW.VOL_WINDOW_CLOSES,
                "vol_min_returns": TRW.VOL_MIN_RETURNS,
                "liq_window_sessions": TRW.LIQ_WINDOW_OBS,
                "liq_min_obs": TRW.LIQ_MIN_OBS,
                "window_max_span_days": TRW.WINDOW_MAX_SPAN_DAYS,
                "sector_bench_min_members": TRW.SECTOR_BENCH_MIN_MEMBERS,
                "note": "experimental thresholds of this step, declared "
                        "not hidden"},
            "family_gate": ("distance_from_52w_high is needs_development "
                            "and in NO family map — never computed, scored "
                            "or redistributed"),
        },
        "weight_tables": t_report["weight_tables"],
        "input_diagnostics": {
            "history_extraction": hist_diag,
        },
        "engine_cross_check": cross,
        "normalization_populations": norm["populations"],
        "t_observed_report": t_report,
        "coverage_summary": coverage_summary,
        "not_modified": ("Q axis output of step 2-B-8 and V axis output of "
                         "step 2-J-1 untouched; V1/V4 engines, "
                         "Raw/Normalize/Config/ScoreV2Engine, database, "
                         "ingestion, API and UI unchanged; no QVT total, "
                         "no commit"),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-10-08")
    ap.add_argument("--cutoff", default="2026-10-08T23:59:00+00:00")
    ap.add_argument("--q-report", default=str(HERE / "output"
                                              / "v2_q_observed_report.json"))
    ap.add_argument("--v-report", default=str(HERE / "output"
                                              / "v2_value_pilot.json"))
    ap.add_argument("--out", default=str(HERE / "output" / "v2_t_pilot.json"))
    args = ap.parse_args()
    as_of = dt.date.fromisoformat(args.as_of)
    cutoff = dt.datetime.fromisoformat(args.cutoff)

    q_eligible, q_diag = PV.load_q_eligible(Path(args.q_report))
    v_eligible, v_diag = load_v_eligible(Path(args.v_report))

    report = run_t_pilot(as_of, cutoff, q_eligible=q_eligible,
                         v_eligible=v_eligible)
    report["q_axis_artifact"] = q_diag
    report["v_axis_artifact"] = v_diag

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=1, default=str,
                                   ensure_ascii=False), encoding="utf-8")

    # ---- console summary --------------------------------------------------
    ts = report["t_observed_report"]["summary"]
    cov = report["coverage_summary"]
    print("== pilot_v2_t (2-D-1) ==", report["as_of"],
          "cutoff", report["cutoff"])
    print("companies:", ts["n_companies_total"],
          "| any t points:", ts["n_any_score"],
          "| t pilot eligible:", ts["n_pilot_eligible"])
    for fam, t in sorted(report["weight_tables"].items()):
        print(f"  weight table {fam}: {t['weights']} = {t['total_weight']}")
    print("input diagnostics:", json.dumps(report["input_diagnostics"],
                                           default=str, ensure_ascii=False))
    print("engine cross-check:", json.dumps(
        {k: v for k, v in report["engine_cross_check"].items()
         if k not in ("divergences",)}, default=str))
    print("raw valid:", ts["n_raw_valid_by_factor"],
          "| scored:", ts["n_scored_by_factor"])
    print("coverage summary:", json.dumps(cov, default=str,
                                          ensure_ascii=False))
    print("covered distribution:", ts["covered_weight_distribution"])
    print("refusals:", json.dumps(ts["refusal_reasons_by_factor"],
                                  default=str, ensure_ascii=False)[:2400])
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
