import { useCallback, useEffect, useState } from "react";
import {
  fetchCompanyNames,
  fetchSalesData,
  fetchSalesData2,
  fetchSalesDataScore,
  fetchUrlForScript,
  runScript,
} from "../utils/api";

interface Metadata {
  companyName: string;
  rowMeta: number;
  baseUrl: string;
  pageNumbers: number[];
}

interface CompanyData {
  companyName: string;
  [key: string]: any;
}

type ScriptKey = "script1" | "script2";

const initialMetadata: Metadata = {
  companyName: "",
  rowMeta: 20,
  baseUrl: "",
  pageNumbers: [1, 2],
};

export default function useCompanyData() {
  const [companyOptions, setCompanyOptions] = useState<
    { value: string; label: string }[]
  >([]);
  const [selectedCompany, setSelectedCompany] = useState<string>("");
  const [data1, setData1] = useState<CompanyData[]>([]);
  const [data2, setData2] = useState<CompanyData[]>([]);
  const [dataScore, setDataScore] = useState<number>();
  const [loadingData, setLoadingData] = useState(false);
  const [loadingCompanies, setLoadingCompanies] = useState(false);

  const [modal, setModal] = useState<{ visible: boolean; script: ScriptKey }>({
    visible: false,
    script: "script1",
  });

  const [metadata, setMetadata] = useState<Metadata>(initialMetadata);

  const [runningScripts, setRunningScripts] = useState<
    Record<ScriptKey, boolean>
  >({
    script1: false,
    script2: false,
  });

  const loadCompanyOptions = useCallback(async () => {
    setLoadingCompanies(true);
    try {
      const names = await fetchCompanyNames();
      const options = names.map((name) => ({ value: name, label: name }));
      setCompanyOptions(options);
      if (names.length > 0) setSelectedCompany(names[0]);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingCompanies(false);
    }
  }, []);

  useEffect(() => {
    loadCompanyOptions();
  }, [loadCompanyOptions]);

  const fetchData = useCallback(async () => {
    if (!selectedCompany) return;
    setLoadingData(true);
    try {
      const [json1, json2, jsonScore] = await Promise.all([
        fetchSalesData(selectedCompany),
        fetchSalesData2(selectedCompany),
        fetchSalesDataScore(selectedCompany),
      ]);
      setData1(json1);
      setData2(json2);
      setDataScore(jsonScore);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingData(false);
    }
  }, [selectedCompany]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const openModalForScript = useCallback(
    async (script: ScriptKey) => {
      if (!data1[0]?.companyName) return;
      try {
        const res = await fetchUrlForScript(data1[0].companyName, script);
        setMetadata({
          ...metadata,
          companyName: data1[0].companyName,
          baseUrl: res.url || "",
        });
        setModal({ visible: true, script });
      } catch (e) {
        console.error(e);
      }
    },
    [data1, metadata]
  );

  const submitMetadata = useCallback(async () => {
    setModal((m) => ({ ...m, visible: false }));
    setRunningScripts((prev) => ({ ...prev, [modal.script]: true }));
    try {
      const res = await runScript(modal.script, metadata);
      alert(res.message);
      // await loadCompanyOptions();
    } catch (e) {
      alert("Error running script");
      console.error(e);
    } finally {
      setRunningScripts((prev) => ({ ...prev, [modal.script]: false }));
    }
  }, [modal.script, metadata, loadCompanyOptions]);

  useEffect(() => {
    let interval: NodeJS.Timeout;

    if (runningScripts.script2 && selectedCompany) {
      interval = setInterval(async () => {
        try {
          const updatedData = await fetchSalesData2(selectedCompany);
          setData2(updatedData);
        } catch (error) {
          console.error("Error fetching data2 in interval:", error);
        }
      }, 1000);
    }

    return () => clearInterval(interval);
  }, [runningScripts.script2, selectedCompany]);

  useEffect(() => {
    let interval: NodeJS.Timeout;

    if (runningScripts.script1 && selectedCompany) {
      interval = setInterval(async () => {
        try {
          const updatedData = await fetchSalesData(selectedCompany);
          setData1(updatedData);
        } catch (error) {
          console.error("Error fetching data in interval:", error);
        }
      }, 1000);
    }

    return () => clearInterval(interval);
  }, [runningScripts.script1, selectedCompany]);

  return {
    companyOptions,
    selectedCompany,
    setSelectedCompany,
    data1,
    data2,
    dataScore,
    loadingData,
    loadingCompanies,
    modal,
    setModal,
    metadata,
    setMetadata,
    runningScripts,
    openModalForScript,
    submitMetadata,
  };
}
