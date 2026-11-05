"""Minimal research layer on top of the existing adjusted-price engine.

This package does not re-implement preparation, scoring, prices or replay. It
reuses `ranking_research.top10_six_month` and the frozen point-in-time feature
table, and adds only: a feature/access-time contract, a registered signal set,
portfolio policies, a time split, an experiment registry with atomic writes and
resume, and corrected point-in-time benchmarks.

Nothing here touches a production pointer or places an order.
"""
ENGINE_VERSION = 'strategy-search-2-corrected-member-limit'
