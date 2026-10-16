"""Canonical screen engine with the same verified financial adapter as QVT."""
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'canonical_postgres_v1_2_1/analytics_canonical_v1'))
os.environ.setdefault('CDF_PILOT_DB', 'company_financial_analytics_shadow_v121')
import compute_metrics as CM
import complete_ranking_coverage as C


def source_manifest():
    """Include fiscal catalogs as well as facts; no network access."""
    paths = set((C.OUT / 'facts').glob('*.json'))
    paths.update((C.OUT / 'letters').glob('*.json'))
    paths.update(C.LEGACY.glob('*_letters.json'))
    paths.update((ROOT / 'historical_codal_backfill/output/pub_backfill').glob('*_lt6.json'))
    paths.update([Path(__file__), Path(C.__file__), Path(CM.__file__),
                  ROOT / 'provenance_v1/verified_financial_inputs.py'])
    if not list((C.OUT / 'facts').glob('*.json')):
        raise RuntimeError('verified financial cache is absent')
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


class VerifiedScreenEngine(CM.Engine):
    def load(self):
        # compute() calls load(); never apply the overlay a second time.
        if getattr(self, '_verified_loaded', False):
            return
        before = source_manifest()
        super().load()
        C.mark_unattributed_legacy_reports(self)
        accepted, skipped, fiscal = C.overlay_financial_facts(self, self.as_of, self.cutoff)
        if source_manifest() != before:
            raise RuntimeError('financial source files changed during load')
        self.financial_input_evidence = {
            'adapter': 'verified-financial-inputs-v1', 'source_manifest': before,
            'source_digest': hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
            'accepted_facts': accepted, 'skipped_facts': skipped,
            'replacements': self.verified_legacy_replacements,
            'recovered_columns': self.verified_recovered_columns, 'fiscal_metadata': fiscal,
            'as_of': str(self.as_of), 'cutoff': self.cutoff.isoformat(),
            'weights_changed': False,
        }
        self._verified_loaded = True


def validate_metrics(actual, expected):
    """Publication requires exact equality with the reviewed controlled result."""
    public = {str(cid): {k: v for k, v in row.items()
                        if not k.startswith('_') or k in ('_ttm_prov', '_valuation_prov', '_fiscal_calendar')}
              for cid, row in actual.items()}
    public = json.loads(json.dumps(public, default=str, allow_nan=False))
    if public != expected:
        differing = [cid for cid in set(public) | set(expected) if public.get(cid) != expected.get(cid)]
        raise ValueError(f'controlled metrics no longer match: {len(differing)} companies; rerun attribution')
    for row in actual.values():
        total = row['growth_score'] + row['profitability_score'] + row['valuation_score'] + row['market_score']
        # Stored category totals are rounded to one decimal before the final
        # score is displayed; their combined rounding bound is 0.2 points.
        if abs(round(row['data_quality_score'] * total, 2) - row['quant_score']) > .211:
            raise ValueError('screen category arithmetic mismatch')

