import React from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Label } from "recharts";
import { useDarkMode } from "../utils/theme";

type GaugeChartProps = {
  score?: number; // 0 to 100
};

const GaugeChartComponent: React.FC<GaugeChartProps> = ({ score = 0 }) => {
  const { darkMode } = useDarkMode();

  const clampedScore = Math.max(0, Math.min(100, score));

  const data = [
    { name: "Score", value: clampedScore },
    { name: "Remaining", value: 100 - clampedScore },
  ];

  const COLORS = ["#82ca9d", "#dddddd"];

  return (
    <ResponsiveContainer width="100%" height={200}>
      <PieChart>
        <Pie
          data={data}
          startAngle={180}
          endAngle={0}
          innerRadius={60}
          outerRadius={90}
          dataKey="value"
          isAnimationActive
        >
          {data.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
          ))}
          <Label
            value={`${clampedScore}%`}
            position="center"
            fontSize={16}
            fill={darkMode ? "#eee" : "#333"}
            offset={10}
          />
        </Pie>
      </PieChart>
    </ResponsiveContainer>
  );
};

export default GaugeChartComponent;
