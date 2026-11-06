"""Browser checks with real exported backtest and the existing dev-only mock."""
import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.runtime/reportflow/ui'
URL = 'http://localhost:3000/strategy/reportflow?__mock=1'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = json.loads((ROOT / 'client/public/strategies/reportflow-033/backtest.json').read_text('utf8'))
    checks = []; errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = context.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(URL, wait_until='networkidle')
        expect(page.get_by_role('heading', name='سبد با رسیدن گزارش‌ها بررسی می‌شود')).to_be_visible(timeout=20000)
        expect(page.get_by_text('۵۰۰٬۶۱۹٬۹۲۵', exact=True).first).to_be_visible()
        expect(page.locator('.recharts-line-curve')).to_have_count(3)
        expect(page.get_by_role('link', name='مشاهدهٔ FactorMix اصلی')).to_have_attribute('href', '/strategy')
        checks.append('real 1401 results, all three curves and independent parent link render')
        with page.expect_download() as event:
            page.get_by_role('link', name='همهٔ خرید و فروش‌ها', exact=True).click()
        download = event.value; target = OUT / download.suggested_filename; download.save_as(target)
        lines = target.read_text(encoding='utf-8-sig').splitlines()
        assert len(lines) - 1 == result['accounts']['reportflow']['fills']
        checks.append('downloaded real transaction ledger has all 659 fills')
        page.get_by_role('heading', name='سبد با رسیدن گزارش‌ها بررسی می‌شود').scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / 'desktop.png'), full_page=True)
        page.locator('[aria-label="نمودار ارزش سبد ReportFlow، FactorMix اصلی و کنترل فصلی"]').screenshot(path=str(OUT / 'comparison-chart.png'))
        page.set_viewport_size({'width': 390, 'height': 844})
        expect(page.get_by_role('heading', name='سبد با رسیدن گزارش‌ها بررسی می‌شود')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        page.screenshot(path=str(OUT / 'mobile.png'), full_page=True)
        checks.append('390px mobile has no page overflow')
        # Invalid version fails visibly and retry recovers from the real source.
        invalid = {**result, 'strategy_id': 'wrong-version'}
        page.route('**/strategies/reportflow-033/backtest.json', lambda route: route.fulfill(json=invalid))
        page.reload(wait_until='networkidle')
        expect(page.get_by_text('گزارش ReportFlow معتبر نیست.', exact=True)).to_be_visible()
        page.unroute('**/strategies/reportflow-033/backtest.json')
        page.get_by_role('button', name='تلاش دوباره', exact=True).click()
        expect(page.get_by_text('۵۰۰٬۶۱۹٬۹۲۵', exact=True).first).to_be_visible()
        checks.append('wrong strategy version is rejected and retry recovers')
        assert not errors, errors
        browser.close()
    (OUT / 'result.json').write_text(json.dumps(dict(status='PASS', checks=checks, browser_errors=errors), indent=2), encoding='utf8')
    print(json.dumps(dict(status='PASS', checks=checks)))


if __name__ == '__main__':
    main()
