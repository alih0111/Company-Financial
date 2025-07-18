import React from "react";

const ScriptFullModal = ({
  modal,
  setModal,
  submitMetadata,
}: {
  modal: any;
  setModal: (val: any) => void;
  submitMetadata: () => void;
}) => {
  if (!modal.visible) return null;

  const handleToggle = (company: string, type: "script1" | "script2") => {
    const updated = {
      ...modal.selections,
      [company]: {
        ...modal.selections[company],
        [type]: !modal.selections[company][type],
      },
    };
    setModal({ ...modal, selections: updated });
  };

  const handleRowMetaChange = (company: string, value: number) => {
    const updated = {
      ...modal.selections,
      [company]: {
        ...modal.selections[company],
        rowMeta: value,
      },
    };
    setModal({ ...modal, selections: updated });
  };

  const [selectAll, setSelectAll] = React.useState(false);
  const handleToggleAll = () => {
    const updated = Object.fromEntries(
      modal.companies.map((name: string) => [
        name,
        {
          ...modal.selections[name],
          script1: selectAll,
          // script2: selectAll,
        },
      ])
    );
    setModal({ ...modal, selections: updated });
    setSelectAll(!selectAll);
  };

  const handleToggleAll2 = () => {
    const updated = Object.fromEntries(
      modal.companies.map((name: string) => [
        name,
        {
          ...modal.selections[name],
          // script1: selectAll,
          script2: selectAll,
        },
      ])
    );
    setModal({ ...modal, selections: updated });
    setSelectAll(!selectAll);
  };

  const [searchTerm, setSearchTerm] = React.useState("");

  const filteredCompanies = modal.companies.filter((name: string) =>
    name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const [rowNum, setRowNum] = React.useState(2);

  const handleMainRowMetaChange=(num:number)=>{
    modal.companies.forEach(element => {
      modal.selections[element].rowMeta = num
    });
    setRowNum(num)
  }

  return (
    <div className="fixed inset-0 z-50 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center">
      <div className="bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 rounded-2xl shadow-2xl w-full max-w-4xl p-6 transition-all duration-300">
        <h2 className="text-3xl font-semibold mb-6 text-center">
          Full Gathering Setup
        </h2>

        <div className="overflow-auto max-h-[500px] border border-gray-200 dark:border-gray-700 rounded-xl">
          <div className="flex items-center justify-between px-6 py-3 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
            <h3 className="text-lg font-medium">Configure Companies</h3>
            <button
              onClick={handleToggleAll}
              className="text-sm font-medium px-4 py-1.5 bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 rounded-md transition"
            >
              {selectAll ? "Select All" : "Deselect All"}
            </button>
            <button
              onClick={handleToggleAll2}
              className="text-sm font-medium px-4 py-1.5 bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 rounded-md transition"
            >
              {selectAll ? "Select All" : "Deselect All"}
            </button>
          </div>

          <div className="px-6 py-4 flex items-center justify-between gap-2">
            <input
              type="text"
              placeholder="Search company..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-800 dark:text-white"
            />
             <input
              type="number"
              min="1"
              className="w-20 px-2 py-2 rounded-md border border-gray-300 dark:border-gray-600 dark:bg-gray-800 text-center focus:outline-none focus:ring-2 focus:ring-indigo-500"
              value={rowNum}
 onChange={(e) =>
                        handleMainRowMetaChange(Number(e.target.value))
                      }
            />
          </div>

          <table className="w-full table-auto text-sm">
            <thead className="bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">
              <tr>
                <th className="px-4 py-3 text-left">Company</th>
                <th className="px-4 py-3">Profit</th>
                <th className="px-4 py-3">Sales</th>
                <th className="px-4 py-3"># Links</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {filteredCompanies.map((name: string) => (
                <tr
                  key={name}
                  className="text-center hover:bg-gray-50 dark:hover:bg-gray-800"
                >
                  <td className="px-4 py-2 text-left font-medium">{name}</td>
                  <td className="px-4 py-2">
                    <input
                      type="checkbox"
                      checked={modal.selections[name].script1}
                      onChange={() => handleToggle(name, "script1")}
                      className="h-4 w-4 accent-indigo-600"
                    />
                  </td>
                  <td className="px-4 py-2">
                    <input
                      type="checkbox"
                      checked={modal.selections[name].script2}
                      onChange={() => handleToggle(name, "script2")}
                      className="h-4 w-4 accent-indigo-600"
                    />
                  </td>
                  <td className="px-4 py-2">
                    <input
                      type="number"
                      min="1"
                      className="w-20 text-sm px-2 py-1 rounded-md border border-gray-300 dark:border-gray-600 dark:bg-gray-800 text-center focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      value={modal.selections[name].rowMeta}
                      onChange={(e) =>
                        handleRowMetaChange(name, Number(e.target.value))
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex justify-end mt-6 space-x-3">
          <button
            onClick={() => setModal({ ...modal, visible: false })}
            className="px-5 py-2 rounded-lg bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-gray-800 dark:text-white transition"
          >
            Cancel
          </button>
          <button
            onClick={submitMetadata}
            className="px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-medium transition"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
};

export default ScriptFullModal;
