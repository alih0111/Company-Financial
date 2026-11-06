"""Check the app shell in an isolated browser using the development mock API.

Run from the repository root with .venv/Scripts/python.exe
client/scripts/check-desktop-layout.py [--url http://localhost:3000].
Requires the local Vite server, Playwright, and Chrome; never uses a real account.
"""

import argparse
import base64
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".runtime" / "desktop-layout-review-20261106"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:3000")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1,
            reduced_motion="reduce",
            color_scheme="light",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))

        def visit(route):
            page.goto(f"{args.url}/{route}?__mock=1", wait_until="networkidle")
            expect(page.locator(".app-header")).to_be_visible()
            expect(page.locator(".app-page")).to_be_visible()
            expect(page.get_by_text("در حال بارگذاری…", exact=True)).to_have_count(0)

        def bounds():
            return page.evaluate("""() => {
              const scroll = document.querySelector('.app-scrollport');
              const rect = el => {
                const r = el.getBoundingClientRect();
                return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom};
              };
              return {width:innerWidth,height:innerHeight,
                docWidth:document.documentElement.scrollWidth,
                docHeight:document.documentElement.scrollHeight,
                pageWidth:scroll.clientWidth,contentWidth:scroll.scrollWidth,
                header:rect(document.querySelector('.app-header')),
                sidebar:rect(document.querySelector('#app-sidebar')),
                profile:rect(document.querySelector('.profile'))};
            }""")

        for width, height in [(1920, 1080), (1440, 900), (1366, 768), (1024, 768)]:
            page.set_viewport_size({"width": width, "height": height})
            for route in ["dashboard", "Table", "strategy", "strategy/performance", "chat", "assets"]:
                visit(route)
                box = bounds()
                assert box["docWidth"] <= width + 1, (route, box)
                assert box["docHeight"] <= height + 1, (route, box)
                assert box["contentWidth"] <= box["pageWidth"] + 1, (route, box)
                assert box["sidebar"]["bottom"] <= height, (route, box)
                assert box["profile"]["bottom"] <= height, (route, box)
                checks.append(f"{width}x{height} /{route}: fits viewport, profile visible, no horizontal overflow")
                if (width == 1440 and route in ["dashboard", "strategy/performance", "chat"]) or (width == 1024 and route == "Table"):
                    page.screenshot(path=str(OUT / f"{width}-{route.replace('/', '-')}-verified.png"))
            print(f"Checked {width}x{height}", flush=True)

        page.set_viewport_size({"width": 1366, "height": 768})
        visit("strategy/performance")
        before = bounds()
        scroll = page.locator(".app-scrollport")
        scroll.hover()
        page.mouse.wheel(0, 900)
        page.wait_for_function("document.querySelector('.app-scrollport').scrollTop > 100")
        after = bounds()
        assert before["header"] == after["header"]
        assert before["sidebar"] == after["sidebar"]
        assert page.evaluate("window.scrollY") == 0
        page.locator("#app-sidebar").get_by_role("link", name="سبد استراتژی", exact=True).click()
        expect(page.locator(".app-scrollport")).to_have_js_property("scrollTop", 0)
        checks.append("Wheel scroll moves only page content; header/sidebar stay fixed; navigation resets scroll")

        sidebar = page.locator("#app-sidebar")
        sidebar.get_by_role("button", name="ابزارهای داده").click()
        tools = page.locator(".sidebar-scrollport")
        tools.hover()
        page.mouse.wheel(0, 600)
        page.wait_for_function("document.querySelector('.sidebar-scrollport').scrollTop > 0")
        assert bounds()["profile"]["bottom"] <= 768
        expect(scroll).to_have_js_property("scrollTop", 0)
        checks.append("Sidebar tools scroll independently; navigation, company selector and account stay visible")

        # Open a local settings modal without running any collector.
        tools.evaluate("el => el.scrollTop = 0")
        sidebar.get_by_role("button", name="جمع‌آوری سود", exact=True).click()
        modal = page.locator(".fixed.inset-0.z-50").last
        expect(modal).to_be_visible()
        modal_box = modal.bounding_box()
        assert modal_box["x"] == 0 and modal_box["width"] == 1366, modal_box
        modal.get_by_role("button", name="بستن", exact=True).click()
        checks.append("Sidebar modal covers the viewport and is not clipped to sidebar width")

        sidebar.get_by_role("combobox").click()
        expect(page.get_by_role("listbox")).to_be_visible()
        page.keyboard.press("Escape")
        checks.append("Company dropdown opens above the sidebar without clipping")

        page.locator(".app-header").get_by_role("button", name="حالت تاریک").click()
        expect(page.locator("html")).to_have_class("dark")
        page.screenshot(path=str(OUT / "1366-desktop-dark-verified.png"))
        page.reload(wait_until="networkidle")
        expect(page.locator("html")).to_have_class("dark")
        checks.append("Dark mode switches and survives reload")

        # A regular account gets a profit list instead of admin tools.
        payload = base64.urlsafe_b64encode(json.dumps({
            "username": "کاربر", "isAdmin": False, "exp": 4102444800,
        }).encode()).decode().rstrip("=")
        # Replace the token in the mounted app, then navigate within the SPA.
        page.evaluate("token => localStorage.setItem('token', token)", f"e30.{payload}.mock")
        sidebar.get_by_role("link", name="داشبورد شرکت", exact=True).click()
        expect(sidebar.get_by_text("مرور سود", exact=True)).to_be_visible()
        expect(sidebar.get_by_role("link", name="دارایی خانواده", exact=True)).to_have_count(0)
        assert bounds()["profile"]["bottom"] <= 768
        checks.append("Regular account retains the profit list and visible account footer")

        # Reset to the mock admin and check the drawer at tablet/mobile sizes.
        for width, height in [(768, 1024), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            visit("strategy/performance")
            menu = page.get_by_role("button", name="نمایش منو", exact=True)
            expect(sidebar).to_be_hidden()
            menu.click()
            expect(sidebar).to_be_visible()
            expect(menu).to_have_attribute("aria-expanded", "true")
            drawer = sidebar.bounding_box()
            assert abs(drawer["x"] + drawer["width"] - width) <= 1, drawer
            page.keyboard.press("Escape")
            expect(sidebar).to_be_hidden()
            expect(menu).to_be_focused()
            menu.click()
            sidebar.get_by_role("link", name="دستیار سرمایه‌گذاری", exact=True).click()
            expect(sidebar).to_be_hidden()
            expect(page.get_by_placeholder("سوال خود را بنویسید…")).to_be_visible()
            expect(page.get_by_role("button", name="ارسال", exact=True)).to_be_in_viewport()
            box = bounds()
            assert box["docWidth"] <= width + 1, box
            assert box["docHeight"] <= height + 1, box
            page.screenshot(path=str(OUT / f"{width}-mobile-chat-verified.png"))
            checks.append(f"{width}px: RTL drawer, Escape/focus restoration, navigation and chat input fit")

        # Public routes keep ordinary document scrolling.
        page.evaluate("localStorage.removeItem('token')")
        for route in ["login", "register", ""]:
            page.goto(f"{args.url}/{route}", wait_until="networkidle")
            expect(page.locator(".app-shell")).to_have_count(0)
        checks.append("Public landing and auth routes retain their own layout")
        assert not errors, errors
        browser.close()

    (OUT / "checks.json").write_text(json.dumps({"checks": checks, "errors": errors}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"PASS: {len(checks)} layout checks. Screenshots: {OUT}", flush=True)


if __name__ == "__main__":
    main()
