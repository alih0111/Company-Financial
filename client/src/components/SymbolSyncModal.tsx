import React, { useState } from "react";
import { syncCodal, type SyncCodalSummary } from "../utils/api";

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
  const [count, setCount] = useState("4");
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<SyncCodalSummary | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!visible) return null;

  const label = mode === "financial" ? "سود" : "فروش";

  const handleRun = async () => {
    if (running) return;
    setRunning(true);
    setErrorMsg(null);
    setSummary(null);
    try {
      const n = Math.max(1, Math.min(20, Number(count) || 4));
      const res = await syncCodal({ mode, symbol, limit: n });
      setSummary(res);
      onDataCollected?.();
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "خطا در ارتباط با سرور");
    } finally {
      setRunning(false);
    }
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
            در حال دریافت و پردازش گزارش‌ها...
          </div>
        )}

        {errorMsg && !running && (
          <div className="mb-4 p-3 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
            جمع‌آوری ناموفق بود.
            <div className="mt-1 text-xs break-words">{errorMsg}</div>
          </div>
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
              <Row label="اعداد استخراج‌شده" value={total.completed ?? 0} />
              {(total.quarantined ?? 0) > 0 && (
                <Row label="خارج از پوشش" value={total.quarantined!} />
              )}
              {(total.unsupported ?? 0) > 0 && (
                <Row label="فرمت پشتیبانی‌نشده" value={total.unsupported!} />
              )}
              <Row label="خطا" value={total.failed ?? 0} />
            </div>
          </div>
        )}

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
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
            {running ? "در حال اجرا..." : "شروع جمع‌آوری"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default SymbolSyncModal;
