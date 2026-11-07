import { API_BASE } from "../config";

import { getAuthStatus, clearSession, sessionRevision } from "../hooks/useGetUser";

export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const started = sessionRevision();
  const username = getAuthStatus().username;
  const requestUrl = new URL(input instanceof Request ? input.url : String(input), window.location.origin);
  const base = new URL(API_BASE, window.location.origin);
  const isApi = requestUrl.origin === base.origin && requestUrl.pathname.startsWith(`${base.pathname}/`);
  const response = await fetch(input, { ...init, credentials: "same-origin" });
  if (response.status === 401 && isApi && username && started === sessionRevision()) {
    clearSession();
    const next = window.location.pathname + window.location.search;
    window.location.replace(`/login?next=${encodeURIComponent(next)}`);
  }

  if (isApi) {
    let message: string | undefined;
    if (response.status===429 || response.status===403 || response.status===413) {
      const body=await response.clone().json().catch(()=>null);
      if (typeof body?.code==="string" && body.code.startsWith("data_")) {
        message=body.error || "دریافت داده محدود شده است.";
      }
    }
    const remaining=response.headers.get("X-Data-Requests-Remaining");
    const reset=response.headers.get("X-Data-Reset");
    if (remaining!==null && reset && username && username===getAuthStatus().username && started===sessionRevision()) {
      try { window.dispatchEvent?.(new CustomEvent("rfa-data-budget",{detail:{remainingRequests:Number(remaining),remainingSymbols:Number(response.headers.get("X-Data-Symbols-Remaining")||0),reset,message}})); } catch { /* Notification is optional. */ }
    }
    if (message) throw new Error(message);
  }
  return response;
}

export async function authResponse(response: Response): Promise<{ token?: string; error?: string }> {
  const data = await response.json().catch(() => null);
  if (response.status === 429) return { error: "درخواست بیش از حد؛ کمی بعد دوباره تلاش کنید." };
  if (response.status >= 500) return { error: data?.error || "سرویس موقتاً در دسترس نیست؛ دوباره تلاش کنید." };
  if (response.status === 401) return { error: "نام کاربری یا گذرواژه نادرست است." };
  if (!data || typeof data !== "object") throw new Error("پاسخ نامعتبر سرور؛ دوباره تلاش کنید.");
  return data;
}
