import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelCodalSyncJob,
  getActiveCodalSyncJob,
  getCodalSyncJob,
  refreshCodalCaptcha,
  resumeCodalChallenge,
  startCodalSyncJob,
  submitCodalCaptcha,
  type CodalSyncJob,
  type SyncCodalPayload,
} from "../utils/api";

const FINAL = new Set(["completed", "completed_with_errors", "failed", "cancelled", "expired", "interrupted"]);
const STORAGE_KEY = "activeCodalSyncJobId";

export function useCodalSyncJob(enabled: boolean) {
  const [job, setJob] = useState<CodalSyncJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const timer = useRef<number | null>(null);
  const currentId = useRef<string | null>(null);
  const alive = useRef(true);

  const apply = useCallback((next: CodalSyncJob | null) => {
    if (!alive.current) return;
    setJob(next);
    currentId.current = next?.job_id ?? null;
    if (next?.job_id && !FINAL.has(next.state)) localStorage.setItem(STORAGE_KEY, next.job_id);
    if (next && FINAL.has(next.state)) localStorage.removeItem(STORAGE_KEY);
  }, []);

  const attach = useCallback(async (jobId: string) => {
    const next = await getCodalSyncJob(jobId);
    apply(next);
    return next;
  }, [apply]);

  const poll = useCallback(async () => {
    if (!enabled || !currentId.current || !alive.current) return;
    const id = currentId.current;
    try {
      const next = await getCodalSyncJob(id);
      if (!alive.current || currentId.current !== id) return;
      apply(next);
      setError(null);
      if (!FINAL.has(next.state)) timer.current = window.setTimeout(poll, 1500);
    } catch (err) {
      if (!alive.current || currentId.current !== id) return;
      setError(err instanceof Error ? err.message : "وضعیت جمع‌آوری دریافت نشد");
      timer.current = window.setTimeout(poll, 2500);
    }
  }, [apply, enabled]);

  useEffect(() => {
    alive.current = true;
    if (!enabled) {
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = null;
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const active = await getActiveCodalSyncJob();
        if (cancelled) return;
        const saved = localStorage.getItem(STORAGE_KEY);
        const next = active ?? (saved ? await getCodalSyncJob(saved).catch(() => null) : null);
        if (cancelled) return;
        if (next) {
          apply(next);
          if (!FINAL.has(next.state)) timer.current = window.setTimeout(poll, 0);
        } else {
          apply(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "وضعیت جمع‌آوری دریافت نشد");
      }
    })();
    return () => {
      cancelled = true;
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = null;
    };
  }, [apply, enabled, poll]);

  useEffect(() => () => { alive.current = false; }, []);

  const start = useCallback(async (payload: SyncCodalPayload) => {
    setError(null); setActionError(null);
    try {
      const next = await startCodalSyncJob(payload);
      apply(next);
      if (!FINAL.has(next.state)) timer.current = window.setTimeout(poll, 0);
      return next;
    } catch (err) {
      const conflict = err as Error & { active_job_id?: string };
      if (conflict.active_job_id) {
        const next = await attach(conflict.active_job_id);
        timer.current = window.setTimeout(poll, 0);
        return next;
      }
      setError(err instanceof Error ? err.message : "شروع جمع‌آوری ناموفق بود");
      return null;
    }
  }, [apply, attach, poll]);

  const answer = useCallback(async (value: string) => {
    if (!job?.challenge || actionPending) return;
    setActionPending(true); setActionError(null);
    try {
      await submitCodalCaptcha(job.job_id, job.challenge.challenge_id, value);
      const next = await attach(job.job_id);
      if (next.state !== "waiting_captcha") timer.current = window.setTimeout(poll, 0);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "ارسال کد انجام نشد");
    } finally { setActionPending(false); }
  }, [actionPending, attach, job, poll]);

  const refresh = useCallback(async () => {
    if (!job?.challenge || actionPending) return;
    setActionPending(true); setActionError(null);
    try {
      await refreshCodalCaptcha(job.job_id, job.challenge.challenge_id);
      timer.current = window.setTimeout(poll, 500);
    } catch (err) { setActionError(err instanceof Error ? err.message : "تصویر تازه نشد"); }
    finally { setActionPending(false); }
  }, [actionPending, job, poll]);

  const resumeInBrowser = useCallback(async () => {
    if (!job?.challenge || actionPending) return;
    setActionPending(true); setActionError(null);
    try {
      await resumeCodalChallenge(job.job_id, job.challenge.challenge_id);
      timer.current = window.setTimeout(poll, 500);
    } catch (err) { setActionError(err instanceof Error ? err.message : "بررسی دوباره انجام نشد"); }
    finally { setActionPending(false); }
  }, [actionPending, job, poll]);

  const cancel = useCallback(async () => {
    if (!job || actionPending) return;
    setActionPending(true); setActionError(null);
    try { await cancelCodalSyncJob(job.job_id); timer.current = window.setTimeout(poll, 500); }
    catch (err) { setActionError(err instanceof Error ? err.message : "لغو جمع‌آوری انجام نشد"); }
    finally { setActionPending(false); }
  }, [actionPending, job, poll]);

  return { job, running: !!job && !FINAL.has(job.state), summary: job?.summary ?? null,
    error, actionError, actionPending, start, answer, refresh, resumeInBrowser, cancel, clearError: () => setError(null) };
}
