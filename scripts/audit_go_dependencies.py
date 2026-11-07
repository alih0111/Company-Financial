"""Audit Linux runtime imports with OSV when the Go database is inaccessible.

This is a package-import audit, not govulncheck's symbol/call-graph analysis.
Unimported affected subpackages are reported separately, never as a clean module.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def fetch(url,body=None):
    request=urllib.request.Request(url,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json','User-Agent':'RFA-dependency-audit'})
    with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'.runtime/security-osv-go-runtime.json')
    args=parser.parse_args()
    environment={**os.environ,'GOOS':'linux','GOARCH':'amd64','CGO_ENABLED':'0'}
    raw=subprocess.check_output(['go','list','-deps','-json','./...'],cwd=ROOT/'go-app',env=environment,text=True,encoding='utf-8')
    decoder=json.JSONDecoder();offset=0;modules={};imports=set()
    while offset<len(raw):
        while offset<len(raw) and raw[offset].isspace():offset+=1
        if offset>=len(raw):break
        item,length=decoder.raw_decode(raw[offset:]);offset+=length
        imports.add(item.get('ImportPath',''));module=item.get('Module',{})
        if module.get('Version'):modules[module['Path']]=module['Version'].removeprefix('v')
    modules['stdlib']=subprocess.check_output(['go','env','GOVERSION'],cwd=ROOT/'go-app',text=True,encoding='utf-8').strip().removeprefix('go')
    queries=[{'package':{'name':name,'ecosystem':'Go'},'version':version} for name,version in sorted(modules.items())]
    response=fetch('https://api.osv.dev/v1/querybatch',{'queries':queries})
    if len(response['results'])!=len(queries):raise SystemExit('Incomplete audit response; no clean result was recorded.')
    findings=[];seen=set()
    for query,result in zip(queries,response['results']):
        for entry in result.get('vulns',[]):
            details=fetch('https://api.osv.dev/v1/vulns/'+entry['id'])
            identifier=next((identifier for identifier in [details['id'],*details.get('aliases',[])] if identifier.startswith('GO-')),details['id'])
            key=(query['package']['name'],identifier)
            if key in seen:continue
            seen.add(key)
            if details['id']!=identifier:details=fetch('https://api.osv.dev/v1/vulns/'+identifier)
            affected=[]
            for item in details.get('affected',[]):
                if item['package']['name']!=query['package']['name']:continue
                entries=item.get('ecosystem_specific',{}).get('imports')
                if not entries:affected.append('<module-wide advisory; review required>')
                else:affected.extend(package['path'] for package in entries if package['path'] in imports)
            findings.append({'module':query['package']['name'],'version':query['version'],'id':identifier,'affected_packages_in_application':sorted(set(affected))})
    report={'source':'OSV API','target':'linux/amd64 CGO_ENABLED=0','modules_checked':len(queries),'application_packages':len(imports),'findings':findings}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    actionable=sum(bool(item['affected_packages_in_application']) for item in findings)
    print(f'OSV: {len(queries)} runtime modules checked; {actionable} advisories affect imported packages; {len(findings)-actionable} concern unimported subpackages.')
    for item in findings:print(item['id'],item['module'],','.join(item['affected_packages_in_application']) or '(affected subpackages are not imported)')
    raise SystemExit(bool(actionable))


if __name__=='__main__':main()
