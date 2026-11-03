## زمینه

کاربر دو خطا را در UI دیده و خواسته است به‌جای «فقط نمایش خطا»، سیستم خودش تلاش دوباره کند یا دکمهٔ تلاش دوباره داشته باشد:

1. **«خطای روزانه» سبد کاغذی (P1):** خطای موقت `HTTP 502` از TSETMC هنگام گرفتن شواهد قیمت در اجرای ۱۳:۳۰ تهران. `ranking_research/future_eval_v12_30/http_retry.py` طبق طراحی فقط 429 را دوباره تلاش می‌کند. حساب‌ها سالم‌اند (خطا قبل از هر تغییر رخ داده) و اجرای زمان‌بندی‌شده بعدی خودکار جبران می‌کند، ولی کاربر می‌خواهد با مراجعه به صفحه، تلاش دوباره انجام شود.
2. **«جمع‌آوری سریع ناموفق بود»:** `Page.goto: net::ERR_TUNNEL_CONNECTION_FAILED` — اجرای دستی جمع‌آوری کدال در Chromium بدون override پروکسی اجرا می‌شود (`go-app/py/codal_transport.py:119-161`)، پس از پروکسی سیستم ویندوز پیروی می‌کند و پروکسی تونل CONNECT به search.codal.ir را برقرار نکرد. `page.goto` در `codal_transport.py:447` هیچ retry ندارد و خطای خام به UI می‌رسد (`sync_codal.py:1312-1320` فقط خطای «مرورگر بسته شد» را فارسی می‌کند). اتصال مستقیم به سایت‌های داخلی سالم است، پس fallback به اتصال مستقیم مشکل را برطرف می‌کند.

## بخش ۱ — سبد کاغذی: تلاش دوبارهٔ خودکار هنگام بازدید + دکمهٔ دستی

1. **فایل جدید `go-app/handlers/paper_trial_refresh.go`** (قالب: `go-app/handlers/ranking_refresh.go`):
   - `paperTrialStartBusy atomic.Bool` (CAS → 409 «busy»)؛ ساختار وضعیت `{state, stage, started_at, finished_at, exp_exit_code, trial_exit_code, message, error}`؛ فایل وضعیت `.runtime/paper-trial-refresh-status.json`؛ لاگ `.runtime/paper-trial-refresh.log`.
   - `StartPaperTrialRefresh` (با `adminOnly`): اگر وضعیت Running و کمتر از ۱۵ دقیقه → 202 `already_running`؛ وگرنه Running را می‌نویسد و در goroutine دو اسکریپت را **به‌ترتیب** اجرا می‌کند (آینهٔ `Update-Paper-Portfolio.cmd`):
     - `<python> -B -X utf8 ranking_research/future_eval_v12_30/experimental_paper.py update --publish`
     - `<python> -B -X utf8 ranking_research/future_eval_v12_30/paper_month_trial.py`
     - `cmd.Dir=root`، python از `analyticsRefreshPython(root)` (موجود در `analytics_refresh.go`)، root از `analyticsRepoRoot()`، env: `PYTHONIOENCODING=utf-8` و `PYTHONDONTWRITEBYTECODE=1`؛ هر مرحله exit code و پیام فارسی در فایل وضعیت می‌نویسد (Running → Finished/Failed).
   - `GetPaperTrialRefreshStatus` (adminOnly؛ در نبود فایل → Idle).
2. **`go-app/main.go`** (گروه protected، حدود خط 97-101): `POST /admin/paper-trial/refresh` و `GET /admin/paper-trial/refresh/status`.
3. **`client/src/utils/api.ts`** (آینهٔ `startRankingRefresh`/`getRankingRefreshStatus` خطوط 290-334): `startPaperTrialRefresh()` + `getPaperTrialRefreshStatus()` + تایپ‌های مربوطه، با پیام‌های خطای فارسی.
4. **`client/src/components/PaperTrialPanel.tsx`:**
   - چک ادمین مثل `LatestLockedRanking.tsx` (useGetUser/isAdmin).
   - دکمهٔ «تلاش دوبارهٔ اجرا» کنار دکمهٔ «بازخوانی» (خط 76)؛ وقتی `trial.state==="DAILY_ERRORS"` با رنگ کهربایی برجسته می‌شود؛ حین اجرا غیرفعال با متن «در حال تلاش دوباره…»؛ کلیک → POST → poll هر ۵ ثانیه تا خروج از Running → پیام نهایی فارسی → بامپ `reload` برای بارگیری دوبارهٔ JSONهای استاتیک.
   - **تلاش دوبارهٔ خودکار هنگام بازدید صفحه** وقتی `DAILY_ERRORS` است: فقط برای ادمین، یک بار در هر mount، با cooldown نیم‌ساعته در localStorage.
   - به‌روزرسانی متن راهنما (خط 78) و همهٔ رشته‌های جدید به فارسی.

## بخش ۲ — جمع‌آوری سریع کدال: ترمیم خطای پروکسی + پیام خوانا

1. **`go-app/py/codal_transport.py`:**
   - `_launch_browser`: ساخت آرگومان‌های launch در یک نقطه؛ فلگ جدید `self._browser_direct` که در صورت فعال بودن `args=["--no-proxy-server"]` اضافه می‌کند.
   - هلپر جدید `_goto_resilient(page, url, timeout)`: خطای Playwright را طبقه‌بندی می‌کند:
     - خطاهای تونل/پروکسی (`ERR_TUNNEL_CONNECTION_FAILED`, `ERR_PROXY_CONNECTION_FAILED`): یک تلاش دوباره با همان مرورگر بعد از مکث کوتاه؛ اگر باز شکست خورد و fallback هنوز استفاده نشده: پیام فارسی روی کانال («اتصال از طریق پروکسی سیستم برقرار نشد؛ با اتصال مستقیم ادامه می‌دهم»)، بستن context/مرورگر فعلی (شامل recovery tab و ریست `self._recovery_page`)، `_launch_browser(direct=True)`، و goto روی صفحهٔ جدید؛ response و صفحهٔ جدید را برمی‌گرداند.
     - خطاهای گذرا (`ERR_CONNECTION_RESET`, `ERR_CONNECTION_CLOSED`, `ERR_TIMED_OUT`, `ERR_NETWORK_CHANGED`): حداکثر ۲ تلاش دیگر با backoff (استفاده از `_browser_backoff` موجود).
     - بقیه: رِیز مجدد.
   - `_browser_get`: خواندن `page = self._page` در ابتدای هر دور حلقه و بعد از فراخوانی هلپر (خط 447) تا بعد از relaunch از صفحهٔ جدید استفاده شود.
   - متد کلاس `navigate()` (خطوط 690-701، ناوبری متن گزارش‌ها) هم از همان هلپر استفاده کند.
   - `_goto_capture_json` تغییر نمی‌کند: شکستش بی‌صدا None برمی‌گرداند و goto پشتیبانِ resilient همان را جبران می‌کند.
2. **`go-app/py/sync_codal.py`** — `_friendly_sync_error` (خطوط 1312-1320): نگاشت خطاهای تونل/پروکسی به پیام فارسی («پروکسی سیستم به کدال نرسید و اتصال مستقیم هم پاسخ نداد؛ اتصال اینترنت/پروکسی را بررسی کنید و «جمع‌آوری سریع» را دوباره بزنید.») و خطاهای اتصال/timeout به پیام شبکهٔ کوتاه فارسی؛ خطاهای ناشناخته مثل قبل عبور می‌کنند.
3. **UI نیازی به تغییر ندارد:** دکمهٔ «شروع جمع‌آوری سریع» موجود است؛ فقط پیام خطا خوانا می‌شود و اجرا خودش ترمیم می‌شود.

## فایل‌ها

- جدید: `go-app/handlers/paper_trial_refresh.go`
- تغییر: `go-app/main.go`، `client/src/utils/api.ts`، `client/src/components/PaperTrialPanel.tsx`، `go-app/py/codal_transport.py`، `go-app/py/sync_codal.py`

## نکات ایمنی

- هم‌زمانی با اجراهای زمان‌بندی‌شدهٔ سبد امن است: قفل trial-controller باعث می‌شود python هم‌زمان با کد `PAPER_ACCOUNT_LOCKED` خارج شود که در وضعیت/لاگ دیده می‌شود.
- هر دو endpoint جدید ادمین‌فقط هستند؛ fallback پروکسی فقط مرورگر خود transport را relaunch می‌کند و مسیر HTTP اجرای خودکار نیم‌ساعته دست‌نخورده می‌ماند.
- هیچ رفتار backdating یا دور زدن تقویم معرفی نمی‌شود؛ فقط اجرای همان دو اسکریپت رسمی است.

## راستی‌آزمایی

1. `cd go-app && go build ./... && go vet ./...` و `cd client && npm run build`.
2. **جمع‌آوری سریع E2E:** اجرای go-app، باز کردن «جمع‌آوری سریع» با نوع «همه» و حداکثر ۱۰ صفحه؛ بررسی `go-app/.runtime/codal-jobs/<id>/worker.log` برای تلاش‌های دوباره و پیام fallback؛ با پروکسی سیستم خراب/روشن بودن، اتمام موفق جمع‌آوری با اتصال مستقیم؛ قطع کامل اینترنت → نمایش پیام فارسی جدید به‌جای متن خام Playwright.
3. **سبد کاغذی E2E:** ورود ادمین → PaperTrialPanel → کلیک «تلاش دوبارهٔ اجرا»؛ دیده شدن حرکت `.runtime/paper-trial-refresh-status.json` از Running به Finished، بررسی `.runtime/paper-trial-refresh.log`، تازه شدن `updated_at_utc` در `client/public/research/paper-experimental/trial.json` و پاک شدن خطای P1؛ دابل‌کلیک → رفتار 409/already_running؛ کاربر غیرادمین دکمه را نمی‌بیند و auto-retry اجرا نمی‌شود.