"""Guard the live scorer against silently changing the registered factor mix."""
import importlib.util
import json
from pathlib import Path

import numpy as np

from factormix.refresh_ranking import ARCHIVE, score_blocks


def test_registered_scores_reproduced_exactly():
    spec = importlib.util.spec_from_file_location('locked_feature_math', ARCHIVE / 'source/model_search_features.py')
    features = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(features)
    policy = json.loads((ARCHIVE / 'strategy.locked.json').read_text(encoding='utf8'))
    data = dict(np.load(ARCHIVE / 'snapshot_data/model_market_inputs.npz', allow_pickle=False))
    bank = dict(np.load(ARCHIVE / 'snapshot_data/model_features.npz', allow_pickle=False))
    actual = score_blocks(bank['raw'].astype(float), data['close'], data['adv'], data['p1'],
                          data['cal'], policy['source_model']['weights'], features)
    actual[~bank['allowed']] = np.nan
    expected = np.load(ARCHIVE / 'snapshot_data/selected_score.npz')['score']
    np.testing.assert_array_equal(actual, expected)


def test_new_report_changes_scores_without_future_data():
    spec = importlib.util.spec_from_file_location('locked_feature_math', ARCHIVE / 'source/model_search_features.py')
    features = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(features)
    policy = json.loads((ARCHIVE / 'strategy.locked.json').read_text(encoding='utf8'))
    data = dict(np.load(ARCHIVE / 'snapshot_data/model_market_inputs.npz', allow_pickle=False))
    raw = np.load(ARCHIVE / 'snapshot_data/model_features.npz')['raw'].astype(float)
    before = score_blocks(raw, data['close'], data['adv'], data['p1'], data['cal'], policy['source_model']['weights'], features)
    target = int(np.flatnonzero(np.isfinite(before[-1]))[0])
    raw[-1, target, 1] = 1e6
    after = score_blocks(raw, data['close'], data['adv'], data['p1'], data['cal'], policy['source_model']['weights'], features)
    np.testing.assert_array_equal(before[:-1], after[:-1])
    assert before[-1, target] != after[-1, target]
