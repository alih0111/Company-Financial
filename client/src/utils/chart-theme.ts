// تم مشترک برای همه‌ی نمودارها (recharts)
// رنگ‌ها، گرادیان‌ها و helper‌ها برای حفظ یکپارچگی ظاهری و dark mode.

export const chartPalette = {
  // مقیاس رنگی امتیاز (0=قرمز → 100=سبز)
  scoreStops: [
    { p: 0, color: "#ef4444" }, // red-500
    { p: 35, color: "#f59e0b" }, // amber-500
    { p: 70, color: "#84cc16" }, // lime-500
    { p: 100, color: "#10b981" }, // emerald-500
  ],

  // سری‌های داده‌ای
  series: ["#6366f1", "#ec4899", "#f59e0b", "#10b981", "#06b6d4", "#a855f7"],

  // نگاشت‌های مبحثی
  positive: "#10b981",
  negative: "#ef4444",
  neutral: "#f59e0b",

  // لبه‌های grid بسیار ملایم
  gridStroke: (dark: boolean) => (dark ? "rgba(148,163,184,0.12)" : "rgba(100,116,139,0.15)"),
  axisStroke: (dark: boolean) => (dark ? "#64748b" : "#94a3b8"),
  axisTick: (dark: boolean) => (dark ? "#94a3b8" : "#64748b"),

  cardBg: (dark: boolean) => (dark ? "rgba(31,41,55,0.6)" : "rgba(255,255,255,0.7)"),
  tooltipBg: (dark: boolean) => (dark ? "#0f172a" : "#ffffff"),
  tooltipBorder: (dark: boolean) => (dark ? "#1e293b" : "#e2e8f0"),
  tooltipText: (dark: boolean) => (dark ? "#e2e8f0" : "#0f172a"),
};

// کمکی: تولید رنگ pوی低压 از روی امتیاز 0..100
export const colorForScore = (score: number): string => {
  const s = Math.max(0, Math.min(100, score));
  for (let i = chartPalette.scoreStops.length - 1; i >= 0; i--) {
    if (s >= chartPalette.scoreStops[i].p) return chartPalette.scoreStops[i].color;
  }
  return chartPalette.scoreStops[0].color;
};

// محتوای مشترک Tooltip سفارشی برای recharts
export const glassTooltipStyle = (dark: boolean) => ({
  backgroundColor: chartPalette.tooltipBg(dark),
  border: `1px solid ${chartPalette.tooltipBorder(dark)}`,
  borderRadius: 14,
  boxShadow: "0 10px 30px -10px rgba(15,23,42,0.45)",
  padding: "10px 14px",
  color: chartPalette.tooltipText(dark),
  fontSize: 12,
  fontWeight: 600 as const,
  borderStyle: "solid" as const,
  // ترفند برای glassiness
  backdropFilter: "blur(8px)",
});

// فرمت عدد کوتاه
export const fmtShort = (n: number | null | undefined, digits = 2) => {
  if (n == null || Number.isNaN(n)) return "--";
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return (n / 1_000_000_000).toFixed(2) + "B";
  if (abs >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
  if (abs >= 1_000) return (n / 1_000).toFixed(2) + "K";
  return n.toFixed(digits);
};