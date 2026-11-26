"""Bounded, resumable public-source acquisition for a separate FactorMix run."""
import argparse
from datetime import datetime, timezone
import json
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
import urllib.request

from factormix.refresh_ranking import ROOT, publish, ranking_identities
from ranking_research.future_eval_v12_30.http_retry import ReadOnlyRateLimitedError, _retry_after
from runtime_lock import acquire_file_lock, release_file_lock


class Budget:
    def __init__(self, attempts, seconds):
        self.limit = attempts
        self.deadline = time.monotonic() + seconds
        self.attempts = []
        self.cooldown = {}
        self.opener = urllib.request.build_opener(NoRedirect())

    def __call__(self, request, timeout=35):
        url = urlsplit(request.full_url)
        if (request.get_method() != 'GET' or url.scheme != 'https' or url.hostname not in {
                'cdn.tsetmc.com', 'service.tsetmc.com', 'search.codal.ir', 'www.codal.ir', 'codal.ir', 'excel.codal.ir'}):
            raise ValueError('public GET only')
        host = url.hostname
        family = 'codal' if 'codal.ir' in host else host
        for attempt in (1, 2):
            if family in self.cooldown:
                delay, retry_at = self.cooldown[family]
                raise ReadOnlyRateLimitedError(attempts=0, retry_after_seconds=delay, retry_at_utc=retry_at)
            remaining = self.deadline - time.monotonic()
            if remaining < 1 or len(self.attempts) >= self.limit:
                raise RuntimeError('public_capture_budget_exhausted')
            item = dict(host=host, path=url.path, started_at_utc=datetime.now(timezone.utc).isoformat())
            self.attempts.append(item)
            try:
                response = self.opener.open(request, timeout=min(timeout, remaining, 8))
                item['status'] = response.status
                return response, attempt, float(attempt - 1)
            except HTTPError as exc:
                item['status'] = exc.code
                if exc.code == 429:
                    delay, retry_at = _retry_after(exc)
                    self.cooldown[family] = delay, retry_at
                    exc.close()
                    raise ReadOnlyRateLimitedError(attempts=attempt, retry_after_seconds=delay, retry_at_utc=retry_at) from None
                if exc.code not in (502, 503, 504) or attempt == 2:
                    raise
                exc.close()
                time.sleep(1)
            except OSError as exc:
                item['error'] = type(exc).__name__
                raise


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def collect(out, source, attempts, seconds, from_jalali):
    out.mkdir(parents=True, exist_ok=True)
    audit = out / ('attempts-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    budget = Budget(attempts, seconds)
    old_argv = sys.argv
    with (out / '.capture.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        acquire_file_lock(lock)
        try:
            for earlier in out.glob('attempts-*.json'):
                doc = json.loads(earlier.read_text(encoding='utf8'))
                for family, (_, retry_at) in doc.get('cooldown', {}).items():
                    if datetime.fromisoformat(retry_at) > datetime.now(timezone.utc):
                        budget.cooldown[family] = (None, retry_at)
            return run_collector(out, source, budget, seconds, from_jalali)
        finally:
            sys.argv = old_argv
            publish(audit, dict(source=source, limit=attempts, seconds=seconds, attempts=budget.attempts,
                                cooldown=budget.cooldown))
            release_file_lock(lock)


def run_collector(out, source, budget, seconds, from_jalali):
    from ranking_research.future_eval_v12_30 import acquire_codal_incremental as codal
    from ranking_research.future_eval_v12_30 import acquire_official_tsetmc_v12_35 as market
    from ranking_research.future_eval_v12_30 import acquire_public_market_calendar as calendar

    if source == 'market':
        market.open_readonly = budget
        sys.argv = [source, '--output-dir', str(out / 'market'), '--with-adjustments']
        market.main()
        manifest = out / 'market/manifest.json'
        archive = manifest.with_name(datetime.now(timezone.utc).strftime('manifest.%Y%m%dT%H%M%S%fZ.json'))
        with archive.open('xb') as handle:
            handle.write(manifest.read_bytes())
        return 0
    if source == 'codal':
        codal.OUT = out / 'codal'
        codal.open_readonly = budget
        run = 'paper-cycle-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        sys.argv = [source, run, '--evidence-from-jalali', from_jalali,
                    '--feed-budget-seconds', str(max(1, seconds // 2))]
        return codal.main()
    identities, _ = ranking_identities()
    symbol = 'فولاد'
    identity = identities[symbol]
    policy = calendar.make_policy(market='TSE', window_start=datetime.now(calendar.TEHRAN).strftime('%Y%m%d'),
                                  indices=calendar.TSE_INDEX_PROFILES)
    candidate = dict(symbol=symbol, ins_code=str(identity['ins_code']))
    now = datetime.now(timezone.utc)
    result = calendar.collect_live(policy=policy, candidate=candidate, out_dir=out / 'calendar', now_utc=now, opener=budget)
    evaluated = calendar.evaluate_public_calendar(policy=policy, sources=result['sources'], now_utc=datetime.now(timezone.utc))
    doc = calendar.build_manifest(policy=policy, sources=result['sources'], evaluation=evaluated,
                                  run_id=result['run_id'], mode='live', now_utc=now, candidate=candidate,
                                  stock_cross_meta=None)
    path, _ = calendar.write_manifest_files(doc, out / 'calendar', result['run_id'])
    print(json.dumps({'calendar_manifest': str(path.relative_to(ROOT)), 'status': doc['quality']}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('source', choices=('market', 'codal', 'calendar'))
    parser.add_argument('--attempts', type=int, required=True)
    parser.add_argument('--seconds', type=int, required=True)
    parser.add_argument('--from-jalali')
    args = parser.parse_args()
    if (not args.run.isascii() or not args.run.replace('-', '').isalnum()
            or min(args.attempts, args.seconds) <= 0 or args.source == 'codal' and not args.from_jalali):
        parser.error('run must be alphanumeric with optional hyphens, budgets positive, and Codal needs --from-jalali')
    return collect(ROOT / '.runtime/factormix-source-evidence' / args.run, args.source,
                   args.attempts, args.seconds, args.from_jalali)


if __name__ == '__main__':
    raise SystemExit(main())
