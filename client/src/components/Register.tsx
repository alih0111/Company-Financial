import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  FaEnvelope,
  FaUser,
  FaLock,
  FaShieldAlt,
  FaCheckCircle,
  FaArrowLeft,
} from "react-icons/fa";
import { useDarkMode } from "../utils/theme";
import AuthLayout from "./AuthLayout";
import { API_BASE } from "../config";

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
    } catch (err) {
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
    } catch (err) {
      setError("خطای شبکه — دوباره تلاش کنید.");
    } finally {
      setBusy(false);
    }
  };

  const inputCls =
    "w-full rounded-xl border border-gray-200 dark:border-gray-600 bg-white/70 dark:bg-gray-900/50 text-gray-800 dark:text-gray-100 placeholder:text-gray-400 py-2.5 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-500 transition-all duration-200";

  return (
    <AuthLayout darkMode={darkMode} toggleDarkMode={toggleDarkMode}>
      <h1 className="text-xl font-bold text-gray-800 dark:text-white mb-1 text-center">
        ساخت حساب جدید
      </h1>
      <p className="text-xs text-gray-400 text-center mb-6">
        ابتدا ایمیل خود را تأیید کنید
      </p>

      {error && (
        <div className="animate-scale-in mb-4 rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/30 px-4 py-2.5 text-sm text-red-600 dark:text-red-300 text-center">
          {error}
        </div>
      )}
      {notice && (
        <div className="animate-scale-in mb-4 flex items-center justify-center gap-2 rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/30 px-4 py-2.5 text-sm text-emerald-600 dark:text-emerald-300 text-center">
          <FaCheckCircle size={13} />
          {notice}
        </div>
      )}

      <div className="space-y-4">
        <div className="relative">
          <FaEnvelope className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
          <input
            type="email"
            placeholder="ایمیل"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={inputCls}
            disabled={codeSent}
          />
        </div>

        {!codeSent ? (
          <>
            <button
              onClick={handleSendCode}
              disabled={busy || !email}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 py-2.5 text-sm font-bold text-white shadow-lg shadow-emerald-500/25 transition hover:scale-[1.02] hover:shadow-xl hover:shadow-emerald-500/30 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
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
            <div className="relative">
              <FaShieldAlt className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
              <input
                type="text"
                placeholder="کد تأیید"
                value={verificationCode}
                onChange={(e) => setVerificationCode(e.target.value)}
                className={inputCls}
                autoFocus
              />
            </div>
            <div className="relative">
              <FaUser className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
              <input
                type="text"
                placeholder="نام کاربری"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className={inputCls}
              />
            </div>
            <div className="relative">
              <FaLock className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
              <input
                type="password"
                placeholder="گذرواژه"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputCls}
              />
            </div>
            <button
              onClick={handleRegister}
              disabled={busy || !verificationCode || !username || !password}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 py-2.5 text-sm font-bold text-white shadow-lg shadow-emerald-500/25 transition hover:scale-[1.02] hover:shadow-xl hover:shadow-emerald-500/30 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
            >
              {busy ? "در حال ثبت…" : "تکمیل ثبت‌نام"}
              <FaArrowLeft size={12} />
            </button>
            <button
              onClick={() => {
                setCodeSent(false);
                setNotice(null);
                setError(null);
              }}
              className="w-full text-center text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
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
