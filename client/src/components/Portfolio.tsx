import { useCallback, useEffect, useMemo, useState } from "react";
import Select from "react-select";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
  Label,
} from "recharts";
import { FaPlus, FaTrash, FaEdit, FaTimes, FaCheck } from "react-icons/fa";
import {
  getPortfolio,
  upsertHolding,
  deleteHolding,
  getAIStockSummary,
} from "../utils/api";
import type {
  PortfolioSummary,
  PortfolioHoldingEnriched,
  AIStockMetric,
} from "../utils/api";
import { useDarkMode } from "../utils/theme";
import { glassTooltipStyle, fmtShort } from "../utils/chart-theme";

type CompanyOption = { value: string; label: string; price?: number };

const fmt = (n: number | null | undefined, digits = 2) => {
  if (n == null || Number.isNaN(n)) return "--";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

const fmtCompact = (n: number | null | undefined) => {
  if (n == null || Number.isNaN(n)) return "--";
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return (n / 1_000_000_000).toFixed(2) + "B";
  if (abs >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
  if (abs >= 1_000) return (n / 1_000).toFixed(2) + "K";
  return n.toFixed(2);
};

const ALLOC_COLORS = [
  "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981",
  "#06b6d4", "#ef4444", "#3b82f6", "#a855f7", "#14b8a6",
  "#f97316", "#84cc16", "#64748b", "#0ea5e9", "#d946ef",
];

const Portfolio = () => {
  const { darkMode } = useDarkMode();

  const [data, setData] = useState<PortfolioSummary | null>(null);
  const [companies, setCompanies] = useState<CompanyOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // فرم افزودن/ویرایش
  const emptyForm = {
    company_id: "",
    company_name: "",
    symbol: "",
    quantity: "",
    buy_price: "",
    buy_date: "",
    note: "",
  };
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [pf, rows] = await Promise.all([
        getPortfolio(),
        getAIStockSummary(1000),
      ]);
      setData(pf);
      setCompanies(
        rows
          .filter((r: AIStockMetric) => !!r.company_id)
          .map((r: AIStockMetric) => ({
            value: r.company_id,
            label: r.symbol ? `${r.symbol} — ${r.company_name}` : r.company_name,
            price: r.latest_price,
          }))
      );
    } catch (e: any) {
      setError(e?.message || "Failed to load portfolio");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const selectedCompanyOption = useMemo(
    () => companies.find((c) => c.value === form.company_id) || null,
    [companies, form.company_id]
  );

  const resetForm = () => {
    setForm(emptyForm);
    setEditingId(null);
    setShowForm(false);
  };

  const startAdd = () => {
    setForm(emptyForm);
    setEditingId(null);
    setShowForm(true);
  };

  const startEdit = (h: PortfolioHoldingEnriched) => {
    setForm({
      company_id: h.company_id,
      company_name: h.company_name,
      symbol: h.symbol || "",
      quantity: String(h.quantity),
      buy_price: String(h.buy_price),
      buy_date: h.buy_date || "",
      note: h.note || "",
    });
    setEditingId(h.company_id);
    setShowForm(true);
  };

  const onSelectCompany = (opt: CompanyOption | null) => {
    if (!opt) {
      setForm((f) => ({ ...f, company_id: "", company_name: "", symbol: "" }));
      return;
    }
    const price = opt.price ?? "";
    setForm((f) => ({
      ...f,
      company_id: opt.value,
      company_name: opt.label.split(" — ").pop() || opt.label,
      symbol: opt.label.split(" — ")[0] || "",
      buy_price: f.buy_price || (price ? String(price) : ""),
    }));
  };

  const submit = async () => {
    if (!form.company_id) {
      setError("یک شرکت انتخاب کنید");
      return;
    }
    const qty = parseFloat(form.quantity);
    const bp = parseFloat(form.buy_price);
    if (!qty || qty <= 0) {
      setError("تعداد معتبر نیست");
      return;
    }
    if (!bp || bp <= 0) {
      setError("قیمت خرید معتبر نیست");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await upsertHolding({
        company_id: form.company_id,
        company_name: form.company_name,
        symbol: form.symbol,
        quantity: qty,
        buy_price: bp,
        buy_date: form.buy_date,
        note: form.note,
      });
      resetForm();
      await loadData();
    } catch (e: any) {
      setError(e?.message || "ذخیره ناموفق بود");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (h: PortfolioHoldingEnriched) => {
    if (!window.confirm(`حذف «${h.company_name}» از پورتفولیو؟`)) return;
    try {
      await deleteHolding(h.company_id);
      await loadData();
    } catch (e: any) {
      setError(e?.message || "حذف ناموفق بود");
    }
  };

  const totalGain = data?.total_gain ?? 0;
  const totalGainPct = data?.total_gain_pct ?? 0;
  const gainPositive = totalGain >= 0;

  const allocData = useMemo(() => {
    if (!data) return [];
    return data.holdings
      .filter((h) => h.market_value > 0)
      .map((h) => ({
        name: h.symbol || h.company_name,
        value: Math.round(h.market_value),
      }))
      .sort((a, b) => b.value - a.value);
  }, [data]);

  const cardCls =
    "rounded-2xl border border-gray-200 dark:border-gray-700 bg-white/70 dark:bg-gray-800/60 backdrop-blur-lg p-4 shadow-sm";

  return (
    <div className="flex flex-col gap-4" dir="rtl">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-gray-800 dark:text-white">
          پورتفولیو
        </h2>
        {!showForm && (
          <button
            onClick={startAdd}
            className="flex items-center gap-2 px-4 h-9 rounded-xl bg-gradient-to-r from-indigo-500 to-indigo-600 hover:from-indigo-600 hover:to-indigo-700 text-white font-semibold shadow-lg transition"
          >
            <FaPlus /> افزودن دارایی
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-xl bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 text-red-700 dark:text-red-300 px-4 py-2 text-sm">
          {error}
        </div>
      )}

      {/* خلاصه */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className={cardCls}>
          <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">
            ارزش هزینه (سرمایه‌گذاری)
          </div>
          <div className="text-lg font-bold text-gray-800 dark:text-white">
            {fmtCompact(data?.total_cost)}
          </div>
        </div>
        <div className={cardCls}>
          <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">
            ارزش بازار
          </div>
          <div className="text-lg font-bold text-gray-800 dark:text-white">
            {fmtCompact(data?.total_market_value)}
          </div>
        </div>
        <div className={cardCls}>
          <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">
            سود/زیان کل
          </div>
          <div
            className={`text-lg font-bold ${
              gainPositive
                ? "text-green-600 dark:text-green-400"
                : "text-red-600 dark:text-red-400"
            }`}
          >
            {gainPositive ? "+" : ""}
            {fmtCompact(totalGain)}
          </div>
        </div>
        <div className={cardCls}>
          <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">
            بازده کل (%)
          </div>
          <div
            className={`text-lg font-bold ${
              gainPositive
                ? "text-green-600 dark:text-green-400"
                : "text-red-600 dark:text-red-400"
            }`}
          >
            {gainPositive ? "+" : ""}
            {fmt(totalGainPct)}%
          </div>
        </div>
      </div>

      {/* فرم افزودن/ویرایش */}
      {showForm && (
        <div
          className={`rounded-2xl border p-4 shadow-sm ${
            darkMode
              ? "bg-gray-800/60 border-gray-700"
              : "bg-white/70 border-gray-200"
          }`}
        >
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-gray-800 dark:text-white">
              {editingId ? "ویرایش دارایی" : "افزودن دارایی جدید"}
            </h3>
            <button
              onClick={resetForm}
              className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
            >
              <FaTimes />
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="md:col-span-2">
              <label className="block text-xs mb-1 text-gray-500 dark:text-gray-400">
                شرکت
              </label>
              <Select
                options={companies}
                value={selectedCompanyOption}
                onChange={onSelectCompany}
                isSearchable
                placeholder="جستجوی شرکت..."
                isDisabled={!!editingId}
                styles={{
                  control: (base, state) => ({
                    ...base,
                    borderRadius: "0.75rem",
                    borderColor: state.isFocused ? "#6366f1" : "#d1d5db",
                    backgroundColor: darkMode ? "#1f2937" : "white",
                    color: darkMode ? "#e5e7eb" : "#1f2937",
                  }),
                  menu: (base) => ({
                    ...base,
                    backgroundColor: darkMode ? "#1f2937" : "white",
                    color: darkMode ? "#e5e7eb" : "#1f2937",
                    zIndex: 50,
                  }),
                  option: (base, state) => ({
                    ...base,
                    backgroundColor: state.isSelected
                      ? "#6366f1"
                      : state.isFocused
                        ? darkMode ? "#374151" : "#eef2ff"
                        : "transparent",
                    color: state.isSelected ? "white" : darkMode ? "#e5e7eb" : "#1f2937",
                  }),
                  singleValue: (base) => ({
                    ...base,
                    color: darkMode ? "#e5e7eb" : "#1f2937",
                  }),
                  input: (base) => ({ ...base, color: darkMode ? "#e5e7eb" : "#1f2937" }),
                }}
              />
            </div>

            <div>
              <label className="block text-xs mb-1 text-gray-500 dark:text-gray-400">
                تعداد سهم
              </label>
              <input
                type="number"
                value={form.quantity}
                onChange={(e) => setForm({ ...form, quantity: e.target.value })}
                placeholder="مثلاً 1000"
                className="w-full rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100 px-3 py-2 text-sm focus:border-indigo-500 outline-none"
              />
            </div>

            <div>
              <label className="block text-xs mb-1 text-gray-500 dark:text-gray-400">
                قیمت خرید (میانگین)
              </label>
              <input
                type="number"
                value={form.buy_price}
                onChange={(e) => setForm({ ...form, buy_price: e.target.value })}
                placeholder="مثلاً 1250"
                className="w-full rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100 px-3 py-2 text-sm focus:border-indigo-500 outline-none"
              />
            </div>

            <div>
              <label className="block text-xs mb-1 text-gray-500 dark:text-gray-400">
                تاریخ خرید (اختیاری)
              </label>
              <input
                type="text"
                value={form.buy_date}
                onChange={(e) => setForm({ ...form, buy_date: e.target.value })}
                placeholder="1403/01/15 یا 2024-04-03"
                className="w-full rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100 px-3 py-2 text-sm focus:border-indigo-500 outline-none"
              />
            </div>

            <div>
              <label className="block text-xs mb-1 text-gray-500 dark:text-gray-400">
                یادداشت (اختیاری)
              </label>
              <input
                type="text"
                value={form.note}
                onChange={(e) => setForm({ ...form, note: e.target.value })}
                placeholder="یادداشت..."
                className="w-full rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100 px-3 py-2 text-sm focus:border-indigo-500 outline-none"
              />
            </div>
          </div>

          <div className="flex gap-2 mt-3">
            <button
              onClick={submit}
              disabled={saving}
              className="flex items-center gap-2 px-4 h-9 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-semibold shadow disabled:opacity-50"
            >
              <FaCheck /> {saving ? "در حال ذخیره..." : "ذخیره"}
            </button>
            <button
              onClick={resetForm}
              className="px-4 h-9 rounded-xl bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 font-semibold"
            >
              انصراف
            </button>
          </div>
        </div>
      )}

      {/* چارت تخصیص + جدول */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {allocData.length > 0 && (
          <div
            className={`lg:col-span-1 rounded-2xl border p-4 shadow-sm ${
              darkMode
                ? "bg-gray-800/60 border-gray-700"
                : "bg-white/70 border-gray-200"
            }`}
          >
            <h3 className="font-semibold mb-2 text-gray-800 dark:text-white">
              تخصیص دارایی
            </h3>
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={allocData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={62}
                  outerRadius={96}
                  paddingAngle={3}
                  cornerRadius={6}
                  isAnimationActive
                  animationDuration={700}
                  animationEasing="ease-out"
                  stroke={darkMode ? "rgba(15,23,42,0.5)" : "rgba(255,255,255,0.7)"}
                  strokeWidth={2}
                >
                  {allocData.map((_, i) => (
                    <Cell key={i} fill={ALLOC_COLORS[i % ALLOC_COLORS.length]} />
                  ))}
                  <Label
                    value={fmtShort(data?.total_market_value)}
                    position="center"
                    dy={-4}
                    fontSize={18}
                    fontWeight={800}
                    fill={darkMode ? "#e2e8f0" : "#0f172a"}
                  />
                  <Label
                    value="ارزش کل"
                    position="center"
                    dy={16}
                    fontSize={11}
                    fill={darkMode ? "#94a3b8" : "#64748b"}
                  />
                </Pie>
                <Tooltip
                  formatter={(v: any) => fmtShort(Number(v))}
                  {...({
                    contentStyle: glassTooltipStyle(darkMode),
                    itemStyle: { color: darkMode ? "#e2e8f0" : "#0f172a" },
                  } as any)}
                />
                <Legend
                  wrapperStyle={{ fontSize: 11 }}
                  iconType="circle"
                  iconSize={9}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        <div
          className={`lg:col-span-2 rounded-2xl border p-4 shadow-sm overflow-auto ${
            darkMode
              ? "bg-gray-800/60 border-gray-700"
              : "bg-white/70 border-gray-200"
          }`}
        >
          {loading ? (
            <p className="text-center text-gray-500 dark:text-gray-300 py-10">
              در حال بارگذاری...
            </p>
          ) : !data || data.holdings.length === 0 ? (
            <p className="text-center text-gray-500 dark:text-gray-300 py-10">
              هنوز دارایی‌ای اضافه نکرده‌اید. روی «افزودن دارایی» بزنید.
            </p>
          ) : (
            <table className="w-full text-sm text-right">
              <thead>
                <tr className="text-xs text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
                  <th className="py-2 font-medium">نماد / شرکت</th>
                  <th className="py-2 font-medium">تعداد</th>
                  <th className="py-2 font-medium">قیمت خرید</th>
                  <th className="py-2 font-medium">قیمت زنده</th>
                  <th className="py-2 font-medium">ارزش بازار</th>
                  <th className="py-2 font-medium">سود/زیان</th>
                  <th className="py-2 font-medium">وزن</th>
                  <th className="py-2 font-medium">عملیات</th>
                </tr>
              </thead>
              <tbody>
                {data.holdings.map((h) => {
                  const pos = h.gain >= 0;
                  return (
                    <tr
                      key={h.company_id}
                      className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700/40"
                    >
                      <td className="py-2">
                        <div className="font-semibold text-gray-800 dark:text-gray-100">
                          {h.symbol || "--"}
                        </div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          {h.company_name}
                        </div>
                      </td>
                      <td className="py-2">{fmt(h.quantity, 0)}</td>
                      <td className="py-2">{fmt(h.buy_price)}</td>
                      <td className="py-2">
                        {h.has_live_price ? (
                          fmt(h.latest_price)
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="py-2 font-medium">
                        {h.market_value > 0 ? fmtCompact(h.market_value) : "—"}
                      </td>
                      <td
                        className={`py-2 font-semibold ${
                          pos
                            ? "text-green-600 dark:text-green-400"
                            : "text-red-600 dark:text-red-400"
                        }`}
                      >
                        {pos ? "+" : ""}
                        {fmtCompact(h.gain)}
                        <div className="text-[11px] font-normal opacity-80">
                          ({pos ? "+" : ""}
                          {fmt(h.gain_pct)}%)
                        </div>
                      </td>
                      <td className="py-2 text-gray-600 dark:text-gray-300">
                        {fmt(h.weight)}%
                      </td>
                      <td className="py-2">
                        <div className="flex gap-2 text-gray-500 dark:text-gray-400">
                          <button
                            onClick={() => startEdit(h)}
                            className="hover:text-indigo-500"
                            title="ویرایش"
                          >
                            <FaEdit />
                          </button>
                          <button
                            onClick={() => remove(h)}
                            className="hover:text-red-500"
                            title="حذف"
                          >
                            <FaTrash />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
};

export default Portfolio;