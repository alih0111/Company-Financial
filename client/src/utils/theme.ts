import { useEffect, useState } from "react";

// تم به‌صورت اشتراکی بین همه‌ی نمونه‌های useDarkMode نگه داشته می‌شود
// تا سوییچ تم از هدر، همه‌ی کامپوننت‌ها را هم‌زمان به‌روز کند.
let sharedDark: boolean | null = null;
const listeners = new Set<(v: boolean) => void>();

const readInitial = (): boolean => {
  const stored = localStorage.getItem("darkMode");
  if (stored !== null) return stored === "true";
  // در نبود انتخاب کاربر، از ترجیح سیستم پیروی می‌کنیم.
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-color-scheme: dark)").matches === true
  );
};

const applyTheme = (dark: boolean) => {
  document.documentElement.classList.toggle("dark", dark);
  localStorage.setItem("darkMode", String(dark));
};

export const useDarkMode = () => {
  const [darkMode, setDarkMode] = useState<boolean>(() => {
    if (sharedDark === null) {
      sharedDark = readInitial();
      applyTheme(sharedDark);
    }
    return sharedDark;
  });

  useEffect(() => {
    const fn = (v: boolean) => setDarkMode(v);
    listeners.add(fn);
    // همگام‌سازی با تغییری که پیش از mount رخ داده باشد
    if (sharedDark !== null && sharedDark !== darkMode) setDarkMode(sharedDark);
    return () => {
      listeners.delete(fn);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleDarkMode = () => {
    const next = !(sharedDark ?? darkMode);
    sharedDark = next;
    applyTheme(next);
    listeners.forEach((l) => l(next));
  };

  return { darkMode, toggleDarkMode };
};
