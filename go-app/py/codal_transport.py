"""Per-job HTTP-first Codal transport with a persistent Playwright fallback."""
from __future__ import annotations

import http.cookiejar
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from codal_challenge import current_channel

log = logging.getLogger(__name__)
_CHALLENGE_MARKERS = (
    "captcha", "کد امنیتی", "کد تصویری", "security code", "verification code",
)


class CodalHTTPError(RuntimeError):
    def __init__(self, status: int, url: str, retry_at: float | None = None):
        self.status, self.url, self.retry_at = status, url, retry_at
        super().__init__(f"Codal HTTP {status} for {urllib.parse.urlsplit(url).netloc}{urllib.parse.urlsplit(url).path}")


class CodalRateLimited(RuntimeError):
    """Codal refused the feed with a rate-limit envelope even after a pause.

    Callers treat this as "stop scanning for now", not as a broken run: pages
    already collected stay valid and the next run continues from them.
    """


class CodalTransport:
    def __init__(self):
        self.channel = current_channel()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.minimum_interval = max(0.0, float(os.getenv("CODAL_REQUEST_INTERVAL_SECONDS", "2")))
        self._last_request = 0.0
        self._lock = threading.RLock()
        self._playwright = self._browser = self._context = self._page = None
        self._recovery_page = None
        self._browser_mode = False
        self._cache: dict[str, tuple[bytes, str, int]] = {}

    def _pace(self):
        delay = self.minimum_interval - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.monotonic()

    def visible_collection(self) -> bool:
        """True when the real collection must run in a browser the operator sees.

        The operator watches the very tab that is working — no separate log
        window, nothing headless: every feed page and every report body is
        fetched by navigating that page.

        Manual runs are visible by default. The half-hourly automatic run keeps
        the quiet HTTP path so it does not open a window on the operator's
        desktop unattended; set ``CODAL_VISIBLE_BROWSER_AUTOMATIC=1`` to watch it
        too, or ``CODAL_VISIBLE_BROWSER=0`` to turn watching off everywhere.
        """
        if not self.channel:
            return False
        if os.getenv("CODAL_BROWSER_HEADLESS", "0") != "0":
            return False
        if os.getenv("CODAL_VISIBLE_BROWSER", "1") == "0":
            return False
        if os.getenv("CODAL_JOB_SOURCE", "manual") == "automatic":
            return os.getenv("CODAL_VISIBLE_BROWSER_AUTOMATIC", "0") != "0"
        return True

    def _goto_capture_json(self, page, page_url: str, timeout: int):
        """Open Codal's own report list and take the payload it loads itself.

        One navigation, one API call: the operator watches the real filtered list
        while the worker consumes exactly the JSON that page received, so the
        window never shows a second, separately fetched request.
        """
        try:
            with page.expect_response(
                lambda response: ("/api/search/" in response.url
                                  and "/v2/q" in response.url
                                  and response.status == 200),
                timeout=max(15, timeout) * 1000,
            ) as captured:
                page.goto(page_url, wait_until="domcontentloaded", timeout=max(15, timeout) * 1000)
            response = captured.value
            headers = response.all_headers()
            return (response.body(),
                    self._safe_type(headers.get("content-type", "application/json")),
                    response.status, headers)
        except Exception:
            log.debug("report list did not report its own JSON; using the feed URL", exc_info=True)
            return None

    @staticmethod
    def _retry_at(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return time.time() + max(0, int(value.strip()))
        except ValueError:
            try:
                parsed = datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
                return parsed.timestamp()
            except ValueError:
                return None

    @staticmethod
    def _safe_type(content_type: str) -> str:
        return content_type.split(";", 1)[0].strip().lower()

    def _launch_browser(self):
        if self._context is not None:
            return
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        binary = os.getenv("CHROMIUM_BINARY", "").strip()
        if not binary:
            try:
                import MianSql
                binary = str(getattr(MianSql, "CHROMIUM_BINARY", "")).strip()
            except Exception:
                binary = ""
        # Keep the browser visible by default so an operator can inspect Codal's
        # response on the desktop running the server. Set CODAL_BROWSER_HEADLESS=1
        # explicitly for unattended/server-only deployments.
        args = {"headless": os.getenv("CODAL_BROWSER_HEADLESS", "0") != "0"}
        if binary and os.path.isfile(binary):
            args["executable_path"] = binary
        else:
            channel = os.getenv("CODAL_BROWSER_CHANNEL", "").strip()
            if channel:
                args["channel"] = channel
        self._browser = self._playwright.chromium.launch(**args)
        self._context = self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
        )
        cookie_jar = getattr(self.opener, "handlers", [])
        jar = next((getattr(handler, "cookiejar", None) for handler in cookie_jar
                    if isinstance(handler, urllib.request.HTTPCookieProcessor)), None)
        if jar is not None:
            cookies = []
            for cookie in jar:
                item = {"name": cookie.name, "value": cookie.value, "domain": cookie.domain,
                        "path": cookie.path or "/", "secure": bool(cookie.secure)}
                if cookie.expires is not None:
                    item["expires"] = cookie.expires
                cookies.append(item)
            if cookies:
                self._context.add_cookies(cookies)
        self._page = self._context.new_page()
        self._browser_mode = True


    def _looks_like_challenge(self, page, content_type: str) -> bool:
        try:
            title = page.title().lower()
            body = page.locator("body").inner_text(timeout=1200).lower()[:5000]
        except Exception:
            title, body = "", ""
        text = title + " " + body
        if any(marker in text for marker in _CHALLENGE_MARKERS):
            return True
        # An HTML 200 where JSON was expected is suspicious only when controls
        # or verification language exist; ordinary HTML errors stay explicit.
        if "json" in content_type:
            return False
        # ReportList itself has ordinary search inputs and many report/icon
        # images. Their mere co-existence is not evidence of a CAPTCHA. Only
        # classify structural controls when their own accessible attributes
        # explicitly identify a security/captcha field or image.
        structural_markers = (
            "captcha", "security code", "verification code", "کد امنیتی", "کد تصویری",
        )
        try:
            for selector, attributes in (
                ("input:visible", ("id", "name", "placeholder", "aria-label", "title", "class")),
                ("img:visible", ("id", "alt", "aria-label", "title", "class")),
                ("canvas:visible", ("id", "aria-label", "title", "class")),
            ):
                locator = page.locator(selector)
                for i in range(min(locator.count(), 30)):
                    element = locator.nth(i)
                    value = " ".join(filter(None, (element.get_attribute(name) for name in attributes))).lower()
                    if any(marker in value for marker in structural_markers):
                        return True
        except Exception:
            return False
        return False

    def _recovery_ready(self, page) -> bool:
        """Whether the opened ReportList page finished its security check.

        The security modal is gone and the Angular report table is rendered;
        at that point the context cookies are valid for the JSON endpoint.
        """
        try:
            if self._looks_like_challenge(page, "text/html"):
                return False
            return page.locator("table.search-result-table").count() > 0
        except Exception:
            return False

    def _bound_captcha_wait(self) -> None:
        """Automatic runs may still wait for an in-site answer, but only briefly.

        The panel is visible in the app wherever the operator is, so a scheduled
        run is no longer forced to fail the moment Codal challenges it. The wait
        is bounded so an unattended run never holds the browser for the full
        manual timeout either.
        """
        if os.getenv("CODAL_JOB_SOURCE", "manual").strip().lower() != "automatic":
            return
        if not self.channel:
            return
        limit = max(60, int(os.getenv("CODAL_AUTO_CAPTCHA_TIMEOUT_SECONDS", "180")))
        self.channel.captcha_timeout = min(self.channel.captcha_timeout, limit)

    def _codal_captcha_image(self, page):
        """Codal's own captcha image, fetched inside the real page session.

        Same ASP.NET session as the page, so the picture matches the answer the
        operator types here. Returns a data URL or None when the page is on the
        API host (cross-origin) or the endpoint is unavailable.
        """
        try:
            host = urllib.parse.urlsplit(page.url).hostname or ""
        except Exception:
            return None
        if host not in ("www.codal.ir", "codal.ir"):
            return None
        try:
            raw = page.evaluate(
                """async (url) => {
                     const r = await fetch(url, {method: 'POST', credentials: 'include',
                       headers: {'Content-Type': 'application/json; charset=UTF-8'}, body: '{}'});
                     return await r.text();
                   }""", "https://www.codal.ir/ReportsCaptcha.aspx/GetCaptchaImage")
            value = json.loads(raw).get("d") if raw else None
        except Exception:
            log.debug("Codal captcha image unavailable from page context", exc_info=True)
            return None
        return value if isinstance(value, str) and value.startswith("data:image/") else None

    def _codal_captcha_verify(self, page, code: str) -> bool:
        """Submit the typed code to Codal and report whether it was accepted."""
        try:
            raw = page.evaluate(
                """async ([url, code]) => {
                     const r = await fetch(url, {method: 'POST', credentials: 'include',
                       headers: {'Content-Type': 'application/json; charset=UTF-8'},
                       body: JSON.stringify({code})});
                     return await r.text();
                   }""", ["https://www.codal.ir/ReportsCaptcha.aspx/VerifyCaptcha", code])
            return bool(json.loads(raw).get("d"))
        except Exception:
            log.debug("Codal captcha verification failed", exc_info=True)
            return False

    def _captcha(self, page, message: str | None = None):
        if not self.channel:
            raise RuntimeError("Codal challenge needs an interactive job channel")
        self._bound_captcha_wait()
        # Preferred: Codal's real captcha image + verification API. The operator
        # reads the code from the app panel; nothing has to be clicked in Chromium.
        api_image = self._codal_captcha_image(page)
        if api_image:
            self.channel.wait_for_challenge(
                page, kind="text", image_data_url=api_image,
                message=message or (
                    "کدال برای ادامه کد امنیتی می‌خواهد؛ کد را از تصویر بخوانید و همین‌جا وارد کنید؛ "
                    "جمع‌آوری خودکار ادامه می‌دهد."
                ),
                verify_answer=lambda code: self._codal_captcha_verify(page, code),
                refresh_image=lambda: self._codal_captcha_image(page),
            )
            return
        images = page.locator("img:visible,canvas:visible")
        image = images.nth(0) if images.count() else None
        buttons = page.locator("button:visible, input[type=button]:visible")
        refresh = None
        # Refresh is enabled only when a visible control's accessible name or
        # title explicitly identifies it as refresh/reload.
        for i in range(min(buttons.count(), 12)):
            candidate = buttons.nth(i)
            label = " ".join(filter(None, [candidate.inner_text(timeout=500), candidate.get_attribute("aria-label"), candidate.get_attribute("title")])).lower()
            if any(word in label for word in ("refresh", "reload", "تازه", "جدید", "بازآوری")):
                refresh = candidate
                break
        fields = page.locator("input:visible")
        text_count = sum(1 for i in range(min(fields.count(), 12))
                         if (fields.nth(i).get_attribute("type") or "text").lower() in ("text", "tel", "number"))
        submits = page.locator("button:visible:not([type=button]), input[type=submit]:visible")
        submit_count = sum(1 for i in range(min(submits.count(), 12)) if submits.nth(i).is_enabled())
        if image is None and text_count == 0 and submit_count == 0:
            # Nothing on this page can be answered, so blocking the operator
            # would only freeze the job until the captcha timeout.
            log.info("Codal page exposes no captcha controls; skipping the code prompt")
            return
        supported = image is not None and text_count == 1 and submit_count == 1
        kind = "text" if supported else "unsupported"
        if not supported:
            # Without a single, unambiguous form the first image on the page may
            # well be a logo; a viewport shot is what the operator can read.
            image = None
        message = (message or (
            "کدال برای ادامه کد امنیتی می‌خواهد. کد تصویر را وارد کنید." if supported
            else "صفحهٔ تأیید کدال ساختار متنی شناخته‌شده ندارد؛ تصویر برای بررسی نمایش داده شده است."))
        self.channel.wait_for_challenge(page, image, kind=kind, message=message, refresh_locator=refresh)

    def _open_recovery_page(self, recovery_url: str):
        """Open the filtered Codal report list once and keep it in its own tab.

        API retries must not navigate/reload this tab: otherwise the operator's
        CAPTCHA page refreshes in a loop and the answer is lost.
        """
        page = self._recovery_page
        if page is not None and not page.is_closed():
            try:
                page.bring_to_front()
            except Exception:
                pass
            return page
        page = self._context.new_page()
        self._recovery_page = page
        log.info("Opening Codal report list for manual recovery: %s", recovery_url)
        page.goto(recovery_url, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.bring_to_front()
        except Exception:
            pass
        return page

    def _manual_browser_recovery(self, recovery_url: str, retry_at: float | None = None,
                                 *, message: str | None = None, assume_captcha: bool = False):
        """Show Codal's public report page and wait while the operator solves it.

        The recovery URL is built locally from the requested feed page. This
        keeps a headed browser on Codal's interactive UI instead of leaving the
        operator on the JSON endpoint's XML/429 response.

        ``assume_captcha`` publishes the in-site code form even when no security
        modal is detected — used when the feed endpoint already refused us, where
        the code has to be typed in the app rather than in the Chromium window.
        """
        if not self.channel:
            raise RuntimeError("Manual Codal recovery needs an interactive job channel")
        page = self._open_recovery_page(recovery_url)
        if retry_at:
            # Keep the actual page visible during Retry-After; don't hit Codal
            # again until its requested wait has elapsed.
            self.channel.wait_rate_limit(retry_at)
        # Codal sometimes renders the security modal a moment after load.
        page.wait_for_timeout(1000)
        has_challenge = assume_captcha or self._looks_like_challenge(page, "text/html")
        if has_challenge:
            # Type the code in the app: the image and the verification both use
            # this page's session, so the answer applies to the same cookies.
            self._captcha(page, message=message)
        else:
            self._bound_captcha_wait()
            self.channel.update(state="running_browser", stage="recovery",
                                message="صفحهٔ گزارش‌ها باز شد؛ پس از بررسی، ادامه را بزنید.",
                                challenge=None)
            self.channel.wait_for_challenge(
                page, None, kind="inspection",
                message=message or (
                    "کدال درخواست را محدود کرده است. صفحهٔ گزارش‌ها باز شد؛ اگر کد امنیتی دیدید "
                    "همان‌جا حل کنید، سپس ادامه را بزنید."
                ),
                is_resolved=lambda: self._recovery_ready(page),
            )
        self.channel.update(state="running_browser", stage="recovery",
                            message="تأیید دریافت شد؛ درخواست قبلی دوباره بررسی می‌شود.",
                            challenge=None)

    @staticmethod
    def _browser_backoff(retry_number: int) -> float:
        base = max(1.0, float(os.getenv("CODAL_BROWSER_RETRY_BASE_SECONDS", "3")))
        return min(60.0, base * (2 ** max(0, retry_number - 1)))

    def _wait_for_api_retry(self, recovery_url: str | None, retry_at: float | None,
                            retry_number: int, message: str,
                            assume_captcha: bool = False) -> None:
        """Wait out a bounded API retry without leaving the operator on an XML page.

        The recovery tab is opened at most once and never reloaded here; the API
        retry happens on the separate worker page, so a CAPTCHA the operator is
        solving is not refreshed away.

        A plain rate limit only pauses: no panel is published, because there is
        nothing to answer and a waiting panel used to stall the job for minutes.
        ``assume_captcha`` is the only case that asks for a code.
        """
        if assume_captcha and recovery_url and self.channel:
            try:
                page = self._open_recovery_page(recovery_url)
                self._captcha(page, message=message)
            except (InterruptedError, TimeoutError):
                # The operator had the panel open and did not answer in time; the
                # job must end as expired instead of pretending nothing happened.
                raise
            except Exception:
                log.debug("captcha prompt during API wait failed", exc_info=True)
        wait_until = retry_at or time.time() + self._browser_backoff(retry_number)
        if self.channel:
            self.channel.wait_rate_limit(wait_until, message=message)
        else:
            time.sleep(max(0, wait_until - time.time()))

    def _browser_get(self, url: str, timeout: int, *, expect_json=False,
                     recovery_url: str | None = None,
                     recovery_confirmed: bool = False) -> tuple[bytes, str, int]:
        self._launch_browser()
        page = self._page
        challenge_retries = 0
        rate_retries = 0
        inspection_retries = 0
        while True:
            if self.channel:
                # Keep the message published by the sync loop; only the transport
                # state changes here.
                self.channel.update(state="running_browser", stage="browser_request",
                                    challenge=None)
            self._pace()
            captured = None
            if expect_json and recovery_url and "/api/search/" in url:
                # Watch mode: open the real filtered list and consume the JSON it
                # loads itself — the operator sees the page that is being read.
                captured = self._goto_capture_json(page, recovery_url, timeout)
            if captured is not None:
                body, content_type, status, headers = captured
                response = None
                log.info("Codal browser host=%s path=%s status=%s content_type=%s (captured)",
                         urllib.parse.urlsplit(page.url).netloc,
                         urllib.parse.urlsplit(page.url).path, status, content_type)
            else:
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                status = response.status if response else 0
                headers = response.all_headers() if response else {}
                content_type = self._safe_type(headers.get("content-type", ""))
                location = urllib.parse.urlsplit(page.url)
                log.info("Codal browser host=%s path=%s status=%s content_type=%s",
                         location.netloc, location.path, status, content_type)
                try:
                    body = response.body() if response else page.content().encode("utf-8")
                except Exception:
                    body = page.content().encode("utf-8")
            if self._looks_like_challenge(page, content_type):
                if recovery_url and self.channel:
                    self._manual_browser_recovery(recovery_url)
                    recovery_confirmed = True
                    challenge_retries += 1
                    if challenge_retries > 1:
                        raise RuntimeError("Codal challenge retry limit reached")
                    continue
                self._captcha(page)
                challenge_retries += 1
                if challenge_retries > 1:
                    raise RuntimeError("Codal challenge retry limit reached")
                continue
            if status == 429:
                retry_at = self._retry_at(headers.get("retry-after"))
                if (recovery_url and self.channel
                        and os.getenv("CODAL_BROWSER_HEADLESS", "0") == "0"
                        and not recovery_confirmed):
                    self._manual_browser_recovery(recovery_url, retry_at)
                    recovery_confirmed = True
                    continue
                rate_retries += 1
                # One 429 followed by an XML envelope is the same limiter: allow
                # two pauses in total, then stop instead of hammering Codal.
                if rate_retries > 2:
                    raise CodalHTTPError(status, page.url, retry_at)
                self._wait_for_api_retry(
                    recovery_url, retry_at, rate_retries,
                    "API کدال هنوز پاسخ ۴۲۹ می‌دهد؛ پنجره روی صفحهٔ گزارش‌ها باز است و بعد از مکث کوتاه دوباره تلاش می‌کنم.",
                )
                continue
            if status in (403, 429) or status >= 500:
                raise CodalHTTPError(status, page.url)
            if status and status >= 400:
                raise CodalHTTPError(status, page.url)
            if expect_json and not self._valid_json_feed(body):
                headed = os.getenv("CODAL_BROWSER_HEADLESS", "0") == "0"
                # Codal answers the JSON endpoint in two different ways when it
                # refuses: an XML rate-limit envelope (no code involved — waiting
                # it out is the only fix) or an HTML security page (a code helps).
                # Treating both as CAPTCHA used to burn minutes asking for a code
                # that did not exist.
                xml_like = "xml" in content_type or body[:200].lstrip().startswith(b"<?xml")
                # Without a recovery page there is nothing the operator could act
                # on in headless mode, so return the body and let the caller
                # report a precise non-JSON error instead of waiting for a code.
                if self.channel and (headed or recovery_url):
                    if xml_like:
                        rate_retries += 1
                        if rate_retries > 2:
                            raise CodalRateLimited(
                                "کدال موقتاً درخواست‌ها را محدود کرده است (به‌جای داده، پاسخ XML "
                                f"با نوع {content_type or 'نامشخص'} می‌دهد). چند دقیقه صبر کنید و "
                                "«جمع‌آوری» را دوباره بزنید؛ یا «حداکثر صفحات» را کمتر کنید."
                            )
                        # A rate limit needs a real pause, not the 3s default backoff.
                        pause = max(1.0, float(os.getenv("CODAL_RATE_LIMIT_PAUSE_SECONDS", "45")))
                        limited_until = (self._retry_at(headers.get("retry-after"))
                                         or time.time() + max(pause, self._browser_backoff(rate_retries)))
                        self._wait_for_api_retry(
                            recovery_url, limited_until, rate_retries,
                            "کدال موقتاً درخواست‌ها را محدود کرده؛ کمی صبر می‌کنم و همان صفحه را دوباره می‌گیرم.",
                        )
                        continue
                    if recovery_url and not recovery_confirmed:
                        self._manual_browser_recovery(
                            recovery_url,
                            assume_captcha=True,
                            message=(
                                "کدال به‌جای دادهٔ گزارش‌ها صفحهٔ امنیتی برگرداند. کد تصویر را همین‌جا "
                                "وارد کنید؛ پس از تأیید، همان درخواست خودکار تکرار می‌شود."
                            ),
                        )
                        recovery_confirmed = True
                        continue
                    if recovery_url:
                        inspection_retries += 1
                        if inspection_retries > 1:
                            raise RuntimeError(
                                "کدال هنوز به‌جای دادهٔ گزارش‌ها صفحهٔ امنیتی برمی‌گرداند؛ کد پذیرفته نشد یا "
                                "نشست معتبر نیست. چند دقیقه صبر کنید و یک بار دیگر «جمع‌آوری» را بزنید."
                            )
                        self._wait_for_api_retry(
                            recovery_url, self._retry_at(headers.get("retry-after")), inspection_retries,
                            "کدال هنوز پاسخ JSON نمی‌دهد؛ اگر کد امنیتی لازم است همین‌جا وارد کنید.",
                            assume_captcha=True,
                        )
                    else:
                        if inspection_retries >= 1:
                            raise RuntimeError(
                                f"Codal still returned non-JSON content ({content_type or 'unknown content type'}) after retry"
                            )
                        self.channel.wait_for_challenge(
                            page, None, kind="inspection",
                            message=(f"پاسخ feed کدال به‌جای JSON از نوع {content_type or 'نامشخص'} بود. "
                                     "پنجرهٔ مرورگر را بررسی کنید؛ سپس برای تلاش دوباره دکمه را بزنید."),
                        )
                        inspection_retries += 1
                    continue
            return body, content_type, status or 200

    def get(self, url: str, timeout: int = 45, *, expect_json=False,
            recovery_url: str | None = None) -> tuple[bytes, str, int]:
        with self._lock:
            if url in self._cache:
                return self._cache[url]
            # Watch mode: the visible Chromium does the real work, from the very
            # first request, so nothing is fetched behind the operator's back.
            if self._browser_mode or self.visible_collection():
                result = self._browser_get(url, timeout, expect_json=expect_json,
                                           recovery_url=recovery_url)
                if not expect_json or self._valid_json_feed(result[0]):
                    self._cache[url] = result
                return result
            self._pace()
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                "Accept": "application/json, text/plain, */*", "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
                "Referer": "https://www.codal.ir/ReportList.aspx",
            })
            t0 = time.monotonic()
            try:
                with self.opener.open(req, timeout=timeout) as response:
                    status, final_url = response.status, response.geturl()
                    content_type = self._safe_type(response.headers.get("Content-Type", ""))
                    data = response.read(2_000_000)
                    retry = self._retry_at(response.headers.get("Retry-After"))
            except urllib.error.HTTPError as exc:
                status, final_url = exc.code, exc.geturl()
                content_type = self._safe_type(exc.headers.get("Content-Type", ""))
                data = exc.read(32_000)
                retry = self._retry_at(exc.headers.get("Retry-After"))
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                # A socket read timeout is not a URLError; treating it as a hard
                # failure used to abort the whole run instead of letting the
                # browser (which has a different path to Codal) take over.
                reason = getattr(exc, "reason", None)
                log.info("Codal HTTP transport failed for %s: %s", urllib.parse.urlsplit(url).netloc,
                         type(reason).__name__ if reason else type(exc).__name__)
                if self.channel:
                    self.channel.update(state="opening_browser", stage="recovery", message="در حال ادامهٔ دریافت با مرورگر")
                self._launch_browser()
                result = self._browser_get(url, timeout, expect_json=expect_json,
                                           recovery_url=recovery_url)
                if not expect_json or self._valid_json_feed(result[0]):
                    self._cache[url] = result
                return result
            elapsed = int((time.monotonic() - t0) * 1000)
            hostpath = urllib.parse.urlsplit(final_url)
            log.info("Codal HTTP host=%s path=%s status=%s elapsed_ms=%s content_type=%s retry_after=%s",
                     hostpath.netloc, hostpath.path, status, elapsed, content_type,
                     max(0, int(retry-time.time())) if retry else "-")
            if self.channel:
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
                page_number = int((query.get("PageNumber") or ["0"])[0] or 0)
                self.channel.update(state="running_http", stage="discovery" if "PageNumber" in query else "report_body",
                                    current_page=page_number or None,
                                    message="در حال بررسی گزارش‌های کدال" if "PageNumber" in query else "در حال دریافت متن گزارش")
            sample = data[:32000].lower()
            # The "input + image" heuristic belongs to the JSON feed endpoint: a
            # report body is ordinary HTML with many inputs/icons and would
            # otherwise be misread as a challenge, forcing every body through a
            # browser. Explicit captcha wording still applies to both.
            html_challenge = content_type in ("text/html", "application/xhtml+xml") and (
                any(marker.encode("utf-8").lower() in sample for marker in _CHALLENGE_MARKERS)
                or (expect_json and re.search(rb"<input\b", sample) and re.search(rb"<(?:img|canvas)\b", sample))
            )
            if status in (403, 429) or html_challenge:
                if self.channel:
                    self.channel.update(state="opening_browser", stage="recovery", message="در حال ادامهٔ دریافت با مرورگر")
                self._launch_browser()
                if status == 429 and recovery_url and self.channel:
                    # Put the headed browser on the actual Codal UI immediately
                    # so the operator can solve a challenge during Retry-After.
                    self._manual_browser_recovery(recovery_url, retry)
                elif retry:
                    if self.channel:
                        self.channel.update(state="rate_limited", stage="http", retry_at=retry,
                                            message="دریافت گزارش‌ها موقتاً محدود شده؛ مرورگر پس از مهلت ادامه می‌دهد.")
                    time.sleep(max(0, retry - time.time()))
                elif status == 429:
                    time.sleep(2)
                result = self._browser_get(url, timeout, expect_json=expect_json,
                                           recovery_url=recovery_url,
                                           recovery_confirmed=(status == 429 and bool(recovery_url)
                                               and self.channel is not None
                                               and os.getenv("CODAL_BROWSER_HEADLESS", "0") == "0"))
                if not expect_json or self._valid_json_feed(result[0]):
                    self._cache[url] = result
                return result
            if status >= 400:
                raise CodalHTTPError(status, final_url, retry)
            # For JSON endpoints, an HTML 200 is a transport challenge/error,
            # never an empty feed. Browser navigation inspects the real page.
            if expect_json and content_type not in ("application/json", "text/json") and not self._valid_json_feed(data):
                self._launch_browser()
                result = self._browser_get(url, timeout, expect_json=expect_json,
                                           recovery_url=recovery_url)
                if not expect_json or self._valid_json_feed(result[0]):
                    self._cache[url] = result
                return result
            result = (data, content_type, status)
            if not expect_json or self._valid_json_feed(data):
                self._cache[url] = result
            return result

    @staticmethod
    def _valid_json_feed(data: bytes) -> bool:
        try:
            value = json.loads(data.decode("utf-8-sig"))
            return isinstance(value, dict) and isinstance(value.get("Letters"), list) and "Total" in value
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False

    def close(self):
        if self._recovery_page:
            try:
                self._recovery_page.close()
            except Exception:
                pass
            self._recovery_page = None
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def shared_page(self):
        self._launch_browser()
        return self._page

    def navigate(self, page, url: str, timeout: int = 60_000):
        self._browser_mode = True
        for attempt in range(3):
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            content_type = self._safe_type(response.headers.get("content-type", "")) if response else ""
            if self._looks_like_challenge(page, content_type):
                self._captcha(page)
                continue
            if response and response.status >= 400:
                raise CodalHTTPError(response.status, page.url, self._retry_at(response.headers.get("retry-after")))
            return response
        raise RuntimeError("Codal challenge retry limit reached")


_instance: CodalTransport | None = None


def current() -> CodalTransport:
    global _instance
    if _instance is None:
        _instance = CodalTransport()
    return _instance


def close_current():
    global _instance
    if _instance:
        _instance.close()
        _instance = None


def navigate(page, url: str, timeout: int = 60_000):
    if os.getenv("CODAL_JOB_DIR"):
        return current().navigate(page, url, timeout)
    return page.goto(url, wait_until="domcontentloaded", timeout=timeout)

