import React from "react";

type ScriptModalProps = {
  modal: { visible: boolean; script: string };
  setModal: (val: { visible: boolean }) => void;
  metadata: {
    companyName: string;
    rowMeta: number;
    baseUrl: string;
    pageNumbers: number[];
  };
  setMetadata: (meta: any) => void;
  runningScripts: Record<string, boolean>;
  submitMetadata: () => void;
};

const formatScriptName = (name: string) => {
  if (name === "full") return "Full Script";
  const match = name.match(/([a-zA-Z]+)(\d+)/);
  if (match)
    return `${match[1].charAt(0).toUpperCase() + match[1].slice(1)} ${
      match[2]
    }`;
  return name.charAt(0).toUpperCase() + name.slice(1);
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

  const scriptDisplayName = formatScriptName(modal.script);
  const isRunning = runningScripts?.[modal.script];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl dark:bg-gray-900">
        <h2 className="mb-6 text-center text-2xl font-semibold text-gray-800 dark:text-white">
          {scriptDisplayName} Metadata
        </h2>

        <div className="space-y-4">
          <input
            type="text"
            placeholder="Company Name"
            value={metadata.companyName}
            onChange={(e) =>
              setMetadata({ ...metadata, companyName: e.target.value })
            }
            className="w-full rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          />

          <input
            type="number"
            placeholder="Row Meta"
            value={metadata.rowMeta}
            onChange={(e) =>
              setMetadata({ ...metadata, rowMeta: Number(e.target.value) })
            }
            className="w-full rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          />

          <input
            type="text"
            placeholder="Base URL"
            value={metadata.baseUrl}
            onChange={(e) =>
              setMetadata({ ...metadata, baseUrl: e.target.value })
            }
            className="w-full rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          />

          <input
            type="text"
            placeholder="Page Numbers (comma separated)"
            value={metadata.pageNumbers.join(",")}
            onChange={(e) =>
              setMetadata({
                ...metadata,
                pageNumbers: e.target.value.split(",").map(Number),
              })
            }
            className="w-full rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          />
        </div>

        <div className="mt-6 space-y-3">
          <button
            onClick={submitMetadata}
            disabled={isRunning}
            className={`w-full rounded-lg py-2 text-white transition ${
              isRunning
                ? "bg-indigo-400 cursor-not-allowed"
                : "bg-indigo-600 hover:bg-indigo-700"
            }`}
          >
            {isRunning ? "Running..." : `Run ${scriptDisplayName}`}
          </button>

          <button
            onClick={() => setModal({ visible: false })}
            className="w-full rounded-lg border border-gray-300 py-2 text-sm text-gray-700 transition hover:bg-gray-100 dark:border-gray-600 dark:text-white dark:hover:bg-gray-700"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

export default ScriptModal;
