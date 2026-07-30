import React from "react";
import { RadialBarChart, RadialBar, ResponsiveContainer, PolarAngleAxis, Label } from "recharts";
import { useDarkMode } from "../utils/theme";
import { chartPalette, colorForScore } from "../utils/chart-theme";

type GaugeChartProps = {
  score?: number; // 0 to 100
};

const GaugeChartComponent: React.FC<GaugeChartProps> = ({ score = 0 }) => {
  const { darkMode } = useDarkMode();
  const dark = darkMode;

  const clampedScore = Math.max(0, Math.min(100, score));
  const mainColor = colorForScore(clampedScore);
  const labelColor = dark ? "#e2e8f0" : "#0f172a";

  // data برای radial bar (یک نوار منفرد روی مقدار)
  const data = [{ name: "score", value: clampedScore, fill: mainColor }];

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
      {/* تار کم‌رنگ فضایی پشت gauge (halo) */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background: `radial-gradient(circle at 50% 75%, ${mainColor}22 0%, transparent 60%)`,
        }}
      />
      <ResponsiveContainer width="100%" height="100%">
        <RadialBarChart
          data={data}
          startAngle={180}
          endAngle={0}
          innerRadius="70%"
          outerRadius="100%"
          barSize={16}
        >
          <defs>
            <linearGradient id="gaugeFill" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor={chartPalette.scoreStops[0].color} />
              <stop offset="50%" stopColor={chartPalette.scoreStops[1].color} />
              <stop offset="100%" stopColor={mainColor} />
            </linearGradient>
          </defs>

          <PolarAngleAxis
            type="number"
            domain={[0, 100]}
            tick={false}
            axisLine={false}
          />
          <RadialBar
            dataKey="value"
            cornerRadius={10}
            isAnimationActive
            animationDuration={800}
            animationEasing="ease-out"
            background={{
              fill: dark ? "rgba(148,163,184,0.18)" : "rgba(100,116,139,0.14)",
            }}
            fill="url(#gaugeFill)"
          />
          <Label
            value={`${Number(clampedScore.toFixed(1))}`}
            position="center"
            dy={-4}
            fontSize={28}
            fontWeight={800}
            fill={labelColor}
          />
          <Label
            value="%"
            position="center"
            dy={18}
            fontSize={11}
            fill={dark ? "#94a3b8" : "#64748b"}
          />
        </RadialBarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default GaugeChartComponent;