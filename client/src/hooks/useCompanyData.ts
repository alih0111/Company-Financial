import { useCallback, useEffect, useState } from "react";
import {
  fetchCompanyNames,
  fetchSalesData,
  fetchSalesData2,
  fetchSalesDataAllScore,
  fetchSalesDataScore,
  // fetchStockPrice,
  fetchStockPriceScore,
} from "../utils/api";
import type { DataPoint } from "../components/ChartComponent";

import { useSearchParams } from "react-router-dom";

interface ScoreModel {
  companyID: string;
  companyName: string;
  epsGrowth: number;
  epsLevel: string;
  finalScore: string;
  salesGrowth: number;
  salesStability: string;
}

interface AllScoreModel {
  company_id: string;
  company_name: string;
  eps_growth: number;
  sales_growth: number;
  pe: number;
  price: number;
  Stable: boolean;
  operation: number;
  epsGrowth: number;
  priceScore: number;
}

interface StockDataPoint {
  TradeDate: string; // e.g., "2023-05-23"
  Open: number;
  High: number;
  Low: number;
  Close: number;
}

export default function useCompanyData() {
  const [companyOptions, setCompanyOptions] = useState<
    { value: string; label: string }[]
  >([]);
  const [selectedCompany, setSelectedCompany] = useState<string>("");
  const [data1, setData1] = useState<DataPoint[]>([]);
  const [data2, setData2] = useState<DataPoint[]>([]);
  const [dataScore, setDataScore] = useState<ScoreModel[]>();
  const [allDataScore, setAllDataScore] = useState<AllScoreModel[]>();
  const [stockPriceScore, setStockPriceScore] = useState<ScoreModel[]>();
  const [loadingData, setLoadingData] = useState(false);
  const [loadingCompanies, setLoadingCompanies] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const [stockPrice, setStockPrice] = useState<StockDataPoint[]>([]);

  const [hasSynced, setHasSynced] = useState(false);

  useEffect(() => {
    if (!hasSynced && companyOptions.length) {
      const paramCompany = searchParams.get("companyname");
      if (paramCompany) {
        setSelectedCompany(paramCompany);
      }
      setHasSynced(true);
    }
  }, [searchParams, companyOptions, hasSynced]);

  // همگام‌سازی با تغییر companyname در URL (مثلاً کلیک روی نماد در غربال بازار
  // وقتی داشبورد از قبل باز است) — بدون نیاز به رفرش دستی صفحه.
  const paramCompany = searchParams.get("companyname") || "";
  useEffect(() => {
    if (paramCompany) {
      setSelectedCompany((prev) => (prev === paramCompany ? prev : paramCompany));
    }
  }, [paramCompany]);

  const loadCompanyOptions = useCallback(async () => {
    setLoadingCompanies(true);
    try {
      const names = await fetchCompanyNames();
      const options = names.map((name) => ({ value: name, label: name }));
      setCompanyOptions(options);

      const paramCompany = searchParams.get("companyname");

      if(paramCompany == null || paramCompany == ""){
        const firstName = names[0];
        setSelectedCompany(firstName);
      }

      // if (paramCompany && names.includes(paramCompany)) {
      //   setSelectedCompany(paramCompany);
      // } else if (names.length > 0) {
      //   const firstName = names[0];
      //   setSelectedCompany(firstName);
      //   setSearchParams({ companyname: firstName });
      // }
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingCompanies(false);
    }
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    loadCompanyOptions();
  }, [loadCompanyOptions]);

  const fetchData = useCallback(async () => {
    if (!selectedCompany) return;
    setLoadingData(true);

    // Reset previous data immediately
    setData1([]);
    setData2([]);
    setDataScore(undefined);
    setStockPriceScore(undefined);
    setStockPrice([]);
    // setAllDataScore(undefined);

    try {
      const [
        result1,
        result2,
        resultScore,
        resultAllScore,
        // resultPrice,
        resultPriceScore,
      ] = await Promise.allSettled([
        fetchSalesData(selectedCompany),
        fetchSalesData2(selectedCompany),
        fetchSalesDataScore(selectedCompany),
        fetchSalesDataAllScore(),
        // fetchStockPrice(selectedCompany),
        fetchStockPriceScore(selectedCompany),
      ]);

      if (result1.status === "fulfilled") {
        setData1((result1.value as DataPoint[]) || []);
      } else {
        console.error("Error fetching data1:", result1.reason);
      }

      if (result2.status === "fulfilled") {
        setData2((result2.value as DataPoint[]) || []);
      } else {
        console.error("Error fetching data2:", result2.reason);
      }

      if (resultScore.status === "fulfilled") {
        setDataScore(resultScore.value || []);
      } else {
        console.error("Error fetching score data:", resultScore.reason);
      }

      if (resultAllScore.status === "fulfilled") {
        setAllDataScore(resultAllScore.value || []);
      } else {
        console.error("Error fetching score data:", resultAllScore.reason);
      }

      // if (resultPrice.status === "fulfilled") {
      //   setStockPrice(resultPrice.value || []);
      // } else {
      //   console.error("Error fetching score data:", resultPrice.reason);
      // }

      if (resultPriceScore.status === "fulfilled") {
        setStockPriceScore(resultPriceScore.value || []);
      } else {
        console.error("Error fetching score data:", resultPriceScore.reason);
      }
    } catch (e) {
      console.error("Unexpected error in fetchData:", e);
    } finally {
      setLoadingData(false);
    }
  }, [selectedCompany]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return {
    companyOptions,
    selectedCompany,
    setSelectedCompany,
    data1,
    data2,
    dataScore,
    stockPrice,
    allDataScore,
    stockPriceScore,
    loadingData,
    loadingCompanies,
    refreshData: fetchData,
  };
}
