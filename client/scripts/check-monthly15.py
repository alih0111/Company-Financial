"""Local browser QA: real registered exports, isolated mock API and no account writes."""
from pathlib import Path
import base64
import json
import os

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.runtime/factormix-monthly15/ui'
URL = os.environ.get('RFA_UI_TEST_URL', 'http://localhost:3000')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dashboard = json.loads((ROOT / 'client/public/strategies/factormix-033/dashboard.json').read_text(encoding='utf8'))
    ranking = dashboard['rankings']['latest']
    ranking = dict(ranking, strategy_id=dashboard['strategy_id'], market_date=dashboard['as_of'],
                   computed_at_utc='2026-11-06T17:00:00Z', rows=[dict(r, reason=None,
                    previous_rank=None, previous_score=None, price_date=dashboard['as_of']) for r in ranking['rows']])
    payload = base64.urlsafe_b64encode(json.dumps(dict(username='Local UI test',isAdmin=True,exp=4102444800)).encode()).decode().rstrip('=')
    token = 'eyJhbGciOiJub25lIn0.' + payload + '.local-test'
    errors=[]; calls=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        context=browser.new_context(viewport=dict(width=1440,height=1000),device_scale_factor=1)
        context.add_init_script('localStorage.setItem("token",'+json.dumps(token)+')')
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        def api(route):
            path=route.request.url
            calls.append(dict(method=route.request.method,url=path))
            if path.endswith('/me'):
                route.fulfill(json=dict(username='Local UI test',isAdmin=True))
            elif path.endswith('/factormix/ranking'):
                route.fulfill(json=dict(ranking=ranking,running=False))
            elif '/price-history' in path or '/family/history' in path:
                route.fulfill(json=[])
            else:
                route.fulfill(json={})
        page.route('**/api/**',api)
        page.goto(URL+'/strategy/performance',wait_until='networkidle')
        expect(page.get_by_text('۲٬۹۴۳٬۴۸۲٬۵۶۳',exact=True)).to_be_visible(timeout=20_000)
        chart=page.locator('section[aria-labelledby="capital-chart-title"]')
        dd=page.locator('section[aria-labelledby="drawdown-title"]')
        expect(chart.locator('.recharts-line-curve')).to_have_count(5)
        expect(dd.locator('.recharts-area-curve')).to_have_count(5)
        assert chart.locator('.recharts-line-curve[stroke="#7c3aed"]').count()==1
        chart.get_by_role('button',name='FactorMix · ماهانه ۱۵',exact=False).click()
        expect(chart.locator('.recharts-line-curve')).to_have_count(4)
        expect(dd.locator('.recharts-area-curve')).to_have_count(5)
        chart.get_by_role('button',name='FactorMix · ماهانه ۱۵',exact=False).click()
        page.get_by_role('button',name='بازده تجمعی',exact=True).click()
        expect(chart.locator('.recharts-line-curve')).to_have_count(5)
        page.get_by_role('button',name='ارزش سبد',exact=True).click()
        expect(page.get_by_role('heading',name='عملکرد مدل نهایی · FactorMix ماهانه ۱۵',exact=True)).to_be_visible()
        with page.expect_download() as annual_event:
            page.get_by_role('link',name='دریافت جدول سالانه',exact=True).click()
        annual_download=annual_event.value
        assert annual_download.suggested_filename=='from-1401-monthly15-annual.csv'
        annual_download.save_as(OUT/'selected-annual.csv')
        import csv
        annual=list(csv.DictReader((OUT/'selected-annual.csv').open(encoding='utf-8-sig')))
        assert abs(float(annual[-1]['final_toman'])-2_943_482_563.3857675)<1
        chart.scroll_into_view_if_needed();chart.screenshot(path=str(OUT/'monthly15-chart.png'))
        with page.expect_download() as event:
            page.get_by_role('link',name='مسیر سرمایهٔ ماهانه',exact=True).click()
        download=event.value;download.save_as(OUT/download.suggested_filename)
        assert (OUT/download.suggested_filename).read_bytes()==(ROOT/'strategy_registry/RFA-FactorMix-033-M15/v1.0.0/results/monthly_jalali_15_nav.csv').read_bytes()
        page.set_viewport_size(dict(width=390,height=844))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        chart.screenshot(path=str(OUT/'monthly15-chart-mobile.png'))
        page.goto(URL+'/strategy?tab=ranking',wait_until='networkidle')
        expect(page.get_by_role('heading',name='FactorMix · ماهانه ۱۵',exact=True).last).to_be_visible()
        assert page.get_by_role('link',name='استراتژی گزارش‌محور',exact=True).count()==0
        planner=page.locator('section[aria-labelledby="monthly-planner-title"]')
        expect(planner.get_by_role('button',name='بررسی سبد ماهانه',exact=True)).to_be_enabled()
        planner.get_by_label('نقد فعلی سبد · تومان',exact=True).fill('۱۰۰٬۰۰۰٬۰۰۰')
        planner.get_by_role('button',name='بررسی سبد ماهانه',exact=True).click()
        proposal=planner.get_by_label('پیشنهاد سبد ماهانه',exact=True)
        expect(proposal.locator('tbody tr')).to_have_count(5)
        assert all('۲۰٬۰۰۰٬۰۰۰' in text for text in proposal.locator('tbody tr').all_text_contents())
        planner.get_by_role('button',name='افزودن دارایی',exact=True).click()
        assert proposal.count()==0
        planner.get_by_label('نماد دارایی ۱',exact=True).fill(ranking['rows'][7]['symbol'])
        planner.get_by_label('ارزش روز دارایی ۱ · تومان',exact=True).fill('۲۰٬۰۰۰٬۰۰۰')
        planner.get_by_label('نقد فعلی سبد · تومان',exact=True).fill('۸۰٬۰۰۰٬۰۰۰')
        planner.get_by_role('button',name='بررسی سبد ماهانه',exact=True).click()
        held=proposal.get_by_role('row').filter(has_text=ranking['rows'][7]['symbol'])
        expect(held).to_contain_text('نگهداری')
        with page.expect_download() as event:
            planner.get_by_role('button',name='دریافت پیشنهاد JSON',exact=True).click()
        event.value.save_as(OUT/'proposal.json')
        assert not json.loads((OUT/'proposal.json').read_text(encoding='utf8'))['executed']
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        planner.get_by_role('heading').scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/'monthly15-planner-mobile.png'))
        page.set_viewport_size(dict(width=1440,height=1000))
        planner.screenshot(path=str(OUT/'monthly15-planner-desktop.png'))
        page.goto(URL+'/strategy/reportflow',wait_until='networkidle')
        expect(page.get_by_role('heading',name='آزمایش قبلی گزارش‌محور',exact=True)).to_be_visible()
        assert page.locator('.recharts-line-curve').count()==0
        assert page.get_by_role('button',name='درخواست بررسی',exact=True).count()==0
        assert not any('/api/reportflow' in c['url'] for c in calls)
        page.screenshot(path=str(OUT/'reportflow-archived.png'))
        page.get_by_role('button',name='مشاهدهٔ گزارش آزمایش قدیمی ReportFlow',exact=True).click()
        expect(page.locator('.recharts-line-curve')).to_have_count(3)
        page.get_by_role('link',name='مدل نهایی · FactorMix ماهانه ۱۵',exact=True).click()
        expect(page.get_by_role('heading',name='FactorMix · ماهانه ۱۵',exact=True).last).to_be_visible()
        assert not any(c['method']!='GET' for c in calls),calls
        assert not errors,errors
        browser.close()
    result=dict(status='PASS',curves=5,actual_csv_matches_registered=True,monthly_toggle_and_return_modes=True,
                cash_entry_and_rank8_hold=True,mobile_overflow=False,proposal_download_not_executed=True,
                api_mutations=0,browser_errors=errors,selected_model_home=True,selected_annual_download=True,
                reportflow_archived_and_readonly=True)
    (OUT/'result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result))


if __name__=='__main__':
    main()
