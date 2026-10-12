"""Cross-sectional normalization (percentile ranking) for Score v2 Q factors.

Step 2-B-2 — normalization + cross-sectional ranking ONLY. This layer turns
the validated raw records of score_v2_raw.build_q_raw() into comparable
cross-sectional percentiles. It does NOT produce a final Q score, does not
weight factors, and knows nothing about V, T, Confidence or the Risk Gate.

Reuse contract with Score v4 (same pattern as score_v2.py, which imports
score_v4 for the same reason):
  * S4.midrank     — the tested V4 midrank percentile engine, used unchanged
                     for both family and sector ranks
  * S4._percentile — V4's linear-interpolation order statistic, used for the
                     P1/P99 winsor bounds
  * sector-weight decay — V4's SECTOR_BLEND_DECAY functional form
                     (w = W * (n - lo) / (hi - lo)), reparametrized to this
                     step's three-zone small-sector policy
V4's winsor_bounds / apply_winsor / combined_percentile are structurally
coupled to CFG.FACTOR_CONFIG and the v4 assembled-input shape, so this
module carries small parametric equivalents with identical math — the
pattern sanctioned for this step. No algorithm is reinvented.

Comparison populations:
  * only economically VALID raw values enter a unit's ranking population —
    missing / invalid / not_applicable / not_implemented never do; the
    excluded counts stay visible in the output
  * model families never mix: every population (family AND sector) is built
    inside one model family (general/bank/insurance/investment)
  * family population : valid values across the company's model family
  * sector population : valid values sharing model family AND industry group
  * an unknown industry group is never silently treated as a valid industry:
    the company ranks family-wide, percentile_sector is null with an explicit
    reason, and a warning is attached
  * winsorization bounds are estimated family-wide per unit (V4's
    universe-wide logic, one family down) and reused for the sector ranks —
    one consistent transform per population
  * real zeros are values and rank like any other value; missing is the
    absence of a unit from the ranking, never zero

Small-sector policy (experimental thresholds, NOT backtest-optimized):
    n_sector <  5    sector weight 0 — family rank only
    5 <= n < 20      sector weight ramps linearly 0 -> full_sector_weight
    n_sector >= 20   full_sector_weight (default 0.65 sector / 0.35 family)
    n_family < 10    insufficient_peers — no percentile is produced at all
                     instead of a seemingly precise rank
All thresholds live in RankPolicy and are configurable.

Composite factor blend (step 2-B-3-B): the two composite Q factors (margins,
earnings_growth) rank their components independently. Where an approved
weight table exists (score_v2_config.COMPOSITE_COMPONENT_WEIGHTS — currently
the "general" family only), the factor ALSO gets factor_blend_score when
EVERY component is valid AND ranked: the config-weighted mean of the
component percentile_combined values — a [0, 1] score, NOT itself a
percentile, never re-ranked, with the industry/family weighting applied
exactly once (inside the component ranks this layer already produced).
All-or-nothing by contract: no partial blend, no redistribution of a missing
component's weight, no fabricated substitute for absent data, and the
engine-side min_axis_coverage never licenses a partial blend here. Refusal
priority (deterministic): corrupt or PIT-refused component data ->
"unavailable"; then insufficient component peer populations ->
"insufficient_peers"; then missing / not_applicable components ->
"pending_data". Every no-score state carries an explicit reason naming the
components; a missing score is never a zero score. Families without a
contract (bank / insurance / investment) keep "pending_blend" — presence in
FAMILY_WEIGHTS activates nothing here.

PIT policies:
  current_exploratory  rank all valid values; PIT stays visible (pit_status
                       is echoed per record and unverified values carry a
                       pit_unverified_exploratory warning); never
                       backtest-valid.
  historical_strict    requires as_of. Only pit_status "verified" values may
                       rank, and ONLY they form the peer population —
                       unverified peers are excluded from ranks as well, so
                       a rank is never built against data that was not yet
                       published at as_of.

Explicit trust dependency: this layer never re-derives provenance. It can
only honor the "verified" state produced by the raw layer's provenance
contract (timestamp + source_ref); it cannot attest the true origin of a
publication timestamp itself.

Publication guard (defense-in-depth, both policies): the raw layer only
compares publication timestamps against as_of when IT was built with one —
a raw build without as_of can mark attributable-but-later provenance
"verified". So whenever THIS layer receives as_of, it re-checks every
eligible value's available_at: anything published after as_of is excluded
from ranks, peer populations and winsor bounds in BOTH policies
(normalization_status "not_ranked_after_as_of", populations key
"excluded_after_as_of"). historical_strict additionally refuses values
whose timestamp type is not comparable with as_of (publication before as_of
cannot be attested). period_end is never promoted to a publication date
here.

Non-finite defense: the raw layer rejects non-finite INPUTS, but a ratio of
finite inputs can still overflow (margins / cash_conversion over an extreme
denominator) and reach this layer as a "valid" +/-inf. Such values are
excluded under the populations key "non_finite" (factor rollup
"not_ranked_non_finite") before they can enter percentiles or turn a
winsor bound infinite.

Known limitation (window alignment): every value comes from ONE
Engine.compute() snapshot and same-window ratios (raw-layer contract), and
units are factor-level constants — homogeneous by construction. But this
layer cannot verify that peers' TTM windows cover identical fiscal spans:
records expose no window identity. Ranks therefore assume engine-resolved
LTM comparability across companies; a window key in the raw contract is a
prerequisite before historical_strict backtests.

Pure and deterministic: in-memory inputs only, no database, no engine, no
clock; identical inputs in any company order produce identical output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import score_v2_config as CFG2
import score_v2_raw as RAW
import score_v4 as S4  # reused percentile engine (same contract as score_v2.py)

__all__ = [
    "RankPolicy",
    "normalize_q_cross_section",
    "PIT_CURRENT_EXPLORATORY",
    "PIT_HISTORICAL_STRICT",
    "PIT_POLICIES",
    "NR_RANKED",
    "NR_INSUFFICIENT_PEERS",
    "NR_PIT_STRICT",
    "NR_AFTER_AS_OF",
    "NR_NON_FINITE",
    "NR_PENDING_BLEND",
    "BLEND_METHOD",
    "FS_BLENDED",
    "FS_PENDING_DATA",
    "FS_INSUFFICIENT_PEERS",
    "FS_UNAVAILABLE",
]

SCORE_VERSION = CFG2.SCORE_VERSION
STAGE = "normalize_cross_section"

PIT_CURRENT_EXPLORATORY = "current_exploratory"
PIT_HISTORICAL_STRICT = "historical_strict"
PIT_POLICIES = (PIT_CURRENT_EXPLORATORY, PIT_HISTORICAL_STRICT)

# normalization_status vocabulary
NR_RANKED = "ranked"
NR_INSUFFICIENT_PEERS = "insufficient_peers"
NR_PIT_STRICT = "not_ranked_pit_strict"
NR_AFTER_AS_OF = "not_ranked_after_as_of"
NR_NON_FINITE = "not_ranked_non_finite"
NR_PENDING_BLEND = "pending_blend"

# Composite blend contract (step 2-B-3-B). Factor-level statuses for
# composites WITH an approved weight table; "pending_blend" (NR_PENDING_BLEND)
# stays the contract of families without one.
BLEND_METHOD = "weighted_mean_of_component_percentile_combined"
FS_BLENDED = "blended"
FS_PENDING_DATA = "pending_data"
FS_INSUFFICIENT_PEERS = "insufficient_peers"
FS_UNAVAILABLE = "unavailable"

# Component states that refuse a blend outright (priority 1 — corrupt data):
# definite raw-layer corruption, non-finite ratios, look-ahead publication
# and PIT-unverified values under historical_strict. Unknown statuses fall
# into the same class — a blend is refused loudly, never guessed.
_CORRUPT_COMPONENT_STATUSES = frozenset({
    "not_ranked_raw_invalid", NR_NON_FINITE, NR_AFTER_AS_OF, NR_PIT_STRICT,
})


@dataclass(frozen=True)
class RankPolicy:
    """Ranking-method settings. The defaults are this step's experimental
    policy proposal — not backtest-optimized — and every threshold is
    configurable here, never hardcoded in the ranking logic."""

    sector_small_max: int = 5         # n_sector below this -> sector weight 0
    sector_full_min: int = 20         # n_sector at/above this -> full weight
    full_sector_weight: float = 0.65  # 65% sector / 35% family at full strength
    family_min_n: int = 10            # family population below -> insufficient_peers
    winsor_min_n: int = 20            # V4's min-sample guard for P1/P99 bounds
    winsor_low_q: float = 0.01        # V4 P1
    winsor_high_q: float = 0.99       # V4 P99

    def __post_init__(self):
        if self.sector_small_max < 1 or self.sector_full_min <= self.sector_small_max:
            raise ValueError(
                f"rank policy: need 1 <= sector_small_max < sector_full_min, "
                f"got {self.sector_small_max} / {self.sector_full_min}")
        if not 0.0 <= self.full_sector_weight <= 1.0:
            raise ValueError(
                f"rank policy: full_sector_weight must be in [0, 1], "
                f"got {self.full_sector_weight}")
        if self.family_min_n < 2 or self.winsor_min_n < 2:
            raise ValueError(
                "rank policy: family_min_n and winsor_min_n must be >= 2")
        if not 0.0 <= self.winsor_low_q < self.winsor_high_q <= 1.0:
            raise ValueError(
                f"rank policy: need 0 <= winsor_low_q < winsor_high_q <= 1, "
                f"got {self.winsor_low_q} / {self.winsor_high_q}")

    def to_dict(self) -> dict:
        return {
            "sector_small_max": self.sector_small_max,
            "sector_full_min": self.sector_full_min,
            "full_sector_weight": self.full_sector_weight,
            "family_min_n": self.family_min_n,
            "winsor_min_n": self.winsor_min_n,
            "winsor_low_q": self.winsor_low_q,
            "winsor_high_q": self.winsor_high_q,
        }


def _sector_weight(n_sector: int, pol: RankPolicy) -> float:
    """Effective sector weight for a sector population of n_sector companies.

    V4's SECTOR_BLEND_DECAY functional form (linear from 0 at the small
    threshold up to the full weight at the full threshold), reparametrized
    to this step's three-zone policy."""
    if n_sector < pol.sector_small_max:
        return 0.0
    if n_sector >= pol.sector_full_min:
        return pol.full_sector_weight
    span = pol.sector_full_min - pol.sector_small_max
    return pol.full_sector_weight * (n_sector - pol.sector_small_max) / span


def _winsor_bounds(values, pol: RankPolicy):
    """Parametric equivalent of score_v4.winsor_bounds: P1/P99 via V4's
    linear interpolation, with V4's min-sample guard — a sample too small
    to support percentile bounds is NOT force-clipped."""
    vals = sorted(float(v) for v in values)
    if len(vals) < pol.winsor_min_n:
        return None
    lo = S4._percentile(vals, pol.winsor_low_q)
    hi = S4._percentile(vals, pol.winsor_high_q)
    return (lo, hi)


def _collect_units(raw_by_company: dict) -> dict:
    """(factor_id, component_id) -> {"eligible": {cid: entry},
                                     "excluded": {status: count}}

    entry = {"value": float, "pit_status": str, "available_at": ts or None,
             "warnings": list}

    A composite component ranks independently whenever ITS OWN part status
    is valid — the composite factor's aggregate status never gates a valid
    component out of its population (the factor-level blend is a separate,
    still-pending contract). Single-component factors rank at factor level
    (component_id None). Factors outside IN_SCOPE_FACTORS (e.g. roic's
    not_implemented placeholder) never enter this stage.

    Defense-in-depth finite guard: the raw layer rejects non-finite INPUTS,
    but margins/cash_conversion ratios can still overflow to +/-inf from
    finite inputs (e.g. a denormal denominator) and arrive "valid". Those
    values are excluded under the "non_finite" key — never ranked, never
    fed to percentile or winsor-bound math.
    """
    units: dict = {}
    for cid in sorted(raw_by_company):
        for fid in sorted(raw_by_company[cid]):
            if fid not in RAW.IN_SCOPE_FACTORS:
                continue
            rec = raw_by_company[cid][fid]
            if "components" in rec:
                for comp in sorted(rec["components"]):
                    part = rec["components"][comp]
                    unit = units.setdefault((fid, comp),
                                            {"eligible": {}, "excluded": {}})
                    if part["status"] == RAW.STATUS_VALID:
                        value = float(part["value"])
                        if not math.isfinite(value):
                            unit["excluded"]["non_finite"] = \
                                unit["excluded"].get("non_finite", 0) + 1
                            continue
                        unit["eligible"][cid] = {
                            "value": value,
                            "pit_status": part["pit_status"],
                            "available_at": part.get("available_at"),
                            "warnings": list(part["warnings"]),
                        }
                    else:
                        unit["excluded"][part["status"]] = \
                            unit["excluded"].get(part["status"], 0) + 1
            else:
                unit = units.setdefault((fid, None),
                                        {"eligible": {}, "excluded": {}})
                if rec["status"] == RAW.STATUS_VALID:
                    value = float(rec["raw_value"])
                    if not math.isfinite(value):
                        unit["excluded"]["non_finite"] = \
                            unit["excluded"].get("non_finite", 0) + 1
                        continue
                    unit["eligible"][cid] = {
                        "value": value,
                        "pit_status": rec["pit_status"],
                        "available_at": rec.get("available_at"),
                        "warnings": list(rec["warnings"]),
                    }
                else:
                    unit["excluded"][rec["status"]] = \
                        unit["excluded"].get(rec["status"], 0) + 1
    return units


def _blend_composite_factor(cid, fid, rec, detail, weights, rec_by_unit,
                            family) -> dict:
    """Factor-level rollup for a composite with an approved weight table.

    factor_blend_score exists ONLY when EVERY component is valid AND ranked
    (finite percentile_combined in [0, 1]) — all-or-nothing. A missing
    component's weight is never redistributed, absent data is never replaced
    by 0 or 0.5, the engine-side min_axis_coverage never licenses a partial
    blend, and the score is never re-ranked: it is the config-weighted mean
    of the component percentile_combined values — a [0, 1] score, not itself
    a percentile — with the industry/family weighting applied exactly once
    (inside the component ranks already produced above). Sums use math.fsum
    over sorted keys, so the result is independent of dict order.

    Refusal priority (deterministic, ratified in step 2-B-3-B): corrupt or
    PIT-refused component data -> "unavailable"; then insufficient component
    peer populations -> "insufficient_peers"; then missing / not_applicable
    components -> "pending_data". Every no-score state carries an explicit
    reason naming the components; a missing score is never a zero score.
    Anomaly warnings never become numeric penalties: a factor with warned
    (but valid and ranked) components blends normally with the warnings
    preserved.
    """
    components = rec["components"]
    ranked: dict = {}
    corrupt: list = []
    insufficient: list = []
    absent: list = []   # "comp (missing)" / "comp (not_applicable)" strings

    for comp in sorted(weights):
        d = detail[comp]
        st, pc = d["normalization_status"], d["percentile_combined"]
        if (st == NR_RANKED and isinstance(pc, float) and math.isfinite(pc)
                and 0.0 <= pc <= 1.0):
            ranked[comp] = pc
        elif st in _CORRUPT_COMPONENT_STATUSES:
            corrupt.append(f"{comp} ({st})")
        elif st == NR_INSUFFICIENT_PEERS:
            insufficient.append(comp)
        elif st == "not_ranked_raw_missing":
            absent.append(f"{comp} (missing)")
        elif st == "not_ranked_raw_not_applicable":
            absent.append(f"{comp} (not_applicable)")
        else:
            # includes NR_RANKED with a percentile that is not a finite
            # [0, 1] number — cannot happen via midrank; refused, not guessed
            corrupt.append(f"{comp} ({st})")

    # explainability: raw echo, rank population, PIT and warnings per component
    for comp in sorted(detail):
        d = detail[comp]
        part = components[comp]
        runit = rec_by_unit.get((cid, fid, comp))
        d["raw_status"] = part["status"]
        d["raw_value"] = part.get("value")
        d["pit_status"] = part["pit_status"]
        d["available_at"] = part.get("available_at")
        d["weight"] = float(weights[comp])
        d["warnings"] = list(dict.fromkeys(
            list(part["warnings"])
            + (list(runit["warnings"]) if runit else [])))
        if runit is not None:
            d["n_valid_market_family"] = runit["n_valid_market_family"]
            d["n_valid_sector"] = runit["n_valid_sector"]
        else:
            d["n_valid_market_family"] = None
            d["n_valid_sector"] = None
        d["contribution"] = (weights[comp] * ranked[comp]
                             if comp in ranked else None)

    coverage = math.fsum(weights[c] for c in sorted(ranked))
    blend = {
        "family": family,
        "method": BLEND_METHOD,
        "weights": {c: float(weights[c]) for c in sorted(weights)},
        # diagnostic ONLY: the ranked share of the factor's internal weight.
        # It never licenses a score — e.g. 0.60 coverage with the other
        # component missing still yields factor_blend_score None.
        "coverage_weight": coverage,
    }

    no_score = " — factor_blend_score stays None"
    if corrupt:
        status, score = FS_UNAVAILABLE, None
        reason = ("no blend: corrupt or PIT-refused component data: "
                  + "; ".join(corrupt) + no_score)
    elif insufficient:
        status, score = FS_INSUFFICIENT_PEERS, None
        reason = ("no blend: component peer population below family_min_n: "
                  + ", ".join(insufficient) + no_score)
    elif absent:
        status, score = FS_PENDING_DATA, None
        reason = ("no blend: component(s) without a rankable value: "
                  + "; ".join(absent) + no_score)
    elif rec["status"] != RAW.STATUS_VALID:
        # defensive last resort: an aggregate the raw layer refused must
        # never blend, even if every component above somehow looked ranked
        # (an honest invalid aggregate always names its invalid component in
        # the corrupt branch above; this catches contract violations only)
        status, score = FS_UNAVAILABLE, None
        reason = (f"no blend: raw factor aggregate status is "
                  f"{rec['status']!r}{no_score}")
    else:
        status = FS_BLENDED
        score = math.fsum(weights[c] * ranked[c] for c in sorted(ranked))
        reason = ("all components valid and ranked — factor_blend_score is "
                  "the config-weighted mean of the component "
                  "percentile_combined values (a score in [0, 1], not "
                  "itself a percentile)")
        blend["contributions"] = {c: weights[c] * ranked[c]
                                  for c in sorted(ranked)}

    return {
        "company_id": cid,
        "factor_id": fid,
        "component_id": None,
        "composite": True,
        "normalization_status": status,
        "reason": reason,
        "factor_blend_score": score,
        "blend": blend,
        "components": detail,
        "warnings": list(rec["warnings"]),
    }


def normalize_q_cross_section(raw_by_company: dict,
                              company_meta: dict,
                              *,
                              as_of=None,
                              pit_policy: str = PIT_CURRENT_EXPLORATORY,
                              policy: RankPolicy | None = None) -> dict:
    """Rank validated raw Q factors cross-sectionally, industry-relative.

    raw_by_company : output of score_v2_raw.build_q_raw —
                     {company_id: {factor_id: raw record}}
    company_meta   : {company_id: {"model_family": one of
                     score_v2_config.FAMILIES, "industry": str or None}}
    as_of          : evaluation date; REQUIRED for historical_strict
    pit_policy     : "current_exploratory" | "historical_strict"
    policy         : optional RankPolicy override (defaults are the
                     experimental thresholds documented in the module)

    Returns {"score_version", "stage", "pit_policy", "as_of", "policy",
             "records", "factors", "populations"} where
      records     one entry per RANKABLE unit (factor-level for
                  single-component factors, component-level for composites):
                  every valid raw value gets a record, either ranked or with
                  null percentiles + explicit null_reasons. Percentiles live
                  in [0, 1]; null is never replaced by zero.
      factors     per-company factor rollup: composites WITH an approved
                  blend table (general) get "blended" + factor_blend_score
                  when every component is valid and ranked, else a refusal
                  status (unavailable / insufficient_peers / pending_data)
                  with an explicit reason; composites without a table
                  (bank/insurance/investment) stay "pending_blend"; singles
                  carry the record status.
      populations per-unit population accounting: valid counts, sector
                  sizes, winsor bounds/sample, and excluded-status counts.
    """
    pol = policy if policy is not None else RankPolicy()
    if pit_policy not in PIT_POLICIES:
        raise ValueError(f"unknown pit_policy {pit_policy!r}; "
                         f"expected one of {PIT_POLICIES}")
    if pit_policy == PIT_HISTORICAL_STRICT and as_of is None:
        raise ValueError(
            "historical_strict requires an explicit as_of evaluation date — "
            "without it publication-vs-as_of cannot be judged")
    missing_meta = sorted(cid for cid in raw_by_company if cid not in company_meta)
    if missing_meta:
        raise ValueError(f"company_meta missing for companies: {missing_meta}")

    meta: dict = {}
    for cid, m in company_meta.items():
        fam = (m or {}).get("model_family")
        if fam not in CFG2.FAMILIES:
            raise ValueError(f"{cid}: unknown model_family {fam!r} — "
                             f"expected one of {CFG2.FAMILIES}")
        ind = (m or {}).get("industry")
        ind = ind.strip() if isinstance(ind, str) and ind.strip() else None
        meta[cid] = (fam, ind)

    strict = pit_policy == PIT_HISTORICAL_STRICT
    units = _collect_units(raw_by_company)

    records: list = []
    unit_rank: dict = {}  # (cid, fid, comp) -> (normalization_status, combined pct)
    populations: dict = {}

    for fid, comp in sorted(units):
        unit = units[(fid, comp)]
        direction = CFG2.V2_QVT_FACTORS[fid]["direction"]
        higher = direction == "higher"

        # normalize-side look-ahead guard (defense-in-depth): this layer's
        # as_of bounds what may rank REGARDLESS of how the raw layer was
        # built — a raw build without as_of can mark attributable-but-later
        # provenance "verified", so the publication timestamp is re-checked
        # here in BOTH policies. RAW._ts_after returns None on incomparable
        # timestamp types (never guess): strict cannot attest such a value
        # for this as_of; exploratory tolerates it as it tolerates all
        # unverified data.
        def _late(e) -> bool:
            return as_of is not None and \
                RAW._ts_after(e["available_at"], as_of) is True

        def _attestable(e) -> bool:
            return e["pit_status"] == RAW.PIT_VERIFIED and \
                RAW._ts_after(e["available_at"], as_of) is False

        if strict:
            # only PIT-verified values may rank AND form the peer population
            # — unverified peers never leak into a rank.
            pool = {cid: e for cid, e in unit["eligible"].items()
                    if _attestable(e)}
        else:
            pool = {cid: e for cid, e in unit["eligible"].items()
                    if not _late(e)}

        fam_members: dict = {}
        for cid in sorted(pool):
            fam_members.setdefault(meta[cid][0], []).append(cid)

        unit_pops = {
            "factor_id": fid,
            "component_id": comp,
            "families": {},
            "excluded": dict(sorted(unit["excluded"].items())),
        }
        if strict:
            unit_pops["excluded_pit_strict"] = sum(
                1 for e in unit["eligible"].values()
                if e["pit_status"] != RAW.PIT_VERIFIED)
        if as_of is not None:
            # every eligible entry lands in exactly one bucket: the pool,
            # excluded for missing PIT verification (strict), or excluded
            # for publication after as_of — mirroring the record statuses.
            unit_pops["excluded_after_as_of"] = sum(
                1 for e in unit["eligible"].values()
                if _late(e) and (not strict
                                 or e["pit_status"] == RAW.PIT_VERIFIED))

        fam_values: dict = {}   # family -> {cid: winsorized value}
        fam_pct: dict = {}      # family -> {cid: percentile}
        fam_winsor: dict = {}   # family -> bounds or None
        sector_values: dict = {}  # (family, industry) -> {cid: winsorized}
        for fam in sorted(fam_members):
            cids = fam_members[fam]
            raw_vals = {cid: pool[cid]["value"] for cid in cids}
            bounds = _winsor_bounds(raw_vals.values(), pol)
            norm = {cid: (v if bounds is None
                          else min(max(v, bounds[0]), bounds[1]))
                    for cid, v in raw_vals.items()}
            fam_values[fam] = norm
            fam_winsor[fam] = bounds
            fam_pct[fam] = S4.midrank(norm, higher)

            by_ind: dict = {}
            for cid in cids:
                by_ind.setdefault(meta[cid][1], []).append(cid)
            sectors = {}
            for ind in sorted(by_ind, key=lambda x: (x is None, x or "")):
                if ind is None:
                    continue  # unknown industry joins no sector population
                sectors[f"family:{fam}|industry:{ind}"] = {
                    "n_valid": len(by_ind[ind])}
                sector_values[(fam, ind)] = {cid: norm[cid]
                                             for cid in by_ind[ind]}
            unit_pops["families"][fam] = {
                "n_valid": len(cids),
                "winsor": {
                    "applied": bounds is not None,
                    "low": None if bounds is None else bounds[0],
                    "high": None if bounds is None else bounds[1],
                    "n": len(cids),
                    "min_n": pol.winsor_min_n,
                    "low_q": pol.winsor_low_q,
                    "high_q": pol.winsor_high_q,
                },
                "sectors": sectors,
            }
        populations[fid if comp is None else f"{fid}.{comp}"] = unit_pops

        for cid in sorted(unit["eligible"]):
            fam, ind = meta[cid]
            entry = unit["eligible"][cid]
            fam_n = len(fam_values.get(fam, {}))
            sector_n = (len(sector_values[(fam, ind)])
                        if ind is not None and (fam, ind) in sector_values
                        else None)
            warnings = list(entry["warnings"])
            null_reasons: dict = {}
            weight = 0.0
            sec_p = None
            comb = None

            if strict and entry["pit_status"] != RAW.PIT_VERIFIED:
                status = NR_PIT_STRICT
                fam_p = None
                null_reasons = {
                    key: "pit_not_verified_historical_strict"
                    for key in ("percentile_market_family",
                                "percentile_sector",
                                "percentile_combined")}
            elif _late(entry):
                # valid raw value, but published after this layer's as_of —
                # refused in BOTH policies (look-ahead guard), with the raw
                # value kept on the record for audit.
                status = NR_AFTER_AS_OF
                fam_p = None
                null_reasons = {
                    key: "published_after_as_of"
                    for key in ("percentile_market_family",
                                "percentile_sector",
                                "percentile_combined")}
                warnings.append(
                    "published_after_as_of: the record's latest publication "
                    "timestamp is after this layer's as_of — excluded from "
                    "ranks, peer populations and winsor bounds in every "
                    "policy")
            elif strict and RAW._ts_after(entry["available_at"],
                                          as_of) is None:
                # verified per the raw layer, but its timestamp type is not
                # comparable with as_of — publication before as_of cannot be
                # attested, so strict refuses to rank rather than guess.
                status = NR_PIT_STRICT
                fam_p = None
                null_reasons = {
                    key: "pit_not_verified_historical_strict"
                    for key in ("percentile_market_family",
                                "percentile_sector",
                                "percentile_combined")}
            elif fam_n < pol.family_min_n:
                status = NR_INSUFFICIENT_PEERS
                fam_p = None
                null_reasons = {
                    key: "insufficient_peers"
                    for key in ("percentile_market_family",
                                "percentile_sector",
                                "percentile_combined")}
            else:
                status = NR_RANKED
                fam_p = fam_pct[fam][cid]
                if ind is None:
                    warnings.append(
                        "industry_unknown: no industry group supplied — the "
                        "company is ranked against its model family only and "
                        "joins no sector population")
                    null_reasons["percentile_sector"] = "industry_unknown"
                elif sector_n < pol.sector_small_max:
                    null_reasons["percentile_sector"] = "sector_too_small"
                else:
                    sec_p = S4.midrank(sector_values[(fam, ind)], higher)[cid]
                    weight = _sector_weight(sector_n, pol)
                if sec_p is not None and weight > 0.0:
                    comb = weight * sec_p + (1.0 - weight) * fam_p
                else:
                    comb = fam_p
                if (pit_policy == PIT_CURRENT_EXPLORATORY
                        and entry["pit_status"] != RAW.PIT_VERIFIED):
                    warnings.append(
                        "pit_unverified_exploratory: ranked on an unverified "
                        "publication date — exploratory only, never "
                        "backtest-valid")

            peer_group = (f"family:{fam}|industry:{ind}"
                          if status == NR_RANKED and weight > 0.0
                          else f"family:{fam}")
            records.append({
                "company_id": cid,
                "factor_id": fid,
                "component_id": comp,
                "raw_value": entry["value"],
                "normalized_input": fam_values.get(fam, {}).get(cid),
                "percentile_market_family": fam_p,
                "percentile_sector": sec_p,
                "percentile_combined": comb,
                "direction": direction,
                "peer_group": peer_group,
                "n_valid_market_family": fam_n,
                "n_valid_sector": sector_n,
                "effective_sector_weight": weight,
                "validation_status": RAW.STATUS_VALID,
                "pit_status": entry["pit_status"],
                "warnings": warnings,
                "normalization_status": status,
                "pit_policy": pit_policy,
                "null_reasons": null_reasons,
                "winsor_applied": fam_winsor.get(fam) is not None,
            })
            unit_rank[(cid, fid, comp)] = (status, comb)

    records.sort(key=lambda r: (r["company_id"], r["factor_id"],
                                r["component_id"] or ""))
    rec_by_unit = {(r["company_id"], r["factor_id"], r["component_id"]): r
                   for r in records}

    # Factor rollup: composites with an approved blend contract (step
    # 2-B-3-B, general family) get factor_blend_score when EVERY component
    # is valid AND ranked; composites without a contract stay pending_blend
    # (component ranks kept separate); singles carry their unit's outcome.
    factors: dict = {}
    for cid in sorted(raw_by_company):
        factors[cid] = {}
        for fid in sorted(raw_by_company[cid]):
            if fid not in RAW.IN_SCOPE_FACTORS:
                continue
            rec = raw_by_company[cid][fid]
            if "components" in rec:
                detail = {}
                for comp in sorted(rec["components"]):
                    part = rec["components"][comp]
                    if part["status"] == RAW.STATUS_VALID:
                        # a valid part dropped at collect time (non-finite
                        # ratio overflow) has no rank — named, never silent
                        st, pc = unit_rank.get((cid, fid, comp),
                                               (NR_NON_FINITE, None))
                    else:
                        st, pc = f"not_ranked_raw_{part['status']}", None
                    detail[comp] = {"normalization_status": st,
                                    "percentile_combined": pc}
                weights_tbl = CFG2.COMPOSITE_COMPONENT_WEIGHTS.get(
                    meta[cid][0], {}).get(fid)
                if isinstance(weights_tbl, dict) and weights_tbl \
                        and set(weights_tbl) == set(rec["components"]):
                    factors[cid][fid] = _blend_composite_factor(
                        cid, fid, rec, detail, weights_tbl, rec_by_unit,
                        meta[cid][0])
                elif weights_tbl is not None:
                    # a weight table exists for this family/factor but does
                    # not match the raw components — refuse loudly, never
                    # blend against the wrong component set
                    factors[cid][fid] = {
                        "company_id": cid,
                        "factor_id": fid,
                        "component_id": None,
                        "composite": True,
                        "normalization_status": NR_PENDING_BLEND,
                        "reason": "component-weight config does not match "
                                  "the raw components of this factor — "
                                  "no blend",
                        "components": detail,
                        "warnings": list(rec["warnings"]),
                    }
                else:
                    factors[cid][fid] = {
                        "company_id": cid,
                        "factor_id": fid,
                        "component_id": None,
                        "composite": True,
                        "normalization_status": NR_PENDING_BLEND,
                        "reason": "no approved component blend contract yet — "
                                  "component ranks are kept separate; the factor "
                                  "itself gets no percentile",
                        "components": detail,
                        "warnings": list(rec["warnings"]),
                    }
            else:
                if rec["status"] == RAW.STATUS_VALID:
                    st, pc = unit_rank.get((cid, fid, None),
                                           (NR_NON_FINITE, None))
                else:
                    st, pc = f"not_ranked_raw_{rec['status']}", None
                factors[cid][fid] = {
                    "company_id": cid,
                    "factor_id": fid,
                    "component_id": None,
                    "composite": False,
                    "normalization_status": st,
                    "percentile_combined": pc,
                    "warnings": list(rec["warnings"]),
                }

    return {
        "score_version": SCORE_VERSION,
        "stage": STAGE,
        "pit_policy": pit_policy,
        "as_of": as_of,
        "policy": pol.to_dict(),
        "records": records,
        "factors": factors,
        "populations": populations,
    }
