import React, { useEffect, useState } from "react";
import { type SyncCodalMode, type SyncCodalSummary } from "../utils/api";
import { useCodalSyncJob } from "../hooks/useCodalSyncJob";
import CodalCaptchaPanel from "./CodalCaptchaPanel";

interface QuickSyncModalProps {
  visible: boolean;
  onClose: () => void;
  onRunningChange?: (running: boolean) => void;
}

const modeOptions: { value: SyncCodalMode; label: string }[] = [
  { value: "all", label: "همه" },
  { value: "financial", label: "مالی" },
  { value: "monthly", label: "ماهانه" },
];

const QuickSyncModal: React.FC<QuickSyncModalProps> = ({
  visible,
  onClose,
  onRunningChange,
}) => {
  const sync = useCodalSyncJob(visible);
  const [mode, setMode] = useState<SyncCodalMode>("all");
  const [maxPages, setMaxPages] = useState<string>("");
  const running = sync.running;
  const summary: SyncCodalSummary | null = sync.summary;
  const errorMsg = sync.error;

  useEffect(() => { onRunningChange?.(running); }, [onRunningChange, running]);

  if (!visible) return null;

  const handleRun = async () => {
    if (running) return;
    sync.clearError();
    await sync.start({ mode, dry_run: false, max_pages: maxPages ? Number(maxPages) : undefined });
  };

  const handleClose = () => {
    onClose();
  };

  const total = summary?.total;
  const financialNew = summary?.financial?.new ?? 0;
  const monthlyNew = summary?.monthly?.new ?? 0;
  const newCount = total?.new ?? 0;
  const failed = total?.failed ?? 0;
  const completed = total?.completed ?? 0;
  const quarantined = total?.quarantined ?? 0;
  const repaired = total?.repaired ?? 0;
  const repairFailed = total?.repair_failed ?? 0;
  const quarantinedSymbols = Object.entries(total?.quarantined_symbols ?? {})
    .sort((a, b) => b[1] - a[1]);
  const syncFailed = summary?.success === false;
  const backfillStopped = [summary?.financial, summary?.monthly].some(
    (feed) => feed?.stop_reason === "backfill_floor_reached",
  );
  const scanIncomplete =
    backfillStopped ||
    [summary?.financial, summary?.monthly].some(
      (feed) => feed?.stop_reason === "max_pages_reached",
    );
  const rateLimited = [summary?.financial, summary?.monthly].some(
    (feed) => feed?.stop_reason === "rate_limited",
  );

  const scanWindow = (() => {
    const from = total?.scan_oldest;
    const to = total?.scan_newest;
    if (!from || !to) return null;
    const fmt = (iso: string) => {
      const date = new Date(iso);
      if (Number.isNaN(date.getTime())) return iso;
      return date.toLocaleString("fa-IR", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    };
    return { from: fmt(from), to: fmt(to) };
  })();

  return (
    <div className="fixed inset-0 z-50 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center">
      <div
        dir="rtl"
        className="bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 rounded-2xl shadow-2xl w-full max-w-lg p-6 transition-all duration-300"
      >
        <h2 className="text-2xl font-semibold mb-1 text-center">
          ⚡ جمع‌آوری سریع
        </h2>
        <p className="text-xs text-center text-gray-500 dark:text-gray-400 mb-5">
          فقط گزارش‌های جدید کدال برای نمادهای تحت پوشش شما بررسی و دریافت
          می‌شود.
          <span className="mt-1 block text-[11px] text-gray-400 dark:text-gray-500">
            مرورگر فقط وقتی باز می‌شود که گزارش جدیدی برای دریافت متن وجود داشته
            باشد؛ اگر همه قبلاً دریافت شده باشند، پنجره‌ای باز نمی‌شود.
          </span>
        </p>

        {/* تنظیمات پیشرفته (اختیاری) */}
        <div className="flex flex-col gap-3 mb-5">
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              نوع گزارش
            </label>
            <div className="flex gap-2">
              {modeOptions.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  disabled={running}
                  onClick={() => setMode(opt.value)}
                  className={`flex-1 h-9 rounded-xl text-sm transition-all duration-200 disabled:opacity-50 ${
                    mode === opt.value
                      ? "bg-indigo-600 text-white shadow-sm"
                      : "bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            {mode !== "monthly" && (
              <p className="mt-1 text-[11px] leading-5 text-gray-400 dark:text-gray-500">
                در «مالی» فقط گزارش‌های حسابرسی‌نشده دریافت می‌شوند؛ گزارش‌های
                حسابرسی‌شده/تلفیقی (زیرمجموعه‌ها) کنار گذاشته می‌شوند.
              </p>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              حداکثر صفحات (خالی = خودکار تا آخرین sync و در صورت وجود گزارش
              عقب‌افتاده تا بازهٔ بازگشتی؛ عدد = فقط همان عمق)
            </label>
            <input
              type="number"
              min="1"
              disabled={running}
              value={maxPages}
              placeholder="خودکار"
              onChange={(e) => setMaxPages(e.target.value)}
              className="w-full h-9 px-3 rounded-xl border border-gray-300 dark:border-gray-600 dark:bg-gray-800 text-center focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
            />
            <p className="mt-1 text-[11px] leading-5 text-gray-400 dark:text-gray-500">
              هر صفحه ۲۰ نامهٔ کدال است (نه ۲۰ نماد شما)؛ ۲ صفحه معمولاً فقط
              حدود دو ساعت اخیر را می‌پوشاند.
            </p>
          </div>
        </div>

        {/* وضعیت اجرا */}
        {running && (
          <div className="mb-4 rounded-xl bg-indigo-50 p-3 text-center text-sm text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-300">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
                fill="none"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            {sync.job?.message || (sync.job?.state === "opening_browser" ? "در حال ادامه با مرورگر" : sync.job?.state === "rate_limited" ? "در انتظار رفع محدودیت کدال" : "در حال بررسی گزارش‌های کدال")}
            {sync.job?.source === "automatic" && <span className="mr-2 text-xs">· اجرای خودکار</span>}
            {sync.job?.current_page ? <span className="mr-2 text-xs">· صفحه {sync.job.current_page}</span> : null}
            {sync.job?.parameters && <div className="mt-1 text-xs">تنظیمات این اجرا: {sync.job.parameters.mode || "all"}{sync.job.parameters.symbol ? ` · ${sync.job.parameters.symbol}` : " · همهٔ نمادها"}{sync.job.parameters.max_pages ? ` · حداکثر ${sync.job.parameters.max_pages} صفحه` : ""}</div>}
            {sync.job?.counters && <div className="mt-1 text-xs">بررسی‌شده {sync.job.counters.scanned ?? 0} · جدید {sync.job.counters.new ?? 0} · استخراج‌شده {sync.job.counters.completed ?? 0} · خطا {sync.job.counters.failed ?? 0}</div>}
            {sync.error && <div role="status" className="mt-1 text-xs text-amber-700 dark:text-amber-300">اتصال وضعیت موقتاً برقرار نشد؛ دوباره تلاش می‌شود.</div>}
          </div>
        )}
        {sync.job?.state === "waiting_captcha" && <CodalCaptchaPanel job={sync.job} pending={sync.actionPending} error={sync.actionError} onAnswer={sync.answer} onRefresh={sync.refresh} onResume={sync.resumeInBrowser} onCancel={sync.cancel} />}

        {/* خطای سطح درخواست */}
        {errorMsg && !running && !sync.job && (
          <div className="mb-4 p-3 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
            جمع‌آوری ناموفق بود.
            <div className="mt-1 text-xs break-words">{errorMsg}</div>
          </div>
        )}
        {sync.job?.error && !running && (
          <div role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">{sync.job.error.message}</div>
        )}

        {/* خطای سطح اجرا (پاسخ بدون total — مثلا خطای اتصال به کدال) */}
        {summary && !total && !running && (
          <div className="mb-4 p-3 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
            جمع‌آوری سریع ناموفق بود.
            <div className="mt-1 text-xs break-words">
              {summary.error || "خطای ناشناخته"}
            </div>
          </div>
        )}

        {/* خروجی موفق */}
        {summary && total && !running && (
          <div className="mb-4 text-sm">
            {rateLimited ? (
              <p className="text-center text-amber-700 dark:text-amber-300 font-medium">
                کدال موقتاً درخواست‌ها را محدود کرد؛ اسکن همان‌جا ایستاد و
                گزارش‌های صفحات قبلی ذخیره شد. چند دقیقه بعد یک بار دیگر
                «جمع‌آوری سریع» را بزنید.
              </p>
            ) : scanIncomplete ? (
              <p className="text-center text-amber-700 dark:text-amber-300 font-medium">
                {backfillStopped
                  ? "اسکن تا مرز بازهٔ بازگشتی عقب رفت؛ گزارش‌های قدیمی‌تر از این بازه بررسی نشدند."
                  : "اسکن به سقف صفحات رسید؛ نتیجه کامل نیست و هنوز نمی‌توان گفت گزارشی وجود ندارد."}
              </p>
            ) : newCount === 0 && failed === 0 ? (
              <p className="text-center text-gray-600 dark:text-gray-300 font-medium">
                گزارش جدیدی برای نمادهای شما پیدا نشد.
              </p>
            ) : syncFailed ? (
              <p className="text-center text-red-600 dark:text-red-400 font-semibold mb-3">
                جمع‌آوری با خطا متوقف شد — {failed} گزارش ناموفق
              </p>
            ) : (
              <p className="text-center font-semibold mb-3 text-emerald-600 dark:text-emerald-400">
                جمع‌آوری سریع تمام شد
              </p>
            )}

            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 tabular-nums">
              <Row label="گزارش‌های بررسی‌شده" value={total.scanned} />
              <Row
                label="گزارش‌های نمادهای خارج از لیست"
                value={total.skipped_unknown_ticker}
              />
              <Row label="گزارش‌های قبلاً دریافت‌شده" value={total.already} />
              <Row label="گزارش‌های جدید" value={newCount} />
              <Row label="جمع‌آوری موفق" value={completed} />
              {repaired > 0 && (
                <Row label="گزارش‌های ناقص تکمیل‌شده" value={repaired} />
              )}
              <Row label="خطا" value={failed} />
              {quarantined > 0 && (
                <Row
                  label="بدون تطبیق شرکت (خارج از پوشش)"
                  value={quarantined}
                />
              )}
            </div>

            {scanWindow && (
              <p className="mt-3 text-center text-xs text-gray-500 dark:text-gray-400">
                این اسکن گزارش‌های منتشرشده از {scanWindow.from} تا{" "}
                {scanWindow.to} را پوشش داد؛ «صفحه» معیار زمانی نیست و هر صفحه
                فقط ۲۰ نامهٔ کدال است.
              </p>
            )}

            {scanIncomplete && (
              <p className="mt-2 text-center text-xs text-gray-500 dark:text-gray-400">
                {backfillStopped
                  ? "برای گزارش‌های قدیمی‌تر از این بازه، «جمع‌آوری سود/فروش» همان نماد را اجرا کنید."
                  : "برای عقب‌تر رفتن، تعداد صفحات را بیشتر کنید. اجرای دوباره با همان عدد، همان بازهٔ زمانی را از نو بررسی می‌کند."}
              </p>
            )}

            {quarantinedSymbols.length > 0 && (
              <div className="mt-3 rounded-lg bg-gray-50 p-2 text-xs text-gray-600 dark:bg-gray-800/60 dark:text-gray-300">
                <p className="mb-1 font-medium">
                  نمادهای خارج از پوشش دادهٔ شما (این گزارش‌ها ذخیره نمی‌شوند):
                </p>
                <p className="leading-6">
                  {quarantinedSymbols
                    .slice(0, 10)
                    .map(([symbol, count]) =>
                      count > 1 ? `${symbol} (${count})` : symbol,
                    )
                    .join("، ")}
                  {quarantinedSymbols.length > 10
                    ? ` و ${quarantinedSymbols.length - 10} نماد دیگر`
                    : ""}
                </p>
              </div>
            )}

            {repairFailed > 0 && (
              <p className="mt-2 text-center text-xs text-amber-700 dark:text-amber-300">
                {repairFailed} گزارش ناقص در این اجرا تکمیل نشد؛ اجرای بعدی دوباره
                تلاش می‌کند.
              </p>
            )}

            {quarantined > 0 && (
              <p className="mt-3 text-center text-xs text-gray-500 dark:text-gray-400">
                «بدون تطبیق شرکت» یعنی گزارشِ نمادهایی است که در پوشش دادهٔ شما نیستند؛
                جمع‌آوری سریع فقط نمادهای تحت پوشش شما را دریافت می‌کند.
              </p>
            )}

            <div className="flex justify-center gap-4 mt-3 pt-3 border-t border-gray-100 dark:border-gray-700/60 text-xs text-gray-600 dark:text-gray-300">
              <span>مالی: {financialNew}</span>
              <span>ماهانه: {monthlyNew}</span>
              <span>ذخیره‌شده: {total.fetched}</span>
            </div>

            {failed > 0 && (
              <div className="mt-3 p-2 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-center text-xs text-amber-700 dark:text-amber-300">
                جمع‌آوری با چند خطا انجام شد. موفق: {completed} — ناموفق:{" "}
                {failed}
              </div>
            )}
            {(total.errors_detail?.length ?? 0) > 0 && (
              <div className="mt-2 rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
                <p className="font-medium">دلیل خطا:</p>
                <ul className="mt-1 list-inside list-disc space-y-0.5 break-words">
                  {total.errors_detail!.slice(0, 3).map((item) => (
                    <li key={item.report_id}>
                      گزارش {item.report_id}: {item.error || "خطای نامشخص"}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div className="flex justify-end gap-3 mt-2">
          <button
            onClick={handleClose}
            className="px-5 py-2 rounded-lg bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-gray-800 dark:text-white transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            بستن
          </button>
          <button
            onClick={handleRun}
            disabled={running}
            className={`px-5 py-2 rounded-lg text-white font-medium transition ${
              running
                ? "bg-gray-400 cursor-not-allowed"
                : "bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700"
            }`}
          >
            {running ? "در حال اجرا..." : "شروع جمع‌آوری سریع"}
          </button>
        </div>
      </div>
    </div>
  );
};

const Row = ({ label, value }: { label: string; value: number }) => (
  <div className="flex items-center justify-between">
    <span className="text-gray-500 dark:text-gray-400">{label}</span>
    <span className="font-semibold">{value}</span>
  </div>
);

export default QuickSyncModal;
