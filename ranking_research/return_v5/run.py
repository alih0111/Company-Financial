import argparse
from pathlib import Path
import pandas as pd
from .common import V3,V4,register,validate,write

def main():
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['register','all','diagnostics','candidates','report','seal','verify']);p.add_argument('--run');args=p.parse_args()
    if args.stage=='register':print(register());return
    if not args.run:p.error('--run explicit path required')
    out=Path(args.run).resolve();validate(out)
    from . import report
    if args.stage=='verify' or (args.stage=='all' and (out/'delivery_manifest.json').exists()):report.verify(out);print('verified');return
    if args.stage in ['report','seal']:
        if args.stage=='report':report.run(out)
        else:report.seal(out)
        return
    from ranking_research.return_v3.common import snapshot
    snapshot(V3)
    from ranking_research.return_v3.market import markets
    _,md,new=markets(V3);d=pd.read_parquet(V4/'repaired_panel.parquet')
    if args.stage=='all':
        from . import prices,acquire,events
        prices.run(out,md,new);acquire.run(out);events.run(out)
    if args.stage in ['all','diagnostics']:
        from . import diagnostics
        if not (out/'signal_diagnostics.csv').exists():diagnostics.run(out,md,d)
    if args.stage in ['all','candidates']:
        from . import candidates
        candidates.run(out,md,d)
    if args.stage=='all':report.run(out);write(out/'checkpoint.json',{'phase':'financial_and_reporting_complete','pending':['tests','frontend validation','seal']})

if __name__=='__main__':main()
