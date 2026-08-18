import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { FaPlus, FaTrash, FaEdit, FaTimes, FaCheck, FaCoins } from "react-icons/fa";
import { useDarkMode } from "../utils/theme";
import { glassTooltipStyle } from "../utils/chart-theme";
import {
  getFamilyAssets,
  saveFamilyPrices,
  syncFamilyPrices,
  upsertFamilyHolding,
  deleteFamilyHolding,
  createFamilyPerson,
  createFamilyAsset,
  updateFamilyAccount,
  getFamilyCashFlows,
  addFamilyCashFlow,
  deleteFamilyCashFlow,
  getFamilyHistory,
} from "../utils/api";
import type {
  FamilyState,
  FamilyPerson,
  FamilyHistoryRow,
  FamilyCashFlow,
} from "../utils/api";

const fmtInt = (n: number | null | undefined) => {
  if (n == null || Number.isNaN(n)) return "--";
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
};

const fmtCompact = (n: number | null | undefined) => {
  if (n == null || Number.isNaN(n)) return "--";
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return (n / 1_000_000_000).toFixed(2) + "B";
  if (abs >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (abs >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return n.toFixed(0);
};

const fmtPct = (n: number | null | undefined, digits = 1) => {
  if (n == null || Number.isNaN(n)) return "--";
  return (n * 100).toFixed(digits) + "%";
};

const inputCls =
  "w-full rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100 px-3 py-1.5 text-sm focus:border-indigo-500 outline-none";

type Tab = "summary" | "people" | "history" | "flows";

// رنگ اختصاصی هر شخص (به ترتیب SortOrder) و گرادیان جمع کل
const PERSON_COLORS = [
  "#6366f1",
  "#ec4899",
  "#10b981",
  "#f59e0b",
  "#06b6d4",
  "#8b5cf6",
  "#f43f5e",
  "#84cc16",
  "#f97316",
  "#14b8a6",
];
const personColor = (i: number) => PERSON_COLORS[i % PERSON_COLORS.length];

// n ماه قبل از یک تاریخ شمسی (برای فیلتر بازه چارت) — رشته صفرپَد قابل مقایسه
const jalaliMonthsAgo = (dateKey: string, months: number): string => {
  const [y, m, d] = dateKey.split("/").map(Number);
  const total = y * 12 + (m - 1) - months;
  const y2 = Math.floor(total / 12);
  const m2 = (total % 12) + 1;
  const maxDay = m2 <= 6 ? 31 : m2 === 12 ? 29 : 30;
  const d2 = Math.min(d, maxDay);
  return `${String(y2).padStart(4, "0")}/${String(m2).padStart(2, "0")}/${String(d2).padStart(2, "0")}`;
};

const RANGES = [
  { key: "all", label: "همه", months: 0 },
  { key: "3y", label: "۳ سال", months: 36 },
  { key: "1y", label: "۱ سال", months: 12 },
  { key: "6m", label: "۶ ماه", months: 6 },
  { key: "3m", label: "۳ ماه", months: 3 },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

const FamilyAssets = () => {
  const { darkMode } = useDarkMode();

  const [state, setState] = useState<FamilyState | null>(null);
  const [history, setHistory] = useState<FamilyHistoryRow[]>([]);
  const [flows, setFlows] = useState<FamilyCashFlow[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("summary");

  const [priceDate, setPriceDate] = useState("");
  const [priceInputs, setPriceInputs] = useState<Record<number, string>>({});
  const [savingPrices, setSavingPrices] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const [rangeKey, setRangeKey] = useState<RangeKey>("all");
  const [chartMode, setChartMode] = useState<"line" | "stack">("line");
  const [logScale, setLogScale] = useState(false);
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set());
  const [backfilling, setBackfilling] = useState(false);

  const [editing, setEditing] = useState<{
    personId: number;
    assetId: number;
    quantity: string;
    costBasis: string;
  } | null>(null);

  const [addingFor, setAddingFor] = useState<number | null>(null);
  const [addForm, setAddForm] = useState({ asset_id: "", quantity: "", cost_basis: "" });

  const [cashEdit, setCashEdit] = useState<{ personId: number; value: string } | null>(null);

  const [newPersonName, setNewPersonName] = useState("");
  const [newAssetName, setNewAssetName] = useState("");
  const [newAssetCategory, setNewAssetCategory] = useState("stock");

  const [flowForm, setFlowForm] = useState({ date_key: "", amount: "", direction: "in", note: "" });
  const [savingFlow, setSavingFlow] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [st, hist, fl] = await Promise.all([
        getFamilyAssets(),
        getFamilyHistory(),
        getFamilyCashFlows(),
      ]);
      setState(st);
      setHistory(hist || []);
      setFlows(fl || []);
      setPriceDate((prev) => prev || st.today_datekey);
      setFlowForm((f) => ({ ...f, date_key: f.date_key || st.today_datekey }));
      setPriceInputs((prev) => {
        const next: Record<number, string> = {};
        for (const a of st.assets) next[a.asset_id] = prev[a.asset_id] ?? String(a.latest_price || "");
        return next;
      });
    } catch (e: any) {
      setError(e?.message || "خطا در بارگذاری دارایی‌ها");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(null), 4000);
    return () => clearTimeout(t);
  }, [msg]);

  const submitPrices = async () => {
    if (!state) return;
    const prices: { asset_id: number; price: number }[] = [];
    for (const a of state.assets) {
      const raw = priceInputs[a.asset_id];
      if (!raw || raw.trim() === "") continue;
      const p = parseFloat(raw);
      if (!Number.isNaN(p) && p > 0) prices.push({ asset_id: a.asset_id, price: p });
    }
    if (!priceDate || prices.length === 0) {
      setError("تاریخ و حداقل یک قیمت معتبر لازم است");
      return;
    }
    setSavingPrices(true);
    setError(null);
    try {
      const res = await saveFamilyPrices(priceDate, prices);
      setMsg(`قیمت‌های ${priceDate} ذخیره شد — جمع کل: ${fmtInt(res.total_value)}`);
      await loadAll();
    } catch (e: any) {
      setError(e?.message || "ذخیره قیمت‌ها ناموفق بود");
    } finally {
      setSavingPrices(false);
    }
  };

  const syncFromMarket = async () => {
    setSyncing(true);
    setError(null);
    try {
      const res = await syncFamilyPrices();
      const parts: string[] = [];
      if (res.updated?.length) {
        const dates = [...new Set(res.updated.map((u) => u.date_key))];
        parts.push(`${res.updated.length} قیمت از بازار (${dates.join("، ")}) دریافت شد ✓`);
      }
      if (res.missing?.length) {
        parts.push(`دستی وارد کنید: ${res.missing.join("، ")}`);
      }
      setMsg(parts.join(" — ") || "قیمتی برای دریافت نبود");
      await loadAll();
    } catch (e: any) {
      setError(e?.message || "دریافت قیمت از بازار ناموفق بود");
    } finally {
      setSyncing(false);
    }
  };

  const startEdit = (personId: number, assetId: number, qty: number, cost: number) => {
    setAddingFor(null);
    setEditing({
      personId,
      assetId,
      quantity: String(qty),
      costBasis: String(cost),
    });
  };

  const saveEdit = async () => {
    if (!editing) return;
    const quantity = parseFloat(editing.quantity);
    const costBasis = parseFloat(editing.costBasis);
    if (Number.isNaN(quantity) || quantity < 0 || Number.isNaN(costBasis) || costBasis < 0) {
      setError("تعداد یا بهای تمام‌شده معتبر نیست");
      return;
    }
    try {
      await upsertFamilyHolding({
        person_id: editing.personId,
        asset_id: editing.assetId,
        quantity,
        cost_basis: costBasis,
      });
      setEditing(null);
      setMsg("ذخیره شد ✓");
      await loadAll();
    } catch (e: any) {
      setError(e?.message || "ذخیره ناموفق بود");
    }
  };

  const removeHolding = async (personId: number, assetId: number, name: string) => {
    if (!window.confirm(`حذف «${name}» از این سبد؟`)) return;
    try {
      await deleteFamilyHolding(personId, assetId);
      await loadAll();
    } catch (e: any) {
      setError(e?.message || "حذف ناموفق بود");
    }
  };

  const saveAdd = async () => {
    if (addingFor == null) return;
    const assetId = parseInt(addForm.asset_id);
    const quantity = parseFloat(addForm.quantity);
    const costBasis = parseFloat(addForm.cost_basis);
    if (!assetId || Number.isNaN(quantity) || quantity <= 0) {
      setError("دارایی و تعداد معتبر لازم است");
      return;
    }
    try {
      await upsertFamilyHolding({
        person_id: addingFor,
        asset_id: assetId,
        quantity,
        cost_basis: Number.isNaN(costBasis) ? 0 : costBasis,
      });
      setAddingFor(null);
      setAddForm({ asset_id: "", quantity: "", cost_basis: "" });
      setMsg("دارایی به سبد اضافه شد ✓");
      await loadAll();
    } catch (e: any) {
      setError(e?.message || "ذخیره ناموفق بود");
    }
  };

  const saveCash = async () => {
    if (!cashEdit) return;
    const value = parseFloat(cashEdit.value);
    if (Number.isNaN(value)) {
      setError("مانده معتبر نیست");
      return;
    }
    try {
      await updateFamilyAccount(cashEdit.personId, value);
      setCashEdit(null);
      setMsg("مانده حساب ذخیره شد ✓");
      await loadAll();
    } catch (e: any) {
      setError(e?.message || "ذخیره ناموفق بود");
    }
  };

  const submitNewPerson = async () => {
    if (!newPersonName.trim()) return;
    try {
      await createFamilyPerson(newPersonName.trim());
      setNewPersonName("");
      setMsg("شخص جدید اضافه شد ✓");
      await loadAll();
    } catch (e: any) {
      setError(e?.message || "افزودن شخص ناموفق بود");
    }
  };

  const submitNewAsset = async () => {
    if (!newAssetName.trim()) return;
    try {
      await createFamilyAsset(newAssetName.trim(), newAssetCategory);
      setNewAssetName("");
      setMsg("دارایی جدید اضافه شد ✓");
      await loadAll();
    } catch (e: any) {
      setError(e?.message || "افزودن دارایی ناموفق بود");
    }
  };

  const submitFlow = async () => {
    const amount = parseFloat(flowForm.amount);
    if (!flowForm.date_key || Number.isNaN(amount) || amount <= 0) {
      setError("تاریخ و مبلغ معتبر لازم است");
      return;
    }
    setSavingFlow(true);
    try {
      await addFamilyCashFlow({
        date_key: flowForm.date_key,
        amount,
        direction: flowForm.direction,
        note: flowForm.note,
      });
      setFlowForm((f) => ({ ...f, amount: "", note: "" }));
      setMsg("جریان نقدی ثبت شد ✓");
      await loadAll();
    } catch (e: any) {
      setError(e?.message || "ثبت ناموفق بود");
    } finally {
      setSavingFlow(false);
    }
  };

  const removeFlow = async (id: number) => {
    if (!window.confirm("حذف این جریان نقدی؟")) return;
    try {
      await deleteFamilyCashFlow(id);
      await loadAll();
    } catch (e: any) {
      setError(e?.message || "حذف ناموفق بود");
    }
  };

  // متادیتای هر شخص برای چارت: id → {name, color, index}
  const personMeta = useMemo(() => {
    const map: Record<string, { name: string; color: string; index: number }> = {};
    (state?.people || []).forEach((p, i) => {
      map[String(p.person_id)] = { name: p.name, color: personColor(i), index: i };
    });
    return map;
  }, [state]);

  // داده چارت: فیلتر بر اساس بازه انتخابی
  const chartData = useMemo(() => {
    if (history.length === 0) return [];
    const range = RANGES.find((r) => r.key === rangeKey);
    if (!range || range.months === 0) return history;
    const threshold = jalaliMonthsAgo(history[history.length - 1].date_key, range.months);
    return history.filter((r) => r.date_key >= threshold);
  }, [history, rangeKey]);

  // آمار بازه: بازده، بهترین/بدترین روز + سقف تاریخی کل
  const chartStats = useMemo(() => {
    if (chartData.length < 2) return null;
    const first = chartData[0];
    const last = chartData[chartData.length - 1];
    const rangeChangePct = first.total > 0 ? last.total / first.total - 1 : null;

    let best = { pct: 0, date: "" };
    let worst = { pct: 0, date: "" };
    for (let i = 1; i < chartData.length; i++) {
      const prev = chartData[i - 1].total;
      if (prev <= 0) continue;
      const pct = chartData[i].total / prev - 1;
      if (pct > best.pct) best = { pct, date: chartData[i].date_key };
      if (pct < worst.pct) worst = { pct, date: chartData[i].date_key };
    }

    let ath = { value: 0, date: "" };
    for (const r of history) {
      if (r.total > ath.value) ath = { value: r.total, date: r.date_key };
    }

    return { first, last, rangeChangePct, best, worst, ath };
  }, [chartData, history]);

  const toggleSeries = (key: string) => {
    setHiddenSeries((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const backfillHistory = async () => {
    setBackfilling(true);
    setError(null);
    try {
      const res = await syncFamilyPrices(true);
      setMsg(
        `تاریخچه ${res.updated?.length || 0} دارایی از بازار دریافت شد` +
          (res.missing?.length ? ` — دستی: ${res.missing.join("، ")}` : "")
      );
      await loadAll();
    } catch (e: any) {
      setError(e?.message || "دریافت تاریخچه ناموفق بود");
    } finally {
      setBackfilling(false);
    }
  };

  const summary = state?.summary;
  const cardCls =
    "rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/40 backdrop-blur-sm p-4 shadow-sm";
  const panelCls =
    "rounded-2xl border p-4 shadow-sm " +
    (darkMode
      ? "bg-gray-800/60 border-gray-700"
      : "bg-white/70 border-gray-200");

  const tabs: { key: Tab; label: string }[] = [
    { key: "summary", label: "خلاصه و ثبت قیمت" },
    { key: "people", label: "سبد اشخاص" },
    { key: "history", label: "تاریخچه" },
    { key: "flows", label: "آورده / برداشت" },
  ];

  const renderPersonCard = (p: FamilyPerson) => {
    const pos = p.profit >= 0;
    return (
      <div key={p.person_id} className={panelCls}>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div>
            <h3 className="font-bold text-gray-800 dark:text-white text-lg">{p.name}</h3>
            <div className="flex gap-3 text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              <span>ارزش سبد: <b className="text-gray-700 dark:text-gray-200">{fmtInt(p.holdings_value)}</b></span>
              <span>سهم از کل: <b className="text-gray-700 dark:text-gray-200">{fmtPct(p.share_of_total)}</b></span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-left">
              <div className="text-[11px] text-gray-500 dark:text-gray-400">سود / زیان</div>
              <div className={`font-bold tabular-nums ${pos ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                {pos ? "+" : ""}{fmtInt(p.profit)}
                <span className="text-xs font-normal"> ({pos ? "+" : ""}{fmtPct(p.profit_pct)})</span>
              </div>
            </div>
            {cashEdit?.personId === p.person_id ? (
              <div className="flex items-center gap-1">
                <input
                  type="number"
                  value={cashEdit.value}
                  onChange={(e) => setCashEdit({ personId: p.person_id, value: e.target.value })}
                  className={inputCls + " w-36"}
                />
                <button onClick={saveCash} className="text-emerald-500 hover:text-emerald-600" title="ذخیره مانده">
                  <FaCheck />
                </button>
                <button onClick={() => setCashEdit(null)} className="text-gray-400 hover:text-gray-600">
                  <FaTimes />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setCashEdit({ personId: p.person_id, value: String(p.cash_balance) })}
                className="text-right hover:ring-2 hover:ring-indigo-500/30 rounded-xl px-3 py-1.5 transition"
                title="ویرایش مانده حساب"
              >
                <div className="text-[11px] text-gray-500 dark:text-gray-400">مانده حساب</div>
                <div className="font-bold text-amber-600 dark:text-amber-400 tabular-nums">{fmtInt(p.cash_balance)}</div>
              </button>
            )}
          </div>
        </div>

        <table className="w-full text-sm text-right">
          <thead>
            <tr className="text-xs text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
              <th className="py-1.5 font-medium">دارایی</th>
              <th className="py-1.5 font-medium">تعداد</th>
              <th className="py-1.5 font-medium">بهای تمام‌شده</th>
              <th className="py-1.5 font-medium">ارزش</th>
              <th className="py-1.5 font-medium">سود/زیان</th>
              <th className="py-1.5 font-medium">وزن</th>
              <th className="py-1.5 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {p.holdings.length === 0 && (
              <tr>
                <td colSpan={7} className="py-3 text-center text-gray-400 text-xs">
                  این سبد خالی است
                </td>
              </tr>
            )}
            {p.holdings.map((h) => {
              const hPos = h.profit >= 0;
              const isEdit =
                editing?.personId === p.person_id && editing?.assetId === h.asset_id;
              return (
                <tr key={h.asset_id} className="border-b border-gray-100 dark:border-gray-800">
                  <td className="py-1.5 font-medium text-gray-800 dark:text-gray-100">{h.asset_name}</td>
                  {isEdit ? (
                    <>
                      <td className="py-1.5">
                        <input
                          type="number"
                          value={editing.quantity}
                          onChange={(e) => setEditing({ ...editing, quantity: e.target.value })}
                          className={inputCls + " w-28"}
                        />
                      </td>
                      <td className="py-1.5">
                        <input
                          type="number"
                          value={editing.costBasis}
                          onChange={(e) => setEditing({ ...editing, costBasis: e.target.value })}
                          className={inputCls + " w-36"}
                        />
                      </td>
                      <td colSpan={3} className="py-1.5">
                        <div className="flex gap-2">
                          <button onClick={saveEdit} className="text-emerald-500 hover:text-emerald-600" title="ذخیره">
                            <FaCheck />
                          </button>
                          <button onClick={() => setEditing(null)} className="text-gray-400 hover:text-gray-600" title="انصراف">
                            <FaTimes />
                          </button>
                        </div>
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="py-1.5 tabular-nums">{fmtInt(h.quantity)}</td>
                      <td className="py-1.5 tabular-nums text-gray-600 dark:text-gray-300">{fmtInt(h.cost_basis)}</td>
                      <td className="py-1.5 tabular-nums font-medium">{fmtInt(h.value)}</td>
                      <td className={`py-1.5 tabular-nums font-semibold ${hPos ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                        {hPos ? "+" : ""}{fmtInt(h.profit)}
                        <div className="text-[11px] font-normal opacity-80">({hPos ? "+" : ""}{fmtPct(h.profit_pct)})</div>
                      </td>
                      <td className="py-1.5 tabular-nums text-gray-600 dark:text-gray-300">{fmtPct(h.weight)}</td>
                      <td className="py-1.5">
                        <div className="flex gap-2 text-gray-500 dark:text-gray-400">
                          <button
                            onClick={() => startEdit(p.person_id, h.asset_id, h.quantity, h.cost_basis)}
                            className="hover:text-indigo-500"
                            title="ویرایش"
                          >
                            <FaEdit />
                          </button>
                          <button
                            onClick={() => removeHolding(p.person_id, h.asset_id, h.asset_name)}
                            className="hover:text-red-500"
                            title="حذف"
                          >
                            <FaTrash />
                          </button>
                        </div>
                      </td>
                    </>
                  )}
                </tr>
              );
            })}
            {addingFor === p.person_id ? (
              <tr className="bg-indigo-50/50 dark:bg-indigo-950/20">
                <td className="py-1.5">
                  <select
                    value={addForm.asset_id}
                    onChange={(e) => setAddForm({ ...addForm, asset_id: e.target.value })}
                    className={inputCls}
                  >
                    <option value="">انتخاب دارایی…</option>
                    {state?.assets.map((a) => (
                      <option key={a.asset_id} value={a.asset_id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="py-1.5">
                  <input
                    type="number"
                    value={addForm.quantity}
                    onChange={(e) => setAddForm({ ...addForm, quantity: e.target.value })}
                    placeholder="تعداد"
                    className={inputCls + " w-28"}
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="number"
                    value={addForm.cost_basis}
                    onChange={(e) => setAddForm({ ...addForm, cost_basis: e.target.value })}
                    placeholder="بهای تمام‌شده"
                    className={inputCls + " w-36"}
                  />
                </td>
                <td colSpan={4} className="py-1.5">
                  <div className="flex gap-2">
                    <button onClick={saveAdd} className="text-emerald-500 hover:text-emerald-600" title="ذخیره">
                      <FaCheck />
                    </button>
                    <button
                      onClick={() => {
                        setAddingFor(null);
                        setAddForm({ asset_id: "", quantity: "", cost_basis: "" });
                      }}
                      className="text-gray-400 hover:text-gray-600"
                      title="انصراف"
                    >
                      <FaTimes />
                    </button>
                  </div>
                </td>
              </tr>
            ) : (
              <tr>
                <td colSpan={7} className="py-1.5">
                  <button
                    onClick={() => {
                      setEditing(null);
                      setAddForm({ asset_id: "", quantity: "", cost_basis: "" });
                      setAddingFor(p.person_id);
                    }}
                    className="text-xs flex items-center gap-1.5 text-indigo-500 hover:text-indigo-600 font-medium"
                  >
                    <FaPlus size={11} /> افزودن دارایی به سبد
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-4" dir="rtl">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-bold text-gray-800 dark:text-white">دارایی خانواده</h2>
        <div className="flex gap-1 rounded-xl bg-gray-100 dark:bg-gray-800 p-1">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 h-8 rounded-lg text-sm font-semibold transition ${
                tab === t.key
                  ? "bg-white dark:bg-gray-700 text-indigo-600 dark:text-indigo-300 shadow"
                  : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-xl bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 text-red-700 dark:text-red-300 px-4 py-2 text-sm">
          {error}
        </div>
      )}
      {msg && (
        <div className="rounded-xl bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-700 text-emerald-700 dark:text-emerald-300 px-4 py-2 text-sm">
          {msg}
        </div>
      )}

      {loading ? (
        <p className="text-center text-gray-500 dark:text-gray-300 py-16">در حال بارگذاری...</p>
      ) : !state ? (
        <p className="text-center text-gray-500 dark:text-gray-300 py-16">
          داده‌ای برای نمایش نیست. ابتدا اسکریپت import را اجرا کنید.
        </p>
      ) : (
        <>
          {/* ── کارت‌های خلاصه ── */}
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
            <div className={cardCls}>
              <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">جمع کل</div>
              <div className="text-lg font-bold text-gray-800 dark:text-white tabular-nums">
                {fmtCompact(summary?.grand_total)}
              </div>
              <div className="text-[11px] text-gray-400 tabular-nums">{fmtInt(summary?.grand_total)}</div>
            </div>
            <div className={cardCls}>
              <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">ارزش دارایی‌ها</div>
              <div className="text-lg font-bold text-gray-800 dark:text-white tabular-nums">
                {fmtCompact(summary?.holdings_value)}
              </div>
              <div className="text-[11px] text-gray-400">مانده: {fmtCompact(summary?.total_cash)}</div>
            </div>
            <div className={cardCls}>
              <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">سود / زیان کل</div>
              <div
                className={`text-lg font-bold tabular-nums ${
                  (summary?.total_profit ?? 0) >= 0
                    ? "text-green-600 dark:text-green-400"
                    : "text-red-600 dark:text-red-400"
                }`}
              >
                {(summary?.total_profit ?? 0) >= 0 ? "+" : ""}
                {fmtCompact(summary?.total_profit)}
              </div>
              <div className="text-[11px] text-gray-400">
                ({(summary?.total_profit ?? 0) >= 0 ? "+" : ""}
                {fmtPct(summary?.total_profit_pct)})
              </div>
            </div>
            <div className={cardCls}>
              <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">بهترین حالت فردا (۳٪+)</div>
              <div className="text-lg font-bold text-green-600 dark:text-green-400 tabular-nums">
                {fmtCompact(summary?.best_tomorrow)}
              </div>
            </div>
            <div className={cardCls}>
              <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">بدترین حالت فردا (۳٪−)</div>
              <div className="text-lg font-bold text-red-600 dark:text-red-400 tabular-nums">
                {fmtCompact(summary?.worst_tomorrow)}
              </div>
            </div>
            <div className={cardCls}>
              <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">سهام / طلا</div>
              <div className="text-sm font-bold text-gray-800 dark:text-white tabular-nums">
                <span title="سهام">{fmtCompact(summary?.stocks_total)}</span>
                <span className="text-gray-400 mx-1">/</span>
                <span className="text-amber-600 dark:text-amber-400" title="طلا">
                  {fmtCompact(summary?.gold_total)}
                </span>
              </div>
              <div className="text-[11px] text-gray-400">آخرین قیمت: {summary?.latest_datekey || "--"}</div>
            </div>
          </div>

          {tab === "summary" && (
            <>
              {/* ── ثبت قیمت روز ── */}
              <div className={panelCls}>
                <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                  <h3 className="font-semibold text-gray-800 dark:text-white">ثبت قیمت روز</h3>
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-gray-500 dark:text-gray-400">تاریخ (شمسی)</label>
                    <input
                      type="text"
                      value={priceDate}
                      onChange={(e) => setPriceDate(e.target.value)}
                      placeholder="1405/05/26"
                      className={inputCls + " w-32"}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
                  {state.assets.map((a) => (
                    <div key={a.asset_id}>
                      <label className="block text-xs mb-1 text-gray-500 dark:text-gray-400">
                        {a.name}
                        {a.category === "gold" && (
                          <span className="text-amber-500 mr-1" title="طلا">
                            ●
                          </span>
                        )}
                        {a.symbol ? (
                          <span className="text-emerald-500 mr-1" title="قیمت خودکار از بازار">
                            ⚡
                          </span>
                        ) : (
                          <span className="text-gray-400 mr-1" title="ورود دستی قیمت">
                            ✎
                          </span>
                        )}
                      </label>
                      <input
                        type="number"
                        value={priceInputs[a.asset_id] ?? ""}
                        onChange={(e) =>
                          setPriceInputs({ ...priceInputs, [a.asset_id]: e.target.value })
                        }
                        placeholder={a.latest_price ? String(a.latest_price) : "قیمت"}
                        className={inputCls}
                      />
                    </div>
                  ))}
                </div>
                <div className="flex flex-wrap items-center gap-3 mt-3">
                  <button
                    onClick={submitPrices}
                    disabled={savingPrices}
                    className="flex items-center gap-2 px-4 h-9 rounded-xl bg-gradient-to-r from-indigo-500 to-indigo-600 hover:from-indigo-600 hover:to-indigo-700 text-white font-semibold shadow-lg transition disabled:opacity-50"
                  >
                    <FaCheck /> {savingPrices ? "در حال ذخیره..." : "ذخیره قیمت‌ها"}
                  </button>
                  <button
                    onClick={syncFromMarket}
                    disabled={syncing}
                    className="flex items-center gap-2 px-4 h-9 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white font-semibold shadow-lg transition disabled:opacity-50"
                    title="آخرین قیمت هر دارایی از داده‌های بازار (BRS) دریافت می‌شود"
                  >
                    📥 {syncing ? "در حال دریافت..." : "دریافت قیمت از بازار"}
                  </button>
                  <span className="text-xs text-gray-400">
                    با دکمه «Daily Prices» در سایدبار هم قیمت‌ها خودکار به‌روز می‌شوند؛ این فرم فقط برای اصلاح دستی
                  </span>
                </div>
              </div>

              {/* ── جدول دارایی‌ها مثل Sheet1 ── */}
              <div className={panelCls + " overflow-auto"}>
                <h3 className="font-semibold text-gray-800 dark:text-white mb-3">پرتفوی کل خانواده</h3>
                <table className="w-full text-sm text-right">
                  <thead>
                    <tr className="text-xs text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
                      <th className="py-2 font-medium">دارایی</th>
                      <th className="py-2 font-medium">آخرین قیمت</th>
                      <th className="py-2 font-medium">تاریخ قیمت</th>
                      <th className="py-2 font-medium">تعداد کل</th>
                      <th className="py-2 font-medium">بهای تمام‌شده</th>
                      <th className="py-2 font-medium">ارزش</th>
                      <th className="py-2 font-medium">سود/زیان</th>
                      <th className="py-2 font-medium">وزن</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.assets.map((a) => {
                      const pos = a.total_profit >= 0;
                      return (
                        <tr key={a.asset_id} className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700/40">
                          <td className="py-2 font-semibold text-gray-800 dark:text-gray-100">
                            {a.name}
                            {a.category === "gold" && (
                              <span className="text-amber-500 mr-1" title="طلا">●</span>
                            )}
                            {a.symbol && (
                              <span className="text-emerald-500 mr-1" title="قیمت خودکار از بازار">⚡</span>
                            )}
                          </td>
                          <td className="py-2 tabular-nums">{a.latest_price ? fmtInt(a.latest_price) : "—"}</td>
                          <td className="py-2 text-gray-500 dark:text-gray-400 text-xs">{a.price_date || "—"}</td>
                          <td className="py-2 tabular-nums">{fmtInt(a.total_quantity)}</td>
                          <td className="py-2 tabular-nums text-gray-600 dark:text-gray-300">{fmtInt(a.total_cost)}</td>
                          <td className="py-2 tabular-nums font-medium">{fmtInt(a.total_value)}</td>
                          <td className={`py-2 tabular-nums font-semibold ${pos ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                            {pos ? "+" : ""}{fmtCompact(a.total_profit)}
                            <div className="text-[11px] font-normal opacity-80">({pos ? "+" : ""}{fmtPct(a.profit_pct)})</div>
                          </td>
                          <td className="py-2 tabular-nums text-gray-600 dark:text-gray-300">{fmtPct(a.weight)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* ── افزودن شخص / دارایی ── */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className={panelCls}>
                  <h3 className="font-semibold text-gray-800 dark:text-white mb-3">افزودن شخص</h3>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={newPersonName}
                      onChange={(e) => setNewPersonName(e.target.value)}
                      placeholder="نام شخص جدید..."
                      className={inputCls}
                    />
                    <button
                      onClick={submitNewPerson}
                      className="shrink-0 px-4 h-9 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-semibold shadow"
                    >
                      <FaPlus />
                    </button>
                  </div>
                </div>
                <div className={panelCls}>
                  <h3 className="font-semibold text-gray-800 dark:text-white mb-3">افزودن دارایی</h3>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={newAssetName}
                      onChange={(e) => setNewAssetName(e.target.value)}
                      placeholder="نام دارایی جدید..."
                      className={inputCls}
                    />
                    <select
                      value={newAssetCategory}
                      onChange={(e) => setNewAssetCategory(e.target.value)}
                      className={inputCls + " w-28"}
                    >
                      <option value="stock">سهام</option>
                      <option value="gold">طلا</option>
                      <option value="dollar">دلار</option>
                    </select>
                    <button
                      onClick={submitNewAsset}
                      className="shrink-0 px-4 h-9 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-semibold shadow"
                    >
                      <FaPlus />
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}

          {tab === "people" && (
            <div className="flex flex-col gap-4">{state.people.map(renderPersonCard)}</div>
          )}

          {tab === "history" && (
            <div className="flex flex-col gap-4">
              {/* ── کنترل‌ها: بازه + نوع نمودار ── */}
              <div className={panelCls + " flex flex-wrap items-center justify-between gap-3"}>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex gap-1 rounded-xl bg-gray-100 dark:bg-gray-900/60 p-1">
                    {RANGES.map((r) => (
                      <button
                        key={r.key}
                        onClick={() => setRangeKey(r.key)}
                        className={`px-3 h-7 rounded-lg text-xs font-semibold transition ${
                          rangeKey === r.key
                            ? "bg-white dark:bg-gray-700 text-indigo-600 dark:text-indigo-300 shadow"
                            : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
                        }`}
                      >
                        {r.label}
                      </button>
                    ))}
                  </div>
                  <div className="flex gap-1 rounded-xl bg-gray-100 dark:bg-gray-900/60 p-1">
                    <button
                      onClick={() => setChartMode("line")}
                      className={`px-3 h-7 rounded-lg text-xs font-semibold transition ${
                        chartMode === "line"
                          ? "bg-white dark:bg-gray-700 text-indigo-600 dark:text-indigo-300 shadow"
                          : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
                      }`}
                    >
                      📈 خطی
                    </button>
                    <button
                      onClick={() => setChartMode("stack")}
                      className={`px-3 h-7 rounded-lg text-xs font-semibold transition ${
                        chartMode === "stack"
                          ? "bg-white dark:bg-gray-700 text-indigo-600 dark:text-indigo-300 shadow"
                          : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
                      }`}
                    >
                      🌊 انباشته
                    </button>
                  </div>
                  <div className="flex gap-1 rounded-xl bg-gray-100 dark:bg-gray-900/60 p-1" title="مقیاس محور عمودی — لگاریتمی برای دیدن رشد نسبی در بازه‌های طولانی">
                    <button
                      onClick={() => setLogScale(false)}
                      className={`px-3 h-7 rounded-lg text-xs font-semibold transition ${
                        !logScale
                          ? "bg-white dark:bg-gray-700 text-indigo-600 dark:text-indigo-300 shadow"
                          : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
                      }`}
                    >
                      خطی
                    </button>
                    <button
                      onClick={() => setLogScale(true)}
                      className={`px-3 h-7 rounded-lg text-xs font-semibold transition ${
                        logScale
                          ? "bg-white dark:bg-gray-700 text-indigo-600 dark:text-indigo-300 shadow"
                          : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
                      }`}
                    >
                      Log
                    </button>
                  </div>
                </div>
                <button
                  onClick={backfillHistory}
                  disabled={backfilling}
                  className="px-3 h-8 rounded-xl text-xs font-semibold bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white shadow disabled:opacity-50 transition"
                  title="تاریخچه کامل قیمت دارایی‌های ⚡ را از داده‌های بازار می‌گیرد (یک‌باره برای دارایی جدید)"
                >
                  {backfilling ? "در حال دریافت..." : "📥 تاریخچه بازار"}
                </button>
              </div>

              {/* ── سری‌های قابل نمایش ── */}
              <div className={panelCls + " flex flex-wrap items-center gap-2"}>
                <button
                  onClick={() => toggleSeries("total")}
                  className={`flex items-center gap-2 px-3 h-8 rounded-xl border text-xs font-bold transition ${
                    hiddenSeries.has("total")
                      ? "opacity-40 border-gray-200 dark:border-gray-700"
                      : "border-indigo-200 dark:border-indigo-800 bg-indigo-50/60 dark:bg-indigo-950/30"
                  }`}
                >
                  <span
                    className="inline-block w-3 h-1.5 rounded-full"
                    style={{ background: "linear-gradient(to left, #6366f1, #a855f7)" }}
                  />
                  جمع کل
                </button>
                {Object.entries(personMeta).map(([pid, meta]) => (
                  <button
                    key={pid}
                    onClick={() => toggleSeries(pid)}
                    className={`flex items-center gap-2 px-3 h-8 rounded-xl border text-xs font-bold transition ${
                      hiddenSeries.has(pid)
                        ? "opacity-40 border-gray-200 dark:border-gray-700"
                        : "border-gray-200 dark:border-gray-700 bg-white/60 dark:bg-gray-800/60"
                    }`}
                  >
                    <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: meta.color }} />
                    {meta.name}
                  </button>
                ))}
              </div>

              {/* ── نمودار ── */}
              <div className={panelCls}>
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <h3 className="font-semibold text-gray-800 dark:text-white">
                    {chartMode === "line" ? "روند دارایی" : "دارایی به تفکیک اشخاص"}{" "}
                    <span className="text-xs font-normal text-gray-400">
                      ({chartData.length} روز، از {chartData[0]?.date_key || "--"})
                    </span>
                  </h3>
                  {chartStats && (
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      سقف تاریخی:{" "}
                      <b className={darkMode ? "text-gray-200" : "text-gray-800"}>
                        {fmtCompact(chartStats.ath.value)}
                      </b>{" "}
                      در {chartStats.ath.date}
                    </div>
                  )}
                </div>
                <ResponsiveContainer width="100%" height={460}>
                  {chartMode === "line" ? (
                    <ComposedChart data={chartData} margin={{ top: 10, right: 10, bottom: 0, left: 10 }}>
                      <defs>
                        <linearGradient id="totalGrad" x1="0" y1="0" x2="1" y2="0">
                          <stop offset="0%" stopColor="#6366f1" />
                          <stop offset="100%" stopColor="#a855f7" />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? "#374151" : "#e5e7eb"} opacity={0.6} />
                      <XAxis
                        dataKey="date_key"
                        tick={{ fontSize: 10, fill: darkMode ? "#9ca3af" : "#6b7280" }}
                        minTickGap={60}
                      />
                      <YAxis
                        scale={logScale ? "log" : "linear"}
                        domain={logScale ? ["auto", "auto"] : [0, "auto"]}
                        allowDataOverflow
                        allowDecimals={false}
                        tick={{ fontSize: 10, fill: darkMode ? "#9ca3af" : "#6b7280" }}
                        tickFormatter={(v: number) => fmtCompact(v)}
                        width={62}
                      />
                      <Tooltip content={<HistoryTooltip darkMode={darkMode} personMeta={personMeta} mode="line" />} />
                      {Object.entries(personMeta).map(([pid, meta]) =>
                        !hiddenSeries.has(pid) ? (
                          <Line
                            key={pid}
                            type="monotone"
                            dataKey={`people.${pid}`}
                            name={meta.name}
                            stroke={meta.color}
                            strokeWidth={1.8}
                            dot={false}
                            activeDot={{ r: 3.5, strokeWidth: 0 }}
                            animationDuration={700}
                          />
                        ) : null
                      )}
                      {!hiddenSeries.has("total") && (
                        <Line
                          type="monotone"
                          dataKey="total"
                          name="جمع کل"
                          stroke="url(#totalGrad)"
                          strokeWidth={3.5}
                          dot={false}
                          activeDot={{ r: 5, strokeWidth: 2, stroke: darkMode ? "#1f2937" : "#fff" }}
                          animationDuration={700}
                        />
                      )}
                    </ComposedChart>
                  ) : (
                    <AreaChart data={chartData} margin={{ top: 10, right: 10, bottom: 0, left: 10 }}>
                      <defs>
                        {Object.entries(personMeta).map(([pid, meta]) => (
                          <linearGradient key={pid} id={`stackGrad-${pid}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={meta.color} stopOpacity={0.75} />
                            <stop offset="100%" stopColor={meta.color} stopOpacity={0.08} />
                          </linearGradient>
                        ))}
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? "#374151" : "#e5e7eb"} opacity={0.6} />
                      <XAxis
                        dataKey="date_key"
                        tick={{ fontSize: 10, fill: darkMode ? "#9ca3af" : "#6b7280" }}
                        minTickGap={60}
                      />
                      <YAxis
                        scale={logScale ? "log" : "linear"}
                        domain={logScale ? ["auto", "auto"] : [0, "auto"]}
                        allowDataOverflow
                        allowDecimals={false}
                        tick={{ fontSize: 10, fill: darkMode ? "#9ca3af" : "#6b7280" }}
                        tickFormatter={(v: number) => fmtCompact(v)}
                        width={62}
                      />
                      <Tooltip content={<HistoryTooltip darkMode={darkMode} personMeta={personMeta} mode="stack" />} />
                      {Object.entries(personMeta).map(([pid, meta]) =>
                        !hiddenSeries.has(pid) ? (
                          <Area
                            key={pid}
                            type="monotone"
                            dataKey={`people.${pid}`}
                            name={meta.name}
                            stackId="family"
                            stroke={meta.color}
                            strokeWidth={1.5}
                            fill={`url(#stackGrad-${pid})`}
                            animationDuration={700}
                          />
                        ) : null
                      )}
                      {!hiddenSeries.has("total") && (
                        <Line
                          type="monotone"
                          dataKey="total"
                          name="جمع کل (واقعی)"
                          stroke={darkMode ? "#f8fafc" : "#0f172a"}
                          strokeWidth={1.8}
                          strokeDasharray="6 4"
                          dot={false}
                          animationDuration={700}
                        />
                      )}
                    </AreaChart>
                  )}
                </ResponsiveContainer>
                <p className="text-[11px] text-gray-400 dark:text-gray-500 mt-2 leading-5">
                  سری اشخاص = دارایی‌های امروز × قیمت تاریخی + مانده فعلی حساب؛ بنابراین جمع اشخاص در گذشته ممکن است
                  با خط «جمع کل» واقعی (ترکیب سبد آن زمان) تفاوت داشته باشد. خط ممتد = داده واقعی اکسل و سایت.
                </p>
              </div>

              {/* ── آمار بازه ── */}
              {chartStats && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className={cardCls}>
                    <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">آخرین ارزش کل</div>
                    <div className="text-lg font-bold text-gray-800 dark:text-white tabular-nums">
                      {fmtCompact(chartStats.last.total)}
                    </div>
                    <div className="text-[11px] text-gray-400">{chartStats.last.date_key}</div>
                  </div>
                  <div className={cardCls}>
                    <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">بازده این بازه</div>
                    <div
                      className={`text-lg font-bold tabular-nums ${
                        (chartStats.rangeChangePct ?? 0) >= 0
                          ? "text-green-600 dark:text-green-400"
                          : "text-red-600 dark:text-red-400"
                      }`}
                    >
                      {(chartStats.rangeChangePct ?? 0) >= 0 ? "+" : ""}
                      {fmtPct(chartStats.rangeChangePct)}
                    </div>
                    <div className="text-[11px] text-gray-400">از {chartStats.first.date_key}</div>
                  </div>
                  <div className={cardCls}>
                    <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">بهترین روز بازه</div>
                    <div className="text-lg font-bold text-green-600 dark:text-green-400 tabular-nums">
                      +{fmtPct(chartStats.best.pct)}
                    </div>
                    <div className="text-[11px] text-gray-400">{chartStats.best.date || "--"}</div>
                  </div>
                  <div className={cardCls}>
                    <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">بدترین روز بازه</div>
                    <div className="text-lg font-bold text-red-600 dark:text-red-400 tabular-nums">
                      {fmtPct(chartStats.worst.pct)}
                    </div>
                    <div className="text-[11px] text-gray-400">{chartStats.worst.date || "--"}</div>
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === "flows" && (
            <>
              <div className={panelCls}>
                <h3 className="font-semibold text-gray-800 dark:text-white mb-3">ثبت آورده / برداشت</h3>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                  <div>
                    <label className="block text-xs mb-1 text-gray-500 dark:text-gray-400">تاریخ (شمسی)</label>
                    <input
                      type="text"
                      value={flowForm.date_key}
                      onChange={(e) => setFlowForm({ ...flowForm, date_key: e.target.value })}
                      placeholder="1405/05/26"
                      className={inputCls}
                    />
                  </div>
                  <div>
                    <label className="block text-xs mb-1 text-gray-500 dark:text-gray-400">مبلغ</label>
                    <input
                      type="number"
                      value={flowForm.amount}
                      onChange={(e) => setFlowForm({ ...flowForm, amount: e.target.value })}
                      placeholder="مبلغ"
                      className={inputCls}
                    />
                  </div>
                  <div>
                    <label className="block text-xs mb-1 text-gray-500 dark:text-gray-400">جهت</label>
                    <select
                      value={flowForm.direction}
                      onChange={(e) => setFlowForm({ ...flowForm, direction: e.target.value })}
                      className={inputCls}
                    >
                      <option value="in">آورده (+)</option>
                      <option value="out">برداشت (−)</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs mb-1 text-gray-500 dark:text-gray-400">یادداشت</label>
                    <input
                      type="text"
                      value={flowForm.note}
                      onChange={(e) => setFlowForm({ ...flowForm, note: e.target.value })}
                      placeholder="یادداشت..."
                      className={inputCls}
                    />
                  </div>
                  <div className="flex items-end">
                    <button
                      onClick={submitFlow}
                      disabled={savingFlow}
                      className="w-full h-9 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white font-semibold shadow disabled:opacity-50"
                    >
                      {savingFlow ? "..." : "ثبت"}
                    </button>
                  </div>
                </div>
              </div>

              <div className={panelCls + " overflow-auto"}>
                <table className="w-full text-sm text-right">
                  <thead>
                    <tr className="text-xs text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
                      <th className="py-2 font-medium">تاریخ</th>
                      <th className="py-2 font-medium">جهت</th>
                      <th className="py-2 font-medium">مبلغ</th>
                      <th className="py-2 font-medium">یادداشت</th>
                      <th className="py-2 font-medium"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {flows.length === 0 && (
                      <tr>
                        <td colSpan={5} className="py-3 text-center text-gray-400 text-xs">
                          جریان نقدی ثبت نشده است
                        </td>
                      </tr>
                    )}
                    {flows.map((f) => (
                      <tr key={f.id} className="border-b border-gray-100 dark:border-gray-800">
                        <td className="py-2 tabular-nums">{f.date_key}</td>
                        <td className="py-2">
                          <span
                            className={`inline-flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded-lg ${
                              f.direction === "in"
                                ? "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30"
                                : "text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/30"
                            }`}
                          >
                            <FaCoins size={10} />
                            {f.direction === "in" ? "آورده" : "برداشت"}
                          </span>
                        </td>
                        <td className="py-2 tabular-nums font-medium">{fmtInt(f.amount)}</td>
                        <td className="py-2 text-gray-500 dark:text-gray-400">{f.note || "—"}</td>
                        <td className="py-2">
                          <button onClick={() => removeFlow(f.id)} className="text-gray-400 hover:text-red-500" title="حذف">
                            <FaTrash />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
};

// ── Tooltip سفارشی چارت تاریخچه ──
type PersonMetaMap = Record<string, { name: string; color: string; index: number }>;

const HistoryTooltip: React.FC<{
  active?: boolean;
  payload?: any[];
  label?: string;
  darkMode: boolean;
  personMeta: PersonMetaMap;
  mode: "line" | "stack";
}> = ({ active, payload, label, darkMode, personMeta, mode }) => {
  if (!active || !payload || payload.length === 0) return null;

  const totalEntry = payload.find((p) => p.dataKey === "total");
  const personEntries = payload
    .filter((p) => String(p.dataKey).startsWith("people."))
    .map((p) => {
      const pid = String(p.dataKey).replace("people.", "");
      return { pid, meta: personMeta[pid], value: Number(p.value) };
    })
    .filter((p) => p.meta)
    .sort((a, b) => b.value - a.value);
  const personsSum = personEntries.reduce((s, p) => s + p.value, 0);

  const rowCls = "flex items-center justify-between gap-6 tabular-nums";
  const labelCls = "flex items-center gap-2 text-xs";

  return (
    <div
      dir="rtl"
      style={glassTooltipStyle(darkMode) as any}
      className="rounded-xl px-3 py-2.5 min-w-56 max-h-80 overflow-auto"
    >
      <div className={`text-xs font-bold mb-2 pb-2 border-b ${darkMode ? "border-gray-600 text-gray-100" : "border-gray-200 text-gray-800"}`}>
        {label}
      </div>
      <div className="flex flex-col gap-1.5">
        {mode === "line" && totalEntry && (
          <div className={rowCls}>
            <span className={labelCls}>
              <span
                className="inline-block w-3 h-1.5 rounded-full"
                style={{ background: "linear-gradient(to left, #6366f1, #a855f7)" }}
              />
              <b className={darkMode ? "text-gray-100" : "text-gray-800"}>جمع کل</b>
            </span>
            <span className={`text-sm font-bold ${darkMode ? "text-gray-100" : "text-gray-800"}`}>
              {fmtInt(Number(totalEntry.value))}
            </span>
          </div>
        )}
        {mode === "stack" && (
          <div className={rowCls}>
            <span className={labelCls}>
              <b className={darkMode ? "text-gray-100" : "text-gray-800"}>جمع اشخاص</b>
            </span>
            <span className={`text-sm font-bold ${darkMode ? "text-gray-100" : "text-gray-800"}`}>
              {fmtInt(personsSum)}
            </span>
          </div>
        )}
        {personEntries.map((p) => (
          <div key={p.pid} className={rowCls}>
            <span className={labelCls}>
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: p.meta.color }} />
              <span className={darkMode ? "text-gray-300" : "text-gray-600"}>{p.meta.name}</span>
            </span>
            <span className="flex items-center gap-2">
              {personsSum > 0 && (
                <span className="text-[10px] text-gray-400">{((p.value / personsSum) * 100).toFixed(0)}%</span>
              )}
              <span className={`text-xs font-semibold ${darkMode ? "text-gray-200" : "text-gray-700"}`}>
                {fmtInt(p.value)}
              </span>
            </span>
          </div>
        ))}
        {mode === "stack" && totalEntry && (
          <div className={`${rowCls} pt-1.5 mt-1 border-t ${darkMode ? "border-gray-600" : "border-gray-200"}`}>
            <span className={labelCls}>
              <span
                className="inline-block w-3 border-t-2 border-dashed"
                style={{ borderColor: darkMode ? "#f8fafc" : "#0f172a" }}
              />
              <span className="text-gray-400">جمع کل واقعی</span>
            </span>
            <span className="text-xs font-semibold text-gray-400">{fmtInt(Number(totalEntry.value))}</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default FamilyAssets;
