import React, { useEffect, useRef, useState } from "react";
import { type SyncCodalSummary } from "../utils/api";
import { useCodalSyncJob } from "../hooks/useCodalSyncJob";
import CodalCaptchaPanel from "./CodalCaptchaPanel";

interface SymbolSyncModalProps {
  visible: boolean;
  mode: "financial" | "monthly";
  symbol: string;
  onClose: () => void;
  onDataCollected?: () => void;
}

const Row = ({ label, value }: { label: string; value: number }) => (
  <div className="flex items-center justify-between">
    <span className="text-gray-500 dark:text-gray-400">{label}</span>
    <span className="font-semibold tabular-nums">{value}</span>
  </div>
);

// جمع‌آوری گزارش‌های یک نماد مشخص (سود/فروش) — آخرین N گزارش از سرچ کدال
const SymbolSyncModal: React.FC<SymbolSyncModalProps> = ({
  visible,
  mode,
  symbol,
  onClose,
  onDataCollected,
}) => {
  const sync = useCodalSyncJob(visible);
  const [count, setCount] = useState("4");
  const running = sync.running;
  const summary: SyncCodalSummary | null = sync.summary;
  const errorMsg = sync.error;
  const notifiedJob = useRef<string | null>(null);

  useEffect(() => {
    if (sync.job && ["completed", "completed_with_errors"].includes(sync.job.state) && sync.summary?.total && notifiedJob.current !== sync.job.job_id) {
      notifiedJob.current = sync.job.job_id;
      if ((sync.summary.total.new ?? 0) > 0 || (sync.summary.total.completed ?? 0) > 0) onDataCollected?.();
    }
  }, [onDataCollected, sync.job, sync.summary]);

  if (!visible) return null;

  const label = mode === "financial" ? "سود" : "فروش";

  const handleRun = async () => {
    if (running) return;
    const n = Math.max(1, Math.min(20, Number(count) || 4));
    await sync.start({ mode, symbol, limit: n });
  };

  const total = summary?.total;
  const syncFailed = summary?.success === false;

  return (
    <div className="fixed inset-0 z-50 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center">
      <div
        dir="rtl"
        className="bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 rounded-2xl shadow-2xl w-full max-w-md p-6"
      >
        <h2 className="text-xl font-semibold mb-1 text-center">
          {mode === "financial" ? "💰 جمع‌آوری سود" : "📈 جمع‌آوری فروش"} —{" "}
          {symbol}
        </h2>
        <p className="text-xs text-center text-gray-500 dark:text-gray-400 mb-5">
          آخرین گزارش‌های کدالِ همین نماد بررسی و دریافت می‌شود.
        </p>

        <div className="mb-5">
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
            چند گزارش آخر؟
          </label>
          <input
            type="number"
            min="1"
            max="20"
            disabled={running}
            value={count}
            onChange={(e) => setCount(e.target.value)}
            className="w-full h-9 px-3 rounded-xl border border-gray-300 dark:border-gray-600 dark:bg-gray-800 text-center focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:opacity-50"
          />
        </div>

        {running && (
          <div className="flex items-center justify-center gap-2 text-sm text-emerald-600 dark:text-emerald-400 mb-4">
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
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            {sync.job?.message || "در حال دریافت و پردازش گزارش‌ها..."}
            {sync.job?.parameters?.symbol && sync.job.parameters.symbol !== symbol && <span className="mr-2 text-xs">· اجرای فعال برای {sync.job.parameters.symbol}</span>}
            {sync.job?.source === "automatic" && <span className="mr-2 text-xs">· اجرای خودکار</span>}
            {sync.job?.counters && <div className="mt-1 text-xs">بررسی‌شده {sync.job.counters.scanned ?? 0} · جدید {sync.job.counters.new ?? 0} · استخراج‌شده {sync.job.counters.completed ?? 0}</div>}
          </div>
        )}

        {sync.job?.state === "waiting_captcha" && <CodalCaptchaPanel job={sync.job} pending={sync.actionPending} error={sync.actionError} onAnswer={sync.answer} onRefresh={sync.refresh} onResume={sync.resumeInBrowser} onCancel={sync.cancel} />}

        {errorMsg && !running && !sync.job && (
          <div className="mb-4 p-3 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
            جمع‌آوری ناموفق بود.
            <div className="mt-1 text-xs break-words">{errorMsg}</div>
          </div>
        )}
        {sync.job?.error && !running && (
          <div role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">{sync.job.error.message}</div>
        )}

        {summary && !total && !running && (
          <div className="mb-4 p-3 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
            جمع‌آوری ناموفق بود.
            <div className="mt-1 text-xs break-words">
              {summary.error || "خطای ناشناخته"}
            </div>
          </div>
        )}

        {summary && total && !running && (
          <div className="mb-4 text-sm">
            {total.new === 0 && total.failed === 0 ? (
              <p className="text-center text-gray-600 dark:text-gray-300 font-medium mb-2">
                گزارش جدیدی برای {symbol} پیدا نشد — همه قبلاً دریافت شده.
              </p>
            ) : syncFailed ? (
              <p className="text-center text-red-600 dark:text-red-400 font-semibold mb-2">
                جمع‌آوری با خطا متوقف شد
              </p>
            ) : (
              <p className="text-center font-semibold mb-2 text-emerald-600 dark:text-emerald-400">
                {label} {symbol} به‌روز شد ✓
              </p>
            )}
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 tabular-nums">
              <Row label="گزارش‌های بررسی‌شده" value={total.scanned} />
              <Row label="قبلاً دریافت‌شده" value={total.already ?? 0} />
              <Row label="گزارش‌های جدید" value={total.new ?? 0} />
              {(total.repaired ?? 0) > 0 && (
                <Row label="گزارش‌های ناقص تکمیل‌شده" value={total.repaired ?? 0} />
              )}
              <Row label="اعداد استخراج‌شده" value={total.completed ?? 0} />
              {(total.quarantined ?? 0) > 0 && (
                <Row label="خارج از پوشش" value={total.quarantined!} />
              )}
              {(total.unsupported ?? 0) > 0 && (
                <Row label="فرمت پشتیبانی‌نشده" value={total.unsupported!} />
              )}
              <Row label="خطا" value={total.failed ?? 0} />
            </div>
            {(total.errors_detail?.length ?? 0) > 0 && (
              <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
                <p className="font-medium">دلیل خطا:</p>
                <ul className="mt-1 list-inside list-disc space-y-0.5 break-words">
                  {total.errors_detail!.slice(0, 3).map((item) => (
                    <li key={item.report_id}>
                      گزارش {item.report_id}: {item.error || "خطای نامشخص"}
                    </li>
                  ))}
                </ul>
                <p className="mt-1 opacity-80">
                  اگر کدال موقتاً پاسخ نداده، «شروع جمع‌آوری» را دوباره بزنید؛ گزارش نیمه‌کاره دوباره تلاش می‌شود.
                </p>
              </div>
            )}
          </div>
        )}

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
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
            {running ? "در حال اجرا..." : "شروع جمع‌آوری"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default SymbolSyncModal;
