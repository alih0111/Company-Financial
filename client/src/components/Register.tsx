import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  FaEnvelope,
  FaUser,
  FaLock,
  FaShieldAlt,
  FaCheckCircle,
  FaArrowLeft,
  FaExclamationCircle,
} from "react-icons/fa";
import { useDarkMode } from "../utils/theme";
import AuthLayout from "./AuthLayout";
import { API_BASE } from "../config";

// سنجه‌ی ساده‌ی قدرت گذرواژه — فقط راهنمای بصری، نه اعتبارسنجی امنیتی
const passwordStrength = (pass: string): { score: number; label: string; barCls: string } => {
  if (!pass) return { score: 0, label: "", barCls: "" };
  let score = 0;
  if (pass.length >= 8) score++;
  if (pass.length >= 12) score++;
  if (/[A-Z]/.test(pass) && /[a-z]/.test(pass)) score++;
  if (/\d/.test(pass)) score++;
  if (/[^A-Za-z0-9]/.test(pass)) score++;
  if (score <= 1) return { score: 1, label: "ضعیف", barCls: "bg-red-500 w-1/5" };
  if (score <= 2) return { score: 2, label: "متوسط", barCls: "bg-amber-500 w-2/5" };
  if (score <= 3) return { score: 3, label: "خوب", barCls: "bg-yellow-400 w-3/5" };
  return { score: 4, label: "قوی", barCls: "bg-emerald-500 w-full" };
};

const Register = () => {
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [verificationCode, setVerificationCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const { darkMode, toggleDarkMode } = useDarkMode();

  const strength = useMemo(() => passwordStrength(password), [password]);

  const handleSendCode = async () => {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/register/send-code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (res.ok) {
        setCodeSent(true);
        setNotice("کد تأیید به ایمیل شما ارسال شد.");
      } else {
        setError(data.error || "ارسال کد ناموفق بود.");
      }
    } catch {
      setError("خطای شبکه — دوباره تلاش کنید.");
    } finally {
      setBusy(false);
    }
  };

  const handleRegister = async () => {
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, username, password, code: verificationCode }),
      });
      const data = await res.json();

      if (res.ok) {
        setNotice("ثبت‌نام موفق بود! در حال انتقال به صفحه ورود…");
        setTimeout(() => navigate("/login"), 1200);
      } else {
        setError(data.error || "ثبت‌نام ناموفق بود.");
      }
    } catch {
      setError("خطای شبکه — دوباره تلاش کنید.");
    } finally {
      setBusy(false);
    }
  };

  const labelCls =
    "mb-1.5 block text-xs font-semibold text-gray-600 dark:text-gray-300";
  const inputCls =
    "w-full rounded-xl border border-gray-200 dark:border-gray-600/80 dark:bg-gray-900/40 bg-white/70 text-gray-800 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 py-2.5 pr-10 text-sm transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-500/60 hover:border-gray-300 dark:hover:border-gray-500";

  return (
    <AuthLayout darkMode={darkMode} toggleDarkMode={toggleDarkMode}>
      <h1 className="text-xl font-bold text-gray-800 dark:text-white mb-1 text-center">
        ساخت حساب جدید
      </h1>
      <p className="text-xs text-gray-500 dark:text-gray-400 text-center mb-5">
        ابتدا ایمیل خود را تأیید کنید
      </p>

      {/* اندیکاتور مرحله */}
      <div className="mb-6 flex items-center justify-center gap-2" dir="ltr">
        {[
          { label: "ایمیل", done: codeSent },
          { label: "تأیید و اطلاعات", done: false },
        ].map((step, i) => {
          const active = (i === 0 && !codeSent) || (i === 1 && codeSent);
          return (
            <div key={step.label} className="flex items-center gap-2">
              <span
                className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-bold transition-all duration-300 ${
                  step.done
                    ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 ring-1 ring-emerald-500/30"
                    : active
                      ? "bg-emerald-600 text-white shadow-md shadow-emerald-500/25"
                      : "bg-gray-100 dark:bg-white/5 text-gray-400 dark:text-gray-500"
                }`}
              >
                {step.done ? <FaCheckCircle size={10} /> : <span>{i + 1}</span>}
                {step.label}
              </span>
              {i === 0 && (
                <span
                  className={`h-px w-8 rounded ${step.done ? "bg-emerald-500/50" : "bg-gray-200 dark:bg-white/10"}`}
                />
              )}
            </div>
          );
        })}
      </div>

      {error && (
        <div className="animate-scale-in mb-4 flex items-center justify-center gap-2 rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 px-4 py-2.5 text-sm text-red-600 dark:text-red-300 text-center">
          <FaExclamationCircle size={13} className="shrink-0" />
          {error}
        </div>
      )}
      {notice && (
        <div className="animate-scale-in mb-4 flex items-center justify-center gap-2 rounded-xl border border-emerald-200 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-600 dark:text-emerald-300 text-center">
          <FaCheckCircle size={13} />
          {notice}
        </div>
      )}

      <div className="space-y-4">
        <div>
          <label htmlFor="reg-email" className={labelCls}>
            ایمیل
          </label>
          <div className="relative">
            <FaEnvelope className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm pointer-events-none" />
            <input
              id="reg-email"
              type="email"
              dir="ltr"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={`${inputCls} text-left`}
              disabled={codeSent}
            />
          </div>
        </div>

        {!codeSent ? (
          <>
            <button
              onClick={handleSendCode}
              disabled={busy || !email}
              className="group flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 py-2.5 text-sm font-bold text-white shadow-lg shadow-emerald-500/25 transition hover:scale-[1.02] hover:shadow-xl hover:shadow-emerald-500/30 active:scale-[0.99] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
            >
              <FaShieldAlt size={13} />
              {busy ? "در حال ارسال…" : "ارسال کد تأیید"}
            </button>
            <p className="text-sm text-center text-gray-500 dark:text-gray-400">
              حساب دارید؟{" "}
              <Link
                to="/login"
                className="font-bold text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 hover:underline"
              >
                وارد شوید
              </Link>
            </p>
          </>
        ) : (
          <>
            <div>
              <label htmlFor="reg-code" className={labelCls}>
                کد تأیید
              </label>
              <div className="relative">
                <FaShieldAlt className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm pointer-events-none" />
                <input
                  id="reg-code"
                  type="text"
                  dir="ltr"
                  placeholder="کد ۶ رقمی"
                  value={verificationCode}
                  onChange={(e) => setVerificationCode(e.target.value)}
                  className={`${inputCls} text-left tracking-[0.3em]`}
                  autoFocus
                />
              </div>
            </div>
            <div>
              <label htmlFor="reg-username" className={labelCls}>
                نام کاربری
              </label>
              <div className="relative">
                <FaUser className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm pointer-events-none" />
                <input
                  id="reg-username"
                  type="text"
                  placeholder="نامی که با آن وارد می‌شوید"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className={inputCls}
                />
              </div>
            </div>
            <div>
              <label htmlFor="reg-password" className={labelCls}>
                گذرواژه
              </label>
              <div className="relative">
                <FaLock className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm pointer-events-none" />
                <input
                  id="reg-password"
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className={inputCls}
                />
              </div>
              {password && (
                <div className="mt-2 flex items-center gap-2">
                  <div className="h-1 flex-1 overflow-hidden rounded-full bg-gray-200 dark:bg-white/10">
                    <div
                      className={`h-full rounded-full transition-all duration-300 ${strength.barCls}`}
                    />
                  </div>
                  <span className="text-[10px] font-bold text-gray-500 dark:text-gray-400">
                    {strength.label}
                  </span>
                </div>
              )}
            </div>
            <button
              onClick={handleRegister}
              disabled={busy || !verificationCode || !username || !password}
              className="group flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 py-2.5 text-sm font-bold text-white shadow-lg shadow-emerald-500/25 transition hover:scale-[1.02] hover:shadow-xl hover:shadow-emerald-500/30 active:scale-[0.99] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
            >
              {busy ? "در حال ثبت…" : "تکمیل ثبت‌نام"}
              <FaArrowLeft size={12} className="transition-transform duration-300 group-hover:-translate-x-0.5" />
            </button>
            <button
              onClick={() => {
                setCodeSent(false);
                setNotice(null);
                setError(null);
              }}
              className="w-full text-center text-xs text-gray-500 dark:text-gray-400 hover:text-emerald-600 dark:hover:text-emerald-400 transition font-medium"
            >
              تغییر ایمیل
            </button>
          </>
        )}
      </div>
    </AuthLayout>
  );
};

export default Register;
