"""Compare weighting schemes on the frozen PIT protocol and write a verdict.

Reads the per-scheme summaries written by run_backtest (output/weighting_validation/<scheme>/)
and emits comparison.json + comparison.md with a risk-adjusted verdict.

Usage:
  CDF_PILOT_DB=... python weighting_validation.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "output" / "weighting_validation"
SCHEMES = ["equal", "inverse_vol", "min_variance"]


def load(scheme):
    p = BASE / scheme / "summary_metrics.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return d


def fmt_pct(x):
    return f"{x * 100:.1f}%" if x is not None else "--"


def main():
    rows = []
    for s in SCHEMES:
        d = load(s)
        if not d:
            continue
        port = d["portfolio"]["portfolio"]
        net = d["portfolio"]["portfolio_net"]
        rows.append({
            "scheme": s,
            "n_periods": net.get("n"),
            "cumulative_return": net.get("cumulative_return"),
            "annualized_return": net.get("annualized_return"),
            "volatility": net.get("volatility"),
            "max_drawdown": net.get("max_drawdown"),
            "sharpe_like": net.get("sharpe_like"),
            "hit_rate": net.get("hit_rate"),
            "mean_turnover": d["portfolio"].get("mean_turnover"),
            "ic_mean": (d.get("ic") or {}).get("mean_ic"),
            "gross_volatility": port.get("volatility"),
            "gross_cumulative": port.get("cumulative_return"),
        })
    if not rows:
        raise SystemExit("no scheme summaries found under " + str(BASE))

    out_json = BASE / "comparison.json"
    out_json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["# Weighting validation — frozen PIT protocol (2021-01 → 2026-06, monthly, top-20)",
             "",
             "Simulator: `simulate_corrected` (Phase-2 cash-aware policy) for every scheme,",
             "10 bps/side costs, covariance estimated only from closes ≤ signal date",
             "(250-day window, shrinkage 0.3, cap 15%).",
             "",
             "| scheme | net cum | ann. return | vol | maxDD | sharpe-like | hit rate | turnover |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['scheme']} | {fmt_pct(r['cumulative_return'])} | {fmt_pct(r['annualized_return'])} "
                     f"| {fmt_pct(r['volatility'])} | {fmt_pct(r['max_drawdown'])} "
                     f"| {r['sharpe_like']:.2f} | {fmt_pct(r['hit_rate'])} | {fmt_pct(r['mean_turnover'])} |")

    eq = next((r for r in rows if r["scheme"] == "equal"), None)
    mv = next((r for r in rows if r["scheme"] == "min_variance"), None)
    iv = next((r for r in rows if r["scheme"] == "inverse_vol"), None)
    lines += ["", "## Verdict", ""]
    if eq and mv:
        d_sharpe = (mv["sharpe_like"] or 0) - (eq["sharpe_like"] or 0)
        d_vol = (mv["volatility"] or 0) - (eq["volatility"] or 0)
        d_mdd = (mv["max_drawdown"] or 0) - (eq["max_drawdown"] or 0)
        lines.append(f"- min_variance vs equal: sharpe {mv['sharpe_like']:.2f} vs {eq['sharpe_like']:.2f} "
                     f"({d_sharpe:+.2f}), vol {fmt_pct(mv['volatility'])} vs {fmt_pct(eq['volatility'])} "
                     f"({d_vol * 100:+.1f}pp), maxDD {fmt_pct(mv['max_drawdown'])} vs {fmt_pct(eq['max_drawdown'])} "
                     f"({d_mdd * 100:+.1f}pp).")
        verdict = ("min_variance is the default construction" if d_sharpe > 0.05
                   else "no meaningful risk-adjusted edge over equal weighting — equal stays the default")
        lines.append(f"- {verdict}.")
    if iv:
        lines.append(f"- inverse_vol sharpe {iv['sharpe_like']:.2f}, vol {fmt_pct(iv['volatility'])} "
                     f"(reported for completeness).")
    lines += ["", "Caveat: a single full-window run is one path, not an OOS protocol; treat the",
              "differences as indicative until the coverage-controlled revalidation (handoff §38) is done.",
              ""]
    (BASE / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
