"""Compare incremental state with independent full-universe report snapshots."""
import numpy as np

from reportflow.build_inputs import OUT, ROOT, SOURCE_MANIFEST, market_context, read, write


def main():
    from factormix.refresh_ranking import load_replay
    replay = load_replay()
    from ranking_research.return_v8.features import FIELDS
    data = dict(np.load(OUT / 'event_inputs.npz', allow_pickle=False))
    md = market_context(replay)
    replay.OUT = OUT / 'full_snapshot_audit'
    replay.OUT.mkdir(parents=True, exist_ok=True)
    requested = ['2022-03-26', '2024-05-19', '2026-11-04']
    dates = [str(data['cal'][np.searchsorted(data['cal'], day)]) for day in requested]
    frame = replay.append_financial(data, md, read(SOURCE_MANIFEST), dates)
    checks = []
    for day in dates:
        i = int(np.searchsorted(data['cal'], day))
        group = frame[frame.decision_time.eq(day)].set_index('symbol').reindex(data['syms'])
        np.testing.assert_allclose(data['raw'][i], group[FIELDS].to_numpy(float), rtol=1e-10, atol=1e-6, equal_nan=True)
        np.testing.assert_allclose(data['dq'][i], group.dq.to_numpy(float), rtol=0, atol=1e-12)
        np.testing.assert_allclose(data['financial_age'][i], group.financial_age_days.to_numpy(float), rtol=0, atol=0)
        checks.append(dict(date=day, symbols=len(group), all_21_factors=True, dq=True, financial_age=True))
    write(OUT / 'full_snapshot_audit.json', dict(status='PASS', checks=checks))
    print('Independent full-universe snapshot audit PASS', dates, flush=True)


if __name__ == '__main__':
    main()
