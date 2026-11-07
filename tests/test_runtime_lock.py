from pathlib import Path
import os
import subprocess
import sys

from runtime_lock import acquire_file_lock, release_file_lock


ROOT = Path(__file__).resolve().parents[1]


def try_lock(path):
    return subprocess.run([
        sys.executable, '-c',
        "from runtime_lock import acquire_file_lock; import sys; "
        "f=open(sys.argv[1],'a+b'); acquire_file_lock(f)", str(path),
    ], cwd=ROOT, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, timeout=10)


def test_lock_excludes_another_process_and_releases(tmp_path):
    path = tmp_path/'job.lock'
    with path.open('a+b') as handle:
        acquire_file_lock(handle)
        assert try_lock(path).returncode != 0
        release_file_lock(handle)
    assert try_lock(path).returncode == 0


def test_process_exit_releases_lock(tmp_path):
    path = tmp_path/'interrupted.lock'
    assert try_lock(path).returncode == 0
    assert try_lock(path).returncode == 0
