"""Run the V12.37 local-only extraction and immutable ranking build."""
import importlib.util, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
P=ROOT/"ranking_research/future_eval_v12_30/build_latest_supported_v12_37_impl.py"
s=importlib.util.spec_from_file_location("v1237_impl",P)
m=importlib.util.module_from_spec(s); sys.modules[s.name]=m; s.loader.exec_module(m)
if __name__=="__main__": m.main()
