import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchCompanyNames, fetchSalesData, fetchSalesData2, fetchSalesDataAllScore } from "../utils/api";
import { cachedResource } from "../utils/cachedResource";
import { sessionRevision } from "./useGetUser";
import type { DataPoint } from "../components/ChartComponent";

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

const companyNames = cachedResource(fetchCompanyNames, 10 * 60_000);
const allScores = cachedResource<AllScoreModel[]>(fetchSalesDataAllScore, 5 * 60_000);

interface CompanyDataNeeds {
  names: boolean;
  details: boolean;
  scores: boolean;
}

export default function useCompanyData({ names, details, scores }: CompanyDataNeeds) {
  const [searchParams] = useSearchParams();
  const paramCompany = searchParams.get("companyname") || "";
  const [company, setSelectedCompany] = useState("");
  const selectedCompany = paramCompany || company;
  const [companyOptions, setCompanyOptions] = useState<{ value: string; label: string }[]>([]);
  const [data1, setData1] = useState<DataPoint[]>([]);
  const [data2, setData2] = useState<DataPoint[]>([]);
  const [dataCompany, setDataCompany] = useState("");
  const [allDataScore, setAllDataScore] = useState<AllScoreModel[]>([]);
  const [loadingData, setLoadingData] = useState(false);
  const [loadingCompanies, setLoadingCompanies] = useState(false);
  const [companyError, setCompanyError] = useState<string | null>(null);
  const [dataError, setDataError] = useState<string | null>(null);
  const [scoresError, setScoresError] = useState<string | null>(null);
  const [namesRetry, setNamesRetry] = useState(0);
  const [refreshTick, setRefreshTick] = useState(0);
  const sessionKey = String(sessionRevision());
  const latestParam = useRef(paramCompany);
  latestParam.current = paramCompany;

  useEffect(() => {
    if (paramCompany) setSelectedCompany(paramCompany);
  }, [paramCompany]);

  useEffect(() => {
    if (!names) return;
    let active = true;
    setLoadingCompanies(true);
    setCompanyError(null);
    companyNames.load(sessionKey).then((values) => {
      if (!active) return;
      setCompanyOptions(values.map((name) => ({ value: name, label: name })));
      if (!values.length) setCompanyError("فهرست شرکت‌ها خالی است؛ در حال حاضر شرکتی برای نمایش موجود نیست.");
      setSelectedCompany((current) => latestParam.current || current || values[0] || "");
    }).catch((error) => {
      if (active) {
        console.error("Error fetching company names:", error);
        setCompanyError("دریافت فهرست شرکت‌ها انجام نشد. اتصال سرویس داده را بررسی کنید یا دوباره تلاش کنید.");
      }
    }).finally(() => { if (active) setLoadingCompanies(false); });
    return () => { active = false; };
  }, [names, sessionKey, namesRetry]);

  useEffect(() => {
    if (!details || !selectedCompany) return;
    const controller = new AbortController();
    setLoadingData(true);
    setDataError(null);
    setData1([]);
    setData2([]);
    void Promise.allSettled([
      fetchSalesData(selectedCompany, controller.signal),
      fetchSalesData2(selectedCompany, controller.signal),
    ]).then(([profit, sales]) => {
      if (controller.signal.aborted) return;
      if (profit.status === "fulfilled") setData1(profit.value || []);
      else console.error("Error fetching profit data:", profit.reason);
      if (sales.status === "fulfilled") setData2(sales.value || []);
      else console.error("Error fetching sales data:", sales.reason);
      if (profit.status === "rejected" || sales.status === "rejected") {
        setDataError("دریافت بخشی از اطلاعات سود و فروش شرکت انجام نشد؛ دوباره تلاش کنید.");
      }
      setDataCompany(selectedCompany);
      setLoadingData(false);
    });
    return () => controller.abort();
  }, [details, selectedCompany, refreshTick, sessionKey]);

  useEffect(() => {
    if (!scores) return;
    let active = true;
    setScoresError(null);
    allScores.load(sessionKey).then((values) => {
      if (active) setAllDataScore(values);
    }).catch((error) => {
      if (active) {
        console.error("Error fetching market scores:", error);
        setScoresError("دریافت امتیازهای بازار انجام نشد؛ دوباره تلاش کنید.");
      }
    });
    return () => { active = false; };
  }, [scores, refreshTick, sessionKey]);

  const refreshData = useCallback(() => {
    allScores.invalidate();
    setRefreshTick((value) => value + 1);
  }, []);

  const retryCompanyNames = useCallback(() => {
    companyNames.invalidate();
    setNamesRetry((value) => value + 1);
  }, []);

  return {
    companyOptions, selectedCompany, setSelectedCompany,
    data1: dataCompany === selectedCompany ? data1 : [],
    data2: dataCompany === selectedCompany ? data2 : [],
    allDataScore,
    loadingData: details && !!selectedCompany && (loadingData || dataCompany !== selectedCompany),
    loadingCompanies, refreshData, companyError, dataError, scoresError, retryCompanyNames,
  };
}
