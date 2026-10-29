// سلکتور یکپارچه‌ی همه‌ی دارایی‌های قابل‌رسم: سهام + صندوق‌های طلا/کالا + شاخص‌ها.
// داده‌ها یک‌بار (با کش ۱۰ دقیقه‌ای ماژولی) از CompanyNames و market/assets
// برداشته می‌شوند و در گروه‌های جدا نمایش داده می‌شوند.

import React, { useEffect, useMemo, useState } from "react";
import Select, { type GroupBase, type StylesConfig } from "react-select";
import { fetchCompanyNames, getMarketAssets } from "../utils/api";
import { useDarkMode } from "../utils/theme";

export type AssetKind = "stock" | "fund" | "index";

export interface AssetOption {
  value: string;
  label: string;
  kind: AssetKind;
}

type AssetGroup = GroupBase<AssetOption>;

// ── کش ماژولی گزینه‌ها — در همه‌ی صفحات مشترک است ──
let optionsCache: { at: number; options: AssetOption[] } | null = null;
const OPTIONS_TTL = 10 * 60 * 1000;

const KIND_LABEL: Record<AssetKind, string> = {
  stock: "سهام",
  fund: "طلا/کالا",
  index: "شاخص",
};

async function loadOptions(): Promise<AssetOption[]> {
  const [namesRes, assetsRes] = await Promise.allSettled([
    fetchCompanyNames(),
    getMarketAssets(),
  ]);

  const options: AssetOption[] = [];
  const seen = new Set<string>();

  if (assetsRes.status === "fulfilled") {
    // شاخص‌ها — مقدار = نام فارسی شاخص (price-history با نام یا کد می‌پذیرد)
    for (const ix of assetsRes.value.indices || []) {
      if (!ix.name || seen.has(ix.name)) continue;
      seen.add(ix.name);
      options.push({ value: ix.name, label: ix.name, kind: "index" });
    }
    // صندوق‌های طلا/کالا — نماد واقعی و معامله‌پذیر
    for (const f of assetsRes.value.funds || []) {
      if (!f.symbol || seen.has(f.symbol)) continue;
      seen.add(f.symbol);
      options.push({ value: f.symbol, label: f.symbol, kind: "fund" });
    }
  }

  if (namesRes.status === "fulfilled") {
    for (const name of namesRes.value || []) {
      const key = String(name).trim();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      options.push({ value: key, label: key, kind: "stock" });
    }
  }

  return options;
}

export function useAssetOptions() {
  const [options, setOptions] = useState<AssetOption[]>(() => optionsCache?.options ?? []);
  const [loading, setLoading] = useState(!optionsCache);

  useEffect(() => {
    if (optionsCache && Date.now() - optionsCache.at < OPTIONS_TTL) return;
    let alive = true;
    setLoading(true);
    loadOptions()
      .then((opts) => {
        if (!alive || opts.length === 0) return;
        optionsCache = { at: Date.now(), options: opts };
        setOptions(opts);
      })
      .catch(() => undefined)
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const groups = useMemo<AssetGroup[]>(() => {
    const order: AssetKind[] = ["index", "fund", "stock"];
    return order
      .map((kind) => ({
        label:
          kind === "index"
            ? "شاخص‌های بازار"
            : kind === "fund"
              ? "صندوق‌های طلا و کالا"
              : "سهام شرکت‌ها",
        options: options.filter((o) => o.kind === kind),
      }))
      .filter((g) => g.options.length > 0);
  }, [options]);

  return { options, groups, loading };
}

// استایل RTL هماهنگ با بقیه‌ی اپ
const mkStyles = (dark: boolean): StylesConfig<AssetOption, true, AssetGroup> => ({
  control: (base, state) => ({
    ...base,
    borderRadius: "0.75rem",
    borderColor: state.isFocused ? "#059669" : dark ? "#374151" : "#e5e7eb",
    boxShadow: state.isFocused ? "0 0 0 3px rgba(5,150,105,0.15)" : "none",
    backgroundColor: dark ? "#1f293780" : "#ffffff",
    minHeight: "2.25rem",
    ":hover": { borderColor: dark ? "#4b5563" : "#d1d5db" },
  }),
  menu: (base) => ({
    ...base,
    borderRadius: "0.75rem",
    zIndex: 50,
    textAlign: "right",
    backgroundColor: dark ? "#1f2937" : "#ffffff",
    boxShadow: "0 10px 40px -10px rgba(5,150,105,0.2), 0 4px 12px -2px rgba(0,0,0,0.15)",
  }),
  groupHeading: (base) => ({
    ...base,
    textAlign: "right",
    color: dark ? "#9ca3af" : "#6b7280",
    fontSize: "10px",
    fontWeight: 700,
    paddingTop: "0.5rem",
  }),
  option: (base, state) => ({
    ...base,
    direction: "rtl",
    backgroundColor: state.isSelected
      ? "#059669"
      : state.isFocused
        ? dark
          ? "#064e3b"
          : "#ecfdf5"
        : "transparent",
    color: state.isSelected ? "#fff" : dark ? "#e5e7eb" : "#374151",
    cursor: "pointer",
    fontSize: "0.8rem",
  }),
  singleValue: (base) => ({
    ...base,
    color: dark ? "#e5e7eb" : "#1f2937",
    direction: "rtl",
  }),
  input: (base) => ({ ...base, color: dark ? "#e5e7eb" : "#1f2937" }),
  placeholder: (base) => ({ ...base, color: "#9ca3af" }),
});

interface Props {
  value: string[];
  onChange: (vals: string[]) => void;
  max?: number;
  placeholder?: string;
  // پیام خطای سقف انتخاب برای نمایش بیرونی
  onLimitHit?: () => void;
}

const AssetSelect: React.FC<Props> = ({
  value,
  onChange,
  max = 5,
  placeholder = "انتخاب نماد…",
  onLimitHit,
}) => {
  const { darkMode } = useDarkMode();
  const { groups, loading, options } = useAssetOptions();

  const selected = useMemo(
    () =>
      value
        .map((v) => options.find((o) => o.value === v))
        .filter((x): x is AssetOption => Boolean(x)),
    [value, options],
  );

  return (
    <Select<AssetOption, true, AssetGroup>
      isMulti
      isSearchable
      isLoading={loading}
      loadingMessage={() => "در حال دریافت نمادها…"}
      noOptionsMessage={() => "یافت نشد"}
      placeholder={placeholder}
      options={groups}
      value={selected}
      onChange={(vals) => {
        const arr = vals ?? [];
        if (arr.length > max) {
          onLimitHit?.();
          return;
        }
        onChange(arr.map((v) => v.value));
      }}
      isRtl
      className="text-sm"
      styles={mkStyles(darkMode)}
      formatOptionLabel={(opt) => (
        <span className="flex items-center gap-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
            style={{
              background:
                opt.kind === "index" ? "#818cf8" : opt.kind === "fund" ? "#f59e0b" : "#10b981",
            }}
          />
          {opt.label}
          <span className="text-[9px] text-gray-400">{KIND_LABEL[opt.kind]}</span>
        </span>
      )}
    />
  );
};

export default AssetSelect;
