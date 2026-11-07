from .common import HERE, read, write, sha, checkpoint


def publish(out):
    audit = read(out / 'audit.json')
    if audit['status'] != 'passed': raise ValueError('audit_required')
    acceptance = read(out / 'acceptance.json')
    artifacts = {p.name: sha(p) for p in out.iterdir() if p.is_file() and
                 p.name not in ['progress.json', 'publication.json', 'artifact_manifest.json']}
    write(out / 'artifact_manifest.json', artifacts)
    # A research pointer is separate from both current ranking pointers.
    payload = {'run_path': str(out.resolve()), 'status': acceptance['status'],
               'accepted': acceptance['accepted'], 'report_sha256': sha(out / 'report.fa.md'),
               'artifact_manifest_sha256': sha(out / 'artifact_manifest.json'),
               'production_changed': False, 'real_orders': 0}
    write(out / 'publication.json', payload)
    write(HERE / 'output/top10_six_month_latest.json', payload)
    checkpoint(out, 'publish')
