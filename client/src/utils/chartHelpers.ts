// هلپرهای مشترک نمودار lightweight-charts: تقویم شمسی + تم روشن/تاریک.
// PriceChart و ComparePage هر دو از این ماژول استفاده می‌کنند تا محور زمان
// و ظاهر نمودار در کل اپ یکسان بماند.

import {
  ColorType,
  CrosshairMode,
  TickMarkType,
  type DeepPartial,
  type ChartOptions,
  type Time,
} from "lightweight-charts";

export const JALALI_MONTHS = [
  "فروردین",
  "اردیبهشت",
  "خرداد",
  "تیر",
  "مرداد",
  "شهریور",
  "مهر",
  "آبان",
  "آذر",
  "دی",
  "بهمن",
  "اسفند",
];

// فرمترها یک‌بار ساخته می‌شوند؛ ساخت مکرر Intl در هر تیک پرهزینه است.
// تقویم persian با timeZone=UTC چون زمان کندل‌ها نیمه‌شب UTC است.
const jDateFmt = new Intl.DateTimeFormat("en-US-u-ca-persian", {
  timeZone: "UTC",
  year: "numeric",
  month: "numeric",
  day: "numeric",
});
const jClockFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: "UTC",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const jClockSecFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: "UTC",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export const faDigits = (s: string) =>
  s.replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[+d]);

// timestamp را به اجزای تاریخ شمسی تبدیل می‌کند (پشتیبانی از هر سه نوع Time)
export const jalaliParts = (time: Time) => {
  const d =
    typeof time === "number"
      ? new Date(time * 1000)
      : typeof time === "object"
        ? new Date(Date.UTC(time.year, time.month - 1, time.day))
        : new Date(time + "T00:00:00Z");
  const map: Record<string, string> = {};
  for (const p of jDateFmt.formatToParts(d)) map[p.type] = p.value;
  return {
    jy: +map.year,
    jm: +map.month,
    jd: +map.day,
    d,
    // قالب کامل مطابق فرمت بک‌اند: ۱۴۰۳/۰۵/۱۲
    full: faDigits(
      `${map.year}/${String(map.month).padStart(2, "0")}/${String(
        map.day,
      ).padStart(2, "0")}`,
    ),
  };
};

// برچسب تیک‌های محور زمان: سال/ماه/روز شمسی
export const jalaliTickMark = (time: Time, tickMarkType: TickMarkType) => {
  const { jy, jm, jd, d } = jalaliParts(time);
  switch (tickMarkType) {
    case TickMarkType.Year:
      return faDigits(String(jy));
    case TickMarkType.Month:
      return JALALI_MONTHS[jm - 1] ?? faDigits(String(jm));
    case TickMarkType.DayOfMonth:
      return faDigits(String(jd));
    case TickMarkType.Time:
      return faDigits(jClockFmt.format(d));
    case TickMarkType.TimeWithSeconds:
      return faDigits(jClockSecFmt.format(d));
    default:
      return faDigits(String(jy));
  }
};

/** گزینه‌های مشترک ظاهر نمودار (پس‌زمینه شفاف، خطوط راهنما، کراس‌هیر). */
export function baseChartOptions(dark: boolean): DeepPartial<ChartOptions> {
  return {
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: dark ? "#94a3b8" : "#64748b",
      fontFamily: '"Vazirmatn", "Segoe UI", Tahoma, system-ui, sans-serif',
      fontSize: 11,
    },
    grid: {
      vertLines: { visible: false },
      horzLines: {
        color: dark ? "rgba(148,163,184,0.08)" : "rgba(100,116,139,0.1)",
      },
    },
    localization: {
      locale: "fa-IR",
      timeFormatter: (time: Time) => jalaliParts(time).full,
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: {
        color: dark ? "rgba(148,163,184,0.35)" : "rgba(100,116,139,0.35)",
        width: 1,
        style: 2,
        labelBackgroundColor: dark ? "#334155" : "#475569",
      },
      horzLine: {
        color: dark ? "rgba(148,163,184,0.35)" : "rgba(100,116,139,0.35)",
        labelBackgroundColor: dark ? "#334155" : "#475569",
      },
    },
    timeScale: {
      borderVisible: false,
      tickMarkFormatter: jalaliTickMark,
    },
  };
}
