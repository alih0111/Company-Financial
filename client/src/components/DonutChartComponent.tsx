import React from "react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Label,
} from "recharts";
import { useDarkMode } from "../utils/theme";
import { colorForScore, glassTooltipStyle } from "../utils/chart-theme";

type DonutChartProps = {
  score?: number;
};

// برای کمیته مربعی برابر - نیاز به یک تابع Lambdas برای درصد cellPlug
const DonutChartComponent: React.FC<DonutChartProps> = ({ score }) => {
  const { darkMode } = useDarkMode();
  const dark = darkMode;

  const actualScore = parseFloat(score?.toString() || "0");
  const scoreValue = Math.min(100, Math.max(0, actualScore));

  // رنگ بر اساس امتیاز (پویا)
  const mainColor = colorForScore(actualScore);
  const trackColor = dark ? "rgba(148,163,184,0.18)" : "rgba(100,116,139,0.16)";

  const data = [
    { name: "Score", value: scoreValue, color: mainColor },
    { name: "Remaining", value: 100 - scoreValue, color: trackColor },
  ];

  // رنگ متن عنوان: همان whore که tooltip دارد
  const labelColor = dark ? "#e2e8f0" : "#0f172a";

  // نوار زیرین برای حالت "ring" کمی جذاب‌تر
  // (یک قطعه‌ی بزرگ شفاف به‌عنوان halo پشت دونات)
  const haloData = [{ name: "halo", value: 100, color: dark ? "rgba(99,102,241,0.05)" : "rgba(99,102,241,0.04)" }];

  const CustomTooltip = ({ active }: any) => {
    if (!active) return null;
    const sign = actualScore >= 0 ? "" : "";
    return (
      <div style={{ ...glassTooltipStyle(dark), display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            width: 10,
            height: 10,
            borderRadius: 3,
            background: mainColor,
            display: "inline-block",
          }}
        />
        <span>
          امتیاز: {sign}
          {actualScore.toFixed(1)}%
        </span>
      </div>
    );
  };

  return (
    <div
      className={`relative rounded-2xl p-2 h-full flex items-center justify-center ${
        dark
          ? "bg-gradient-to-b from-gray-800/40 to-gray-900/20"
          : "bg-gradient-to-b from-white/40 to-gray-100/30"
      } backdrop-blur-sm border ${
        dark ? "border-gray-700/50" : "border-gray-200/60"
      } overflow-hidden`}
    >
      {/* halo نورانی پشت دونات */}
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={haloData}
            dataKey="value"
            startAngle={90}
            endAngle={-270}
            innerRadius={92}
            outerRadius={112}
            paddingAngle={0}
            isAnimationActive={false}
          >
            <Cell fill={haloData[0].color} />
          </Pie>

          <Pie
            data={data}
            innerRadius={68}
            outerRadius={94}
            paddingAngle={2}
            cornerRadius={10}
            dataKey="value"
            startAngle={90}
            endAngle={-270}
            isAnimationActive
            animationDuration={750}
            animationEasing="ease-out"
          >
            {data.map((entry, index) => (
              <Cell
                key={`cell-${index}`}
                fill={entry.color}
                stroke={dark ? "rgba(15,23,42,0.4)" : "rgba(255,255,255,0.6)"}
                strokeWidth={2}
              />
            ))}
            <Label
              value={`${Number(actualScore.toFixed(1))}%`}
              position="center"
              fontSize={22}
              fontWeight={800}
              fill={labelColor}
            />
            {/* زیرعنوان */}
            <Label
              value="امتیاز"
              position="center"
              dy={22}
              fontSize={11}
              fill={dark ? "#94a3b8" : "#64748b"}
            />
          </Pie>
          <Tooltip content={<CustomTooltip />} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
};

export default DonutChartComponent;