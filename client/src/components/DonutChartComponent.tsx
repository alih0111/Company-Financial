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

const DonutChartComponent: React.FC<DonutChartProps> = ({ score }) => {
  const { darkMode } = useDarkMode();
  const dark = darkMode;

  const actualScore = parseFloat(score?.toString() || "0");
  const scoreValue = Math.min(100, Math.max(0, actualScore));

  const mainColor = colorForScore(actualScore);
  const trackColor = dark ? "rgba(148,163,184,0.12)" : "rgba(100,116,139,0.1)";

  const data = [
    { name: "Score", value: scoreValue, color: mainColor },
    { name: "Remaining", value: 100 - scoreValue, color: trackColor },
  ];

  const labelColor = dark ? "#e2e8f0" : "#0f172a";

  const haloData = [{ name: "halo", value: 100, color: dark ? "rgba(99,102,241,0.04)" : "rgba(99,102,241,0.03)" }];

  // Glow filter color based on score
  const glowColor = actualScore >= 60 ? "#10b981" : actualScore >= 40 ? "#f59e0b" : "#ef4444";

  const CustomTooltip = ({ active }: any) => {
    if (!active) return null;
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
          امتیاز: {actualScore.toFixed(1)}%
        </span>
      </div>
    );
  };

  return (
    <div
      className={`relative rounded-2xl p-2 h-full flex items-center justify-center overflow-hidden animate-scale-in ${
        dark
          ? "bg-gradient-to-b from-gray-800/40 to-gray-900/20 border border-gray-700/40"
          : "bg-gradient-to-b from-white/50 to-gray-50/40 border border-gray-200/50"
      } backdrop-blur-sm`}
    >
      <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 200 200">
        <defs>
          <radialGradient id={`donutGlow-${actualScore.toFixed(0)}`} cx="50%" cy="50%" r="40%">
            <stop offset="0%" stopColor={glowColor} stopOpacity="0.12" />
            <stop offset="100%" stopColor={glowColor} stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx="100" cy="100" r="80" fill={`url(#donutGlow-${actualScore.toFixed(0)})`} />
      </svg>

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
            animationDuration={900}
            animationEasing="ease-out"
          >
            {data.map((entry, index) => (
              <Cell
                key={`cell-${index}`}
                fill={entry.color}
                stroke={dark ? "rgba(15,23,42,0.3)" : "rgba(255,255,255,0.7)"}
                strokeWidth={2}
              />
            ))}
            <Label
              value={`${Number(actualScore.toFixed(1))}%`}
              position="center"
              fontSize={24}
              fontWeight={800}
              fill={labelColor}
              style={{ textShadow: "0 1px 2px rgba(0,0,0,0.1)" }}
            />
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
