"""Historical share-count reconstruction from explicit capital-event evidence.

Design rules (from the HISTORICAL_DIRECT_VALUATION_INPUTS_INCOMPLETE audit and
the frozen SHARE-HISTORY PIT CONTRACT):

* The only trustworthy anchor is an explicit observed share count — today the
  vendor daily snapshot in ``core.share_structure``.
* Going backwards is allowed **only** while the event chain is complete: each
  step must state the previous count, or an exact change ratio that inverts
  cleanly. An unexplained gap becomes ``HISTORICAL_SHARES_UNKNOWN``; it is never
  interpolated, and today's count is never projected backwards.
* Validation against accounting observations (net profit / reported EPS) is a
  *check*, never an input. EPS comparative columns are known to be restated
  inconsistently, so they must not drive a reconstructed share count.
* Share history and return adjustment are different problems: a valuation
  ``effective_date`` does not imply a market ex-date, and no adjustment factor is
  approximated.

## PIT contract for share history (two independent temporal axes)

    VALID TIME      valid_from <= as_of < valid_to
                    when the registered share count economically applies

    KNOWLEDGE TIME  knowledge_from <= cutoff
                    when the evidence that establishes the count was public

A row never becomes usable at a historical signal merely because a
later-backfilled document retrospectively proves an older economic state.
``collected_at`` (acquisition time) is lineage only and is NEVER the knowledge
gate for archival Codal evidence; it remains the real fetch timestamp.

``knowledge_from`` per interval:

  * observed vendor snapshot -> its ``collected_at`` (an observation cannot be
    known before it was observed, which keeps today's shares out of history);
  * reconstructed interval   -> ``MAX(published_at)`` over the *required*
    evidence only; optional cross-check sources never delay availability.
"""
from __future__ import annotations

import datetime as dt
from datetime import date

STATUS_KNOWN = "KNOWN"
STATUS_UNKNOWN = "HISTORICAL_SHARES_UNKNOWN"

BASIS_VENDOR = "VENDOR_SNAPSHOT"
BASIS_RECONSTRUCTED = "RECONSTRUCTED_EVENT_CHAIN"
BASIS_UNKNOWN = "UNKNOWN"

# event types that state a share-count change usable for reconstruction
COUNT_EVENT_TYPES = {
    "REGISTRATION", "CAPITAL_INCREASE_REGISTERED", "CAPITAL_REDUCTION",
    "BONUS_SHARES", "RIGHTS_ISSUE", "NOMINAL_VALUE_CHANGE",
}

# FROZEN (before any reconstruction): only an event whose stage shows the new
# capital/share count actually became effective may move a share interval.
# Proposals, auditor opinions and board/EGM approvals are evidence of intent, not
# of a changed share count, and are stored with status PROPOSED.
PROPOSAL_STAGE_EVENT_TYPES = {
    "CAPITAL_INCREASE_PROPOSAL", "AUDITOR_APPROVAL", "BOARD_APPROVAL",
    "EGM_APPROVAL",
}
SHARE_HISTORY_CONFIRMING_EVENT_TYPES = COUNT_EVENT_TYPES
STAGE_PROPOSED = "PROPOSED"

# FROZEN effective-date precedence for share history. The announcement date is
# deliberately absent: publication is not effectiveness. If none of these dates
# is stated by the source, the transition timing is UNKNOWN and the interval is
# not bridged.
EFFECTIVE_DATE_FIELDS = ("effective_date", "registered_at")


def effective_date_for_shares(ev: dict):
    """(date, status) for a share-count change, or (None, 'UNKNOWN'/'PROPOSED').

    A proposal/approval stage never moves shares, and a count-changing form with
    no source-stated effective/registration date leaves the transition timing
    UNKNOWN rather than using its publication date.
    """
    etype = ev.get("event_type")
    if etype in PROPOSAL_STAGE_EVENT_TYPES or etype not in COUNT_EVENT_TYPES:
        return None, STAGE_PROPOSED
    for field in EFFECTIVE_DATE_FIELDS:
        if ev.get(field):
            return ev[field], "CONFIRMED"
    return None, "UNKNOWN"


def _event_date(ev: dict) -> date | None:
    """Effective date under the frozen rule; announcement dates are never used."""
    when, _status = effective_date_for_shares(ev)
    return when


# ---- knowledge time ---------------------------------------------------------
def _as_dt(value):
    """Normalize a date/datetime/ISO string to an aware datetime (UTC default)."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=dt.timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = dt.datetime.combine(date.fromisoformat(text), dt.time(), tzinfo=dt.timezone.utc)
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def default_required_evidence(ev: dict) -> list:
    """The single fact an event-derived interval depends on."""
    return [{"source": ev.get("source") or "codal",
             "source_report_id": str(ev.get("source_report_id") or ev.get("id") or ""),
             "published_at": ev.get("published_at")}]


def evidence_knowledge_from(required_evidence: list):
    """MAX(published_at) over REQUIRED evidence; None if any required item has no
    publication time (knowledge then cannot be established, so the interval is
    never PIT-eligible). Optional cross-check sources must not be passed here —
    they would delay availability without being necessary."""
    stamps = []
    for item in required_evidence or []:
        stamp = _as_dt((item or {}).get("published_at"))
        if stamp is None:
            return None
        stamps.append(stamp)
    return max(stamps) if stamps else None


def interval_eligible(iv: dict, as_of: date, cutoff) -> tuple:
    """(eligible, reason) under the frozen share-history PIT contract."""
    if iv.get("status") != STATUS_KNOWN:
        return False, "HISTORICAL_SHARES_UNKNOWN"
    valid_from, valid_to = iv.get("valid_from"), iv.get("valid_to")
    if valid_from is None or _as_dt(as_of) < _as_dt(valid_from):
        return False, "OUTSIDE_VALID_TIME"
    if valid_to is not None and _as_dt(as_of) >= _as_dt(valid_to):
        return False, "OUTSIDE_VALID_TIME"
    knowledge_from = _as_dt(iv.get("knowledge_from"))
    if knowledge_from is None:
        return False, "KNOWLEDGE_TIME_UNKNOWN"
    if _as_dt(cutoff) is None:
        return False, "CUTOFF_REQUIRED"
    if knowledge_from > _as_dt(cutoff):
        return False, "EVIDENCE_PUBLISHED_AFTER_CUTOFF"
    return True, "ELIGIBLE"


def _shares_before(ev: dict) -> float | None:
    """Explicit previous count, or the previous count implied by an exact ratio."""
    if ev.get("shares_before") is not None:
        return float(ev["shares_before"])
    after, ratio = ev.get("shares_after"), ev.get("change_ratio")
    if after is not None and ratio not in (None, -1.0):
        return float(after) / (1.0 + float(ratio))
    return None


def reconstruct_intervals(anchor: dict, events: list) -> list:
    """Build PIT intervals backwards from an explicit anchor snapshot.

    ``anchor``: {"security_id", "company_id", "date", "shares", "source"}.
    ``events``: capital/share events for the same security (any order).

    Returns intervals newest-first, each:
      {valid_from, valid_to, shares_outstanding, basis, status, source, evidence}
    """
    sid = anchor.get("security_id")
    cid = anchor.get("company_id")
    out = [{
        "security_id": sid, "company_id": cid,
        "valid_from": anchor["date"], "valid_to": None,
        "shares_outstanding": float(anchor["shares"]),
        "basis": BASIS_VENDOR, "status": STATUS_KNOWN,
        "source": anchor.get("source") or "vendor_snapshot",
        "evidence": {"anchor_date": str(anchor["date"])},
        # an observation cannot be known before it was observed: the snapshot's
        # own collected_at is its knowledge time, which keeps today's count out
        # of every historical cutoff.
        "knowledge_from": anchor.get("collected_at"),
        "required_evidence": [{"source": anchor.get("source") or "vendor_snapshot",
                               "source_report_id": None,
                               "published_at": anchor.get("collected_at")}],
    }]

    usable = [e for e in events
              if e.get("event_type") in COUNT_EVENT_TYPES and _event_date(e) is not None]
    usable.sort(key=_event_date, reverse=True)

    current_from = anchor["date"]
    current_shares = float(anchor["shares"])
    gap_open = False
    for ev in usable:
        ev_date = _event_date(ev)
        if ev_date >= current_from:
            continue                      # at/after the anchor: cannot inform the past
        before = _shares_before(ev)
        after = ev.get("shares_after")
        if before is None:
            # chain break: everything older than this event is unknown
            out.append({
                "security_id": sid, "company_id": cid,
                "valid_from": None, "valid_to": ev_date,
                "shares_outstanding": None, "basis": BASIS_UNKNOWN,
                "status": STATUS_UNKNOWN, "source": ev.get("source") or "codal",
                "evidence": {"reason": "missing_explicit_previous_count",
                             "event_id": ev.get("id"), "event_type": ev.get("event_type")},
            })
            gap_open = True
            break
        if after is not None and abs(float(after) - current_shares) > 0:
            # the event's stated result disagrees with the next interval's count:
            # the chain is not contiguous and must not be silently used
            out.append({
                "security_id": sid, "company_id": cid,
                "valid_from": None, "valid_to": ev_date,
                "shares_outstanding": None, "basis": BASIS_UNKNOWN,
                "status": STATUS_UNKNOWN, "source": ev.get("source") or "codal",
                "evidence": {"reason": "chain_contiguity_violation",
                             "expected": current_shares, "event_states": float(after),
                             "event_id": ev.get("id")},
            })
            gap_open = True
            break
        required = ev.get("required_evidence") or default_required_evidence(ev)
        out.append({
            "security_id": sid, "company_id": cid,
            "valid_from": ev_date, "valid_to": current_from,
            "shares_outstanding": before, "basis": BASIS_RECONSTRUCTED,
            "status": STATUS_KNOWN, "source": ev.get("source") or "codal",
            "evidence": {"event_id": ev.get("id"), "event_type": ev.get("event_type"),
                         "effective_date": str(ev_date)},
            "knowledge_from": evidence_knowledge_from(required),
            "required_evidence": required,
        })
        current_from, current_shares = ev_date, before

    if not gap_open:
        out.append({
            "security_id": sid, "company_id": cid,
            "valid_from": None, "valid_to": current_from,
            "shares_outstanding": None, "basis": BASIS_UNKNOWN,
            "status": STATUS_UNKNOWN, "source": "chain_start",
            "evidence": {"reason": "no_further_evidence"},
        })
    return out


def shares_at(intervals: list, as_of: date, cutoff) -> tuple[float | None, str]:
    """PIT share count: (shares, status).

    Requires BOTH axes: the interval must cover ``as_of`` in valid time AND its
    required evidence must have been published by ``cutoff``. A later-backfilled
    document can therefore never make an older economic state usable at a signal
    whose cutoff precedes the document's publication.
    """
    for iv in intervals:
        valid_from, valid_to = iv.get("valid_from"), iv.get("valid_to")
        if valid_from is not None and _as_dt(as_of) < _as_dt(valid_from):
            continue
        if valid_to is not None and _as_dt(as_of) >= _as_dt(valid_to):
            continue
        eligible, _reason = interval_eligible(iv, as_of, cutoff)
        if not eligible:
            return None, STATUS_UNKNOWN
        return iv["shares_outstanding"], STATUS_KNOWN
    return None, STATUS_UNKNOWN


def return_adjustment_usable(ev: dict) -> bool:
    """An event may inform price/return adjustment only with explicit market
    economics: a market ex-date AND stated economics, and a confirmed status."""
    return bool(ev.get("status") == "CONFIRMED"
                and ev.get("market_ex_date")
                and ev.get("economics_explicit"))


def validate_against_eps(intervals: list, observations: list, cutoff=None) -> list:
    """Cross-check reconstructed shares against net profit / reported EPS.

    Validation only: a deviation is reported, never used to move a share count
    (EPS comparatives are restated inconsistently, so they are not evidence).
    ``cutoff`` defaults to each observation's own date, so the check is itself
    PIT-clean: an observation is only compared against shares that were knowable
    on that date.
    """
    report = []
    for obs in observations:
        when, net_profit, eps = obs.get("date"), obs.get("net_profit"), obs.get("eps")
        if when is None or not eps or net_profit is None:
            continue
        shares, status = shares_at(intervals, when, cutoff if cutoff is not None else when)
        if status != STATUS_KNOWN or not shares:
            continue
        implied = float(net_profit) / float(eps)
        dev = abs(implied - shares) / shares if shares else None
        report.append({"date": str(when), "shares": shares, "implied_shares": implied,
                       "relative_deviation": dev})
    return report
