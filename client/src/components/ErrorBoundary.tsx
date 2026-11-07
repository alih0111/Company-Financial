import { Component, type ErrorInfo, type ReactNode } from "react";

export default class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("RFA render error", error, info); }
  render() {
    if (!this.state.failed) return this.props.children;
    return <main dir="rtl" className="flex min-h-screen flex-col items-center justify-center gap-5 p-6 text-center">
      <h1 className="text-xl font-bold">بارگذاری صفحه کامل نشد</h1>
      <p className="text-sm text-gray-500">صفحه را دوباره بارگذاری کنید؛ ممکن است نسخهٔ تازه‌ای منتشر شده باشد.</p>
      <button className="rounded-xl bg-emerald-600 px-6 py-3 text-white" onClick={() => window.location.reload()}>بارگذاری دوباره</button>
      <a href="/">بازگشت به صفحهٔ اصلی</a>
    </main>;
  }
}
