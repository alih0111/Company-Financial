# -*- coding: utf-8 -*-
"""GAM 2-K-1 — read-only Codal publication-date provenance resolver.

Recovers the REAL publication instant of financial reports whose
``ingestion.reports.published_at`` is NULL (the legacy_sqlserver migration
carries only ``period_end_date``), using two independent evidence classes:

E1  in-DB mapping rows: ``ingestion.reports`` rows with ``source='codal'``
    and ``report_type='financial_statement'`` — each carries a real
    ``published_at`` (written by the codal backfill from the letter's
    PublishDateTime) plus ``tracing_no``-style ``source_report_id``.
    Company binding is already resolved (same ``company_id``).
E2  offline Codal search caches: ``historical_codal_backfill/output/pub_backfill/
    {symbol}_lt{6|58}.json`` — per-letter ``tracing_no`` + ``title`` +
    ``publish_datetime`` (raw Jalali, Persian digits) fetched from
    search.codal.ir/api/search/v2/q (see backfill_pub_times.py:77-82).

Hard rules (mission contract):
- period_end_date is NOT a publication date; collected_at is NOT a
  publication date; DB insertion time is NOT a publication date.
- no publication date is ever estimated from reporting-lag patterns.
- a correction (اصلاحیه) letter keeps its own date; the original's date is
  never inherited. When is_audited/is_restated flags cannot disambiguate
  several letters for the same (company, period), the match is `ambiguous`
  and is NEVER counted as verified.
- ambiguous matches are never verified; conflicts are reported, not hidden.
- this module never writes anything: callers must hold a
  default_transaction_read_only=on session (the runner enforces it).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    import jdatetime
except ImportError:  # pragma: no cover - the runner asserts availability
    jdatetime = None

# تهرانِ تاریخی: ایران تا پایان تابستان ۱۴۰۱ (2022-09-21/22) ساعت تابستانی
# داشت (+04:30) و از ۱۴۰۲ (2023-03-21/22) به بعد ندارد (IANA tzdata 2022g+).
# PublishDateTime کدال ساعت محلیِ دیواری بدون timezone است؛ پارسِ آن با
# +03:30 ثابت در دورهٔ DST لحظهٔ UTC را یک ساعت دیرتر از واقعیت ثبت می‌کرد
# (منشأ ۸۳۵ جفت «تعارض ۶۰دقیقه‌ای» ۲-ک-۳؛ DB درست بود، این پارس غلط).
# ZoneInfo با tzdata ≥2022g قواعد تاریخی را درست اعمال می‌کند؛ اگر در دسترس
# نبود به +03:30 ثابت برمی‌گردیم (برای نامه‌های 2023+ معادل است) و حالت را
# صریح اعلام می‌کنیم تا تست‌ها و audit از fallback باخبر شوند.
try:
    from zoneinfo import ZoneInfo

    TEHRAN = ZoneInfo("Asia/Tehran")
    TEHRAN_TZ_MODE = "iana_historical"
except Exception:  # pragma: no cover - فقط در نبود tzdata
    TEHRAN = timezone(timedelta(hours=3, minutes=30))
    TEHRAN_TZ_MODE = "fixed_0330_fallback"

# Persian ۰-۹ and Arabic-Indic ٠-٩ digits, same table as codal_feed.py:62-65.
_PERSIAN_ARABIC_DIGITS = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
_DIGIT_MAP = {ord(f): str(i) for i, f in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_DIGIT_MAP.update({ord(f): str(i) for i, f in enumerate("٠١٢٣٤٥٦٧٨٩")})

# ``منتهی به ۱۳۹۹/۰۳/۳۱`` inside a Codal letter title (see
# historical_codal_backfill/match_pub_times.py:35-49 for the same regex).
_TITLE_PERIOD_RE = re.compile(
    r"منتهی\s*به\s*([۰-۹٠-٩\d]{4})\s*/\s*([۰-۹٠-٩\d]{1,2})\s*/\s*([۰-۹٠-٩\d]{1,2})"
)

_PUBLISH_RE = re.compile(
    r"([۰-۹٠-٩\d]{4})/([۰-۹٠-٩\d]{1,2})/([۰-۹٠-٩\d]{1,2})"
    r"(?:\s+([۰-۹٠-٩\d]{1,2}):([۰-۹٠-٩\d]{1,2})(?::([۰-۹٠-٩\d]{1,2}))?)?"
)

# status vocabulary of THIS resolver (evidence-oriented, distinct from the
# evidence-chain contract used by the UI):
ST_VERIFIED = "verified_publication_date"
ST_AMBIGUOUS = "ambiguous_match"
ST_NO_EVIDENCE = "no_evidence"
ST_CONFLICTING = "conflicting_publication_date"
ST_ALREADY_PUBLISHED = "already_has_published_at"

# letters whose titles describe financial statements (LetterType 6 family).
LETTER_TYPE_FINANCIAL = 6
# monthly activity letters (LetterType 58, ن-۳۱).
LETTER_TYPE_MONTHLY = 58

_CORRECTION_MARK = "اصلاحیه"
_AUDITED_MARK = "حسابرسی شده"
_UNAUDITED_MARK = "حسابرسی نشده"
_CONSOLIDATED_MARK = "تلفیقی"

# two timestamps count as the same instant when within this tolerance
# (cache wall-clock minute precision vs tz-aware DB timestamps).
_SAME_INSTANT_TOL = timedelta(minutes=1)


def norm_digits(s: str) -> str:
    """Persian/Arabic-Indic digits -> ASCII."""
    return (s or "").translate(_DIGIT_MAP).strip()


def title_period_jalali(title: Optional[str]) -> Optional[str]:
    """Extract ``1403/06/31``-style period from a letter title, or None."""
    if not title:
        return None
    m = _TITLE_PERIOD_RE.search(norm_digits(title))
    if not m:
        return None
    return f"{m.group(1)}/{int(m.group(2)):02d}/{int(m.group(3)):02d}"


def parse_persian_datetime(raw: Optional[str]) -> Optional[datetime]:
    """Jalali ``۱۴۰۵/۰۷/۰۲ ۱۶:۲۸:۴۴`` -> tz-aware Tehran datetime.

    Mirrors codal_feed.parse_persian_datetime (jdatetime.togregorian) and
    attaches Asia/Tehran with IANA historical rules (Iran DST existed until
    1401/2022-09-21; none since 1402/2023 — see TEHRAN above). Falls back to
    fixed +03:30 only when tzdata is unavailable. Returns None when unparsable.
    """
    if not raw:
        return None
    s = norm_digits(str(raw))
    m = _PUBLISH_RE.search(s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh = int(m.group(4) or 0)
    mm = int(m.group(5) or 0)
    ss = int(m.group(6) or 0)
    if not (1200 <= y <= 1600):  # jalali year guard; 1500+ passthrough handled by caller
        return None
    if jdatetime is None:
        return None
    try:
        g = jdatetime.date(y, mo, d).togregorian()
    except (ValueError, OverflowError):
        return None
    return datetime(g.year, g.month, g.day, hh, mm, ss, tzinfo=TEHRAN)


def parse_gregorian_datetime(raw: Optional[str]) -> Optional[datetime]:
    """Passthrough for already-Gregorian publish strings (year > 1500)."""
    if not raw:
        return None
    s = norm_digits(str(raw))
    m = _PUBLISH_RE.search(s)
    if not m:
        return None
    y = int(m.group(1))
    if y <= 1500:
        return None
    try:
        return datetime(y, int(m.group(2)), int(m.group(3)),
                        int(m.group(4) or 0), int(m.group(5) or 0),
                        int(m.group(6) or 0), tzinfo=TEHRAN)
    except ValueError:
        return None


def parse_publish_datetime(raw: Optional[str]) -> Optional[datetime]:
    """Try Gregorian first, then Jalali (Codal is Jalali; defensive both)."""
    return parse_gregorian_datetime(raw) or parse_persian_datetime(raw)


def gregorian_to_jalali_text(d: Optional[date]) -> Optional[str]:
    """date -> ``1403/06/31`` (normalized ASCII digits)."""
    if d is None or jdatetime is None:
        return None
    try:
        j = jdatetime.date.fromgregorian(date=d)
    except (ValueError, OverflowError):
        return None
    return f"{j.year}/{j.month:02d}/{j.day:02d}"


def _same_instant(a: Optional[datetime], b: Optional[datetime]) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= _SAME_INSTANT_TOL


@dataclass
class CodalLetter:
    """One letter from a pub_backfill cache (E2 evidence)."""
    symbol: str
    letter_type: int
    tracing_no: str
    title: Optional[str]
    publish_datetime_raw: Optional[str]
    letter_code: Optional[str]
    url: Optional[str]
    cache_file: str
    publish_at: Optional[datetime] = None
    title_period: Optional[str] = None

    def to_evidence(self) -> Dict[str, Any]:
        return {
            "kind": "pub_backfill_cache",
            "cache_file": self.cache_file,
            "tracing_no": self.tracing_no,
            "letter_code": self.letter_code,
            "title": self.title,
            "publish_datetime_raw": self.publish_datetime_raw,
            "publish_at": self.publish_at.isoformat() if self.publish_at else None,
        }


@dataclass
class DBCodalRow:
    """One ingestion.reports row with source='codal' (E1 evidence)."""
    report_id: str
    source_report_id: Optional[str]
    title: Optional[str]
    published_at: Optional[datetime]
    jalali_period_text: Optional[str]
    period_end_date: Optional[date]

    def to_evidence(self) -> Dict[str, Any]:
        return {
            "kind": "db_codal_report_row",
            "report_id": self.report_id,
            "source_report_id": self.source_report_id,
            "title": self.title,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "jalali_period_text": self.jalali_period_text,
            "period_end_date": self.period_end_date.isoformat() if self.period_end_date else None,
        }


@dataclass
class Resolution:
    """Outcome of resolving one report row's publication date."""
    status: str
    publish_at: Optional[datetime] = None
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "publish_at": self.publish_at.isoformat() if self.publish_at else None,
            "evidence": self.evidence,
            "candidates": self.candidates,
            "reason": self.reason,
        }


class CodalPublishResolver:
    """Read-only resolver joining report rows to Codal letter evidence.

    ``conn`` must be a psycopg connection on a read-only transaction; the
    runner asserts ``default_transaction_read_only=on`` before use.
    """

    def __init__(self, conn: Any, cache_dir: str) -> None:
        self.conn = conn
        self.cache_dir = cache_dir
        self.letters_by_symbol: Dict[str, List[CodalLetter]] = {}
        self.letters_by_tracing: Dict[str, CodalLetter] = {}
        self.cache_files_loaded = 0
        self.cache_letters_loaded = 0
        self.cache_letters_without_date = 0
        self._load_caches()
        # tracing_no -> publish_at from ingestion.reports rows that already
        # carry published_at; used to corroborate cache datetimes.
        self.db_published_by_tracing: Dict[str, datetime] = {}
        for row in self._fetch_db_tracing_published():
            self.db_published_by_tracing[row[0]] = row[1]

    # ---------- evidence loading ----------

    def _load_caches(self) -> None:
        if not os.path.isdir(self.cache_dir):
            return
        for fn in sorted(os.listdir(self.cache_dir)):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(self.cache_dir, fn)
            try:
                doc = json.load(open(path, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            symbol = str(doc.get("symbol") or "").strip()
            letter_type = doc.get("letter_type")
            letters = doc.get("letters") or []
            if not symbol or not isinstance(letters, list):
                continue
            self.cache_files_loaded += 1
            for L in letters:
                if not isinstance(L, dict):
                    continue
                pub_at = parse_publish_datetime(L.get("publish_datetime"))
                lt = CodalLetter(
                    symbol=symbol,
                    letter_type=int(letter_type) if letter_type is not None else None,
                    tracing_no=str(L.get("tracing_no") or "").strip(),
                    title=L.get("title"),
                    publish_datetime_raw=L.get("publish_datetime"),
                    letter_code=L.get("letter_code"),
                    url=L.get("url"),
                    cache_file=fn,
                    publish_at=pub_at,
                    title_period=title_period_jalali(L.get("title")),
                )
                self.cache_letters_loaded += 1
                if lt.publish_at is None:
                    self.cache_letters_without_date += 1
                self.letters_by_symbol.setdefault(symbol, []).append(lt)
                if lt.tracing_no:
                    self.letters_by_tracing[lt.tracing_no] = lt

    def _fetch_db_tracing_published(self) -> Sequence[Any]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT source_report_id, published_at FROM ingestion.reports "
            "WHERE source = 'codal' AND published_at IS NOT NULL "
            "AND source_report_id IS NOT NULL")
        out = [(str(r[0]).strip(), r[1]) for r in cur.fetchall()]
        cur.close()
        return out

    # ---------- DB candidate fetchers ----------

    def db_financial_rows(
        self, company_id: str, period_jalali: Optional[str], period_greg: Optional[date]
    ) -> List[DBCodalRow]:
        """E1: codal financial_statement rows of THIS company for the period."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id::text, source_report_id, title, published_at, "
            "jalali_period_text, period_end_date "
            "FROM ingestion.reports "
            "WHERE source = 'codal' AND report_type = 'financial_statement' "
            "AND company_id = %s::uuid AND published_at IS NOT NULL "
            "AND (jalali_period_text = %s OR period_end_date = %s)",
            (company_id, period_jalali, period_greg))
        rows = [DBCodalRow(r[0], r[1], r[2], r[3], r[4], r[5]) for r in cur.fetchall()]
        cur.close()
        return rows

    def db_any_tracing_for_company(self, company_id: str) -> List[str]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT DISTINCT source_report_id FROM ingestion.reports "
            "WHERE source = 'codal' AND company_id = %s::uuid "
            "AND source_report_id IS NOT NULL", (company_id,))
        out = [str(r[0]).strip() for r in cur.fetchall()]
        cur.close()
        return out

    # ---------- matching ----------

    def _corroborate(self, row: DBCodalRow) -> Optional[CodalLetter]:
        """Find the cache letter for an E1 row by tracing_no."""
        tid = (row.source_report_id or "").strip()
        return self.letters_by_tracing.get(tid) if tid else None

    def _cache_candidates_for_period(
        self, codal_symbol: Optional[str], letter_type: int,
        period_jalali: Optional[str],
    ) -> List[CodalLetter]:
        if not codal_symbol or not period_jalali:
            return []
        out = []
        for lt in self.letters_by_symbol.get(codal_symbol, []):
            if lt.letter_type != letter_type:
                continue
            if lt.title_period == period_jalali and lt.publish_at is not None:
                out.append(lt)
        return out

    def _symbol_binding_ok(self, company_id: str, codal_symbol: Optional[str]) -> bool:
        """Company<->symbol binding proof: at least one DB codal row of this
        company has a tracing_no present in the cache for that symbol."""
        if not codal_symbol:
            return False
        cache_tids = {lt.tracing_no for lt in self.letters_by_symbol.get(codal_symbol, [])}
        if not cache_tids:
            return False
        for tid in self.db_any_tracing_for_company(company_id):
            if tid in cache_tids:
                return True
        return False

    def resolve_statement(
        self,
        company_id: str,
        codal_symbol: Optional[str],
        period_jalali: Optional[str],
        period_greg: Optional[date],
        is_audited: Optional[bool] = None,
        is_restated: Optional[bool] = None,
    ) -> Resolution:
        """Resolve the publication date of one financial-statement report.

        Matching key: company (E1 company_id binding; E2 codal_symbol) +
        period + financial-statement letter family. Ambiguous matches are
        never verified.
        """
        e1 = self.db_financial_rows(company_id, period_jalali, period_greg)
        evidence: List[Dict[str, Any]] = []
        conflicts: List[str] = []

        for row in e1:
            ev = row.to_evidence()
            cache_lt = self._corroborate(row)
            if cache_lt is not None:
                ev["cache_corroboration"] = cache_lt.to_evidence()
                if _same_instant(row.published_at, cache_lt.publish_at):
                    ev["corroboration"] = "db_row_and_cache_agree"
                else:
                    ev["corroboration"] = "db_row_and_cache_disagree"
                    conflicts.append(
                        f"tracing_no {row.source_report_id}: db published_at "
                        f"{row.published_at.isoformat() if row.published_at else None} vs cache "
                        f"{cache_lt.publish_at.isoformat() if cache_lt.publish_at else None}")
            evidence.append(ev)

        candidates: List[Dict[str, Any]] = []
        cand_dt: List[Optional[datetime]] = []
        for row in e1:
            candidates.append({
                "source": "db_codal_report_row",
                "publish_at": row.published_at.isoformat() if row.published_at else None,
                "tracing_no": row.source_report_id,
                "title": row.title,
            })
            cand_dt.append(row.published_at)

        # E2 fallback: no DB row for this (company, period) — match cache
        # letters by symbol + title period, but require a provable
        # company<->symbol binding before any verified claim.
        e2_used = False
        if not candidates:
            cache_cands = self._cache_candidates_for_period(
                codal_symbol, LETTER_TYPE_FINANCIAL, period_jalali)
            if cache_cands:
                e2_used = True
                binding_ok = self._symbol_binding_ok(company_id, codal_symbol)
                for lt in cache_cands:
                    candidates.append({
                        "source": "pub_backfill_cache",
                        "publish_at": lt.publish_at.isoformat() if lt.publish_at else None,
                        "tracing_no": lt.tracing_no,
                        "title": lt.title,
                        "cache_file": lt.cache_file,
                        "company_symbol_binding": "proven_by_db_tracing_overlap"
                        if binding_ok else "symbol_match_only",
                    })
                    cand_dt.append(lt.publish_at)

        if conflicts:
            return Resolution(
                status=ST_CONFLICTING, evidence=evidence, candidates=candidates,
                reason="؛ ".join(conflicts))

        if not candidates:
            return Resolution(
                status=ST_NO_EVIDENCE, evidence=evidence,
                reason="no codal row for this company+period and no cache letter "
                       "matches the symbol+period")

        distinct = {c["publish_at"] for c in candidates if c["publish_at"]}
        if len(candidates) > 1 and len(distinct) > 1:
            return Resolution(
                status=ST_AMBIGUOUS, evidence=evidence, candidates=candidates,
                reason=f"{len(distinct)} different publication dates among "
                       f"{len(candidates)} candidate letters for the same "
                       "company+period; is_audited/is_restated flags cannot "
                       "disambiguate (legacy statements carry is_audited=NULL, "
                       "is_restated=false) — never verified by rule")

        pub = cand_dt[0]
        binding_note = candidates[0].get("company_symbol_binding")
        if e2_used and binding_note == "symbol_match_only":
            return Resolution(
                status=ST_AMBIGUOUS, publish_at=pub, evidence=evidence,
                candidates=candidates,
                reason="cache-only match: symbol equals but no DB tracing_no "
                       "of this company appears in the cache — company binding "
                       "not proven, not verified by rule")
        return Resolution(
            status=ST_VERIFIED, publish_at=pub, evidence=evidence,
            candidates=candidates,
            reason="matched by company+period+financial-statement family"
                   + (" (cache letter corroborated by company's DB tracing_no set)"
                      if e2_used else ""))

    def resolve_monthly(
        self,
        company_id: str,
        codal_symbol: Optional[str],
        period_jalali: Optional[str],
    ) -> Resolution:
        """Resolve publication date of one monthly-activity period (E2 only:
        monthly letters are LetterType 58 caches; DB has no published monthly
        evidence — legacy monthly rows are all published_at NULL)."""
        cache_cands = self._cache_candidates_for_period(
            codal_symbol, LETTER_TYPE_MONTHLY, period_jalali)
        candidates = [{
            "source": "pub_backfill_cache",
            "publish_at": lt.publish_at.isoformat() if lt.publish_at else None,
            "tracing_no": lt.tracing_no,
            "title": lt.title,
            "cache_file": lt.cache_file,
        } for lt in cache_cands]
        first_dt = cache_cands[0].publish_at if cache_cands else None
        if not candidates:
            return Resolution(
                status=ST_NO_EVIDENCE,
                reason="no monthly letter (LetterType 58) matches symbol+period")
        distinct = {c["publish_at"] for c in candidates if c["publish_at"]}
        if len(distinct) > 1:
            return Resolution(
                status=ST_AMBIGUOUS, candidates=candidates,
                reason=f"{len(distinct)} different publication dates among "
                       f"{len(candidates)} monthly letters for the same period")
        binding_ok = self._symbol_binding_ok(company_id, codal_symbol)
        if not binding_ok:
            return Resolution(
                status=ST_AMBIGUOUS, publish_at=first_dt,
                candidates=candidates,
                reason="cache-only match: company<->symbol binding not proven "
                       "by DB tracing overlap")
        return Resolution(
            status=ST_VERIFIED, publish_at=first_dt,
            candidates=candidates,
            reason="monthly letter matched by symbol+period with proven company binding")
