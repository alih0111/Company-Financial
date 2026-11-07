"""Verify the selected strategy portfolio against the actual registered export."""
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.runtime/factormix-monthly15/portfolio-ui'
URL = os.environ.get('RFA_UI_TEST_URL', 'http://localhost:3000')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = json.loads((ROOT / 'client/public/strategies/factormix-033/performance/from-1401-monthly15-portfolio.json').read_text(encoding='utf8'))
    errors, writes = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe', headless=True)
        page = browser.new_page(viewport=dict(width=1440, height=1100), device_scale_factor=1)
        page.on('pageerror', lambda error: errors.append(str(error)))

        def api(route):
            if route.request.method != 'GET':
                writes.append(route.request.url)
            if route.request.url.endswith('/me'):
                route.fulfill(json=dict(username='Local UI test', isAdmin=True))
            elif route.request.url.endswith('/factormix/ranking'):
                route.fulfill(json=dict(ranking=None, running=False))
            else:
                route.fulfill(json={})

        page.route('**/api/**', api)
        page.goto(URL + '/strategy', wait_until='networkidle')
        panel = page.locator('#strategy-portfolio')

        def screenshot(name):
            # The application scrolls inside a fixed shell. Unclip it only for
            # the capture so a tall element screenshot includes its own content.
            style = page.add_style_tag(content='''
                .app-shell { height: auto !important; overflow: visible !important; }
                .app-layout { height: auto !important; }
                .app-main, .app-scrollport { overflow: visible !important; }
            ''')
            panel.screenshot(path=str(OUT / name))
            style.evaluate('(el) => el.remove()')

        expect(panel.get_by_role('heading', name='سبد و خریدوفروش‌ها')).to_be_visible()
        cards = panel.get_by_label('دارایی‌های فعلی مدل').locator('article')
        expect(cards).to_have_count(len(source['positions']))
        expect(cards.filter(has_text='شمواد')).to_contain_text('فروش اجرا نشده')
        expect(cards.filter(has_text='شمواد')).to_contain_text('۸ روز قدیمی‌تر')
        panel.scroll_into_view_if_needed()
        screenshot('holdings-desktop.png')
        panel.get_by_role('button', name='خریدوفروش‌های سباقر', exact=True).click()
        ledger = panel.get_by_label('دفتر خریدوفروش مدل')
        expect(ledger.get_by_role('searchbox')).to_have_value('سباقر')
        assert all('سباقر' in row for row in ledger.locator('ol li').all_text_contents())
        ledger.get_by_role('searchbox').fill('')
        ledger.get_by_role('button', name='فروش‌ها', exact=True).click()
        assert all('فروش' in row for row in ledger.locator('ol li').all_text_contents())
        expect(ledger.locator('ol li')).to_have_count(10)
        first = ledger.locator('ol li').first.inner_text()
        ledger.get_by_role('button', name='بعدی', exact=True).click()
        assert ledger.locator('ol li').first.inner_text() != first
        ledger.get_by_role('button', name='خریدها', exact=True).click()
        assert all('خرید' in row for row in ledger.locator('ol li').all_text_contents())
        ledger.get_by_role('searchbox').fill('نماد ناموجود')
        expect(ledger.get_by_role('status')).to_contain_text('معامله‌ای با این فیلتر پیدا نشد')
        ledger.get_by_role('searchbox').fill('')
        ledger.get_by_role('button', name='همه', exact=True).click()
        with page.expect_download() as download:
            ledger.get_by_role('link', name='دریافت همهٔ معاملات').click()
        download.value.save_as(OUT / 'trades.csv')
        assert (OUT / 'trades.csv').read_bytes() == (ROOT / 'strategy_registry/RFA-FactorMix-033-M15/v1.0.0/results/monthly_jalali_15_trades.csv').read_bytes()
        screenshot('trades-desktop.png')
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        assert panel.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
        screenshot('trades-mobile.png')
        panel.get_by_role('button', name='دارایی‌های فعلی', exact=False).click()
        expect(cards).to_have_count(6)
        assert panel.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
        screenshot('holdings-mobile.png')
        page.evaluate('document.documentElement.classList.add("dark")')
        screenshot('holdings-dark.png')
        page.route('**/from-1401-monthly15-portfolio.json', lambda route: route.fulfill(status=503))
        panel.get_by_role('button', name='بازخوانی سبد', exact=True).click()
        expect(panel.get_by_role('alert')).to_be_visible()
        expect(cards).to_have_count(0)
        page.unroute('**/from-1401-monthly15-portfolio.json')
        panel.get_by_role('button', name='بازخوانی سبد', exact=True).click()
        expect(cards).to_have_count(6)
        assert not errors, errors
        assert not writes, writes
        browser.close()
    result = dict(status='PASS', holdings=6, trades=len(source['trades']), filters=True,
                  pagination=True, csv_matches_registered=True, mobile_overflow=False,
                  error_and_retry=True, api_mutations=writes, browser_errors=errors)
    (OUT / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
