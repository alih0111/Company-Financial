# SIGNAL V1 — FORMAL CLOSEOUT (frozen 2026-10-02)

Preregistration: `signal_engine/SIGNAL_ENGINE_PREREGISTRATION_V1.md`
(SHA-256 `149ba4afd112f63443316a986ac793af60a60f572e13cf446850a6dcea3859ae`).
Execution: exactly once, `signal_engine/output/signal_v1_results.json`; snapshot
`signal_v1_snapshot.jsonl` (SHA-256 `4719eced10fde8f5bcb030764fd11c1acee41671429a0018a8cd7bcd7aca472a`);
integrity `signal_v1_integrity.json`. All artifacts preserved; nothing overwritten.

## SIGNAL_V1_FINAL_STATUS = FAIL

| frozen item | value |
|---|---|
| SIGNAL_V1_PRIMARY_GATE | **FAIL** |
| SIGNAL_V1_SHADOW_ELIGIBLE | **NO** |
| SIGNAL_PROMOTION_READY | **NO** |
| PRODUCTION_SIGNAL_ENGINE_STARTED | **NO** |

Primary measured result (63d excess, 62 dates, 2,733 rows): primary IC63 **+0.0548** ·
positive-date fraction **0.581** · Q5−Q1 excess spread **−0.20pp** (median −0.92pp) ·
ΔIC63 vs identical-row UI baseline **−0.0074** · Δspread **+0.12pp** · turnover **0.633** ·
coverage **97.71%**. Gate record: SG1 PASS · SG2a FAIL · SG2b FAIL · SG3 FAIL · SG4 FAIL ·
SG5 FAIL · SG6 FAIL · SG7 PASS · SG8 PASS. No threshold may be changed; the record stands.

Ablation `signal-v1-A-momentum` (IC63 +0.032) and alternative `signal-v1-B` (IC63 +0.064,
ΔIC63 vs identical-row baseline +0.0018) are diagnostic records only — neither was promoted
and neither justifies reopening the architecture.

## Frozen interpretation (authoritative; supersedes the descriptive phrasing in §61)

**Supported conclusion:** the preregistered combination of 60-day momentum, distance from
the 60-day high, and inverse 30-day volatility did not provide robust incremental timing
value beyond the UI score in the available historical universe. Descriptively: the highest
timing quintile did not outperform the lowest timing quintile.

**Not claimed:** no causal market-regime explanation (no "momentum among good companies
mean-reverted" causal statement — that would require separate evidence), no assertion about
why the overlay failed beyond the measured gates.

## Future signal research (PAUSED)

`SIGNAL_RESEARCH_PAUSED = YES`. Future timing research may resume ONLY with a genuinely
different economic mechanism and a new preregistration. NOT acceptable justifications:
a different momentum window, slightly different weights, slightly different thresholds,
dropping whichever component failed, or trying many variants.

## Product boundary (unchanged)

The UI score remains the sole product-level ranking instrument
(`UI_SCORE_READY_FOR_PRODUCT_USE = YES`). The product must NOT convert the UI score
mechanically into BUY/HOLD/SELL, must not implement rules of the form
"score ≥ X ⇒ BUY" or "top quintile ⇒ BUY": the historical UI-score evidence supports
ranking, not action recommendations.
