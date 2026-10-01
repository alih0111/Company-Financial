import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  FaChartLine,
  FaCoins,
  FaSync,
  FaDownload,
  FaSearch,
  FaGlobe,
} from "react-icons/fa";
import PriceChart from "./PriceChart";
import { useDarkMode } from "../utils/theme";
import { getAuthStatus } from "../hooks/useGetUser";
import {
  getMarketAssets,
  collectMarketAssets,
  type MarketIndex,
  type MarketFund,
} from "../utils/api";

const num = (n: number) => (n || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });

const changeCls = (v: number) =>
  v >= 0
    ? "text-emerald-600 dark:text-emerald-400"
    : "text-red-500 dark:text-red-400";

type Selection =
  | { kind: "index"; key: string; label: string }
  | { kind: "fund"; key: string; label: string }
  | null;

const MarketPage: React.FC = () => {
  const { darkMode } = useDarkMode();
  const dark = darkMode;
  const { isAdmin } = getAuthStatus();

  const [indices, setIndices] = useState<MarketIndex[]>([]);
  const [funds, setFunds] = useState<MarketFund[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Selection>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getMarketAssets();
      setIndices(data.indices || []);
      setFunds(data.funds || []);
      setSelected((cur) => {
        if (cur) return cur;
        const first = data.indices?.[0];
        return first ? { kind: "index", key: first.name, label: first.name } : null;
      });
    } catch (e: any) {
      setError(e?.message || "خطا در دریافت داده بازار");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const goldFunds = useMemo(
    () => funds.filter((f) => f.kind === "gold"),
    [funds]
  );
  const commodityFunds = useMemo(
    () => funds.filter((f) => f.kind !== "gold"),
    [funds]
  );

  const filtered = useCallback(
    (list: MarketFund[]) => {
      const q = query.trim();
      if (!q) return list;
      return list.filter(
        (f) => f.symbol.includes(q) || f.name.includes(q)
      );
    },
    [query]
  );

  const runCollect = async (mode: "daily" | "backfill", symbol?: string) => {
    setBusy(symbol || mode);
    setMsg(null);
    try {
      await collectMarketAssets(mode, { symbol });
      setMsg(
        mode === "daily"
          ? "داده بازار به‌روز شد ✓"
          : `تاریخچه «${symbol}» در حال جمع‌آوری بود ✓`
      );
      setRefreshTick((t) => t + 1);
      await load();
    } catch (e: any) {
      setMsg(e?.message || "خطا در اجرای کالکتور");
    } finally {
      setBusy(null);
    }
  };

  const cardCls = `rounded-2xl border ${
    dark ? "bg-gray-800/50 border-gray-700/60" : "bg-white/60 border-gray-200/60"
  } backdrop-blur-sm`;

  const chipCls = (active: boolean) =>
    `w-full text-right rounded-xl border px-3 py-2 transition-all duration-200 ${
      active
        ? "border-emerald-500/50 bg-emerald-500/10 ring-1 ring-emerald-500/25"
        : dark
          ? "border-gray-700/60 hover:bg-gray-700/30"
          : "border-gray-200/80 hover:bg-gray-100/70"
    }`;

  return (
    <div className="flex flex-col gap-4">
      {/* ── Header ── */}
      <div className={`${cardCls} p-4 flex items-center justify-between flex-wrap gap-3`}>
        <div className="flex items-center gap-2">
          <span className="flex items-center justify-center w-8 h-8 rounded-xl bg-gradient-to-br from-amber-500 to-yellow-600 text-white shadow-sm">
            <FaGlobe size={14} />
          </span>
          <div>
            <h2 className="font-bold text-gray-800 dark:text-white text-sm">
              شاخص‌ها و نمادهای طلا
            </h2>
            <p className="text-[11px] text-gray-400 dark:text-gray-500">
              شاخص کل، هم‌وزن و صندوق‌های طلا/کالا — همراه با نمودار قیمت
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {msg && (
            <span
              className={`text-xs ${
                msg.includes("✓") ? "text-emerald-600 dark:text-emerald-400" : "text-red-500"
              }`}
            >
              {msg}
            </span>
          )}
          <button
            onClick={load}
            disabled={loading}
            className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-xl transition ${
              dark ? "bg-gray-700/60 hover:bg-gray-600/60" : "bg-gray-100 hover:bg-gray-200"
            } text-gray-600 dark:text-gray-300`}
          >
            <FaSync className={loading ? "animate-spin" : ""} size={11} />
            بازخوانی
          </button>
          {isAdmin && (
            <button
              onClick={() => runCollect("daily")}
              disabled={busy === "daily"}
              className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-xl text-white transition ${
                busy === "daily"
                  ? "bg-gray-400 cursor-not-allowed"
                  : "bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700"
              }`}
            >
              <FaDownload size={11} />
              {busy === "daily" ? "در حال به‌روزرسانی…" : "به‌روزرسانی داده بازار"}
            </button>
          )}
        </div>
      </div>

      {error && <p className="text-sm text-red-500 px-1">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-[330px_1fr] gap-4 items-start">
        {/* ── Selector ── */}
        <aside className={`${cardCls} p-3 flex flex-col gap-3 max-h-[720px] overflow-y-auto`}>
          {/* Indices */}
          <div>
            <div className="flex items-center gap-2 mb-2 px-1">
              <FaChartLine size={11} className="text-indigo-500" />
              <span className="text-[11px] font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                شاخص‌های بازار
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              {indices.length === 0 && !loading && (
                <p className="text-[11px] text-gray-400 px-1">شاخصی ثبت نشده است</p>
              )}
              {indices.map((ix) => {
                const active = selected?.kind === "index" && selected.key === ix.name;
                return (
                  <button
                    key={ix.code}
                    onClick={() => setSelected({ kind: "index", key: ix.name, label: ix.name })}
                    className={chipCls(active)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-gray-700 dark:text-gray-200 truncate">
                        {ix.name}
                      </span>
                      <span className="text-xs font-bold tabular-nums text-gray-800 dark:text-white">
                        {num(ix.value)}
                      </span>
                    </div>
                    <div className={`text-[10px] font-medium tabular-nums ${changeCls(ix.change_percent)}`} dir="ltr">
                      {ix.change_percent >= 0 ? "▲ +" : "▼ "}
                      {ix.change_percent.toFixed(2)}%
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Funds */}
          <div>
            <div className="flex items-center gap-2 mb-2 px-1">
              <FaCoins size={11} className="text-amber-500" />
              <span className="text-[11px] font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                طلا و کالا
              </span>
            </div>
            <div className="relative mb-2">
              <FaSearch
                size={10}
                className="absolute top-1/2 -translate-y-1/2 right-3 text-gray-400"
              />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="جست‌وجوی نماد…"
                className={`w-full rounded-xl border px-3 py-1.5 pr-8 text-xs outline-none transition ${
                  dark
                    ? "bg-gray-900/40 border-gray-700/60 text-gray-200 focus:border-emerald-500/60"
                    : "bg-white/70 border-gray-200 text-gray-700 focus:border-emerald-500/60"
                }`}
              />
            </div>
            <FundList
              title="طلا"
              list={filtered(goldFunds)}
              selected={selected}
              onSelect={(f) => setSelected({ kind: "fund", key: f.symbol, label: f.symbol })}
              chipCls={chipCls}
            />
            <FundList
              title="کالا"
              list={filtered(commodityFunds)}
              selected={selected}
              onSelect={(f) => setSelected({ kind: "fund", key: f.symbol, label: f.symbol })}
              chipCls={chipCls}
            />
          </div>
        </aside>

        {/* ── Chart ── */}
        <section className="flex flex-col gap-3 min-w-0">
          {selected ? (
            <>
              <PriceChart companyName={selected.key} refreshTick={refreshTick} />
              {isAdmin && selected.kind === "fund" && (
                <div className="flex items-center gap-2 px-1">
                  <button
                    onClick={() => runCollect("backfill", selected.key)}
                    disabled={busy === selected.key}
                    className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-xl text-white transition ${
                      busy === selected.key
                        ? "bg-gray-400 cursor-not-allowed"
                        : "bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700"
                    }`}
                  >
                    <FaDownload size={11} />
                    {busy === selected.key
                      ? "در حال جمع‌آوری… (سهمیه روزانه محدود است)"
                      : "جمع‌آوری تاریخچه این نماد"}
                  </button>
                  <span className="text-[11px] text-gray-400">
                    سهمیه‌ی رایگان API حدود ۱۰ درخواست تاریخچه در روز است.
                  </span>
                </div>
              )}
            </>
          ) : (
            <div className={`${cardCls} p-10 text-center text-sm text-gray-400`}>
              یک شاخص یا نماد طلا انتخاب کنید
            </div>
          )}
        </section>
      </div>
    </div>
  );
};

const FundList: React.FC<{
  title: string;
  list: MarketFund[];
  selected: Selection;
  onSelect: (f: MarketFund) => void;
  chipCls: (active: boolean) => string;
}> = ({ title, list, selected, onSelect, chipCls }) => {
  if (list.length === 0) return null;
  return (
    <div className="mb-2">
      <p className="text-[10px] font-medium text-gray-400 dark:text-gray-500 px-1 mb-1">{title}</p>
      <div className="flex flex-col gap-1.5">
        {list.map((f) => {
          const active = selected?.kind === "fund" && selected.key === f.symbol;
          const chg = f.change_percent || 0;
          return (
            <button key={f.symbol} onClick={() => onSelect(f)} className={chipCls(active)}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold text-gray-700 dark:text-gray-200 truncate">
                  {f.symbol}
                </span>
                <span className="text-xs font-bold tabular-nums text-gray-800 dark:text-white">
                  {f.last_price > 0 ? num(f.last_price) : "—"}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 mt-0.5">
                <span className="text-[10px] text-gray-400 dark:text-gray-500 truncate">
                  {f.name}
                </span>
                <span
                  className={`text-[10px] font-medium tabular-nums shrink-0 ${
                    chg >= 0
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-red-500 dark:text-red-400"
                  }`}
                  dir="ltr"
                >
                  {f.observations === 0
                    ? "بدون سابقه"
                    : `${chg >= 0 ? "▲ +" : "▼ "}${chg.toFixed(2)}%`}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default MarketPage;
