import { useEffect, useState } from "react";
import type { CodalSyncJob } from "../utils/api";
import { setCaptchaPanelMounted } from "./codalCaptchaVisibility";

interface Props {
  job: CodalSyncJob;
  pending: boolean;
  error?: string | null;
  onAnswer: (answer: string) => void;
  onRefresh: () => void;
  onResume?: () => void;
  onCancel: () => void;
  /**
   * Inline (modal) panels register themselves so the floating watcher stays
   * hidden. The floating panel passes false: registering itself would hide the
   * very card it lives in.
   */
  trackVisibility?: boolean;
}

export default function CodalCaptchaPanel({ job, pending, error, onAnswer, onRefresh, onResume, onCancel, trackVisibility = true }: Props) {
  const challenge = job.challenge;
  const [value, setValue] = useState("");
  useEffect(() => setValue(""), [challenge?.challenge_id]);
  // Keep the floating watcher quiet while this panel is on screen.
  useEffect(() => {
    if (!trackVisibility) return;
    setCaptchaPanelMounted(true);
    return () => setCaptchaPanelMounted(false);
  }, [trackVisibility]);
  const submit = () => { if (value.trim() && !pending) onAnswer(value.trim()); };

  return (
    <section dir="rtl" className="my-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">
      <p className="font-medium">{challenge?.message ?? "کدال برای ادامه کد امنیتی می‌خواهد."}</p>
      {challenge?.attempt && challenge.attempt > 1 && (
        <p className="mt-1 text-xs font-medium text-amber-800 dark:text-amber-200">کد قبلی پذیرفته نشد؛ کد تازه را وارد کنید (تلاش {challenge.attempt} از ۳).</p>
      )}
      {challenge?.image_data_url && <img src={challenge.image_data_url} alt={challenge.kind === "inspection" ? "تصویر صفحهٔ پاسخ کدال" : "کد امنیتی کدال"} className="mx-auto my-3 max-h-48 max-w-full rounded border border-gray-300 bg-white object-contain" />}
      {challenge?.kind === "inspection" ? (
        <p className="text-xs">اگر کد امنیتی کدال را در پنجرهٔ مرورگر حل کردید، دکمهٔ ادامه را بزنید تا همان درخواست دوباره بررسی شود.</p>
      ) : challenge?.kind === "unsupported" ? (
        <p className="text-xs">فرم این چالش در این نسخه قابل ارسال از برنامه نیست. می‌توانید جمع‌آوری را لغو کنید.</p>
      ) : (
        <>
          <form onSubmit={(event) => { event.preventDefault(); submit(); }} className="flex flex-col gap-2 sm:flex-row">
            <input autoComplete="off" autoCapitalize="off" spellCheck={false} inputMode="text" value={value} onChange={(event) => setValue(event.target.value)} disabled={pending} aria-label="کد امنیتی" placeholder="کد تصویر" className="min-w-0 flex-1 rounded-lg border border-amber-300 bg-white px-3 py-2 text-center text-gray-900 tracking-widest dark:border-amber-800 dark:bg-gray-900 dark:text-white" />
            <button type="submit" disabled={pending || !value.trim()} className="rounded-lg bg-amber-700 px-3 py-2 text-white disabled:opacity-50">{pending ? "در حال ارسال…" : "ارسال و ادامه"}</button>
            {challenge?.can_refresh && <button type="button" onClick={onRefresh} disabled={pending} className="rounded-lg border border-amber-500 px-3 py-2 disabled:opacity-50">تصویر جدید</button>}
          </form>
          <p className="mt-2 text-xs opacity-80">کد را از تصویر بخوانید و همین‌جا وارد کنید؛ جمع‌آوری بدون نیاز به کار دیگری ادامه می‌دهد.</p>
        </>
      )}
      {challenge?.can_manual_resume && onResume && <button type="button" onClick={onResume} disabled={pending} className="mt-2 rounded-lg border border-amber-500 px-3 py-2 text-xs disabled:opacity-50">{challenge.kind === "inspection" ? "پس از بررسی کدال، ادامهٔ جمع‌آوری" : "پس از حل در مرورگر میزبان، بررسی و ادامه"}</button>}
      {error && <p role="alert" className="mt-2 text-red-700 dark:text-red-300">{error}</p>}
      <button type="button" onClick={onCancel} disabled={pending} className="mt-3 text-xs underline disabled:opacity-50">لغو جمع‌آوری</button>
    </section>
  );
}
