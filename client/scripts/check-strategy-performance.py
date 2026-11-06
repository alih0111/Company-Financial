"""Headless UI smoke test against a dev Vite server; uses the existing dev mock.

Run with the project Python (Playwright installed), with Vite on localhost:3015.
The report/CSV data are the real verified local exports. Backend-only account
and gold requests use the existing __mock development adapter. No real login,
broker session, collector, trade or remote service is used.
"""
from pathlib import Path
import json
import re
import sys

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'.runtime/factormix-performance-ui-20261106'
OUT.mkdir(parents=True,exist_ok=True)
URL='http://localhost:3015/strategy/performance?__mock=1'


def main():
    checks=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(URL,wait_until='networkidle')
        expect(page.get_by_text('۲٬۵۴۷٬۴۶۵٬۸۲۱',exact=True)).to_be_visible(timeout=20_000)
        expect(page.get_by_role('button',name=re.compile('شروع ۱۴۰۱'))).to_have_attribute('aria-pressed','true')
        assert page.locator('.recharts-wrapper').count()==2
        assert page.locator('.recharts-line-curve').count()==4
        main_chart=page.locator('section[aria-labelledby="capital-chart-title"]')
        expect(main_chart.locator('.recharts-line-curve')).to_have_count(4)
        expect(main_chart).to_contain_text(re.compile(r'۶\s+فروردین\s+۱۴۰۱'))
        expect(main_chart).to_contain_text(re.compile(r'۱۳\s+آبان\s+۱۴۰۵'))
        checks.append('four-series main chart starts in Farvardin 1401 even with short mock API histories')
        colors=main_chart.locator('.recharts-line-curve').evaluate_all('(lines)=>lines.map(p=>p.getAttribute("stroke"))')
        assert set(colors)=={'#059669','#94a3b8','#0284c7','#d97706'},colors
        drawdown_chart=page.locator('section[aria-labelledby="drawdown-title"]')
        expect(drawdown_chart.locator('.recharts-area-curve')).to_have_count(4)
        drawdown_colors=drawdown_chart.locator('.recharts-area-curve').evaluate_all('(lines)=>lines.map(p=>p.getAttribute("stroke"))')
        assert set(drawdown_colors)=={'#059669','#94a3b8','#0284c7','#d97706'},drawdown_colors
        drawdown_text=drawdown_chart.text_content()
        main_chart.get_by_role('button',name='کل مسیر حساب · مدل و P1',exact=True).click()
        expect(main_chart.locator('.recharts-line-curve')).to_have_count(2)
        expect(drawdown_chart.locator('.recharts-area-curve')).to_have_count(4)
        assert drawdown_chart.text_content()==drawdown_text
        main_chart.get_by_role('button',name='همه باهم · بازهٔ مشترک',exact=True).click()
        expect(main_chart.locator('.recharts-line-curve')).to_have_count(4)
        checks.append('main chart shows all four series by default; full-account toggle works')
        checks.append('1401 default, correct final value, two main charts rendered')
        page.screenshot(path=str(OUT/'desktop-1401.png'),full_page=True)
        main_chart.screenshot(path=str(OUT/'main-full-1401.png'))
        drawdown_chart.screenshot(path=str(OUT/'drawdown-all-1401.png'))
        checks.append('four drawdown curves and maxima remain stable across capital chart modes')
        page.get_by_role('button',name='بازده تجمعی',exact=True).click()
        expect(page.get_by_role('button',name='بازده تجمعی',exact=True)).to_have_attribute('aria-pressed','true')
        expect(main_chart.locator('.recharts-line-curve')).to_have_count(4)
        page.get_by_role('button',name='ارزش سبد',exact=True).click()
        page.get_by_role('button',name='مقیاس لگاریتمی',exact=True).click()
        expect(page.get_by_role('button',name='مقیاس خطی',exact=True)).to_be_visible()
        checks.append('cumulative-return and linear/log controls work')
        page.get_by_role('button',name=re.compile('شروع ۱۴۰۲')).click()
        expect(page.get_by_text('۱٬۲۹۰٬۴۶۵٬۶۰۶',exact=True)).to_be_visible()
        assert page.get_by_text('۲٬۵۴۷٬۴۶۵٬۸۲۱',exact=True).count()==0
        link=page.get_by_role('link',name='مسیر سرمایهٔ مدل',exact=True)
        expect(link).to_have_attribute('href',re.compile('from-1402-candidate-nav.csv$'))
        with page.expect_download() as event:
            link.click()
        download=event.value
        assert download.suggested_filename=='from-1402-candidate-nav.csv'
        target=OUT/download.suggested_filename;download.save_as(target)
        first=target.read_text(encoding='utf-8-sig').splitlines()[1]
        assert first.startswith('2023-03-25,100000000.0,100000000.0,0')
        checks.append('1402 selection updates metrics, URL and actual CSV download')
        page.set_viewport_size({'width':390,'height':844})
        page.get_by_role('button',name=re.compile('شروع ۱۴۰۱')).click()
        expect(page.get_by_text('۲٬۵۴۷٬۴۶۵٬۸۲۱',exact=True)).to_be_visible()
        width=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
        assert width['scroll']<=width['width']+1,width
        page.screenshot(path=str(OUT/'mobile-1401.png'),full_page=True)
        checks.append('390px mobile has no page-level horizontal overflow')
        # A tampered report must fail closed; retry must recover without a reload.
        original=json.loads((ROOT/'client/public/strategies/factormix-033/performance/performance.json').read_text(encoding='utf8'))
        original['cases'][0]['accounts']['candidate']['final_toman']+=1_000_000
        page.route('**/performance/performance.json',lambda route:route.fulfill(json=original))
        page.reload(wait_until='networkidle')
        expect(page.get_by_role('heading',name='گزارش عملکرد بارگذاری نشد')).to_be_visible()
        assert page.get_by_text('۲٬۵۴۷٬۴۶۵٬۸۲۱',exact=True).count()==0
        page.unroute('**/performance/performance.json')
        page.get_by_role('button',name='تلاش دوباره',exact=True).click()
        expect(page.get_by_text('۲٬۵۴۷٬۴۶۵٬۸۲۱',exact=True)).to_be_visible()
        checks.append('invalid report is rejected and retry recovers')
        assert not errors,errors
        context.close();browser.close()
    result={'status':'PASS','checks':checks,'uncaught_browser_errors':errors}
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':
    try:main()
    except Exception:
        sys.stderr.write('Strategy performance UI smoke test failed.\n')
        raise
