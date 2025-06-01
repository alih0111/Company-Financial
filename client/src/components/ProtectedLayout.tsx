import React from "react";
import Sidebar from "./Sidebar";
import { Outlet } from "react-router-dom";

const ProtectedLayout = ({
  companyOptions,
  selectedCompany,
  onCompanyChange,
  openModalForScript,
  runningScripts,
  companyProfits,
  ...scriptModalProps
}: any) => {
  return (
    <div className="flex h-full">
      <Sidebar
        companyOptions={companyOptions}
        selectedCompany={selectedCompany}
        onCompanyChange={onCompanyChange}
        openModalForScript={openModalForScript}
        runningScripts={runningScripts}
        companyProfits={companyProfits}
        {...scriptModalProps}
      />
      <main className="flex-1 p-6 bg-white/50 dark:bg-gray-900/40 backdrop-blur-md rounded-xl m-4 shadow-2xl transition-all duration-300">
        <Outlet />
      </main>
    </div>
  );
};

export default ProtectedLayout;
