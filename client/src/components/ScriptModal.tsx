import React from "react";

interface Metadata {
  companyName: string;
  rowMeta: number;
  baseUrl: string;
  pageNumbers: number[];
}

interface ScriptModalProps {
  modal: { visible: boolean; script: "script1" | "script2" };
  setModal: React.Dispatch<
    React.SetStateAction<{ visible: boolean; script: string }>
  >;
  metadata: Metadata;
  setMetadata: React.Dispatch<React.SetStateAction<Metadata>>;
  runningScripts: Record<"script1" | "script2", boolean>;
  submitMetadata: () => void;
}

const modalTitles = {
  script1: "Set Metadata for Profit",
  script2: "Set Metadata for Sales",
};

const ScriptModal: React.FC<ScriptModalProps> = ({
  modal,
  setModal,
  metadata,
  setMetadata,
  runningScripts,
  submitMetadata,
}) => {
  if (!modal.visible) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex justify-center items-center z-50">
      <div className="bg-white dark:bg-gray-700 rounded-xl p-8 w-96 max-w-full shadow-lg flex flex-col gap-4">
        <h2 className="text-xl font-semibold text-center text-gray-900 dark:text-white">
          {modalTitles[modal.script]}
        </h2>

        <input
          type="text"
          placeholder="Company Name"
          value={metadata.companyName}
          onChange={(e) =>
            setMetadata({ ...metadata, companyName: e.target.value })
          }
          className="px-3 py-2 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-600 dark:border-gray-500 dark:text-white"
        />

        <input
          type="number"
          placeholder="Row Meta"
          value={metadata.rowMeta}
          onChange={(e) =>
            setMetadata({ ...metadata, rowMeta: Number(e.target.value) })
          }
          className="px-3 py-2 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-600 dark:border-gray-500 dark:text-white"
        />

        <input
          type="text"
          placeholder="Base URL"
          value={metadata.baseUrl}
          onChange={(e) =>
            setMetadata({ ...metadata, baseUrl: e.target.value })
          }
          className="px-3 py-2 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-600 dark:border-gray-500 dark:text-white"
        />

        <input
          type="text"
          placeholder="Page Numbers (e.g. 1,2,3)"
          value={metadata.pageNumbers.join(",")}
          onChange={(e) =>
            setMetadata({
              ...metadata,
              pageNumbers: e.target.value
                .split(",")
                .map((n) => parseInt(n.trim()))
                .filter((n) => !isNaN(n)),
            })
          }
          className="px-3 py-2 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-600 dark:border-gray-500 dark:text-white"
        />

        <button
          onClick={submitMetadata}
          // disabled={runningScripts[modal.script]}
          className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white rounded-lg py-3 font-semibold transition disabled:cursor-not-allowed"
        >
          {runningScripts[modal.script] ? "Running..." : "Run Script"}
        </button>

        <button
          onClick={() => setModal({ visible: false, script: modal.script })}
          className="bg-transparent border border-gray-400 hover:bg-gray-100 dark:border-gray-600 dark:hover:bg-gray-600 rounded-lg py-3 font-semibold transition"
        >
          Cancel
        </button>
      </div>
    </div>
  );
};

export default ScriptModal;
