"""Canonical v1 Data Quality model (canonical sources only)."""

from __future__ import annotations

from dataclasses import dataclass, field

SEVERITY = {
    "unresolved_identity": "critical",
    "missing_current_financials": "high",
    "missing_price": "high",
    "unknown_unit": "high",
    "stale_financials": "medium",
    "stale_market_data": "medium",
    "missing_monthly_activity": "medium",
    "insufficient_history": "medium",
    "missing_comparable_period": "medium",
    "unknown_quantity_unit": "low",
    "low_confidence_corporate_action": "low",
    # TTM report-chain provenance (informational)
    "MISSING_PRIOR_ANNUAL": "low",
    "MISSING_PRIOR_COMPARABLE": "low",
    "PIT_UNAVAILABLE": "low",
    # Valuation diagnostics. Informational only: reported, never scored
    # (DQ.score() is a function of the boolean components alone).
    "VALUATION_INPUT_MISSING": "medium",
    "FISCAL_CALENDAR_UNKNOWN": "medium",
    "EPS_COMPARATIVE_SHARE_BASE_MISMATCH": "low",
    "EPS_NETPROFIT_SIGN_MISMATCH": "low",
    "TTM_METHOD_MISMATCH": "low",
}

# Components of the prototype DataQualityScore (0..1). NOT VALIDATED FOR CANONICAL V1.
DQ_COMPONENTS = {
    "has_financials": 0.30,
    "has_monthly": 0.20,
    "has_price": 0.20,
    "fresh_financials": 0.15,
    "fresh_market": 0.15,
}


@dataclass
class DQ:
    flags: list = field(default_factory=list)

    def add(self, code: str) -> None:
        if code not in self.flags:
            self.flags.append(code)

    def score(self, has_financials: bool, has_monthly: bool, has_price: bool,
              fresh_financials: bool, fresh_market: bool) -> float:
        comp = DQ_COMPONENTS
        s = 0.0
        s += comp["has_financials"] if has_financials else 0.0
        s += comp["has_monthly"] if has_monthly else 0.0
        s += comp["has_price"] if has_price else 0.0
        s += comp["fresh_financials"] if fresh_financials else 0.0
        s += comp["fresh_market"] if fresh_market else 0.0
        return round(s, 4)

    def as_dict(self) -> dict:
        return {"flags": sorted(self.flags),
                "max_severity": max((SEVERITY[f] for f in self.flags), default="none",
                                    key=lambda x: ["none", "low", "medium", "high", "critical"].index(x))}
