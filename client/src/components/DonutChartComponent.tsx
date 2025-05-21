import React from "react";
import { PieChart, Pie, Tooltip, Cell, ResponsiveContainer } from "recharts";

type DataPoint = {
  reportDate: string;
  percentage: number;
  wow: number;
};

type DonutChartProps = {
  data: DataPoint[];
};

const COLORS = ["#10B981", "#0D9488", "#FB923C", "#F43F5E"];

const DonutChartComponent: React.FC<DonutChartProps> = ({ data }) => {
  // Aggregate or transform data if needed – here just limiting to top 4
  const chartData = data.slice(0, 4).map((d) => ({
    name: d.reportDate,
    value: Math.abs(d.percentage), // Donut values should be positive
  }));

  return (
    <ResponsiveContainer width="100%" height={400}>
      <PieChart>
        <Pie
          data={chartData}
          dataKey="value"
          nameKey="name"
          cx="50%"
          cy="50%"
          innerRadius={70}
          outerRadius={100}
          fill="#8884d8"
          paddingAngle={5}
        >
          {chartData.map((_, index) => (
            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip formatter={(value: number) => `${value}%`} />
      </PieChart>
    </ResponsiveContainer>
  );
};

export default DonutChartComponent;
