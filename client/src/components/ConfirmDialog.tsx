import React, {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
} from "react";
import { FaExclamationTriangle } from "react-icons/fa";

interface ConfirmOptions {
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export const useConfirm = (): ConfirmFn => {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within ConfirmProvider");
  return ctx;
};

export const ConfirmProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback<ConfirmFn>((opts) => {
    setOptions(opts);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const close = (value: boolean) => {
    resolver.current?.(value);
    resolver.current = null;
    setOptions(null);
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {options && (
        <div
          dir="rtl"
          className="fixed inset-0 z-[110] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
          onClick={() => close(false)}
        >
          <div
            className="animate-scale-in w-full max-w-sm rounded-3xl border border-gray-200/80 dark:border-gray-700/60 bg-white dark:bg-gray-800 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <span
                className={`flex items-center justify-center w-10 h-10 rounded-2xl shrink-0 ${
                  options.danger
                    ? "bg-rose-500/10 text-rose-600 dark:text-rose-400"
                    : "bg-teal-500/10 text-teal-600 dark:text-teal-400"
                }`}
              >
                <FaExclamationTriangle />
              </span>
              <div className="flex-1">
                {options.title && (
                  <h3 className="font-bold text-gray-800 dark:text-white">
                    {options.title}
                  </h3>
                )}
                <p className="text-sm text-gray-600 dark:text-gray-300 mt-1 leading-6">
                  {options.message}
                </p>
              </div>
            </div>
            <div className="mt-5 flex justify-start gap-2">
              <button
                onClick={() => close(true)}
                className={`px-4 h-9 rounded-xl text-sm font-semibold text-white shadow-sm transition ${
                  options.danger
                    ? "bg-rose-600 hover:bg-rose-700"
                    : "bg-emerald-600 hover:bg-emerald-700"
                }`}
              >
                {options.confirmLabel ?? "تأیید"}
              </button>
              <button
                onClick={() => close(false)}
                className="px-4 h-9 rounded-xl text-sm font-medium border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition"
              >
                {options.cancelLabel ?? "انصراف"}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
};
