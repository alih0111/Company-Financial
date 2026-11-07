import { jwtDecode } from "jwt-decode";
import { API_BASE } from "../config";

interface AuthStatus { isAdmin: boolean; username: string | null }
const guest: AuthStatus = { isAdmin: false, username: null };
let session: AuthStatus = guest;
let revision = 0;

// Only the explicitly selected development mock uses a fake JWT. Real browser
// credentials stay inside the HttpOnly cookie and are never readable by JS.
export function getDevToken(): string | null {
  if (import.meta.env.DEV && new URLSearchParams(window.location.search).has("__mock")) { try { return localStorage.getItem("token"); } catch { return null; } }
  return null;
}
export function sessionHeaders(): Record<string, string> {
  const token = getDevToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
export const sessionRevision = () => revision;
export function clearSession() { session = guest; revision++; try { localStorage.removeItem("token"); } catch { /* Cookies do not require storage access. */ } }
export function notifySessionChanged() { try { localStorage.setItem("rfa_session_changed", String(Date.now())); } catch { /* Cross-tab notification is optional. */ } }

export const getAuthStatus = (): AuthStatus => {
  const token = getDevToken();
  if (token) {
    try {
      const value = jwtDecode<{ username?: string; exp?: number; isAdmin?: boolean }>(token);
      if (typeof value.username === "string" && typeof value.exp === "number" && value.exp > Date.now()/1000) return { username: value.username, isAdmin: value.isAdmin === true };
    } catch { /* Invalid mock tokens grant no UI access. */ }
  }
  return session;
};

export async function refreshSession(): Promise<boolean> {
  if (getDevToken()) return true;
  try { localStorage.removeItem("token"); } catch { /* Cookies do not require storage access. */ }
  const response = await fetch(`${API_BASE}/me`, { credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(8000) });
  if (!response.ok) { clearSession(); return false; }
  const data = await response.json();
  if (typeof data.username !== "string" || !data.username.trim()) { clearSession(); return false; }
  session = { username: data.username, isAdmin: data.isAdmin === true };
  revision++;
  return true;
}

export async function logoutSession() {
  const response = await fetch(`${API_BASE}/logout`, { method: "POST", credentials: "same-origin", headers: sessionHeaders() });
  if (!response.ok && response.status !== 401) throw new Error("خروج کامل نشد؛ دوباره تلاش کنید.");
  clearSession(); notifySessionChanged();
}

window.addEventListener("storage", (event) => {
  if (event.key === "rfa_session_changed") {
    void refreshSession().catch(clearSession).finally(() => window.location.reload());
  }
});
