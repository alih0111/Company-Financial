import { useCallback, useEffect, useState } from "react";
import { getShadowHealth, type ShadowHealth } from "../utils/api";

/**
 * Shows which score snapshot the table is displaying and whether it is current.
 *
 * The score is a materialised batch run, so it does not change when a new report is
 * ingested — only when the refresh job stores a new run. Without this badge a frozen
 * score is indistinguishable from a live one. Refreshes on focus/visibility and on an
 * interval so a long-lived tab does not keep a stale snapshot on screen.
 */
const REFRESH_MS = 5 * 60 * 1000;

function parsePgDate(s?: string): Date | null {
  if (!s) return null;
  const iso = s.includes("T") ? s : s.replace(" ", "T");
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

function faDate(s?: string): string | null {
  const d = parsePgDate(s);
  return d
    ? d.toLocaleDateString("fa-IR", { year: "numeric", month: "long", day: "numeric" })
    : null;
}

function faDateTime(s?: string): string | null {
  const d = parsePgDate(s);
  if (!d) return null;
  const date = d.toLocaleDateString("fa-IR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const time = d.toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
  return `${date} ${time}`;
}

export default function ScoreFreshnessBadge() {
  const [health, setHealth] = useState<ShadowHealth | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      setHealth(await getShadowHealth());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    load();
    const onFocus = () => load();
    const onVisibility = () => {
      if (document.visibilityState === "visible") load();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearInterval(timer);
    };
  }, [load]);

  if (failed || !health?.score_run_id) return null;

  const stale = Boolean(health.score_stale);
  const asOf = faDate(health.score_as_of);
  const computed = faDateTime(health.score_computed_at);
  const reasons = health.score_stale_reasons?.length
    ? health.score_stale_reasons.join(" • ")
    : null;

  return (
    <div
      dir="rtl"
      className={`mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl px-3 py-2 text-xs ring-1 ${
        stale
          ? "bg-amber-500/10 text-amber-700 ring-amber-500/30 dark:text-amber-300"
          : "bg-emerald-500/10 text-emerald-700 ring-emerald-500/20 dark:text-emerald-300"
      }`}
      title={reasons ?? undefined}
    >
      <span className="font-semibold">
        {stale ? "امتیاز کهنه است" : "امتیاز به‌روز است"}
      </span>
      {asOf && <span>داده تا: {asOf}</span>}
      {computed && <span>محاسبه: {computed}</span>}
      {stale && (
        <span className="opacity-90">
          گزارش‌های جدید آمده‌اند؛ تا اجرای به‌روزرسانی، امتیاز جدول عوض نمی‌شود.
        </span>
      )}
    </div>
  );
}
