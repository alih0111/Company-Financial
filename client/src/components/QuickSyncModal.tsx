import React, { useState } from "react";
import {
  syncCodal,
  type SyncCodalMode,
  type SyncCodalSummary,
} from "../utils/api";

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
  const [mode, setMode] = useState<SyncCodalMode>("all");
  const [maxPages, setMaxPages] = useState<string>("");
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<SyncCodalSummary | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!visible) return null;

  const reset = () => {
    setSummary(null);
    setErrorMsg(null);
  };

  const handleRun = async () => {
    if (running) return;
    setRunning(true);
    onRunningChange?.(true);
    reset();

    try {
      const res = await syncCodal({
        mode,
        dry_run: false,
        max_pages: maxPages ? Number(maxPages) : undefined,
      });
      setSummary(res);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "خطا در ارتباط با سرور");
    } finally {
      setRunning(false);
      onRunningChange?.(false);
    }
  };

  const handleClose = () => {
    if (running) return;
    onClose();
  };

  const total = summary?.total;
  const financialNew = summary?.financial?.new ?? 0;
  const monthlyNew = summary?.monthly?.new ?? 0;
  const newCount = total?.new ?? 0;
  const failed = total?.failed ?? 0;
  const completed = total?.completed ?? 0;
  const quarantined = total?.quarantined ?? 0;
  const syncFailed = summary?.success === false;

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
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              حداکثر صفحات (خالی = خودکار تا آخرین sync؛ عدد = دقیقاً همین
              عمق اسکن می‌شود)
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
          </div>
        </div>

        {/* وضعیت اجرا */}
        {running && (
          <div className="flex items-center justify-center gap-2 text-sm text-indigo-600 dark:text-indigo-400 mb-4">
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
            در حال بررسی گزارش‌های جدید کدال...
          </div>
        )}

        {/* خطای سطح درخواست */}
        {errorMsg && !running && (
          <div className="mb-4 p-3 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
            جمع‌آوری ناموفق بود.
            <div className="mt-1 text-xs break-words">{errorMsg}</div>
          </div>
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
            {newCount === 0 && failed === 0 ? (
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
              <Row label="خطا" value={failed} />
              {quarantined > 0 && (
                <Row
                  label="بدون تطبیق شرکت (خارج از پوشش)"
                  value={quarantined}
                />
              )}
            </div>

            <div className="flex justify-center gap-4 mt-3 pt-3 border-t border-gray-100 dark:border-gray-700/60 text-xs text-gray-600 dark:text-gray-300">
              <span>مالی: {financialNew}</span>
              <span>ماهانه: {monthlyNew}</span>
              <span>دریافت‌شده: {total.fetched}</span>
            </div>

            {failed > 0 && (
              <div className="mt-3 p-2 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-center text-xs text-amber-700 dark:text-amber-300">
                جمع‌آوری با چند خطا انجام شد. موفق: {completed} — ناموفق:{" "}
                {failed}
              </div>
            )}
          </div>
        )}

        <div className="flex justify-end gap-3 mt-2">
          <button
            onClick={handleClose}
            disabled={running}
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
