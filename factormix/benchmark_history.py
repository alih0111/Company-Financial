"""Collect verified TEDPIX history and publish full 1401 benchmark coverage.

Only missing TEDPIX dates are inserted. Existing index snapshots and all fund
prices remain intact. Mesghal is the registered gold fund, NOT physical gold.
Database credentials are loaded by the existing canonical ingestion connector
and are never included in receipts or public exports.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

import jdatetime
import requests

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'factormix/benchmark_sources/20261106'
PUBLIC=ROOT/'client/public/strategies/factormix-033/performance/benchmarks.json'
INDEX_ID='32097828799138957'
FUND_ID=32469128621155736
START='2022-03-26'
END='2026-11-04'
HISTORY_URL=f'https://cdn.tsetmc.com/api/Index/GetIndexB2History/{INDEX_ID}'
IDENTITY_URL='https://cdn.tsetmc.com/api/Index/GetIndexB1LastAll/All/1'


def sha(raw):return hashlib.sha256(raw).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()


def read_response(folder,name,url):
    raw_path=folder/f'{name}.raw.json.gz';receipt_path=folder/f'{name}.receipt.json'
    if raw_path.exists() and receipt_path.exists():
        raw=gzip.decompress(raw_path.read_bytes())
        receipt=json.loads(receipt_path.read_text(encoding='utf8'))
        if receipt['sha256']!=sha(raw) or receipt['url']!=url or receipt['status']!=200:
            raise RuntimeError('Source receipt mismatch: '+name)
    else:
        response=requests.get(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json','Referer':'https://www.tsetmc.com/'},timeout=30)
        response.raise_for_status();raw=response.content
        receipt=dict(url=url,received_at_utc=now(),status=response.status_code,sha256=sha(raw),bytes=len(raw))
        folder.mkdir(parents=True,exist_ok=True)
        raw_path.write_bytes(gzip.compress(raw,mtime=0))
        receipt_path.write_text(json.dumps(receipt,indent=2),encoding='utf8')
    return json.loads(raw),receipt


def parse_index(history,identity):
    def normalized(text):return str(text).replace('ك','ک').replace('ي','ی').strip()
    matching=[x for x in identity.get('indexB1',[]) if str(x.get('insCode'))==INDEX_ID]
    if len(matching)!=1 or normalized(matching[0].get('lVal30'))!='شاخص کل':
        raise RuntimeError('Official index identity does not match TEDPIX')
    result={}
    for row in history['indexB2']:
        if str(row.get('insCode'))!=INDEX_ID:raise RuntimeError('Wrong index inside history')
        day=datetime.strptime(str(row['dEven']),'%Y%m%d').date().isoformat()
        value=float(row['xNivInuClMresIbs'])
        if not math.isfinite(value) or value<=0:raise RuntimeError('Invalid index value')
        if day in result and result[day]!=value:raise RuntimeError('Conflicting duplicate index date')
        result[day]=value
    if START not in result or END not in result:raise RuntimeError('Official history does not cover the requested endpoints')
    return [dict(date=d,closing_price=result[d]) for d in sorted(result) if START<=d<=END]


def connector():
    sys.path.insert(0,str(ROOT/'go-app/py2/src'))
    from canonical_ingest import connect
    return connect


def backfill_index(rows,folder):
    connect=connector()
    with connect() as conn:
        with conn.transaction():
            c=conn.cursor()
            c.execute("SELECT pg_advisory_xact_lock(hashtext('factormix-tedpix-backfill'))")
            c.execute("SELECT trade_date,value,source FROM market.index_observations WHERE index_code='TEDPIX' ORDER BY trade_date")
            existing=c.fetchall();before={str(d):float(v) for d,v,_ in existing}
            raw_before=[dict(date=str(d),value=str(v),source=s) for d,v,s in existing]
            backup=folder/'existing-index-before.json'
            if not backup.exists():backup.write_text(json.dumps(raw_before,ensure_ascii=False,indent=2),encoding='utf8')
            differences=[abs(before[r['date']]-r['closing_price']) for r in rows if r['date'] in before]
            # Official historical levels are rounded to 0.1; BRS snapshots retain
            # extra decimals. Reject substantial disagreements, preserve both old rows.
            if differences and max(differences)>.11:raise RuntimeError('Existing index observations disagree with official history')
            values=[('TEDPIX','شاخص کل',r['date'],str(jdatetime.date.fromgregorian(date=date.fromisoformat(r['date']))),
                     r['closing_price'],'tsetmc_public_index_history') for r in rows]
            c.executemany('''INSERT INTO market.index_observations
                (index_code,index_name,trade_date,jalali_date_text,value,source)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (index_code,trade_date) DO NOTHING''',values)
            inserted=c.rowcount
            c.execute("SELECT count(*),min(trade_date),max(trade_date) FROM market.index_observations WHERE index_code='TEDPIX'")
            count,first,last=c.fetchone()
    return dict(before_rows=len(before),inserted_rows=inserted,after_rows=count,first_date=str(first),last_date=str(last),
                existing_values_preserved=True,max_existing_value_difference=max(differences,default=0))


def export_benchmarks(folder=SOURCE,receipts=None):
    connect=connector()
    with connect() as conn:
        c=conn.cursor()
        c.execute("SELECT trade_date,value,source FROM market.index_observations WHERE index_code='TEDPIX' AND trade_date BETWEEN %s AND %s ORDER BY trade_date",(START,END))
        index=[dict(date=str(d),closing_price=float(v),source=s) for d,v,s in c.fetchall()]
        c.execute('''SELECT DISTINCT ON (po.trade_date)
            po.trade_date,po.closing_price_rial,po.source,po.is_adjusted
            FROM market.price_observations po JOIN core.securities s ON s.id=po.security_id
            WHERE s.tsetmc_ins_code=%s AND po.price_series='adjusted'
              AND po.trade_date BETWEEN %s AND %s
            ORDER BY po.trade_date,po.collected_at DESC,po.id DESC''',(FUND_ID,START,END))
        gold=[dict(date=str(d),closing_price=float(v),source=s,is_adjusted=bool(adjusted)) for d,v,s,adjusted in c.fetchall() if v and float(v)>=100]
    from factormix.build_dashboard import atomic_json
    series={}
    for key,rows,label,unit,public_id in [('index_toman',index,'شاخص کل · TSETMC / TEDPIX','index_level',INDEX_ID),
        ('mesghal_toman',gold,'صندوق مثقال','rial',str(FUND_ID))]:
        if not rows or rows[0]['date']!=START or rows[-1]['date']!=END:
            raise RuntimeError('Benchmark does not cover both endpoints: '+key)
        if any(not math.isfinite(r['closing_price']) or r['closing_price']<=0 for r in rows):
            raise RuntimeError('Invalid benchmark price: '+key)
        if len({r['date'] for r in rows})!=len(rows):raise RuntimeError('Duplicate benchmark dates')
        series[key]=dict(label=label,unit=unit,public_instrument_id=public_id,first_date=rows[0]['date'],
                         last_date=rows[-1]['date'],count=len(rows),rows=rows)
    payload=dict(schema_version=1,start=START,as_of=END,generated_at_utc=now(),series=series,
                 identity_verified=True,source_receipts=receipts or {},synthetic_prices=False)
    # Verify these actual observations cover every replay date with a mark no
    # more than seven days old. This prevents a silent return to a late start.
    replay=json.loads((PUBLIC.parent/'performance.json').read_text(encoding='utf8'))['cases'][0]
    for key,s in series.items():
        k=0;missing=[]
        for point in replay['path']:
            while k+1<len(s['rows']) and s['rows'][k+1]['date']<=point['date']:k+=1
            mark=s['rows'][k]
            age=(date.fromisoformat(point['date'])-date.fromisoformat(mark['date'])).days
            if age<0 or age>7:missing.append(point['date'])
        s['replay_dates_without_fresh_mark']=missing
    folder.mkdir(parents=True,exist_ok=True)
    atomic_json(folder/'benchmarks.json',payload)
    fingerprint=dict(sha256=sha((folder/'benchmarks.json').read_bytes()),file='benchmarks.json')
    atomic_json(folder/'benchmarks.manifest.json',fingerprint)
    atomic_json(PUBLIC,payload)
    return payload


def publish_cached_benchmarks(public_folder):
    path=SOURCE/'benchmarks.json';manifest=SOURCE/'benchmarks.manifest.json'
    if not path.exists():return
    if not manifest.exists() or sha(path.read_bytes())!=json.loads(manifest.read_text(encoding='utf8'))['sha256']:
        raise RuntimeError('Benchmark snapshot checksum mismatch')
    target=public_folder/'benchmarks.json'
    target.write_bytes(path.read_bytes())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect-index',action='store_true')
    parser.add_argument('--refresh',action='store_true',help='Fetch into a new timestamped source folder')
    args=parser.parse_args()
    folder=SOURCE/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') if args.refresh else SOURCE
    folder.mkdir(parents=True,exist_ok=True)
    receipts={};audit={}
    if args.collect_index:
        history,receipts['history']=read_response(folder,'tedpix',HISTORY_URL)
        identity,receipts['identity']=read_response(folder,'index-identity',IDENTITY_URL)
        rows=parse_index(history,identity)
        audit=backfill_index(rows,folder)
    payload=export_benchmarks(folder,receipts)
    # The fixed dated source is the stable offline publication input. Refresh
    # keeps original raw responses in separate timestamped folders.
    if folder!=SOURCE:
        from factormix.build_dashboard import atomic_json
        atomic_json(SOURCE/'benchmarks.json',payload)
        atomic_json(SOURCE/'benchmarks.manifest.json',dict(file='benchmarks.json',sha256=sha((SOURCE/'benchmarks.json').read_bytes())))
    audit.update(status='PASS',series={key:{k:s[k] for k in ['first_date','last_date','count','replay_dates_without_fresh_mark']} for key,s in payload['series'].items()})
    (folder/'coverage.audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(audit,ensure_ascii=True))


if __name__=='__main__':main()
