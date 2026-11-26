"""Controlled Codal/TSETMC payloads in the production receipt formats."""
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace
import gzip
import json

import jdatetime
import numpy as np
import pandas as pd

from factormix.ranking_evidence import EvidenceFiles, TEHRAN, ranking_input_evidence
from ranking_research.future_eval_v12_30.prepare_codal_inputs import parse_financial, parse_sales
from factormix.refresh_ranking import load_replay
from ranking_research.v2_inputs import H
import codal_feed


def _jdate(day):
    return jdatetime.date.fromgregorian(date=day).strftime('%Y/%m/%d')


def _at(day, hour):
    return datetime.combine(day, time(hour), TEHRAN).astimezone(timezone.utc).isoformat()


def _cell(row, column, value, *, header=False, period=None):
    return dict(rowSequence=row, columnSequence=column, value=str(value), isVisible=True,
                cellGroupName='Header' if header else 'Body', periodEndToDate=period)


def _financial(period, prior, scale):
    titles = {'income_statement': 'صورت سود و زیان', 'balance_sheet': 'صورت وضعیت مالی',
              'cash_flow': 'صورت جریان‌های نقدی'}
    tables = []
    for statement in sorted({k[0] for k in H.P.ROW_TITLES} & titles.keys()):
        cells = [_cell(1, 2, '', header=True, period=period), _cell(1, 3, '', header=True, period=prior)]
        for row, ((_, metric), label) in enumerate(
                ((key, name) for key, name in H.P.ROW_TITLES.items() if key[0] == statement), 3):
            factor = {'total_assets': 10, 'total_liabilities': 4, 'total_equity': 6}.get(metric, 1)
            value = 0 if metric == 'eps' else (scale + (6 if metric == 'revenue' else 0)) * factor
            cells += [_cell(row, 1, label), _cell(row, 2, value), _cell(row, 3, value * .8)]
        tables.append(dict(title_Fa=titles[statement], description='میلیون ریال', cells=cells))
    return tables


def _sales(period, value):
    return [dict(title_Fa='فعالیت ماهانه (ریال)', aliasName='ProductionAndSales',
                 cells=[_cell(1, 2, 'دوره یک ماهه مبلغ فروش', header=True, period=period),
                        _cell(3, 1, 'جمع'), _cell(3, 2, value)])]


def controlled_evidence(root, symbols, instrument_ids, as_of, *, fault=None):
    files = EvidenceFiles(root)
    as_of_day = as_of.astimezone(TEHRAN).date()
    lag = as_of_day - timedelta(days=90)
    # Use only dates supplied as completed by the controlled exchange response.
    dates = [as_of_day - timedelta(days=i) for i in range(1000, -1, -1)]
    grid = np.array([d.isoformat() for d in dates[-300:]])
    receipts = {factor: {'report_ids': [], 'raw_pages': []} for factor in ('financial', 'sales')}
    prepared = {'financial': [], 'sales': []}
    records, events, assets, rows, comparisons = [], [], [], [], []
    traces, prices, facts = {}, [], {}
    market = SimpleNamespace(data={}, sym2sid={}, events={})
    market.idx_at = lambda symbol, cutoff: int(np.searchsorted(grid, cutoff, side='right')) - 1
    market.asof_factors = lambda symbol, cutoff: np.ones(len(grid))

    def capture(name, value, received):
        payload = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode('utf8')
        (root / name).write_bytes(gzip.compress(payload))
        return dict(path=name, sha256=sha256(payload).hexdigest(), retrieved_at_utc=received, http_status=200)

    calendar = capture('sessions.json.gz', dict(IsSuccess=True, Data=[
        dict(DEven=d.strftime('%Y%m%d'), NSCEnd='1') for d in dates]), _at(as_of_day, 17))
    calendar = dict(source='TSETMC documented API MarketInfo/NSCStart', raw_path=calendar['path'],
                    raw_sha256=calendar['sha256'], retrieved_at_utc=calendar['retrieved_at_utc'], http_status=200)
    last = jdatetime.date.fromgregorian(date=as_of_day - timedelta(days=40))
    start_j = _jdate(dates[0])
    for j, (symbol, instrument_id) in enumerate(zip(symbols, instrument_ids, strict=True), 1):
        identity = dict(symbol=symbol, company_id=f'company-{j}', security_id=f'security-{j}', ins_code=instrument_id)
        assets.append(identity)
        close = [1000 + (i + 1) * j for i in range(len(grid))]
        bars = [dict(insCode=instrument_id, dEven=int(d.replace('-', '')), pClosing=p,
                     qTotCap=10000000, zTotTran=2, qTotTran5J=100, priceYesterday=close[max(i-1, 0)])
                for i, (d, p) in enumerate(zip(grid, close, strict=True))]
        if fault == 'future' and j == 1:
            bars.append(bars[-1] | {'dEven': int((as_of_day + timedelta(days=1)).strftime('%Y%m%d'))})
        daily = capture(f'{j}-daily.json.gz', dict(closingPriceDaily=bars), _at(as_of_day, 18))
        prices.append(identity | dict(sources={'daily': dict(raw_path=daily['path'], raw_sha256=daily['sha256'],
            retrieved_at_utc=daily['retrieved_at_utc'], http_status=200,
            url=f'https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{instrument_id}/0')}))
        adjust = capture(f'{j}-adjustment.json.gz', {'priceAdjust': []}, _at(as_of_day, 18))
        prices[-1]['sources']['adjustment'] = dict(raw_path=adjust['path'], raw_sha256=adjust['sha256'],
            retrieved_at_utc=adjust['retrieved_at_utc'], http_status=200,
            url=f'https://cdn.tsetmc.com/api/ClosingPrice/GetPriceAdjustList/{instrument_id}')
        traces[symbol] = dict(close=close, age=np.zeros(len(grid)), events=[])
        market.sym2sid[symbol] = identity['security_id']
        market.events[identity['security_id']] = []
        market.data[symbol] = dict(sid=identity['security_id'], dates=grid.tolist(), c=np.array(close),
                                   vol=np.full(len(grid), 100), tval=np.full(len(grid), 10000000))
        rows.append(dict(symbol=symbol, price_date=as_of_day.isoformat()))
        for factor, letter in (('financial', 6), ('sales', 58)):
            listing = []
            specs = []
            if factor == 'financial':
                end = as_of_day - timedelta(days=145)
                specs = [(100000+j*100+i, end.replace(year=end.year-i)) for i in (2, 1, 0)]
            else:
                for i in range(28):
                    yy, mm = divmod(last.year*12+last.month-1-i, 12)
                    next_y, next_m = divmod(yy*12+mm+1, 12)
                    end = jdatetime.date(next_y, next_m+1, 1).togregorian() - timedelta(days=1)
                    specs.append((200000+j*100+i, end))
            for i, (trace, period) in enumerate(specs):
                trace = str(trace)
                pub_day = period + timedelta(days=8)
                pub = _at(pub_day, 10)
                received = _at(pub_day, 11)
                period_j = _jdate(period)
                title = ('صورت‌های مالی دوره ۱۲ ماهه منتهی به ' if factor == 'financial' else 'گزارش فعالیت ماهانه منتهی به ') + period_j
                pub_j = _jdate(pub_day) + ' 10:00:00'
                url = f'https://www.codal.ir/Reports/Decision.aspx?let={letter}&id={trace}'
                listing.append(dict(TracingNo=trace, Symbol=symbol, Title=title, Url=url, PublishDateTime=pub_j))
                source = dict(company_id=identity['company_id'], symbol=symbol, tracing_no=trace,
                              title=title, published_at=pub, url=url, financial_pages_complete=True)
                tables = (_financial(period_j, _jdate(period.replace(year=period.year-1)), 100 + j*10+i)
                          if factor == 'financial' else _sales(period_j, 100 + j*10-i))
                payload = dict(tracingNo=trace, periodEndToDate=period_j, publishDateTime=pub_j,
                               isConsolidated=False, sheets=[dict(tables=tables)])
                page = '<script>var datasource = ' + json.dumps(payload, ensure_ascii=False) + ';</script>'
                if fault == 'missing_sheet' and factor == 'financial' and j == 1 and i == 0:
                    page += '<select id="ddlTable"><option value="8">صورت وضعیت مالی</option></select>'
                body = page.encode('utf8')
                receipt = capture(f'{trace}.html.gz', body, received)
                if fault == 'missing' and factor == 'sales' and j == 1 and i == 5:
                    (root / receipt['path']).unlink()
                source['body_evidence'] = receipt
                if fault == 'incomplete' and factor == 'financial' and j == 1 and i == 0:
                    source['financial_pages_complete'] = False
                parsed = (parse_financial(body.decode(), source, identity, received, receipt['sha256'])
                          if factor == 'financial' else parse_sales(body.decode(), source, received, receipt['sha256']))
                prepared[factor].append(parsed)
                receipts[factor]['report_ids'].append(source)
                if factor == 'financial':
                    import dynamic_financial as dynamic
                    page = dynamic.parsed_page(body.decode(), parsed)
                    for statement, metrics in page['statements'].items():
                        for metric, orders in metrics.items():
                            unit = 'rial_per_share' if metric in H.P.PER_SHARE else 'rial'
                            header = page['period_headers'][statement][1]
                            comparative = jdatetime.date(*header).togregorian().isoformat()
                            comparisons.append(dict(company_id=identity['company_id'], tracing_no=trace,
                                statement_type=statement, metric_code=metric, period_order=2, canonical_unit=unit,
                                canonical_value=orders[2] * (1 if unit == 'rial_per_share' else 1_000_000),
                                source_page_path=receipt['path'], source_page_sha256=receipt['sha256'],
                                source_page_received_at_utc=received, comparative_period=comparative))
                    records.append(parsed)
                else:
                    events.append(dict(event_id=trace, symbol=symbol, company_id=identity['company_id'],
                        period_end=period.isoformat(), published_at=pub, signal_entry_date=(pub_day + timedelta(days=1)).isoformat(),
                        is_correction=False, current_value_version_known=True, CURRENT_PERIOD_SALES=parsed['sales_current_rial']))
            if fault in ('revision', 'unselected_revision') and factor == 'financial' and j == 1:
                orig = records[-1]
                correction_day = as_of_day + timedelta(days=1) if fault == 'revision' else as_of_day - timedelta(days=1)
                trace = '999999'
                correction = orig | dict(tracing_no=trace, published_at=_at(correction_day, 10),
                                         title='اصلاحیه ' + orig['title'])
                if fault == 'revision':
                    records.append(correction)  # A bad snapshot consumed the after-decision amendment.
                else:
                    listing.append(dict(TracingNo=trace, Symbol=symbol, Title=correction['title'],
                        Url=f'https://www.codal.ir/Reports/Decision.aspx?let=6&id={trace}',
                        PublishDateTime=_jdate(correction_day) + ' 10:00:00'))
            for number, offset in enumerate(range(0, len(listing), codal_feed.PAGE_SIZE), 1):
                name = f'{j}-{factor}-p{number}.json.gz'
                receipt = capture(name, dict(Total=len(listing), Page=number, IsAttacker=False,
                                             Letters=listing[offset:offset+codal_feed.PAGE_SIZE]), _at(as_of_day, 18))
                receipt['url'] = codal_feed._build_query(letter, number, from_date=start_j, symbol=symbol)
                receipts[factor]['raw_pages'].append(receipt)
    dates = [lag.isoformat(), as_of_day.isoformat()]
    replay = load_replay()
    panel, _ = replay.financial_snapshots(market, records, comparisons, pd.DataFrame(events),
                                          pd.DataFrame(assets), [], dates, evidence_trace=facts)
    snapshots = {d: g.set_index('symbol') for d, g in panel.groupby('decision_time')}
    if fault == 'revision':
        # A future correction in the source is ignored by the scorer.
        # Also verify that a supplied snapshot claiming it was used is rejected.
        panel = snapshots[dates[-1]]
        selected = json.loads(panel.at[symbols[0], 'sources'])
        selected.append({k: correction[k] for k in ('tracing_no', 'period_end', 'published_at')})
        panel.at[symbols[0], 'sources'] = json.dumps(selected)
    inputs = dict(rows=rows, market_manifest={'records': prices}, codal_manifest={'feeds': receipts}, prepared=prepared,
                  admission={}, snapshots=snapshots, files=files, as_of=as_of,
                  identities={r['symbol']: r for r in assets}, score_calendar=grid, records=records, events=events,
                  calendar_manifest=calendar, market_trace=traces, financial_trace=facts)
    evidence = ranking_input_evidence(**inputs)
    return evidence, files, inputs
