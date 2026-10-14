"""Resume public Codal collection, then compute a separate ranking bundle.

Uses archived search results and HTML before making public GET requests. New
facts require a real publication instant, explicit units, parent-only financial
statements, matching period headers, and same-report comparative columns.
Never writes the database or replaces official artifacts. Stops on challenges.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
ANA = ROOT / "canonical_postgres_v1_2_1" / "analytics_canonical_v1"
sys.path.insert(0, str(ANA))
import codal_fs_fetch as F
import codal_fs_parse as P
from codal_publish_resolver import parse_persian_datetime

OUT = ROOT / "provenance_v1" / "output" / "coverage_verified"
LEGACY = ROOT / "provenance_v1" / "output" / "exp_2k13_codal" / "raw"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


class CollectionPaused(Exception):
    pass


def supplement_fiscal_titles(engine, cutoff):
    """Carry the proven report duration into the same engine as its values."""
    original = len(engine.codal_titles)
    engine.codal_titles = [r for r in engine.codal_titles if not re.search(r'\(\s*شرکت\b', P.norm(r['title']))]
    excluded = original - len(engine.codal_titles)
    existing = {(r['company_id'], r['period_end_date'], r['title']) for r in engine.codal_titles}
    added = 0
    restricted = []
    for path in sorted((OUT / 'facts').glob('*.json')):
        rec = read(path)
        if rec.get('rules_version') != 3:
            continue
        proven = {f['tracing_no'] for f in rec['facts']
                  if f.get('collected_at') and dt.datetime.fromisoformat(f['collected_at']) <= cutoff}
        titles = []
        for period, (_, letter) in select(letters_for(rec['symbol'], False, 0), cutoff):
            if str(letter['TracingNo']) not in proven:
                continue
            titles.append((period, letter))
        if any(F.classify_letter(letter) in ('annual', 'annual_audited') for _, letter in titles):
            # Old catalogs can mix the issuer's symbol with subsidiary fiscal
            # years. Use the same proven parent reports as the financial facts.
            engine.codal_titles = [r for r in engine.codal_titles if r['company_id'] != rec['company_id']]
            existing = {key for key in existing if key[0] != rec['company_id']}
            restricted.append({'company_id': rec['company_id'], 'symbol': rec['symbol'],
                               'annual_periods': [str(period) for period, letter in titles
                                                  if F.classify_letter(letter) in ('annual', 'annual_audited')]})
        for period, letter in titles:
            key = (rec['company_id'], period, letter['Title'])
            if key not in existing:
                engine.codal_titles.append({'company_id': key[0], 'period_end_date': key[1], 'title': key[2]})
                existing.add(key)
                added += 1
    return {'proven_titles_added': added, 'named_other_entity_titles_excluded': excluded,
            'calendar_from_verified_parent_reports': restricted}


def download(url, delay):
    time.sleep(delay)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.codal.ir/"})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise CollectionPaused(f"HTTP {exc.code}; collection saved and paused") from exc
        raise
    if "captcha" in body.lower() and "<table" not in body.lower() and '"Letters"' not in body:
        raise CollectionPaused("captcha; human verification required")
    return body


def letters_for(symbol, fetch, delay, refresh=False):
    if refresh:
        if not fetch:
            raise ValueError('catalog refresh requires --fetch')
        url = F.SEARCH + "?" + urllib.parse.urlencode({"Symbol": symbol, "LetterType": 6, "PageNumber": 1, "PageSize": 100})
        payload = json.loads(download(url, delay))
        if not isinstance(payload.get('Letters'), list):
            raise ValueError('catalog response lacks Letters')
        data = payload['Letters']
        write(OUT / 'letters' / f'{symbol}.json', data)
        return data
    fresh = OUT / "letters" / f"{symbol}.json"
    if fresh.exists():
        data = read(fresh)
        if data:
            return data
    for path in [LEGACY / f"{symbol}_letters.json",
                 ROOT / "historical_codal_backfill" / "output" / "pub_backfill" / f"{symbol}_lt6.json"]:
        if not path.exists():
            continue
        data = read(path)
        if isinstance(data, dict):
            converted = [{"TracingNo": x["tracing_no"], "Title": x["title"],
                     "PublishDateTime": x.get("publish_datetime"), "Url": x.get("url", ""), "Symbol": data.get("symbol")}
                    for x in data.get("letters", [])]
            if converted:
                return converted
            continue
        if data and not any("__error__" in x for x in data):
            return data
    if not fetch:
        return []
    url = F.SEARCH + "?" + urllib.parse.urlencode({"Symbol": symbol, "LetterType": 6, "PageNumber": 1, "PageSize": 100})
    data = json.loads(download(url, delay)).get("Letters", [])
    write(fresh, data)
    return data


def select(letters, cutoff):
    selected = {}
    for letter in letters:
        title = P.norm(letter.get("Title", ""))
        # Codal lists subsidiary reports under the parent's stock symbol too.
        # Explicit named-company qualifiers are a different reporting entity.
        if re.search(r'\(\s*شرکت\b', title):
            continue
        if not any(x in title for x in F.FS_MARK):
            continue
        pub = parse_persian_datetime(letter.get("PublishDateTime"))
        period = F.jalali_date_in(title)
        if pub is None or pub > cutoff or period is None or period > cutoff.date():
            continue
        kind = F.classify_letter(letter)
        if kind not in ("annual", "annual_audited", "interim"):
            continue
        # Latest revision wins for this actual period; no inherited publication.
        prev = selected.get(period)
        if prev is None or pub > prev[0]:
            selected[period] = (pub, letter)
    return sorted(selected.items(), reverse=True)


def report_html(symbol, letter, fetch, delay):
    tracing = str(letter["TracingNo"])
    path = OUT / "raw" / f"{symbol}_{tracing}.html"
    for candidate in [path, LEGACY / path.name]:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8"), str(candidate)
    if not fetch:
        return None, "not_cached"
    url = letter.get("ExcelUrl")
    if not url:
        serial = urllib.parse.parse_qs(urllib.parse.urlsplit(letter.get("Url", "")).query).get("LetterSerial", [None])[0]
        if not serial:
            return None, "no_excel_serial"
        url = "https://excel.codal.ir/service/Excel/GetAll/" + urllib.parse.quote(serial, safe="") + "/0"
    html = download(url, delay)
    if "<table" not in html.lower():
        return None, "no_statement_tables"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8", newline="")
    return html, url


def verified_facts(html, period, pub, letter, source, annual_periods):
    import jdatetime
    parsed = P.parse_report(html, parent_only=True)
    balance = parsed["statements"].get("balance_sheet", {})
    totals = [balance.get(metric, {}).get(1) for metric in ("total_assets", "total_liabilities", "total_equity")]
    if all(value is not None for value in totals):
        assets, liabilities, equity = totals
        if abs(assets - liabilities - equity) > max(2.0, abs(assets) * 1e-6):
            # Reject an inconsistent statement rather than manufacturing ROE/PB.
            parsed["statements"].pop("balance_sheet")
    current = jdatetime.date.fromgregorian(date=period)
    current_j = (current.year, current.month, current.day)
    facts = []
    observed_at = dt.datetime.now(dt.timezone.utc).isoformat()
    for stype, metrics in parsed["statements"].items():
        headers = [tuple(x) for x in parsed["period_headers"][stype]]
        if not headers or headers[0] != current_j:
            continue
        for metric, values in metrics.items():
            for order, value in values.items():
                if not math.isfinite(value):
                    continue
                # Flow comparative must represent the SAME interim window.
                # The annual third column must lie between prior-same/current.
                if stype != "balance_sheet" and order == 2:
                    prior = headers[1]
                    if prior[:2] != (current.year - 1, current.month) or abs(prior[2] - current.day) > 1:
                        continue
                if order == 3:
                    if stype == "balance_sheet" or len(headers) < 3 or not (headers[1] < headers[2] < headers[0]):
                        continue
                    annual_date = jdatetime.date(*headers[2]).togregorian()
                    if annual_date not in annual_periods:
                        continue
                facts.append({"statement_type": stype, "metric_code": metric,
                              "period_end_date": period.isoformat(), "period_order": order,
                              "value": value, "published_at": pub.isoformat(),
                              "collected_at": observed_at,
                              "tracing_no": str(letter["TracingNo"]), "basis": "parent",
                              "unit": "rial_per_share" if metric in P.PER_SHARE else "million_rial",
                              "source": source, "sha256": hashlib.sha256(html.encode()).hexdigest()})
    return facts


def merge_verified_cache(previous_cache, facts):
    merged = {(f['tracing_no'], f['statement_type'], f['metric_code'], f['period_order'], f['period_end_date']): f
              for f in previous_cache.get('facts', []) if previous_cache.get('rules_version') == 3}
    for f in facts:
        key = (f['tracing_no'], f['statement_type'], f['metric_code'], f['period_order'], f['period_end_date'])
        old = merged.get(key)
        # Re-parsing identical saved evidence does not invent a later first-seen time.
        merged[key] = old if old and old.get('sha256') == f.get('sha256') and old['value'] == f['value'] else f
    return list(merged.values())


def collect(args):
    q = read(ANA / "output" / "v2_q_observed_report.json")
    v = read(ANA / "output" / "v2_value_pilot.json")["v_observed_report"]["companies"]
    t = read(ANA / "output" / "v2_t_pilot.json")["t_observed_report"]["companies"]
    cutoff = dt.datetime.fromisoformat(read(ANA / "output" / "v2_value_pilot.json")["cutoff"])
    if args.remaining or args.partial:
        active = Path(read(OUT / 'result.json')['bundle_path'])
        q = read(active / 'v2_q_observed_report.json')
        v = read(active / 'v2_value_pilot.json')['v_observed_report']['companies']
        t = read(active / 'v2_t_pilot.json')['t_observed_report']['companies']
    if args.current:
        cutoff = dt.datetime.now(dt.timezone.utc)
    targets = [(cid, r) for cid, r in q["companies"].items()
               if r.get("model_family") == "general" and
               (not (r.get("pilot_eligible") and v.get(cid, {}).get("pilot_eligible")) or
                (args.partial and any(not f.get('included') and f.get('implementation') == 'implemented'
                                      and f.get('in_aggregation_scope') for f in r.get('factors', {}).values())))]
    if args.symbol:
        targets = [(cid, r) for cid, r in targets if r.get('symbol') == args.symbol]
    targets.sort(key=lambda x: (not bool(t.get(x[0], {}).get("pilot_eligible")), x[1].get("symbol", "")))
    results = []
    attempted = 0
    for cid, record in targets:
        symbol = record.get("symbol")
        cache = OUT / "facts" / f"{cid}.json"
        previous_cache = read(cache) if cache.exists() else {}
        if args.fetch and not args.refresh_catalog and cache.exists():
            cached = read(cache)
            if (cached.get("facts") and cached.get("rules_version") == 3
                    and all(f.get("collected_at") for f in cached["facts"])):
                results.append({"symbol": symbol, "state": "cached"})
                continue
        if attempted >= args.limit:
            break
        attempted += 1
        facts, errors = [], []
        try:
            letters = letters_for(symbol, args.fetch, args.delay, args.refresh_catalog)
            letters = [letter for letter in letters
                       if not letter.get("Symbol") or P.norm_title(letter["Symbol"]) == P.norm_title(symbol)]
            selected = select(letters, cutoff)
            annual_periods = {period for period, (_, letter) in selected
                              if F.classify_letter(letter) in ("annual", "annual_audited")}
            for period, (pub, letter) in selected[:args.reports]:
                try:
                    html, source = report_html(symbol, letter, args.fetch, args.delay)
                    if html:
                        facts.extend(verified_facts(html, period, pub, letter, source, annual_periods))
                    else:
                        errors.append(source)
                except CollectionPaused:
                    raise
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
        except CollectionPaused as exc:
            facts = merge_verified_cache(previous_cache, facts)
            write(cache, {"rules_version": 3, "company_id": cid, "symbol": symbol, "facts": facts, "errors": errors + [str(exc)]})
            results.append({"symbol": symbol, "state": "paused", "reason": str(exc)})
            print(str(exc), flush=True)
            break
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        # A missing report or temporary source failure must not erase proven facts.
        facts = merge_verified_cache(previous_cache, facts)
        write(cache, {"rules_version": 3, "company_id": cid, "symbol": symbol, "catalog_cutoff": cutoff,
                      "catalog_refreshed": args.refresh_catalog, "facts": facts, "errors": errors})
        results.append({"symbol": symbol, "facts": len(facts), "errors": errors})
        print(f"{symbol}: {len(facts)} verified facts; {len(errors)} unavailable reports", flush=True)
    write(OUT / "collection_status.json", {"cutoff": cutoff, "targets": len(targets), "attempted": attempted, "results": results})


def mark_unattributed_legacy_reports(engine):
    import compute_metrics as CM
    with CM.pg_pilot_conn() as db:
        rows = db.execute("SELECT id::text FROM ingestion.reports WHERE source='legacy_sqlserver' AND title IS NULL AND published_at IS NULL").fetchall()
    engine.verified_legacy_report_ids = {row[0] for row in rows}


def eligible_cache_facts(rec, asof, cutoff):
    valid = []
    for f in rec.get('facts', []):
        if not f.get('collected_at'):
            raise RuntimeError('cache lacks actual collection time')
        if (f['basis'] == 'parent' and dt.date.fromisoformat(f['period_end_date']) <= asof and
                dt.datetime.fromisoformat(f['published_at']) <= cutoff and dt.datetime.fromisoformat(f['collected_at']) <= cutoff):
            valid.append(f)
    latest = {}
    for f in valid:
        key = (dt.datetime.fromisoformat(f['published_at']), f['tracing_no'])
        latest[f['period_end_date']] = max(key, latest.get(f['period_end_date'], key))
    return [f for f in valid if (dt.datetime.fromisoformat(f['published_at']), f['tracing_no']) == latest[f['period_end_date']]]


def overlay_financial_facts(engine, asof, cutoff):
    """Attach proven facts in memory, bounded by publication AND collection."""
    existing = {(x['company_id'], x['period_end_date'], x['metric_code']) for x in engine.stmt if x['report_id'] not in engine.superseded}
    accepted, skipped = 0, 0
    recovered_columns = []
    indexed = {}
    for row in engine.stmt:
        if row['report_id'] not in engine.superseded:
            indexed.setdefault((row['company_id'], row['period_end_date'], row['metric_code']), []).append(row)
    caches = [read(cache) for cache in sorted((OUT / 'facts').glob('*.json'))]
    caches = [rec for rec in caches if rec.get('rules_version') == 3]
    for rec in caches:
        rec['facts'] = eligible_cache_facts(rec, asof, cutoff)
    legacy_ids = getattr(engine, 'verified_legacy_report_ids', set())
    replacements = {}
    for rec in caches:
        for f in rec['facts']:
            key = (rec['company_id'], dt.date.fromisoformat(f['period_end_date']), f['metric_code'])
            rows = indexed.get(key, [])
            if f['period_order'] == 1 and rows and all(r['report_id'] in legacy_ids for r in rows):
                replacements[key] = {'company_id': rec['company_id'], 'metric': f['metric_code'],
                    'period': f['period_end_date'], 'source': f['source'], 'sha256': f['sha256'],
                    'tracing_no': f['tracing_no'], 'old_values': {str(r['period_order']): str(r['canonical_value']) for r in rows},
                    'old_report_ids': sorted({r['report_id'] for r in rows})}
    if replacements:
        engine.stmt = [r for r in engine.stmt if not (r['report_id'] in legacy_ids and
            (r['company_id'], r['period_end_date'], r['metric_code']) in replacements)]
        existing.difference_update(replacements)
        for key in replacements:
            indexed.pop(key, None)
    engine.verified_legacy_replacements = list(replacements.values())
    for rec in caches:
        cid = rec['company_id']
        for f in rec['facts']:
            if not f.get('collected_at'):
                raise RuntimeError('cache lacks actual collection time')
            period = dt.date.fromisoformat(f['period_end_date'])
            pub = dt.datetime.fromisoformat(f['published_at'])
            observed = dt.datetime.fromisoformat(f['collected_at'])
            if pub > cutoff or observed > cutoff or period > asof or f['basis'] != 'parent':
                continue
            if (cid, period, f['metric_code']) in existing:
                rows = indexed.get((cid, period, f['metric_code']), [])
                version = max((r['version_no'] for r in rows), default=1)
                current = {r['period_order']: r['canonical_value'] for r in rows if r['version_no'] == version}
                source = {g['period_order']: g['value'] * 1_000_000 for g in rec['facts']
                          if g['tracing_no'] == f['tracing_no'] and g['metric_code'] == f['metric_code']
                          and g['period_end_date'] == f['period_end_date'] and g['unit'] == 'million_rial'}
                # Only a missing annual expense leg can be completed. Both
                # observed comparative anchors must match the same verified
                # parent report exactly; existing amounts are never replaced.
                fill = (f['metric_code'] in ('finance_cost', 'other_non_operating') and f['period_order'] == 3
                        and 3 not in current and all(current.get(order) is not None and order in source and
                        math.isclose(float(current[order]), source[order], rel_tol=1e-12, abs_tol=1.0)
                        for order in (1, 2)))
                if not fill:
                    skipped += 1
                    continue
                recovered_columns.append({'company_id': cid, 'metric': f['metric_code'], 'period': str(period),
                                          'tracing_no': f['tracing_no'], 'source': f['source'], 'sha256': f['sha256']})
            else:
                version = 1
            engine.stmt.append({'company_id': cid, 'statement_type': f['statement_type'],
                'period_end_date': period, 'fiscal_year': None, 'fiscal_month': None,
                'is_restated': False, 'version_no': version, 'collected_at': observed, 'published_at': pub,
                'metric_code': f['metric_code'], 'period_order': f['period_order'],
                'canonical_value': f['value'] * (1 if f['unit'] == 'rial_per_share' else 1_000_000),
                'canonical_unit': 'rial_per_share' if f['unit'] == 'rial_per_share' else 'rial',
                'report_id': f"verified-codal-{cid}-{f['tracing_no']}"})
            indexed.setdefault((cid, period, f['metric_code']), []).append(engine.stmt[-1])
            accepted += 1
    engine.verified_recovered_columns = recovered_columns
    return accepted, skipped, supplement_fiscal_titles(engine, cutoff)


def recompute(current=False, market=False):
    if market and not current:
        raise ValueError('fresh market collection requires a real current cutoff')
    previous = read(OUT / 'result.json') if (OUT / 'result.json').exists() else None
    previous_ids = set()
    if previous and Path(previous['bundle_path']).exists():
        previous_dir = Path(previous['bundle_path'])
        axes = [read(previous_dir / name) for name in ('v2_q_observed_report.json', 'v2_value_pilot.json', 'v2_t_pilot.json')]
        populations = [axes[0]['companies'], axes[1]['v_observed_report']['companies'], axes[2]['t_observed_report']['companies']]
        previous_ids = set.intersection(*[{cid for cid, r in pop.items() if r.get('pilot_eligible')} for pop in populations])
    os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")
    import compute_metrics as CM
    import pilot_v2_qvt as PQ
    import pilot_v2_value as PV
    import pilot_v2_t as PT
    import expense_ttm_recovery as REC
    qofficial = read(ANA / "output" / "v2_q_observed_report.json")
    vofficial = read(ANA / "output" / "v2_value_pilot.json")
    tofficial = read(ANA / "output" / "v2_t_pilot.json")
    cutoff = dt.datetime.fromisoformat(vofficial["cutoff"])
    asof = dt.date.fromisoformat(vofficial["as_of"])
    if current:
        from zoneinfo import ZoneInfo
        cutoff = dt.datetime.now(dt.timezone.utc)
        asof = cutoff.astimezone(ZoneInfo("Asia/Tehran")).date()
    engine = CM.Engine(asof, cutoff)
    print("Loading canonical metrics (read-only)...", flush=True)
    engine.load()
    engine.load = lambda *a, **k: None
    mark_unattributed_legacy_reports(engine)
    accepted, skipped, fiscal_metadata = overlay_financial_facts(engine, asof, cutoff)
    # The statement snapshot is now immutable. Diagnostics repeatedly request
    # its index; reuse that exact index instead of rebuilding it per company.
    report_index = engine.report_index()
    engine.report_index = lambda: report_index
    print(f"Loaded verified caches; accepted {accepted} facts; {len(fiscal_metadata['calendar_from_verified_parent_reports'])} verified parent calendars. Computing Q/V...", flush=True)
    durations, _ = PQ.fiscal_calendar_for(engine)
    recovery = REC.recover_expense_order3(engine.report_index(), durations, asof, cutoff)
    q = PQ.run_pilot(asof, cutoff, sample_limit=10, engine=engine, expense_recovery=recovery)["q_observed"]
    # Q computed this exact in-memory dataset. Reuse its metrics for V instead
    # of running the entire metric engine a second time.
    computed_metrics = engine.metrics
    engine.compute = lambda: computed_metrics
    def eligible(companies):
        return {cid for cid, x in companies.items() if x.get("pilot_eligible")}
    v = PV.run_value_pilot(asof, cutoff, engine=engine, q_eligible=eligible(q["companies"]))
    valuation_market_date = max((x['trade_date'] for x in engine.prices if x['trade_date'] <= asof), default=None)
    market_completion = None
    if market:
        # Vendor daily bar close and the exchange's weighted closing price are
        # distinct. Only timing consumes the new adjusted bar history. V keeps
        # its canonical closing-price contract and exposes its actual date.
        import complete_market_coverage as MC
        market_completion = MC.overlay(engine)
        print(f"Timing history overlay: {market_completion['companies']} identities, {market_completion['rows']} bars", flush=True)
    proof_raw, reopening_proofs = None, {}
    if current and market:
        from verified_reopenings import collect_proofs, timing_with_proofs
        reopening_proofs = collect_proofs(engine)
        with timing_with_proofs(engine, PT, reopening_proofs) as proof_state:
            t = PT.run_t_pilot(asof, cutoff, engine=engine, q_eligible=eligible(q['companies']),
                              v_eligible=eligible(v['v_observed_report']['companies']))
        proof_raw = proof_state['raw']
        t['aligned_window_policy'] = {'version': 'identical_observed_start_end_v1', 'factors': proof_state['aligned_window_policy']}
        t['construction']['return_window_alignment'] = t['aligned_window_policy']
        t['verified_reopening_policy'] = {'version': 'official_reference_corroboration_v1',
            'verified_security_count': len(reopening_proofs),
            'proofs': [r for security in reopening_proofs.values() for r in security.values()],
            'unproven_gaps': 'original jump guard remains active',
            'trading_risk': 'realized reopening repricing remains a warning'}
    else:
        t = (PT.run_t_pilot(asof, cutoff, engine=engine, q_eligible=eligible(q["companies"]),
                           v_eligible=eligible(v["v_observed_report"]["companies"])) if current else tofficial)
    if current:
        # Preserve the exact refusal evidence instead of reducing everything
        # to a generic missing-data message in the product.
        import score_v2_t_raw as TR
        histories, _ = PT.build_histories(engine, asof)
        raw = proof_raw if proof_raw is not None else TR.build_t_raw(histories, {cid: m.get('security_id') for cid, m in engine.metrics.items()},
                                                                   q['companies'], as_of=asof)
        for cid, rec in t['t_observed_report']['companies'].items():
            for fid, factor in rec.get('factors', {}).items():
                evidence = raw.get(cid, {}).get(fid, {})
                factor['validation_reason'] = evidence.get('validation_reason')
                factor['market_evidence'] = evidence.get('market')
                if evidence.get('reopening_evidence'):
                    factor['reopening_evidence'] = evidence['reopening_evidence']
    if market_completion:
        t['market_completion'] = market_completion
        t['construction']['price_basis'] = 'BRS Candlestick type=3 adjusted daily bar close; observed canonical turnover retained on matching dates'
        t['engine_cross_check'] = {'status': 'not_comparable_new_source',
                                   'note': 'Canonical engine metrics use exchange closing-price observations; timing uses newly acquired vendor adjusted bar closes. Equality is not asserted.'}
    ts = eligible(t["t_observed_report"]["companies"])
    before = eligible(qofficial["companies"]) & eligible(vofficial["v_observed_report"]["companies"]) & eligible(tofficial["t_observed_report"]["companies"])
    after = eligible(q["companies"]) & eligible(v["v_observed_report"]["companies"]) & ts
    if not current and before - after:
        raise RuntimeError("coverage regression; bundle was not published")
    market_date = max((x["trade_date"] for x in engine.prices if x["trade_date"] <= asof), default=None)
    q["data_dates"] = {"market_data_as_of": str(valuation_market_date) if valuation_market_date else None,
                       "timing_market_data_as_of": str(market_date) if market_date else None,
                       "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                       "supplemental_catalog_cutoff": vofficial["cutoff"]}
    catalogs = [read(path).get('catalog_cutoff', vofficial['cutoff']) for path in (OUT / 'facts').glob('*.json')]
    if catalogs:
        q['data_dates']['supplemental_catalog_cutoff'] = max(catalogs, key=dt.datetime.fromisoformat)
        q['data_dates']['supplemental_catalog_cutoff_oldest'] = min(catalogs, key=dt.datetime.fromisoformat)
    if current:
        for document in (q, v, t):
            document["as_of_timezone"] = "Asia/Tehran"
    bundle = OUT / "bundles" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write(bundle / "v2_q_observed_report.json", q)
    v["q_axis_artifact"] = {"path": str(bundle / "v2_q_observed_report.json"), "as_of": q["as_of"],
                            "n_pilot_eligible": len(eligible(q["companies"])), "stage": q["stage"]}
    write(bundle / "v2_value_pilot.json", v)
    if current:
        write(bundle / "v2_t_pilot.json", t)
    else:
        shutil.copyfile(ANA / "output" / "v2_t_pilot.json", bundle / "v2_t_pilot.json")
    result = {"as_of": asof, "cutoff": cutoff, "baseline": len(before), "expanded": len(after),
              "previous_bundle": previous['bundle_path'] if previous else None,
              "previous_expanded": len(previous_ids),
              "new_since_previous": [q['companies'][cid]['symbol'] for cid in sorted(after - previous_ids)],
              "ineligible_since_previous": [q['companies'][cid]['symbol'] for cid in sorted(previous_ids - after)],
              "gained": [q["companies"][cid]["symbol"] for cid in sorted(after - before)],
              "previously_ranked_now_ineligible": [qofficial["companies"][cid]["symbol"] for cid in sorted(before - after)],
              "baseline_as_of": vofficial["as_of"], "current_snapshot": current,
              "data_dates": q["data_dates"],
              "accepted_facts": accepted, "existing_facts_preserved": skipped,
              "basis": "parent", "publication_required": True, "database_writes": 0, "bundle_path": str(bundle),
              "fiscal_metadata": fiscal_metadata,
              "recovered_expense_columns": engine.verified_recovered_columns,
              "legacy_groups_replaced_from_verified_reports": engine.verified_legacy_replacements,
              "q_eligible": len(eligible(q["companies"])), "v_eligible": len(eligible(v["v_observed_report"]["companies"]))}
    if market_completion:
        result['market_completion'] = {k: v for k, v in market_completion.items() if k != 'sources'}
    write(OUT / "result.json", result)
    write(bundle / "coverage_manifest.json", {**result, "t_reused_from": None if current else str(ANA / "output" / "v2_t_pilot.json"),
          "files": {name: hashlib.sha256((bundle / name).read_bytes()).hexdigest()
                    for name in ("v2_q_observed_report.json", "v2_value_pilot.json", "v2_t_pilot.json")}})
    print(json.dumps({k: result[k] for k in ('as_of','cutoff','expanded','previous_expanded','q_eligible','v_eligible','bundle_path')}, ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["collect", "recompute"])
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--limit", type=int, default=16)
    parser.add_argument("--delay", type=float, default=2)
    parser.add_argument("--current", action="store_true", help="recompute all three axes at the real current cutoff")
    parser.add_argument('--remaining', action='store_true', help='target active Q/V gaps instead of original gaps')
    parser.add_argument('--partial', action='store_true', help='also collect missing implemented factors of already eligible companies')
    parser.add_argument('--symbol', help='limit collection to one exact symbol')
    parser.add_argument('--refresh-catalog', action='store_true', help='request current Codal catalogs (requires --fetch)')
    parser.add_argument('--reports', type=int, default=5)
    parser.add_argument('--market', action='store_true', help='use verified BRS bar history for T; preserve canonical V closing-price basis')
    args = parser.parse_args()
    collect(args) if args.mode == "collect" else recompute(args.current, args.market)
