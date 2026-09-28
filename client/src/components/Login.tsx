import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FaUser, FaLock, FaEye, FaEyeSlash, FaSignInAlt } from "react-icons/fa";
import { useDarkMode } from "../utils/theme";
import AuthLayout from "./AuthLayout";
import { API_BASE } from "../config";

const Login = () => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { darkMode, toggleDarkMode } = useDarkMode();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json();

      if (res.ok) {
        localStorage.setItem("token", data.token);
        navigate("/dashboard");
      } else {
        setError(data.error || "ورود ناموفق بود");
      }
    } catch (err) {
      setError("خطای شبکه — دوباره تلاش کنید.");
    } finally {
      setLoading(false);
    }
  };

  const inputCls =
    "w-full rounded-xl border border-gray-200 dark:border-gray-600 bg-white/70 dark:bg-gray-900/50 text-gray-800 dark:text-gray-100 placeholder:text-gray-400 py-2.5 pr-10 pl-10 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-500 transition-all duration-200";

  return (
    <AuthLayout darkMode={darkMode} toggleDarkMode={toggleDarkMode}>
      <h1 className="text-xl font-bold text-gray-800 dark:text-white mb-1 text-center">
        ورود به حساب
      </h1>
      <p className="text-xs text-gray-400 text-center mb-6">
        برای دیدن داشبورد، اطلاعات حساب خود را وارد کنید
      </p>

      {error && (
        <div className="animate-scale-in mb-4 rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/30 px-4 py-2.5 text-sm text-red-600 dark:text-red-300 text-center">
          {error}
        </div>
      )}

      <form onSubmit={handleLogin} className="space-y-4">
        <div className="relative">
          <FaUser className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
          <input
            type="text"
            placeholder="نام کاربری"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className={inputCls}
            autoFocus
          />
        </div>

        <div className="relative">
          <FaLock className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
          <input
            type={showPass ? "text" : "password"}
            placeholder="گذرواژه"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputCls}
          />
          <button
            type="button"
            onClick={() => setShowPass((v) => !v)}
            aria-label={showPass ? "پنهان کردن گذرواژه" : "نمایش گذرواژه"}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
          >
            {showPass ? <FaEyeSlash /> : <FaEye />}
          </button>
        </div>

        <button
          type="submit"
          disabled={loading || !username || !password}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 py-2.5 text-sm font-bold text-white shadow-lg shadow-emerald-500/25 transition hover:scale-[1.02] hover:shadow-xl hover:shadow-emerald-500/30 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
        >
          {loading ? (
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <FaSignInAlt size={13} />
          )}
          {loading ? "در حال ورود…" : "ورود"}
        </button>
      </form>

      <p className="mt-6 text-sm text-center text-gray-500 dark:text-gray-400">
        حساب ندارید؟{" "}
        <Link
          to="/register"
          className="font-bold text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 hover:underline"
        >
          ثبت‌نام کنید
        </Link>
      </p>
    </AuthLayout>
  );
};

export default Login;
