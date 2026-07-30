import React, { useMemo } from "react";
import {
  Bar,
  BarChart,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
  Cell,
} from "recharts";
import { useDarkMode } from "../utils/theme";
import {
  chartPalette,
  glassTooltipStyle,
  fmtShort,
} from "../utils/chart-theme";

type DataPoint = {
  reportDate: string;
  percentage: number;
  wow: number;
};

type ChartComponentProps = {
  data: DataPoint[];
};

// بازه‌ی محور Y با کمی padding
const useDomain = (data: DataPoint[]): [number, number] => {
  if (!data.length) return [0, 10];
  const vals = data.map((d) => d.percentage);
  let min = Math.min(...vals);
  let max = Math.max(...vals);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.08;
  return [Math.min(min - pad, 0), max + pad];
};

// محاسبه‌ی خطوط راهنمای «نسبی» — هم سمت مثبت (نسبت به max) و هم سمت منفی (نسبت به min)
const useGuideLines = (data: DataPoint[]) => {
  return useMemo(() => {
    if (!data.length) return [];
    const posVals = data.map((d) => d.percentage);
    const max = Math.max(...posVals, 0);
    const min = Math.min(...posVals, 0);

    const lines: { value: number; label: string; side: "pos" | "neg" }[] = [];

    // خطوط مثبت (نسبت به بیشترین مقدار مثبت)
    if (max > 0) {
      lines.push({ value: max, label: "max", side: "pos" });
      lines.push({ value: (max * 3) / 4, label: "¾ max", side: "pos" });
      lines.push({ value: max / 2, label: "½ max", side: "pos" });
      lines.push({ value: max / 4, label: "¼ max", side: "pos" });
    }

    // خطوط منفی (نسبت به کمترین مقدار منفی)
    if (min < 0) {
      // min منفی‌ترین مقداره؛ خطوط: min، ¾min، ½min، ¼min (همه منفی)
      lines.push({ value: min, label: "min", side: "neg" });
      lines.push({ value: (min * 3) / 4, label: "¾ min", side: "neg" });
      lines.push({ value: min / 2, label: "½ min", side: "neg" });
      lines.push({ value: min / 4, label: "¼ min", side: "neg" });
    }

    return lines;
  }, [data]);
};

const CustomTooltip = ({ active, payload, dark }: any) => {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as DataPoint;
  const color =
    p.wow === 1
      ? chartPalette.positive
      : p.wow === -1
        ? chartPalette.neutral
        : p.percentage >= 0
          ? chartPalette.positive
          : chartPalette.negative;

  return (
    <div
      style={{
        ...glassTooltipStyle(dark),
        display: "flex",
        flexDirection: "column",
        gap: 4,
        minWidth: 130,
      }}
    >
      <div style={{ opacity: 0.7, fontSize: 11 }}>{p.reportDate}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            width: 10,
            height: 10,
            borderRadius: 3,
            background: color,
            display: "inline-block",
          }}
        />
        <span style={{ color, fontWeight: 700 }}>{fmtShort(p.percentage)}</span>
      </div>
    </div>
  );
};

const ChartComponent: React.FC<ChartComponentProps> = ({ data }) => {
  const { darkMode } = useDarkMode();
  const dark = darkMode;
  const domain = useDomain(data);
  const guides = useGuideLines(data);

  return (
    <div
      className={`relative rounded-2xl p-3 ${
        dark ? "bg-gray-800/40" : "bg-white/40"
      } backdrop-blur-sm border ${
        dark ? "border-gray-700/50" : "border-gray-200/60"
      }`}
    >
      <ResponsiveContainer width="100%" height={300}>
        <BarChart
          data={data}
          margin={{ top: 24, right: 16, bottom: 8, left: 8 }}
        >
          <defs>
            <filter
              id="barShadow2"
              x="-20%"
              y="-20%"
              width="140%"
              height="140%"
            >
              <feDropShadow
                dx="0"
                dy="2"
                stdDeviation="3"
                floodColor="#0f172a"
                floodOpacity={0.25}
              />
            </filter>
          </defs>

          <CartesianGrid
            strokeDasharray="3 6"
            stroke={chartPalette.gridStroke(dark)}
            vertical={false}
          />
          <XAxis
            dataKey="reportDate"
            tick={{ fill: chartPalette.axisTick(dark), fontSize: 11 }}
            tickLine={{ stroke: chartPalette.axisStroke(dark) }}
            axisLine={{ stroke: chartPalette.axisStroke(dark) }}
            dy={6}
          />
          <YAxis
            domain={domain}
            tick={false}
            tickLine={false}
            axisLine={false}
            width={16}
          />
          <Tooltip
            cursor={{
              fill: dark ? "rgba(99,102,241,0.08)" : "rgba(99,102,241,0.06)",
            }}
            content={<CustomTooltip dark={dark} />}
          />
          <ReferenceLine
            y={0}
            stroke={dark ? "#475569" : "#cbd5e1"}
            strokeWidth={1.5}
          />

          {/* خطوط راهنمای نسبی (خط‌چین با لیبل عددی) */}
          {guides.map((g, i) => {
            const isMain = g.label === "max" || g.label === "min";
            return (
              <ReferenceLine
                key={i}
                y={g.value}
                // stroke={
                //   g.side === "pos"
                //     ? isMain
                //       ? dark
                //         ? "#6366f1"
                //         : "#a5b4fc"
                //       : chartPalette.axisStroke(dark)
                //     : isMain
                //       ? dark
                //         ? "#ef4444"
                //         : "#fca5a5"
                //       : chartPalette.axisStroke(dark)
                // }
                strokeDasharray={"2 4"}
                strokeWidth={1}
                ifOverflow="extendDomain"
                label={{
                  value: fmtShort(g.value),
                  position:
                    g.side === "pos" ? "insideTopLeft" : "insideBottomLeft",
                  fontSize: 10,
                  fontWeight: 600,
                  fill: dark ? "#94a3b8" : "#64748b",
                }}
              />
            );
          })}

          {/* bar اصلی */}
          <Bar
            dataKey="percentage"
            radius={[6, 6, 0, 0]}
            maxBarSize={46}
            filter="url(#barShadow2)"
            isAnimationActive
            animationDuration={650}
            animationEasing="ease-out"
          >
            {data.map((entry, index) => (
              <Cell
                key={`cell-${index}`}
                fill={
                  entry.wow === 1
                    ? chartPalette.positive
                    : entry.wow === -1
                      ? chartPalette.neutral
                      : entry.percentage >= 0
                        ? chartPalette.positive
                        : chartPalette.negative
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default ChartComponent;
