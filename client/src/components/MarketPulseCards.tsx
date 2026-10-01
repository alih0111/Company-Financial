import React, { useEffect, useMemo, useState } from "react";
import { FaChartLine, FaBalanceScale, FaCoins, FaDollarSign } from "react-icons/fa";
import { useDarkMode } from "../utils/theme";
import {
  getMarketAssets,
  getPriceHistory,
  type MarketIndex,
  type MarketFund,
} from "../utils/api";

// «نبض بازار» — چهار کارت فشرده از وضعیت امروز بازار برای بالای صفحه
// دارایی خانواده: شاخص کل، شاخص هم‌وزن، طلا (مثقال) و دلار.
// داده‌ها از همان endpointهای موجود می‌آید (/api/market/assets و price-history).

const fmtInt = (n: number | null | undefined) =>
  (n ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 });

const Change: React.FC<{ pct: number | null | undefined }> = ({ pct }) => {
  if (pct == null || !Number.isFinite(pct)) return null;
  const up = pct >= 0;
  return (
    <div
      className={`text-[11px] font-semibold tabular-nums ${
        up ? "text-emerald-600 dark:text-emerald-400" : "text-red-500 dark:text-red-400"
      }`}
      dir="ltr"
    >
      {up ? "▲ +" : "▼ "}
      {pct.toFixed(2)}%
    </div>
  );
};

const MarketPulseCards: React.FC<{
  dollarPrice?: number;
  dollarDate?: string;
}> = ({ dollarPrice, dollarDate }) => {
  const { darkMode } = useDarkMode();
  const [indices, setIndices] = useState<MarketIndex[]>([]);
  const [funds, setFunds] = useState<MarketFund[]>([]);
  const [goldMonthPct, setGoldMonthPct] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [assets, hist] = await Promise.allSettled([
          getMarketAssets(),
          getPriceHistory("مثقال", 60),
        ]);
        if (!alive) return;
        if (assets.status === "fulfilled") {
          setIndices(assets.value.indices || []);
          setFunds(assets.value.funds || []);
        }
        if (hist.status === "fulfilled" && hist.value.length > 1) {
          // ردیف‌ها نزولی‌اند (تازه → قدیمی). نقطه‌ی «حدود یک ماه قبل» را پیدا کن.
          const rows = hist.value;
          const latest = new Date(rows[0].date + "T00:00:00Z").getTime();
          const cut = latest - 30 * 86400000;
          const base =
            rows.find((r) => new Date(r.date + "T00:00:00Z").getTime() <= cut) ??
            rows[rows.length - 1];
          const now = rows[0].closing_price;
          if (base && base.closing_price > 0 && now > 0) {
            setGoldMonthPct(((now - base.closing_price) / base.closing_price) * 100);
          }
        }
      } catch {
        /* بازار در دسترس نیست → کارت‌ها خالی می‌مانند */
      } finally {
        if (alive) setLoaded(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const tedpix = useMemo(
    () => indices.find((i) => i.code === "TEDPIX"),
    [indices]
  );
  const tedpixEw = useMemo(
    () => indices.find((i) => i.code === "TEDPIX_EW"),
    [indices]
  );
  const gold = useMemo(
    () => funds.find((f) => f.symbol === "مثقال") || funds.find((f) => f.kind === "gold"),
    [funds]
  );

  if (!loaded) return null;

  const hasMarket = !!(tedpix || tedpixEw || gold);
  if (!hasMarket && !dollarPrice) return null;

  const card = `rounded-2xl border p-4 ${
    darkMode
      ? "bg-gray-800/50 border-gray-700/60"
      : "bg-white/60 border-gray-200/60"
  } backdrop-blur-sm`;

  const indexCard = (ix: MarketIndex | undefined, label: string, icon: React.ReactNode) =>
    ix && (
      <div className={card}>
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs text-gray-500 dark:text-gray-400">{label}</div>
          <span className="text-indigo-500 text-sm">{icon}</span>
        </div>
        <div className="text-lg font-bold text-gray-800 dark:text-white tabular-nums" dir="ltr">
          {fmtInt(ix.value)}
        </div>
        <Change pct={ix.change_percent} />
        <div className="text-[10px] text-gray-400 mt-0.5">{ix.jalali_date}</div>
      </div>
    );

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {indexCard(tedpix, "شاخص کل", <FaChartLine />)}
      {indexCard(tedpixEw, "شاخص کل (هم‌وزن)", <FaBalanceScale />)}
      {gold && (
        <div className={card}>
          <div className="flex items-center justify-between mb-1">
            <div className="text-xs text-gray-500 dark:text-gray-400">
              طلا <span className="text-gray-400/80">({gold.symbol})</span>
            </div>
            <span className="text-amber-500 text-sm">
              <FaCoins />
            </span>
          </div>
          <div className="text-lg font-bold text-gray-800 dark:text-white tabular-nums" dir="ltr">
            {fmtInt(gold.last_price)}
          </div>
          <Change pct={gold.change_percent} />
          {goldMonthPct != null && (
            <div className="text-[10px] text-gray-400 mt-0.5">
              ۱ ماهه:{" "}
              <span
                className={
                  goldMonthPct >= 0
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-red-500 dark:text-red-400"
                }
                dir="ltr"
              >
                {goldMonthPct >= 0 ? "+" : ""}
                {goldMonthPct.toFixed(1)}%
              </span>
            </div>
          )}
        </div>
      )}
      {!!dollarPrice && (
        <div className={card}>
          <div className="flex items-center justify-between mb-1">
            <div className="text-xs text-gray-500 dark:text-gray-400">دلار (آزاد)</div>
            <span className="text-sky-500 text-sm">
              <FaDollarSign />
            </span>
          </div>
          <div className="text-lg font-bold text-gray-800 dark:text-white tabular-nums" dir="ltr">
            {fmtInt(dollarPrice)}
          </div>
          <div className="text-[10px] text-gray-400 mt-1">
            نرخ دستی {dollarDate ? `— ${dollarDate}` : ""}
          </div>
        </div>
      )}
    </div>
  );
};

export default MarketPulseCards;
