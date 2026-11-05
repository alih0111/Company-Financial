"""Reproducible TF-03 subprocess lifecycle with synthetic data and network blocked."""
from __future__ import annotations
import argparse, copy, datetime as dt, gzip, hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile
from decimal import Decimal, ROUND_HALF_UP

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = None
PY = ROOT / ".venv/Scripts/python.exe"
NOW = "2026-10-24T12:05:00+00:00"
DECISION = "2026-10-23T06:00:00+00:00"

def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def write(p, value):
    p = pathlib.Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

def invoke(name, argv, env, account_path=None):
    account_path=pathlib.Path(account_path or paths["account"])
    before = sha(account_path)
    p = subprocess.run([str(PY), "-X", "utf8", *map(str, argv)], cwd=ROOT,
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    after = sha(account_path)
    rec = {"name":name,"command":[str(PY),"-X","utf8",*map(str,argv)],"exit_code":p.returncode,
           "stdout":p.stdout,"stderr":p.stderr,"account_sha256_before":before,"account_sha256_after":after}
    stages.append(rec)
    return p


def main(argv=None):
    global OUT, paths, stages
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)
    OUT = args.output_dir.resolve() if args.output_dir else pathlib.Path(tempfile.mkdtemp(prefix="tf03-offline-", dir=ROOT))
    if OUT.exists():
        if any(OUT.iterdir()):
            raise SystemExit(f"OUTPUT_DIR_NOT_EMPTY: {OUT}")
        OUT.rmdir()
    OUT.mkdir(parents=True, exist_ok=False)
    stages=[]
    blockdir=OUT/"network-block"
    blockdir.mkdir()
    (blockdir/"sitecustomize.py").write_text(
     "import socket\ndef _blocked(*a, **k): raise RuntimeError('NETWORK_BLOCKED_BY_TF03_HARNESS')\nsocket.socket.connect=_blocked\nsocket.create_connection=_blocked\n",encoding="utf-8")
    sys.path.insert(0, str(ROOT))
    from ranking_research.tests import test_public_market_calendar as calfx
    from ranking_research.tests import test_paper_calendar_interface as accfx
    from ranking_research import paper_calendar
    calfx.NOW = dt.datetime.fromisoformat(NOW)

    root=OUT/"fixture"; root.mkdir()
    paths={"account":root/"account.json","rules":root/"rules.json","ranking":root/"ranking.json",
           "evidence":root/"evidence.json","calendar":root/"calendar.json","policy":ROOT/"ranking_research/paper_calendar_policy.public-paper-v1.json"}
    policy=json.loads(paths["policy"].read_text(encoding="utf-8")); policy_sha=sha(paths["policy"])
    binding={"id":policy["policy_id"],"sha256":policy_sha,"provider":policy["provider"],"version":policy["version"]}
    rules={"rule_id":"paper-execution-rules/fixture", "fee_assumption_per_side":0.005}
    rules["calendar_policy"]=binding; write(paths["rules"],rules)
    cid="fixture-company"; symbol="TEST"; ins=calfx.CANDIDATE_INS
    artifact_sha="a"*64
    ranking={"artifact_id":"tf03-synthetic-ranking","artifact_sha256":artifact_sha,"dataset_id":"TF03_SYNTHETIC_FIXTURE",
     "evaluation_date":"2026-10-23","status":"FIXTURE_ONLY_NOT_REAL_RANKING","scored_count":{"P1":1},
     "rows":[{"company_id":cid,"symbol":symbol,"methods":{"P1":{"rank":1,"score":1.0}}}]}
    write(paths["ranking"],ranking)
    original={"account_id":"PROTECTED_SYNTHETIC_FIXTURE", "initial_capital_toman":100000,
              "cash_toman":100000, "holdings":[], "event_log":[], "contract":{},
              "official_future_evaluation_ledger_linked":False,
              "accounting":{"holdings_value_toman":0,"total_value_toman":100000,"profit_loss_toman":0}}
    protected_account=root/"protected-account.json"
    write(protected_account, original)
    primary_account_sha=sha(protected_account)
    account=copy.deepcopy(original)
    account.update({"account_id":"TF03_SYNTHETIC_TEMP","initial_capital_toman":100000,"cash_toman":100000,
     "holdings":[],"event_log":[],"execution_recorded":False,"order_created":False,
     "ranking":{"dataset_id":"TF03_SYNTHETIC_FIXTURE","evaluation_date":"2026-10-23","artifact_sha256":artifact_sha,
                "top_candidate":{"company_id":cid,"symbol":symbol,"rank":1,"score":1.0,"coverage":1.0}},
     "accounting":{"holdings_value_toman":0,"total_value_toman":100000,"profit_loss_toman":0},
     "created_at_utc":DECISION,"created_at_tehran":"2026-10-23T09:30:00+03:30",
     "decision_at_utc":DECISION,"calendar_policy":None})
    account.pop("active_decision",None); account.pop("paper_order",None)
    account["event_log"]=[{"event_id":"tf03-fixture-init","type":"ACCOUNT_CREATED","at_utc":DECISION,"reason":"synthetic fixture","details":"fixture only"}]
    write(paths["account"],account)
    blank_account=copy.deepcopy(account)
    # The registered collector fixture has two sessions after the synthetic decision.
    calendar_path, calendar_doc, _ = calfx.build_pinned_package(OUT/"calendar-fixture",
     primary_dates=["20261023","20261024"],
     secondary_dates=["20261023","20261024"],
     watermark="20261024;20261024", window_start="20261023")
    shutil.copy2(calendar_path, paths["calendar"])
    write(OUT/"deliberately-wrong-calendar.json", {"schema_version": 0, "quality": "INVALID_ENVIRONMENT_SENTINEL"})
    daily=[{"dEven":"20261024","date":"2026-10-24","insCode":ins,"pClosing":1234,"close_rial":1234,
            "qTotTran5J":10000,"volume":10000},
           {"dEven":"20261025","date":"2026-10-25","insCode":ins,"pClosing":1240,"close_rial":1240,
            "qTotTran5J":10000,"volume":10000}]
    sources=[]
    for key, doc in [("candidate_daily",{"closingPriceDaily":daily}),
                     ("candidate_share_changes",{"instrumentShareChange":[]}),
                     ("last_possible_session",{"deven":"20261026"})]:
     body=json.dumps(doc,separators=(",",":")).encode(); raw=root/f"{key}.json.gz"; raw.write_bytes(gzip.compress(body))
     url=f"https://example.invalid/{ins}/0" if key=="candidate_daily" else "https://example.invalid/fixture"
     sources.append({"key":key,"url":url,"raw_path":str(raw),"raw_sha256":hashlib.sha256(body).hexdigest(),
      "retrieved_at_utc":NOW,"http_status":200})
    evidence={"dataset_id":"TF03_SYNTHETIC_FIXTURE","candidate":{"company_id":cid,"symbol":symbol},"ins_code":ins,"sources":sources}
    write(paths["evidence"],evidence)
    calendar_sha=sha(paths["calendar"])
    stages=[]
    env=os.environ.copy(); env["PYTHONPATH"]=str(blockdir)+os.pathsep+str(ROOT); env["PYTHONDONTWRITEBYTECODE"]="1"
    import pandas as pd
    fixture_local_calendar=root/"reference-calendar.parquet"
    pd.DataFrame({"trade_date":["2026-10-22"]}).to_parquet(fixture_local_calendar,index=False)
    env["CDF_STATUS_REFERENCE_RANKING"]=str(paths["ranking"])
    env["CDF_STATUS_LOCAL_CALENDAR"]=str(fixture_local_calendar)
    env["TSETMC_CALENDAR_MANIFEST"]=str(OUT/"deliberately-wrong-calendar.json")
    reg=[ROOT/"ranking_research/future_eval_v12_30/register_paper_decision.py","--fixture","--fixture-clock",DECISION,
     "--calendar-provider","public","--account",paths["account"],"--ranking",paths["ranking"],"--rules",paths["rules"],
     "--evidence",paths["evidence"],"--calendar-policy",paths["policy"]]
    p=invoke("register_decision",reg,env)
    if p.returncode: raise SystemExit(p.stderr or p.stdout)
    registered=json.loads(paths["account"].read_text(encoding="utf-8"))
    assert all(x["calendar_policy"]==binding for x in (registered,registered["active_decision"],registered["paper_order"],rules))
    assert registered["active_decision"]["decided_at_utc"]==DECISION
    cycle_args=[ROOT/"ranking_research/future_eval_v12_30/paper_cycle.py","--order-review-only","--calendar-provider","public",
     "--account",paths["account"],"--rules",paths["rules"],"--output-dir",root/"cycle-output",
    "--public-output-dir",root/"cycle-public","--evidence-manifest",paths["evidence"],"--ranking",paths["ranking"],
     "--calendar-manifest",paths["calendar"],"--calendar-manifest-sha256",sha(paths["calendar"]),
     "--fixture","--reference-now-utc",NOW]
    p=invoke("paper_cycle_main_public_preview_branch",cycle_args,env)
    if p.returncode: raise SystemExit(p.stderr+p.stdout)
    cycle_result=json.loads(next((root/"cycle-output").glob("*.order-review.json")).read_text(encoding="utf-8"))
    assert cycle_result["calendar_manifest"]==str(paths["calendar"])
    assert cycle_result["product_outcome"]=="PREVIEW_COMPLETE"
    assert cycle_result["child_exit_code"]==0
    assert cycle_result["validation_outcome"]=="FILL_ELIGIBLE_PREVIEW_ONLY"
    common=[ROOT/"ranking_research/future_eval_v12_30/apply_paper_fill.py","--session-calendar-manifest",paths["calendar"],
     "--calendar-manifest-sha256",calendar_sha,"--evidence-manifest",paths["evidence"],"--calendar-provider","public",
     "--calendar-policy",paths["policy"],"--reference-now-utc",NOW,"--account",paths["account"],"--rules",paths["rules"]]
    before=sha(paths["account"]); p=invoke("preview",common,env); assert p.returncode==0,p.stderr+p.stdout
    healthy_preview=json.loads(p.stdout)
    assert healthy_preview["status"]=="FILL_ELIGIBLE_PREVIEW_ONLY"
    assert healthy_preview["sessions_after_decision"]==1 and healthy_preview["fill_applied"] is False
    assert sum(e.get("type")=="PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE" for e in json.loads(paths["account"].read_text(encoding="utf-8"))["event_log"])==0
    assert before==sha(paths["account"])
    p=invoke("apply",[*common,"--apply-fill"],env); assert p.returncode==0,p.stderr+p.stdout
    filled=json.loads(paths["account"].read_text(encoding="utf-8")); receipt=copy.deepcopy(filled["paper_order"]["fill_receipt"])
    assert receipt["shares"]==806 and receipt["gross_toman"]==99460 and receipt["fee_toman"]==497 and filled["cash_toman"]==43
    # Exact replay is first tested before mark-to-market.
    p=invoke("replay_before_mark",[*common,"--apply-fill"],env); assert p.returncode==0,p.stderr+p.stdout
    assert json.loads(p.stdout)["status"]=="FILL_ALREADY_APPLIED"
    before_mark=json.loads(paths["account"].read_text(encoding="utf-8")); assert before_mark["cash_toman"]==43
    # Existing mark writer with explicit temp ranking/manifest/calendar/output destinations.
    daily_manifest=root/"market-manifest.json"
    write(daily_manifest,{"records":[{"company_id":cid,"daily":daily}]})
    parquet=root/"calendar.parquet"
    import pandas as pd
    pd.DataFrame({"trade_date":["2026-10-24","2026-10-25","2026-10-26"]}).to_parquet(parquet,index=False)
    p=invoke("mark_to_market",[ROOT/"ranking_research/future_eval_v12_30/check_paper_account.py","--account",paths["account"],
     "--ranking",paths["ranking"],"--tsetmc-manifest",daily_manifest,"--calendar",parquet,"--mark-to-market",
     "--output-dir",root/"status","--public-output-dir",root/"public"],env)
    if p.returncode: raise SystemExit(p.stderr+p.stdout)
    marked=json.loads(paths["account"].read_text(encoding="utf-8")); markdate=marked["holdings"][0]["last_price_date"]
    marked_status=json.loads((root/"public/paper-account-check.json").read_text(encoding="utf-8"))
    assert marked_status["source_paths"]["account"]==str(paths["account"])
    assert marked_status["source_sha256"]["account"]==sha(paths["account"])
    assert markdate=="20261025" or markdate=="2026-10-25"
    receipt_after=marked["paper_order"]["fill_receipt"]
    assert receipt_after==receipt
    p=invoke("replay_after_mark",[x for x in common if x != "--reference-now-utc" and x != NOW]+["--apply-fill"],env); assert p.returncode==0,p.stderr+p.stdout
    assert json.loads(p.stdout)["status"]=="FILL_ALREADY_APPLIED"
    final=json.loads(paths["account"].read_text(encoding="utf-8"))
    assert final["holdings"][0]["last_price_date"]==markdate and final["paper_order"]["fill_receipt"]==receipt
    assert sum(e.get("type")=="PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE" for e in final["event_log"])==1
    assert final["cash_toman"]==43 and len([e for e in final["event_log"] if e.get("type")=="PAPER_MARK_TO_MARKET"])==1
    # Independently recompute with Decimal and ROUND_HALF_UP, without product helpers.
    def round_half_up(x): return int(Decimal(str(x)).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
    shares=806; price=Decimal(1234)/Decimal(10)
    gross=round_half_up(Decimal(shares)*price); fee=round_half_up(Decimal(gross)*Decimal("0.005"))
    cash=100000-gross-fee; fill_nav=cash+gross
    mark_value=round_half_up(Decimal(shares)*Decimal(1240)/Decimal(10))
    mark_nav=cash+mark_value
    accounting={"shares":shares,"gross_toman":gross,"fee_toman":fee,"cash_toman":cash,"fill_nav_toman":fill_nav,
     "fill_pnl_toman":fill_nav-100000,"mark_value_toman":mark_value,"mark_nav_toman":mark_nav,
     "mark_pnl_toman":mark_nav-100000,"method":"independent Decimal ROUND_HALF_UP; no product calculator used"}
    assert (shares,gross,fee,cash,fill_nav,fill_nav-100000)==(806,99460,497,43,99503,-497)
    assert (final["holdings"][0]["shares"],final["paper_order"]["fill_receipt"]["gross_toman"],
            final["paper_order"]["fill_receipt"]["fee_toman"],final["cash_toman"],
            final["accounting"]["total_value_toman"],final["accounting"]["profit_loss_toman"]) == (
                shares,gross,fee,cash,mark_nav,mark_nav-100000)
    assert final["holdings"][0]["market_value_toman"]==mark_value
    # Exercise the other preview gates through real subprocess entrypoints too.
    scenario_results=[]
    def preview_scenario(name, sessions, bars, clock=NOW, failure=None, provider="public", corrupt_quality=False, corrupt_hash=False):
        global NOW
        now_dt=dt.datetime.fromisoformat(clock); calfx.NOW=now_dt
        droot=OUT/"scenarios"/name; droot.mkdir(parents=True,exist_ok=True)
        acc=droot/"account.json"; rank=droot/"ranking.json"; rule=droot/"rules.json"; ev=droot/"evidence.json"
        write(acc,blank_account); write(rank,ranking); write(rule,rules)
        calpath,caldoc,_=calfx.build_pinned_package(droot/"calendar-source",primary_dates=sessions,
            secondary_dates=sessions,watermark=f"{sessions[-1]};{sessions[-1]}",window_start="20261023")
        if corrupt_quality:
            bad=json.loads(calpath.read_text(encoding="utf-8")); bad["quality"]="INPUT_ROWS_REJECTED"
            write(calpath,bad)
        rows=[]
        for day,price in bars:
            rows.append({"dEven":day,"date":f"{day[:4]}-{day[4:6]}-{day[6:]}","insCode":ins,
                "pClosing":price,"close_rial":price,"qTotTran5J":10000,"volume":10000})
        src=[]
        for key,doc in [("candidate_daily",{"closingPriceDaily":rows}),
                        ("candidate_share_changes",{"instrumentShareChange":[]}),
                        ("last_possible_session",{"deven":sessions[-1]})]:
            body=json.dumps(doc,separators=(",",":")).encode(); raw=droot/f"{key}.gz"; raw.write_bytes(gzip.compress(body))
            src.append({"key":key,"url":f"https://example.invalid/{ins}/0","raw_path":str(raw),
                "raw_sha256":hashlib.sha256(body).hexdigest(),"retrieved_at_utc":clock,"http_status":200})
        write(ev,{"dataset_id":"TF03_SYNTHETIC_FIXTURE","candidate":{"company_id":cid,"symbol":symbol},"ins_code":ins,"sources":src})
        regcmd=[ROOT/"ranking_research/future_eval_v12_30/register_paper_decision.py","--fixture","--fixture-clock",DECISION,
            "--calendar-provider","public","--account",acc,"--ranking",rank,"--rules",rule,"--evidence",ev,"--calendar-policy",paths["policy"]]
        p=invoke(name+"_register",regcmd,env,acc); assert p.returncode==0,p.stderr+p.stdout
        expected_calendar_hash="0"*64 if corrupt_hash else sha(calpath)
        cmd=[ROOT/"ranking_research/future_eval_v12_30/apply_paper_fill.py","--session-calendar-manifest",calpath,
            "--calendar-manifest-sha256",expected_calendar_hash,"--evidence-manifest",ev,"--calendar-provider",provider,
            "--calendar-policy",paths["policy"],"--reference-now-utc",clock,"--account",acc,"--rules",rule]
        before=sha(acc); p=invoke(name+"_preview",cmd,env,acc)
        after=sha(acc)
        if failure:
            assert p.returncode!=0 and failure in p.stderr+p.stdout,(failure,p.stderr,p.stdout)
        else:
            assert p.returncode==0,p.stderr+p.stdout
            outcome=json.loads(p.stdout)
        if not failure:
            expected_outcomes={"missing_first_session_bar":"PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE",
                "expired_with_three_sessions":"EXPIRED_NO_FILL","late_ambiguous_first_bar":"LATE_FILL_TIMING_AMBIGUOUS",
                "no_new_session":"NO_NEW_SESSION"}
            assert outcome["status"]==expected_outcomes[name],outcome
            expected_sessions={"missing_first_session_bar":1,"expired_with_three_sessions":3,
                "late_ambiguous_first_bar":3,"no_new_session":0}
            observed=outcome.get("session_count",outcome.get("sessions_after_decision"))
            expected_from_fixture=sum(day>"20261023" and day<=now_dt.strftime("%Y%m%d") for day in sessions)
            assert expected_from_fixture==expected_sessions[name]
            if observed is not None: assert observed==expected_from_fixture,outcome
            elif name=="missing_first_session_bar": assert outcome["first_session"]=="20261024",outcome
            assert outcome["fill_applied"] is False
            if name=="no_new_session":
                assert outcome["session_count"]==0 and outcome["fill_applied"] is False
        assert before==after
        account_after_preview=json.loads(acc.read_text(encoding="utf-8"))
        assert account_after_preview.get("execution_recorded") is False
        assert sum(e.get("type")=="PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE" for e in account_after_preview["event_log"])==0
        case_result={"case":name,"exit_code":p.returncode,"expected_error":failure,
            "account_unchanged":before==after,"stdout":p.stdout,"stderr":p.stderr}
        if name in ("invalid_quality","no_new_session","invalid_hash","provider_mismatch"):
            cycle_out=droot/"cycle-output"; cycle_public=droot/"cycle-public"
            wrapper_provider="nscstart" if name=="provider_mismatch" else "public"
            wrapper_cmd=[ROOT/"ranking_research/future_eval_v12_30/paper_cycle.py","--order-review-only",
                "--calendar-provider",wrapper_provider,"--account",acc,"--rules",rule,"--output-dir",cycle_out,
            "--public-output-dir",cycle_public,"--evidence-manifest",ev,"--ranking",rank,"--calendar-manifest",calpath,
                "--calendar-manifest-sha256",("0"*64 if name=="invalid_hash" else sha(calpath)),"--fixture","--reference-now-utc",clock]
            w=invoke(name+"_cycle_wrapper",wrapper_cmd,env,acc); assert w.returncode==0,w.stderr+w.stdout
            cycle_doc=json.loads(next(cycle_out.glob("*.order-review.json")).read_text(encoding="utf-8"))
            status=json.loads((cycle_public/"paper-account-check.json").read_text(encoding="utf-8"))
            public=status.get("public_calendar")
            if name in ("invalid_quality","invalid_hash","provider_mismatch"):
                assert failure in json.dumps(status,ensure_ascii=False),status
                assert cycle_doc["product_outcome"]=="BLOCKED_VALIDATION_REFUSAL",cycle_doc
                assert cycle_doc["child_exit_code"]!=0 and failure in str(cycle_doc["wrapper_stage"])
                case_result["wrapper_public_status"]=failure
            else:
                assert public is not None
                state=public["sessions_after_decision"]["state"]
                assert state=="NO_NEW_SESSION",public
                assert cycle_doc["product_outcome"]=="NO_NEW_SESSION",cycle_doc
                assert cycle_doc["validation_outcome"]=="NO_NEW_SESSION",cycle_doc
                case_result["wrapper_public_status"]=state
            assert before==sha(acc)
            case_result["wrapper_exit_code"]=w.returncode
            case_result["wrapper_account_unchanged"]=True
        scenario_results.append(case_result)

    preview_scenario("missing_first_session_bar",["20261023","20261024"],[("20261025",1250)])
    preview_scenario("expired_with_three_sessions",["20261023","20261024","20261025","20261026"],[],clock="2026-10-26T12:05:00+00:00")
    preview_scenario("late_ambiguous_first_bar",["20261023","20261024","20261025","20261026"],[("20261024",1234)],clock="2026-10-26T12:05:00+00:00")
    preview_scenario("no_new_session",["20261023"],[],clock="2026-10-23T12:05:00+00:00")
    preview_scenario("invalid_quality",["20261023","20261024"],[("20261024",1234)],corrupt_quality=True,failure="CALENDAR_MANIFEST_QUALITY_INCONSISTENT")
    preview_scenario("provider_mismatch",["20261023","20261024"],[("20261024",1234)],provider="nscstart",failure="CALENDAR_POLICY_MISMATCH")
    preview_scenario("invalid_hash",["20261023","20261024"],[("20261024",1234)],corrupt_hash=True,failure="CALENDAR_MANIFEST_HASH_MISMATCH")
    by_name={stage["name"]:stage for stage in stages}
    evidence_out={"network_block":"sitecustomize patches socket connect/create_connection in every subprocess",
     "mocked":"calendar source raws and candidate market evidence are synthetic; no core entrypoint or writer is mocked",
     "stages":stages,"fill_receipt":receipt,"account_final":final,"independent_accounting":accounting,
     "preview_scenarios":scenario_results,
     "cycle_wrapper_preview_bytes_unchanged":by_name["paper_cycle_main_public_preview_branch"]["account_sha256_before"]==by_name["paper_cycle_main_public_preview_branch"]["account_sha256_after"],
     "preview_bytes_unchanged":by_name["preview"]["account_sha256_before"]==by_name["preview"]["account_sha256_after"],
     "replay_before_mark_idempotent":by_name["replay_before_mark"]["account_sha256_before"]==by_name["replay_before_mark"]["account_sha256_after"],
     "replay_after_mark_idempotent":by_name["replay_after_mark"]["account_sha256_before"]==by_name["replay_after_mark"]["account_sha256_after"],
     "fill_event_count":sum(e.get("type")=="PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE" for e in final["event_log"]),
     "fill_debit_toman":receipt["gross_toman"]+receipt["fee_toman"],
     "protected_account_untouched":sha(protected_account)==primary_account_sha,
     "account_path":str(paths["account"])}
    write(OUT/"lifecycle-evidence.json",evidence_out)
    print(json.dumps({"result":"PASS","stages":len(stages),"account":str(paths["account"]),"receipt":receipt,"independent_accounting":accounting},ensure_ascii=False))

if __name__ == "__main__":
    main()
