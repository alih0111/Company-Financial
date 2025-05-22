// import React from "react";
// import { PieChart, Pie, Tooltip, Cell, ResponsiveContainer } from "recharts";

// type DataPoint = {
//   reportDate: string;
//   percentage: number;
//   wow: number;
// };

// type DonutChartProps = {
//   data: DataPoint[];
// };

// const COLORS = ["#10B981", "#0D9488", "#FB923C", "#F43F5E"];

// const DonutChartComponent: React.FC<DonutChartProps> = ({ data }) => {
//   // Aggregate or transform data if needed – here just limiting to top 4
//   const chartData = data.slice(0, 4).map((d) => ({
//     name: d.reportDate,
//     value: Math.abs(d.percentage), // Donut values should be positive
//   }));

//   return (
//     <ResponsiveContainer width="100%" height={400}>
//       <PieChart>
//         <Pie
//           data={chartData}
//           dataKey="value"
//           nameKey="name"
//           cx="50%"
//           cy="50%"
//           innerRadius={70}
//           outerRadius={100}
//           fill="#8884d8"
//           paddingAngle={5}
//         >
//           {chartData.map((_, index) => (
//             <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
//           ))}
//         </Pie>
//         <Tooltip formatter={(value: number) => `${value}%`} />
//       </PieChart>
//     </ResponsiveContainer>
//   );
// };

// export default DonutChartComponent;

import React from "react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Label,
} from "recharts";
import { useDarkMode } from "../utils/theme"; // adjust path as needed

const COLORS = [
  "#8884d8",
  "#82ca9d",
  "#ffc658",
  "#ff7f50",
  "#00C49F",
  "#FFBB28",
];

const DonutChartComponent = () => {
  const { darkMode } = useDarkMode();

  const data = [
    { name: "Marketing", value: 400 },
    { name: "Sales", value: 300 },
    { name: "Development", value: 300 },
    { name: "Customer Support", value: 200 },
  ];

  const total = data.reduce((sum, entry) => sum + entry.value, 0);

  return (
    <ResponsiveContainer width="100%">
      <PieChart>
        <Pie
          data={data}
          innerRadius={70}
          outerRadius={100}
          paddingAngle={3}
          dataKey="value"
          label={({ name, percent }) =>
            `${name} ${(percent * 100).toFixed(0)}%`
          }
          isAnimationActive
        >
          {data.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
          ))}
          <Label
            value={`Total: ${total}`}
            position="center"
            fontSize={16}
            fill={darkMode ? "#eee" : "#333"} // adapt label color to theme
          />
        </Pie>
        <Tooltip />
      </PieChart>
    </ResponsiveContainer>
  );
};

export default DonutChartComponent;
