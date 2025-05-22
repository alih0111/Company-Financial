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

const COLORS = ["#82ca9d", "#dddddd"];

type DonutChartProps = {
  score?: number;
};

const DonutChartComponent: React.FC<DonutChartProps> = ({ score }) => {
  const { darkMode } = useDarkMode();

  const actualScore = parseFloat(score?.toString() || "0");

  // Clamp the score visually between 0 and 100
  const scoreValue = Math.min(100, Math.max(0, actualScore));

  const data = [
    { name: "Score", value: scoreValue },
    { name: "Remaining", value: 100 - scoreValue },
  ];

  return (
    <ResponsiveContainer width="100%">
      <PieChart>
        <Pie
          data={data}
          innerRadius={70}
          outerRadius={100}
          paddingAngle={3}
          dataKey="value"
          isAnimationActive
        >
          {data.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
          ))}
          <Label
            value={`${actualScore}%`}
            position="center"
            fontSize={16}
            fill={darkMode ? "#eee" : "#333"}
          />
        </Pie>
        <Tooltip />
      </PieChart>
    </ResponsiveContainer>
  );
};

export default DonutChartComponent;
