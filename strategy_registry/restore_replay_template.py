"""Restore the archived replay without the original project or source archives."""
from pathlib import Path
import argparse,hashlib,json,sys


def verify(root):
    manifest=json.loads((root/'MANIFEST.sha256.json').read_text(encoding='utf8'))
    failures=[]
    for item in manifest['files']:
        path=root/item['path']
        if not path.is_file():failures.append(item['path']+': missing')
        elif hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:failures.append(item['path']+': changed')
    if failures:raise RuntimeError('Archive integrity failed: '+repr(failures))
    return len(manifest['files'])


def main():
    p=argparse.ArgumentParser(description='Verify or restore the frozen RFA strategy replay')
    p.add_argument('--verify-only',action='store_true')
    p.add_argument('--output-dir',type=Path)
    args=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    count=verify(root)
    if args.verify_only:
        print(json.dumps({'integrity':'PASS','verified_files':count}));return
    if args.output_dir is None:p.error('--output-dir is required unless --verify-only is used')
    output=args.output_dir.resolve()
    if output.is_relative_to(root.resolve()):raise RuntimeError('Output must be outside the frozen archive')
    if output.exists():raise RuntimeError('Output directory must be new; no existing files are overwritten')
    import numpy as np
    import pandas as pd
    from engine_snapshot import Config,Execution,simulate,save_run
    policy=json.loads((root/'strategy.locked.json').read_text(encoding='utf8'))
    data=dict(np.load(root/'snapshot_data/active_inputs.npz',allow_pickle=False))
    config=Config(**policy['portfolio']);execution=Execution(**policy['execution_assumptions'])
    run=simulate({**data,'p1':data['candidate_score']},config,execution,
                 start=policy['replay']['requested_start'],end=policy['replay']['market_end'],detail=True)
    reference=pd.read_csv(root/'results/active_candidate_nav.csv')
    assert run['cal'].tolist()==reference.session.tolist()
    np.testing.assert_allclose(run['nav'],reference.nav_toman.to_numpy(),rtol=0,atol=1)
    assert abs(run['metrics']['final_toman']-policy['replay']['expected_final_toman'])<1
    output.mkdir(parents=True,exist_ok=False)
    save_run(output/'restored',run)
    result={'integrity':'PASS','verified_files':count,'daily_nav_reproduction':'PASS',
            'strategy_id':policy['registry_id'],'metrics':run['metrics']}
    (output/'restoration_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
