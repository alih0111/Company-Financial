"""Bounded source credential check. Findings contain locations, never values."""
import argparse
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
TEXT_EXTENSIONS={'.py','.go','.ts','.tsx','.js','.mjs','.json','.yaml','.yml','.toml','.ps1','.md','.txt','.sql'}
RULES={
    'private_key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'api_key':re.compile(r'(?<![A-Za-z])sk-[A-Za-z0-9_-]{24,}'),
    'database_credential':re.compile(r'''(?:postgresql|postgres|sqlserver)(?:\+psycopg)?://[^\s'"/:]+:[^\s'"@]{4,}@[^\s'"]+'''),
    'secret_literal':re.compile(r'''(?:DB_PASSWORD|SMTP_PASSWORD|JWT_SECRET|AI_API_KEY|BRS_API_KEY)\s*[:=]\s*['"][^'"\r\n]{8,}['"]''',re.I),
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tracked-only',action='store_true')
    args=parser.parse_args()
    command=['git','ls-files','-z','--cached']
    if not args.tracked_only:command+=['--others','--exclude-standard']
    names=set(subprocess.check_output(command,cwd=ROOT).decode().split('\0'))
    failures=[];checked=0
    for name in sorted(names):
        if not name:continue
        path=ROOT/name
        if path.is_symlink() or not path.is_file():continue
        if path.name=='.env' or path.name.startswith('.env.') and path.name not in ('.env.example','.env.sample'):
            failures.append((name,1,'environment_file'));continue
        if path.suffix.lower() not in TEXT_EXTENSIONS or path.stat().st_size>4_000_000:continue
        checked+=1
        text=path.read_text(encoding='utf-8-sig',errors='replace')
        fixture=path.name.endswith('_test.go') or any(part in ('test','tests') for part in path.parts)
        for rule,pattern in RULES.items():
            for match in pattern.finditer(text):
                if fixture and rule in ('database_credential','secret_literal'):continue
                if rule=='database_credential':
                    parsed=urlsplit(match.group())
                    if parsed.password and re.fullmatch(r'\$\{[A-Z_][A-Z0-9_]*\}',parsed.password):continue
                if rule=='database_credential' and name=='.github/workflows/verify.yaml':
                    parsed=urlsplit(match.group())
                    if parsed.username=='rfa_test' and parsed.password=='isolated-ci-password' and parsed.hostname=='127.0.0.1' and parsed.path.startswith('/company_financial_test_'):continue
                failures.append((name,text.count('\n',0,match.start())+1,rule))
    for name,line,rule in failures:print(f'{name}:{line}: {rule} (value suppressed)')
    print(f'Credential pattern check: {checked} text files, {len(failures)} findings.')
    raise SystemExit(bool(failures))


if __name__=='__main__':main()
