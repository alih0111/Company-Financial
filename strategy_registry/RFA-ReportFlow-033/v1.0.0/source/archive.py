"""Register a new version separately; never edit the FactorMix registration."""
import json
import shutil
import zipfile
from pathlib import Path

from reportflow.build_inputs import HERE, OUT, ROOT, read, sha, write


def main():
    version = ROOT / 'strategy_registry/RFA-ReportFlow-033/v1.0.0'
    if version.exists():
        raise RuntimeError('Registered version already exists; do not overwrite it')
    if read(OUT / 'full_snapshot_audit.json')['status'] != 'PASS':
        raise RuntimeError('Independent source reconstruction has not passed')
    version.mkdir(parents=True)
    for folder in ['source', 'replay', 'results', 'snapshot_data']:
        (version / folder).mkdir()
    for name in ['strategy.json', 'README.fa.md', 'REPORT.fa.md']:
        shutil.copyfile(HERE / name, version / name)
    for p in HERE.glob('*.py'):
        shutil.copyfile(p, version / 'source' / p.name)
    shutil.copyfile(HERE / 'engine.py', version / 'replay/engine.py')
    shutil.copyfile(HERE / 'reproduce.py', version / 'replay/reproduce.py')
    shutil.copyfile(OUT / 'event_inputs.npz', version / 'snapshot_data/event_inputs.npz')
    for p in OUT.iterdir():
        if p.is_file() and p.suffix in ['.csv', '.json', '.xml']:
            shutil.copyfile(p, version / 'results' / p.name)
    (version / 'requirements-replay.txt').write_text('numpy\npandas\njdatetime\n', encoding='utf8')
    (version / 'REPRODUCE.md').write_text(
        'Run `python replay/reproduce.py` inside this version directory. It verifies every file and reproduces all daily NAV/cash and the fill count. '
        'No database/network is needed for the numerical replay. Original raw financial/price sources are referenced by their hashes; they are not all copied into this package. '
        'For fresh CSVs add `--output-dir` with a new directory. Forward paper state is deliberately separate in the project runtime.\n', encoding='utf8')
    files = [dict(path=p.relative_to(version).as_posix(), sha256=sha(p), bytes=p.stat().st_size)
             for p in sorted(version.rglob('*')) if p.is_file()]
    write(version / 'MANIFEST.sha256.json', dict(strategy_id=read(HERE / 'strategy.json')['strategy_id'], files=files))
    archive = ROOT / 'strategy_registry/archives/RFA-ReportFlow-033-v1.0.0-20261106.zip'
    archive.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(version.rglob('*')):
            if p.is_file(): z.write(p, 'RFA-ReportFlow-033-v1.0.0/' + p.relative_to(version).as_posix())
    registration = dict(strategy_id=read(HERE / 'strategy.json')['strategy_id'], version_directory=str(version),
                        archive=str(archive), archive_sha256=sha(archive), files=len(files),
                        old_factormix_unchanged=True, status='EXPERIMENTAL_PAPER_ONLY_UNDERPERFORMS_QUARTERLY_CONTROL')
    write(ROOT / 'strategy_registry/reportflow.registration.json', registration)
    print(json.dumps(registration))


if __name__ == '__main__':
    main()
