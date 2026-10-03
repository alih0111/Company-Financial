"""SHADOW V1 — shared helpers (determinism, hashing, price/calendar contracts).

Frozen contracts implemented here (see SHADOW_V1_SPEC.md):
  - spec §5a  trading calendar (no Thu/Fri; breadth >= 30 securities with volume>0)
  - spec §5b  path-A price source = raw closing caches; path-B = market.price_observations
  - spec §13  sorted iteration, stable serialization, canonical content hashes
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"
ROOT = Path(r"D:\RFA\Company-Financial")
SPEC_PATH = ROOT / "portfolio_shadow" / "SHADOW_V1_SPEC.md"
STATE_PATH = ROOT / "portfolio_shadow" / "shadow_v1_state.json"
IDENTITY_LEDGER = ROOT / "portfolio_shadow" / "identity_onboarding_ledger.jsonl"
RAW_DIR = ROOT / "historical_codal_backfill" / "output" / "raw_closing_universe"
IDENTITY_MAP = ROOT / "portfolio_research" / "portfolio_identity_map.parquet"
CERTIFIED_ENGINE = ROOT / "portfolio_research" / "repair_accounting_v1.py"
TEHRAN = dt.timezone(dt.timedelta(hours=3, minutes=30), "Asia/Tehran")
CALENDAR_MIN_BREADTH = 30          # spec §5a (frozen; evidence in spec)
OBSERVATION_DEADLINE_DAYS = 7      # spec §15b (frozen)
COST_RATE_BASE = 0.005             # spec §10 (frozen 50 bps one-way)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def canonical_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1, default=str)


def canonical_content_hash(records: list[dict]) -> str:
    """Hash of logical content independent of file format (spec §13)."""
    return sha256_bytes(canonical_json(sorted(records, key=lambda r: json.dumps(
        r, ensure_ascii=False, sort_keys=True, default=str))).encode("utf-8"))


def load_raw_cache(symbol: str, ins_code: str) -> dict[str, dict] | None:
    """Raw closing cache records keyed by ISO date. One final record per session."""
    gz = RAW_DIR / f"raw_{symbol}_{ins_code}.json.gz"
    if not gz.exists():
        return None
    with gzip.open(gz, "rt", encoding="utf-8") as fh:
        doc = json.loads(fh.read())
    out = {}
    for r in sorted(doc["closingPriceDaily"], key=lambda x: (x["dEven"], x.get("hEven", 0))):
        s = str(r["dEven"])
        out[f"{s[:4]}-{s[4:6]}-{s[6:8]}"] = r
    return out


def raw_caches_max_date() -> str | None:
    """Max session date available across all raw caches (collection lag check)."""
    import glob
    mx = None
    for gz in glob.glob(str(RAW_DIR / "raw_*.json.gz")):
        # filename layout: raw_{symbol}_{ins_code}.json.gz — strip both extensions
        name = Path(gz).name[len("raw_"):-len(".json.gz")]
        ins = name.rsplit("_", 1)[-1]
        symbol = name[: -(len(ins) + 1)]
        recs = load_raw_cache(symbol, ins)
        if recs:
            d = max(recs)
            if mx is None or d > mx:
                mx = d
    return mx


def shadow_calendar_rows(pg) -> list[tuple[str, int]]:
    """Trading dates under spec §5a, ascending: (date_iso, breadth)."""
    with pg.cursor() as cur:
        cur.execute(
            """SELECT trade_date::text, COUNT(DISTINCT security_id) AS breadth
               FROM market.price_observations
               WHERE volume > 0
               GROUP BY trade_date
               HAVING COUNT(DISTINCT security_id) >= %s
               ORDER BY trade_date""", (CALENDAR_MIN_BREADTH,))
        rows = [(d, int(b)) for d, b in cur.fetchall()]
    return [(d, b) for d, b in rows
            if dt.date.fromisoformat(d).weekday() not in (3, 4)]  # Mon..Sun; 3=Thu, 4=Fri


def first_execution_date(cal_dates: list[str], after_iso: str) -> str | None:
    for d in cal_dates:
        if d > after_iso:
            return d
    return None


def to_tehran(ts) -> dt.datetime:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=TEHRAN)
    return ts.astimezone(TEHRAN)


def cache_identity_scan(symbol: str, ins_code: str) -> dict:
    """Price-source identity evidence (V1.1 §7): the raw cache for (symbol, ins_code)
    exists and every record in it carries the same insCode (no symbol-only acceptance)."""
    gz = RAW_DIR / f"raw_{symbol}_{ins_code}.json.gz"
    if not gz.exists():
        return {"cache_exists": False}
    with gzip.open(gz, "rt", encoding="utf-8") as fh:
        recs = json.loads(fh.read()).get("closingPriceDaily", [])
    bad = sum(1 for r in recs if str(r.get("insCode")) != str(ins_code))
    return {"cache_exists": True, "records": len(recs), "insCode_mismatches": bad,
            "max_session": max((str(r["dEven"]) for r in recs), default=None)}


def ledger_onboarded() -> dict[tuple[str, str, str], dict]:
    """company_id -> mapping entries already accepted in the append-only ledger."""
    out = {}
    if not IDENTITY_LEDGER.exists():
        return out
    with open(IDENTITY_LEDGER, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("record_kind") == "ONBOARDED_IDENTITY":
                out[(rec["company_id"], rec["symbol"], rec["ins_code"])] = rec
    return out


def run_qualifies(as_of_date, source_cutoff_at, completed_at) -> tuple[bool, str]:
    """Spec §1 mid-session guard (data-quality rule)."""
    comp = to_tehran(completed_at)
    cut = to_tehran(source_cutoff_at)
    if as_of_date < comp.date():
        return True, "as_of_date strictly before completion date"
    if cut is not None and cut.time() >= dt.time(12, 45):
        return True, f"source_cutoff_at {cut.isoformat()} is post-close"
    return False, f"mid-session snapshot (cutoff {cut.isoformat() if cut else None})"
