import { useCallback, useEffect, useState } from "react";
import {
  fetchCompanyNames,
  fetchSalesData,
  fetchSalesData2,
  fetchSalesDataAllScore,
  fetchSalesDataScore,
  // fetchStockPrice,
  fetchStockPriceScore,
  fetchUrlForScript,
  runBulkScript,
  runScript,
} from "../utils/api";

import { useSearchParams } from "react-router-dom";

interface Metadata {
  companyName: string;
  rowMeta: number;
  baseUrl: string;
  pageNumbers: number[];
}

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
  companyName: string;
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

interface CompanyData {
  companyName: string;
  [key: string]: any;
}
type ScriptKey = "script1" | "script2" | "full" | "stockPrices";

const initialMetadata: Metadata = {
  companyName: "",
  rowMeta: 1,
  baseUrl: "",
  pageNumbers: [1],
};

export default function useCompanyData() {
  const [companyOptions, setCompanyOptions] = useState<
    { value: string; label: string }[]
  >([]);
  const [selectedCompany, setSelectedCompany] = useState<string>("");
  const [data1, setData1] = useState<CompanyData[]>([]);
  const [data2, setData2] = useState<CompanyData[]>([]);
  const [dataScore, setDataScore] = useState<ScoreModel[]>();
  const [allDataScore, setAllDataScore] = useState<AllScoreModel[]>();
  const [stockPriceScore, setStockPriceScore] = useState<ScoreModel[]>();
  const [loadingData, setLoadingData] = useState(false);
  const [loadingCompanies, setLoadingCompanies] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const [stockPrice, setStockPrice] = useState<StockDataPoint[]>([]);

  const [modal, setModal] = useState<{
    visible: boolean;
    script: ScriptKey;
    type?: "single" | "bulk";
    companies?: string[];
    selections?: Record<string, { script1: boolean; script2: boolean }>;
  }>({
    visible: false,
    script: "script1",
  });

  const [metadata, setMetadata] = useState<Metadata>(initialMetadata);

  const [runningScripts, setRunningScripts] = useState<
    Record<ScriptKey, boolean>
  >({
    script1: false,
    script2: false,
    full: false,
    stockPrices: false,
  });

  const [hasSynced, setHasSynced] = useState(false);

  const [scriptModalStates, setScriptModalStates] = useState<
    Record<ScriptKey, boolean>
  >({
    script1: false,
    script2: false,
    full: false,
    stockPrices: false,
  });

  const [fullModalData, setFullModalData] = useState<{
    companies: string[];
    selections: Record<
      string,
      { script1: boolean; script2: boolean; rowMeta: number }
    >;
  } | null>(null);

  useEffect(() => {
    if (!hasSynced && companyOptions.length) {
      const paramCompany = searchParams.get("companyname");
      if (paramCompany) {
        setSelectedCompany(paramCompany);
      }
      setHasSynced(true);
    }
  }, [searchParams, companyOptions, hasSynced]);

  const loadCompanyOptions = useCallback(async () => {
    setLoadingCompanies(true);
    try {
      const names = await fetchCompanyNames();
      const options = names.map((name) => ({ value: name, label: name }));
      setCompanyOptions(options);

      const paramCompany = searchParams.get("companyname");

      if (paramCompany && names.includes(paramCompany)) {
        setSelectedCompany(paramCompany);
      } else if (names.length > 0) {
        const firstName = names[0];
        setSelectedCompany(firstName);
        setSearchParams({ companyname: firstName });
      }
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
        setData1(result1.value || []);
      } else {
        console.error("Error fetching data1:", result1.reason);
      }

      if (result2.status === "fulfilled") {
        setData2(result2.value || []);
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

  const openModalForScript = useCallback(
    async (script: any) => {
      if (script === "full") {
        const companies = companyOptions.map((c) => c.value);
        const selections = Object.fromEntries(
          companies.map((name) => [
            name,
            { script1: true, script2: true, rowMeta: 1 },
          ])
        );
        setFullModalData({ companies, selections });
        setScriptModalStates((prev) => ({ ...prev, full: true }));
        return;
      }

      if (!data1[0]?.companyName) return;
      try {
        const res = await fetchUrlForScript(data1[0].companyName, script);
        setMetadata({
          ...metadata,
          companyName: data1[0].companyName,
          baseUrl: res.url || "",
        });
        setScriptModalStates((prev) => ({ ...prev, [script]: true }));
      } catch (e) {
        console.error(e);
      }
    },
    [companyOptions, data1, metadata]
  );

  const submitMetadata = useCallback(
    async (script?: ScriptKey) => {
      if (script === "full" && fullModalData) {
        setScriptModalStates((prev) => ({ ...prev, full: false }));

        const { selections } = fullModalData;
        const companiesByScript: Record<"script1" | "script2", string[]> = {
          script1: [],
          script2: [],
        };

        // Group companies by script
        for (const [company, val] of Object.entries(selections)) {
          if (val.script1) companiesByScript.script1.push(company);
          if (val.script2) companiesByScript.script2.push(company);
        }

        try {
          for (const scriptKey of ["script1", "script2"] as const) {
            const scriptCompanies = companiesByScript[scriptKey];

            // Group companies by their rowMeta values
            const groupedByRowMeta: Record<number, string[]> = {};
            for (const company of scriptCompanies) {
              const rowMeta = selections[company].rowMeta;
              if (!groupedByRowMeta[rowMeta]) {
                groupedByRowMeta[rowMeta] = [];
              }
              groupedByRowMeta[rowMeta].push(company);
            }

            // Run scripts for each group
            for (const [rowMetaStr, companies] of Object.entries(
              groupedByRowMeta
            )) {
              const rowMeta = parseInt(rowMetaStr, 10);
              setRunningScripts((prev) => ({ ...prev, full: true }));
              await runBulkScript(scriptKey, companies, rowMeta, [1]);
            }
          }

          alert("Bulk script execution complete.");
        } catch (e) {
          alert("Error running bulk script.");
          console.error(e);
        } finally {
          setRunningScripts({
            script1: false,
            script2: false,
            full: false,
            stockPrices: false,
          });
        }

        return;
      }

      if (!script) return;
      setScriptModalStates((prev) => ({ ...prev, [script]: false }));
      setRunningScripts((prev) => ({ ...prev, [script]: true }));

      try {
        const res = await runScript(script, metadata);
        alert(res.message);
      } catch (e) {
        alert("Error running script");
        console.error(e);
      } finally {
        setRunningScripts((prev) => ({ ...prev, [script]: false }));
      }
    },
    [metadata, fullModalData]
  );

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
    metadata,
    setMetadata,
    runningScripts,
    scriptModalStates,
    setScriptModalStates,
    fullModalData,
    setFullModalData,
    openModalForScript,
    submitMetadata,
  };
}
