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

const useGuideLines = (data: DataPoint[]) => {
  return useMemo(() => {
    if (!data.length) return [];
    const posVals = data.map((d) => d.percentage);
    const max = Math.max(...posVals, 0);
    const min = Math.min(...posVals, 0);

    const lines: { value: number; label: string; side: "pos" | "neg" }[] = [];

    if (max > 0) {
      lines.push({ value: max, label: "max", side: "pos" });
      lines.push({ value: (max * 3) / 4, label: "¾ max", side: "pos" });
      lines.push({ value: max / 2, label: "½ max", side: "pos" });
      lines.push({ value: max / 4, label: "¼ max", side: "pos" });
    }

    if (min < 0) {
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
      className={`relative rounded-2xl p-3 backdrop-blur-sm border ${
        dark
          ? "bg-gray-800/40 border-gray-700/40"
          : "bg-white/50 border-gray-200/50"
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
                dy="1"
                stdDeviation="2"
                floodColor="#6366f1"
                floodOpacity={0.15}
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
              fill: dark ? "rgba(99,102,241,0.06)" : "rgba(99,102,241,0.04)",
            }}
            content={<CustomTooltip dark={dark} />}
          />
          <ReferenceLine
            y={0}
            stroke={dark ? "#475569" : "#cbd5e1"}
            strokeWidth={1.5}
          />

          {guides.map((g, i) => (
            <ReferenceLine
              key={i}
              y={g.value}
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
          ))}

          <Bar
            dataKey="percentage"
            radius={[8, 8, 0, 0]}
            maxBarSize={46}
            filter="url(#barShadow2)"
            isAnimationActive
            animationDuration={700}
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
