// دیده‌بان شخصی — نمادهای منتخب کاربر با آخرین قیمت، تغییر روز و روند ۹۰ روزه.
// داده‌ها در localStorage ذخیره می‌شوند (بدون نیاز به بک‌اند جدید) و برای هر
// نماد فقط یک درخواست price-history با سقف ۱۰۰ روز زده می‌شود (کش ۵ دقیقه).

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { FaEye, FaSync, FaTrash, FaPlus, FaBell } from "react-icons/fa";
import { getPriceHistory, type PriceHistoryRow } from "../utils/api";
import { useDarkMode } from "../utils/theme";
import { useToast } from "./Toast";
import AssetSelect from "./AssetSelect";
import {
  getWatchlist,
  removeFromWatch,
  subscribeWatchlist,
  toggleWatch,
  MAX_WATCH,
  type WatchItem,
} from "../utils/watchlist";
import {
  checkAlerts,
  getAlert,
  removeAlert,
  setAlert,
  subscribeAlerts,
} from "../utils/alerts";

const SPARK_DAYS = 100;

// کش مشترک تاریخچه‌های کوتاه دیده‌بان
const sparkCache = new Map<string, { at: number; rows: PriceHistoryRow[] }>();
const TTL = 5 * 60 * 1000;

async function spark(key: string): Promise<PriceHistoryRow[]> {
  const hit = sparkCache.get(key);
  if (hit && Date.now() - hit.at < TTL) return hit.rows;
  const rows = await getPriceHistory(key, SPARK_DAYS);
  sparkCache.set(key, { at: Date.now(), rows });
  return rows;
}

interface RowState {
  loading: boolean;
  error?: string;
  last?: number;
  chg?: number;
  ret?: number; // بازده کل بازه‌ی اسپارک
  points?: number[]; // سری اسپارک‌لاین
}

const WatchlistPage: React.FC = () => {
  const { darkMode: dark } = useDarkMode();
  const toast = useToast();
  const [items, setItems] = useState<WatchItem[]>(getWatchlist);
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const [refreshing, setRefreshing] = useState(false);
  const [addKey, setAddKey] = useState<string>("");
  // ویرایشگر هشدار قیمت — کلید نمادِ در حال تنظیم
  const [alertEditKey, setAlertEditKey] = useState<string | null>(null);
  const [alertTick, setAlertTick] = useState(0);

  useEffect(() => subscribeWatchlist(() => setItems(getWatchlist())), []);
  useEffect(() => subscribeAlerts(() => setAlertTick((t) => t + 1)), []);

  // اعلان مرورگر (اگر مجوز داده شده باشد)
  const notifyBrowser = (title: string, body: string) => {
    if ("Notification" in window && Notification.permission === "granted") {
      try {
        new Notification(title, { body });
      } catch {
        /* بعضی محیط‌ها Notification سازنده را اجازه نمی‌دهند */
      }
    }
  };

  const loadAll = useCallback(async (force = false) => {
    const list = getWatchlist();
    if (force) {
      for (const it of list) sparkCache.delete(it.key);
    }
    setRefreshing(true);
    setRows(() => {
      const next: Record<string, RowState> = {};
      for (const it of list) next[it.key] = { loading: true };
      return next;
    });
    const latest: Record<string, number | undefined> = {};
    for (const it of list) {
      try {
        const hist = await spark(it.key);
        // جدیدترین اول → صعودی برای اسپارک؛ تکراری‌های یک روز حذف
        const asc: PriceHistoryRow[] = [];
        const seen = new Set<string>();
        for (const r of hist) {
          if (r.closing_price > 0 && !seen.has(r.date)) {
            seen.add(r.date);
            asc.push(r);
          }
        }
        asc.reverse();
        const last = asc[asc.length - 1];
        const prev = asc[asc.length - 2];
        const first = asc[0];
        latest[it.key] = last?.closing_price;
        setRows((p) => ({
          ...p,
          [it.key]: {
            loading: false,
            last: last?.closing_price,
            chg: last && prev ? ((last.closing_price - prev.closing_price) / prev.closing_price) * 100 : undefined,
            ret:
              first && last && first.closing_price > 0
                ? (last.closing_price / first.closing_price - 1) * 100
                : undefined,
            points: asc.map((r) => r.closing_price),
          },
        }));
      } catch (e: any) {
        setRows((p) => ({
          ...p,
          [it.key]: { loading: false, error: e?.message || "خطا" },
        }));
      }
    }
    // بررسی هشدارهای قیمت با آخرین مقادیر — اعلان یک‌باره برای هر هشدار تازه
    const fired = checkAlerts(latest);
    for (const a of fired) {
      const msg = `«${a.label}» به ${a.above ? "بالاتر از" : "پایین‌تر از"} ${a.price.toLocaleString("en-US")} رسید`;
      toast.warning(`🔔 هشدار قیمت: ${msg}`);
      notifyBrowser("هشدار قیمت — RFA", msg);
    }
    setRefreshing(false);
  }, []);

  // کلید رشته‌ای تا آرایه‌ی جدید در هر رندر افکت را دوباره اجرا نکند
  const itemsKey = items.map((i) => i.key).join(",");

  useEffect(() => {
    void loadAll(false);
  }, [itemsKey, loadAll]);

  const onAdd = useCallback((vals: string[]) => {
    const k = vals[0];
    if (!k) return;
    // برچسب = خود نماد؛ نوع از AssetSelect تشخیص داده نمی‌شود، stock پیش‌فرض
    // (برای رسم قیمت تفاوتی ندارد — همه از price-history خوانده می‌شوند)
    toggleWatch({ key: k, label: k, kind: "stock" });
    setAddKey("");
  }, []);

  const cardCls = `rounded-2xl border ${
    dark ? "bg-gray-800/50 border-gray-700/60" : "bg-white/60 border-gray-200/60"
  } backdrop-blur-sm`;

  const fmt = (n: number) =>
    n >= 1000 ? n.toLocaleString("en-US", { maximumFractionDigits: 0 }) : n.toFixed(2);

  const full = items.length >= MAX_WATCH;

  return (
    <div className="flex flex-col gap-4">
      {/* سربرگ */}
      <div className={`${cardCls} p-4 flex items-center justify-between flex-wrap gap-3`}>
        <div className="flex items-center gap-2">
          <span className="flex items-center justify-center w-8 h-8 rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 text-white shadow-sm">
            <FaEye size={14} />
          </span>
          <div>
            <h2 className="font-bold text-gray-800 dark:text-white text-sm">دیده‌بان شخصی</h2>
            <p className="text-[11px] text-gray-500 dark:text-gray-400">
              نمادهای شما با آخرین قیمت، تغییر روز و روند ۹۰ روزه ({items.length.toLocaleString("fa-IR")} از{" "}
              {MAX_WATCH.toLocaleString("fa-IR")})
            </p>
          </div>
        </div>
        <button
          onClick={() => void loadAll(true)}
          disabled={refreshing || items.length === 0}
          className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-xl transition ${
            dark ? "bg-gray-700/60 hover:bg-gray-600/60" : "bg-gray-100 hover:bg-gray-200"
          } text-gray-600 dark:text-gray-300 disabled:opacity-50`}
        >
          <FaSync className={refreshing ? "animate-spin" : ""} size={11} />
          به‌روزرسانی
        </button>
      </div>

      {/* افزودن */}
      <div className={`${cardCls} p-4`}>
        <label className="mb-1.5 block px-1 text-[10px] font-bold text-gray-500 dark:text-gray-400">
          افزودن نماد به دیده‌بان (سهام، صندوق طلا یا شاخص)
        </label>
        <AssetSelect
          value={addKey ? [addKey] : []}
          max={1}
          placeholder={full ? "دیده‌بان پر است (۱۵ نماد)" : "جست‌وجو و افزودن…"}
          onChange={onAdd}
        />
        {full && (
          <p className="mt-1.5 text-[10px] text-amber-600 dark:text-amber-400">
            سقف دیده‌بان {MAX_WATCH.toLocaleString("fa-IR")} نماد است — برای افزودن، یکی را حذف کنید.
          </p>
        )}
      </div>

      {/* ردیف‌ها */}
      {items.length === 0 ? (
        <div className={`${cardCls} p-10 text-center`}>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">
            دیده‌بان خالی است — چند نماد پیشنهادی:
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            {["عیار", "مثقال", "فولاد مبارکه", "شاخص کل", "همیان"].map((s) => (
              <button
                key={s}
                onClick={() => toggleWatch({ key: s, label: s, kind: "fund" })}
                className="text-xs px-3 py-1.5 rounded-full border border-emerald-500/40 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-500/10 transition-colors flex items-center gap-1.5"
              >
                <FaPlus size={9} />
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3" data-tick={alertTick}>
          {items.map((it) => {
            const r = rows[it.key];
            const up = (r?.chg ?? 0) >= 0;
            const alert = getAlert(it.key);
            return (
              <div
                key={it.key}
                className={`${cardCls} p-3.5 group relative transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-emerald-500/5`}
              >
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="min-w-0">
                    <Link
                      to={`/dashboard?companyname=${encodeURIComponent(it.key)}`}
                      className="text-sm font-bold text-gray-800 dark:text-white hover:text-emerald-600 dark:hover:text-emerald-400 transition-colors truncate block"
                    >
                      {it.label}
                    </Link>
                    <span className="text-[10px] text-gray-400">
                      {it.kind === "index" ? "شاخص" : it.kind === "fund" ? "صندوق طلا/کالا" : "نماد بازار"}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() =>
                        setAlertEditKey(alertEditKey === it.key ? null : it.key)
                      }
                      aria-label="هشدار قیمت"
                      title="هشدار قیمت (بالای/زیر یک هدف)"
                      className={`p-1 transition-colors ${
                        alert
                          ? "text-amber-400"
                          : "text-gray-400 opacity-0 group-hover:opacity-100 hover:text-amber-400"
                      }`}
                    >
                      <FaBell size={11} />
                    </button>
                    <button
                      onClick={() => removeFromWatch(it.key)}
                      aria-label={`حذف ${it.label}`}
                      title="حذف از دیده‌بان"
                      className="opacity-0 group-hover:opacity-100 transition text-gray-400 hover:text-red-500 p-1"
                    >
                      <FaTrash size={11} />
                    </button>
                  </div>
                </div>

                {alert && (
                  <p className="text-[9px] text-amber-600 dark:text-amber-400 mb-1.5 flex items-center gap-1 tabular-nums">
                    <FaBell size={7} />
                    هشدار: {alert.above ? "بالای" : "زیر"} {alert.price.toLocaleString("en-US")}
                    {alert.triggeredAt ? " · فعال شد" : " · در انتظار"}
                  </p>
                )}

                {alertEditKey === it.key && (
                  <AlertEditor item={it} last={r?.last} onDone={() => setAlertEditKey(null)} />
                )}

                {r?.loading ? (
                  <div className="h-12 flex items-center text-[11px] text-gray-400">در حال دریافت…</div>
                ) : r?.error ? (
                  <div className="h-12 flex items-center text-[11px] text-red-400">{r.error}</div>
                ) : (
                  <div className="flex items-end justify-between gap-2">
                    <div className="flex flex-col">
                      <span className="text-sm font-bold text-gray-800 dark:text-white tabular-nums" dir="ltr">
                        {r?.last != null ? fmt(r.last) : "—"}
                      </span>
                      <span
                        className={`text-[11px] font-semibold tabular-nums ${
                          up ? "text-emerald-600 dark:text-emerald-400" : "text-red-500 dark:text-red-400"
                        }`}
                        dir="ltr"
                      >
                        {r?.chg != null ? `${up ? "▲ +" : "▼ "}${r.chg.toFixed(2)}%` : "—"}
                      </span>
                      {r?.ret != null && (
                        <span className="text-[9px] text-gray-400 tabular-nums" dir="ltr">
                          {r.ret >= 0 ? "+" : ""}
                          {r.ret.toFixed(1)}% / 90d
                        </span>
                      )}
                    </div>
                    <Sparkline points={r?.points ?? []} up={up} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="text-[10px] text-gray-400 px-1">
        با کلیک روی نام هر نماد، صفحه‌ی تحلیل آن باز می‌شود. داده‌ها با کش ۵ دقیقه‌ای از
        همان تاریخچه‌ی قیمت سامانه خوانده می‌شوند.
      </p>
    </div>
  );
};

// ویرایشگر هشدار قیمت — داخل کارت دیده‌بان باز می‌شود
const AlertEditor: React.FC<{
  item: WatchItem;
  last?: number;
  onDone: () => void;
}> = ({ item, last, onDone }) => {
  const existing = getAlert(item.key);
  const [above, setAbove] = useState(existing?.above ?? true);
  const [price, setPrice] = useState<string>(() => {
    if (existing?.price) return String(existing.price);
    if (last && last > 0) return String(Math.round(last * 1.05));
    return "";
  });

  const save = () => {
    const p = Number(price);
    if (!Number.isFinite(p) || p <= 0) return;
    setAlert({ key: item.key, label: item.label, above, price: p });
    if ("Notification" in window && Notification.permission === "default") {
      void Notification.requestPermission();
    }
    onDone();
  };

  const inputCls =
    "w-24 rounded-lg border border-gray-200 dark:border-gray-700 bg-white/70 dark:bg-gray-900/40 px-2 py-1 text-xs tabular-nums text-gray-800 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-amber-500/30";

  return (
    <div className="mb-2 rounded-xl border border-amber-200/70 dark:border-amber-800/40 bg-amber-50/60 dark:bg-amber-950/20 p-2 flex flex-wrap items-center gap-2">
      <span className="text-[10px] font-bold text-amber-700 dark:text-amber-300">
        هشدار وقتی قیمت رفت
      </span>
      <div className="flex rounded-lg overflow-hidden border border-amber-300/50 dark:border-amber-700/50">
        <button
          onClick={() => setAbove(true)}
          className={`px-2 py-1 text-[10px] font-bold transition ${
            above ? "bg-amber-500 text-white" : "text-amber-700 dark:text-amber-300 hover:bg-amber-500/10"
          }`}
        >
          بالای
        </button>
        <button
          onClick={() => setAbove(false)}
          className={`px-2 py-1 text-[10px] font-bold transition ${
            !above ? "bg-amber-500 text-white" : "text-amber-700 dark:text-amber-300 hover:bg-amber-500/10"
          }`}
        >
          زیر
        </button>
      </div>
      <input
        dir="ltr"
        inputMode="decimal"
        value={price}
        onChange={(e) => setPrice(e.target.value.replace(/[^\d.]/g, ""))}
        placeholder="قیمت هدف"
        className={inputCls}
      />
      <button
        onClick={save}
        className="px-2.5 py-1 rounded-lg bg-amber-500 hover:bg-amber-600 text-white text-[10px] font-bold transition"
      >
        ذخیره
      </button>
      {existing && (
        <button
          onClick={() => {
            removeAlert(item.key);
            onDone();
          }}
          className="px-2.5 py-1 rounded-lg border border-amber-300/60 dark:border-amber-700/50 text-amber-700 dark:text-amber-300 hover:bg-amber-500/10 text-[10px] font-bold transition"
        >
          حذف هشدار
        </button>
      )}
    </div>
  );
};

// اسپارک‌لاین SVG سبک — بدون کتابخانه‌ی چارت
const Sparkline: React.FC<{ points: number[]; up: boolean }> = ({ points, up }) => {
  const memo = useMemo(() => {
    if (!points || points.length < 2) return null;
    const w = 96;
    const h = 34;
    const min = Math.min(...points);
    const max = Math.max(...points);
    const span = max - min || 1;
    const step = w / (points.length - 1);
    const coords = points.map(
      (p, i) => `${(i * step).toFixed(1)},${(h - 3 - ((p - min) / span) * (h - 6)).toFixed(1)}`,
    );
    return { w, h, line: coords.join(" "), area: `0,${h} ${coords.join(" ")} ${w},${h}` };
  }, [points]);

  if (!memo) return <div className="w-24 h-9" />;
  const color = up ? "#10b981" : "#ef4444";
  return (
    <svg width={memo.w} height={memo.h} className="shrink-0">
      <polygon points={memo.area} fill={color} opacity={0.1} />
      <polyline points={memo.line} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
};

export default WatchlistPage;
