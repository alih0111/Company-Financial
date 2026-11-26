"""Imports must not initiate broker connections or create account files."""
from pathlib import Path
import subprocess
import sys

from ranking_research.tests.fixture_env import fixture_environment


def test_financial_imports_are_read_only_and_offline(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = fixture_environment()
    env['PYTHONPATH'] = str(root)
    code = r'''
import os, sys
def audit(event, args):
    if event in ('socket.connect', 'socket.connect_ex', 'socket.bind'):
        raise AssertionError('network access during import')
    if event == 'open':
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            raise AssertionError('write during import')
sys.addaudithook(audit)
import factormix.monthly_paper
import factormix.decision_readiness
import ranking_research.experimental_risk
import live_broker.ledger
import live_broker.pishro
import live_broker.paper
import live_broker.paper_service
import live_broker.preview
import live_broker.reconciliation
import live_broker.risk
'''
    subprocess.run([sys.executable, '-B', '-c', code], cwd=tmp_path, env=env,
                   check=True, capture_output=True, text=True, timeout=30)
    assert list(tmp_path.iterdir()) == []
