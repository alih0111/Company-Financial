"""Verify a running deployment using an isolated test account in CI only."""
import json
import urllib.error
import urllib.request
import argparse


def main():
    parser=argparse.ArgumentParser(description='Read-only public deployment checks')
    parser.add_argument('url')
    args=parser.parse_args()
    base=args.url.rstrip('/')
    for path,expected in [('/',200),('/login',200),('/api/health/live',200),('/api/health/ready',200),('/api/portfolio',401),('/api/family/assets',401),('/api/does-not-exist',404),('/.env',404),('/performance',200),('/api/strategy/summary',200),('/strategies/factormix-033/performance/performance.json',401),('/strategies/factormix-033/trades.csv',401),('/research/future-eval-v12-28-contract.json',401)]:
        try:
            response=urllib.request.urlopen(base+path,timeout=15)
        except urllib.error.HTTPError as error:
            response=error
        with response:
            if response.status!=expected:
                raise SystemExit(f'Failed {path}: status {response.status}, expected {expected}')
            if response.headers.get('X-Content-Type-Options')!='nosniff':
                raise SystemExit(f'Missing security header: {path}')
            if path.startswith('/api/health/'):
                json.load(response)
        print(f'PASS {path}: {expected}')


if __name__=='__main__':
    main()
