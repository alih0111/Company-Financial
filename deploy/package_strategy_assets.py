"""Package only hash-verified, immutable strategy archives for deployment."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ('RFA-FactorMix-033', 'RFA-ReportFlow-033')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'.runtime/strategy-assets.zip')
    args = parser.parse_args()
    sources = []
    for strategy in STRATEGIES:
        folder = ROOT/'strategy_registry'/strategy/'v1.0.0'
        manifest = folder/'MANIFEST.sha256.json'
        data = json.loads(manifest.read_text(encoding='utf-8'))
        sources.append((manifest, hashlib.sha256(manifest.read_bytes()).hexdigest()))
        for record in data['files']:
            name = PurePosixPath(record['path'])
            if name.is_absolute() or '..' in name.parts or '\\' in record['path'] or ':' in record['path']:
                raise SystemExit('Unsafe archive member; package not created.')
            source = folder.joinpath(*name.parts)
            if not source.resolve().is_relative_to(folder.resolve()) or not source.is_file():
                raise SystemExit(f'Missing frozen strategy asset: {source.relative_to(ROOT)}')
            sources.append((source, record['sha256']))
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    for source, expected in sources:
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise SystemExit(f'Strategy integrity failed: {source.relative_to(ROOT)}')
    created = False
    try:
        with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            created = True
            for source, expected in sources:
                body = source.read_bytes()
                if hashlib.sha256(body).hexdigest() != expected:
                    raise RuntimeError('Source changed while packaging')
                archive.writestr(source.relative_to(ROOT).as_posix(), body)
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(f'{digest}  {output.name}\n', encoding='ascii')
    print(f'Verified and packaged {len(sources)} immutable strategy files: {output}')
    print(f'SHA256: {digest}')


if __name__ == '__main__':
    main()
