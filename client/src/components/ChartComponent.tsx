import React from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
  Cell,
} from "recharts";

type DataPoint = {
  reportDate: string;
  percentage: number;
  wow: number;
};

type ChartComponentProps = {
  data: DataPoint[];
};

const ChartComponent: React.FC<ChartComponentProps> = ({ data }) => {
  return (
    <ResponsiveContainer width="100%" height={400}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="reportDate" />
        <YAxis />
        <Tooltip formatter={(value) => `${value}%`} />
        <ReferenceLine y={0} stroke="#000" />
        <Bar dataKey="percentage">
          {data.map((entry, index) => (
            <Cell
              key={`cell-${index}`}
              fill={
                entry.wow === 1
                  ? "#0D9488" // green
                  : entry.wow === -1
                  ? "#FB923C" // orange
                  : entry.percentage >= 0
                  ? "#10B981" // teal
                  : "#F43F5E" // red
              }
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
};

export default ChartComponent;
