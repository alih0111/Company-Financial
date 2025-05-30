import React, { useRef } from "react";
import {
  LineSeries,
  XAxis,
  YAxis,
  ChartCanvas,
  Chart,
} from "react-financial-charts";
import { scaleTime, scaleLog } from "d3-scale";
import { timeParse } from "d3-time-format";
import useResizeObserver from "use-resize-observer";
import jalaali from "jalaali-js";
// import { timeParse } from "d3-time-format";

type StockDataPoint = {
  date: string;
  Open: number;
  High: number;
  Low: number;
  Close: number;
};

type FormattedDataPoint = {
  date: Date;
  open: number;
  high: number;
  low: number;
  close: number;
};

type Props = {
  data: StockDataPoint[];
};

const parseDate = timeParse("%Y-%m-%d");

const StockChartComponent: React.FC<Props> = ({ data }) => {
  const parseDate = timeParse("%Y-%m-%d");

  const convertJalaliToGregorian = (jalaliDate: string): Date | null => {
    // Assume jalaliDate like "1403/12/08"
    const parts = jalaliDate.split("/");
    if (parts.length !== 3) return null;

    const jy = parseInt(parts[0], 10);
    const jm = parseInt(parts[1], 10);
    const jd = parseInt(parts[2], 10);

    if (isNaN(jy) || isNaN(jm) || isNaN(jd)) return null;

    const { gy, gm, gd } = jalaali.toGregorian(jy, jm, jd);

    // Construct a date string in YYYY-MM-DD format
    const gregorianDateString = `${gy}-${String(gm).padStart(2, "0")}-${String(
      gd
    ).padStart(2, "0")}`;

    return parseDate(gregorianDateString);
  };

  const containerRef = useRef<HTMLDivElement>(null);
  const { width = 0, height = 0 } = useResizeObserver({ ref: containerRef });
  if (data != undefined) {
    if (data.length > 0) {
      var formattedData: FormattedDataPoint[] = data
        .map((d) => {
          const parsedDate = convertJalaliToGregorian(d.date);
          if (!parsedDate || d.Close <= 0) return null;
          return {
            date: parsedDate,
            open: d.Open,
            high: d.High,
            low: d.Low,
            close: d.Close,
          };
        })
        .filter((d): d is FormattedDataPoint => d !== null);
    }
  } else {
    return false;
  }
  const margin = { left: 50, right: 50, top: 10, bottom: 30 };

  return (
    <div ref={containerRef} className="w-full h-full">
      {width > 0 && height > 0 && formattedData?.length > 0 ? (
        <ChartCanvas
          height={height}
          width={width}
          ratio={1}
          margin={margin}
          data={formattedData}
          seriesName="Stock"
          xAccessor={(d) => d.date}
          xScale={scaleTime()}
          xExtents={[
            formattedData[0].date,
            formattedData[formattedData.length - 1].date,
          ]}
        >
          <Chart id={0} yExtents={(d) => d.close} yScale={scaleLog()}>
            <XAxis />
            <YAxis />
            <LineSeries yAccessor={(d) => d.close} />
          </Chart>
        </ChartCanvas>
      ) : (
        <div className="text-sm text-gray-500">Loading chart...</div>
      )}
    </div>
  );
};

export default StockChartComponent;
