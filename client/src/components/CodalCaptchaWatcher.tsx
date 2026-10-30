import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import {
  cancelCodalSyncJob,
  getActiveCodalSyncJob,
  getCodalSyncJob,
  refreshCodalCaptcha,
  resumeCodalChallenge,
  submitCodalCaptcha,
  type CodalSyncJob,
} from "../utils/api";
import { getAuthStatus } from "../hooks/useGetUser";
import CodalCaptchaPanel from "./CodalCaptchaPanel";
import { getCaptchaPanelCount, subscribeCaptchaPanel } from "./codalCaptchaVisibility";

const POLL_MS = 3000;

/**
 * Site-wide captcha prompt.
 *
 * A Codal run can hit a security code at any moment — quick collect, per-symbol
 * collect, or the scheduled run — and it then waits for an answer. The job's own
 * modal may be closed (or was never opened), so this watcher surfaces the same
 * panel as a floating card on every page: the operator types the code here and
 * the worker continues. Nothing is retried while it waits.
 */
export default function CodalCaptchaWatcher() {
  const { isAdmin } = getAuthStatus();
  const [job, setJob] = useState<CodalSyncJob | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedInsideModal = useSyncExternalStore(subscribeCaptchaPanel, getCaptchaPanelCount);

  const poll = useCallback(async () => {
    try {
      setJob(await getActiveCodalSyncJob());
    } catch {
      // The watcher is a safety net; a failed poll must stay silent.
    }
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    let stopped = false;
    let timer = 0;
    const tick = async () => {
      if (stopped) return;
      await poll();
      if (!stopped) timer = window.setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [isAdmin, poll]);

  const challenge = job?.challenge;
  const visible =
    isAdmin && mountedInsideModal === 0 && !!job && job.state === "waiting_captcha" &&
    !!challenge?.challenge_id;

  const act = async (run: () => Promise<unknown>) => {
    if (!job || pending) return;
    setPending(true);
    setError(null);
    try {
      await run();
      setJob(await getCodalSyncJob(job.job_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "ارسال کد انجام نشد");
    } finally {
      setPending(false);
    }
  };

  if (!visible || !job || !challenge) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-3 z-50 flex justify-center px-3">
      <div className="pointer-events-auto w-full max-w-2xl rounded-3xl border border-amber-400/60 bg-white/95 p-1 shadow-2xl shadow-amber-500/20 backdrop-blur-xl dark:border-amber-700/60 dark:bg-gray-900/95">
        <div className="flex items-center justify-between gap-2 px-3 pt-1 text-xs font-bold text-amber-800 dark:text-amber-200">
          <span>کدال کد امنیتی می‌خواهد — جمع‌آوری تا واردکردن کد متوقف است</span>
          <button
            type="button"
            onClick={() => act(() => cancelCodalSyncJob(job.job_id))}
            disabled={pending}
            className="rounded-lg px-2 py-1 text-xs font-normal underline disabled:opacity-50"
          >
            توقف جمع‌آوری
          </button>
        </div>
        <CodalCaptchaPanel
          job={job}
          pending={pending}
          error={error}
          trackVisibility={false}
          onAnswer={(value) => act(() => submitCodalCaptcha(job.job_id, challenge.challenge_id, value))}
          onRefresh={() => act(() => refreshCodalCaptcha(job.job_id, challenge.challenge_id))}
          onResume={() => act(() => resumeCodalChallenge(job.job_id, challenge.challenge_id))}
          onCancel={() => act(() => cancelCodalSyncJob(job.job_id))}
        />
      </div>
    </div>
  );
}
