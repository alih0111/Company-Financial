import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import {
  FaCheckCircle,
  FaExclamationCircle,
  FaExclamationTriangle,
  FaInfoCircle,
  FaTimes,
} from "react-icons/fa";

type ToastKind = "success" | "error" | "info" | "warning";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastApi {
  push: (kind: ToastKind, message: string) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
  warning: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export const useToast = (): ToastApi => {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
};

const KIND_STYLES: Record<
  ToastKind,
  { wrap: string; icon: React.ReactNode }
> = {
  success: {
    wrap: "border-emerald-200 dark:border-emerald-700 bg-emerald-50/95 dark:bg-emerald-900/80 text-emerald-800 dark:text-emerald-200",
    icon: <FaCheckCircle />,
  },
  error: {
    wrap: "border-rose-200 dark:border-rose-700 bg-rose-50/95 dark:bg-rose-900/80 text-rose-800 dark:text-rose-200",
    icon: <FaExclamationCircle />,
  },
  warning: {
    wrap: "border-amber-200 dark:border-amber-700 bg-amber-50/95 dark:bg-amber-900/80 text-amber-800 dark:text-amber-200",
    icon: <FaExclamationTriangle />,
  },
  info: {
    wrap: "border-teal-200 dark:border-teal-700 bg-teal-50/95 dark:bg-teal-900/80 text-teal-800 dark:text-teal-200",
    icon: <FaInfoCircle />,
  },
};

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = Date.now() + Math.random();
      setToasts((prev) => [...prev, { id, kind, message }]);
      window.setTimeout(() => dismiss(id), 5000);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      push,
      success: (m) => push("success", m),
      error: (m) => push("error", m),
      info: (m) => push("info", m),
      warning: (m) => push("warning", m),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        dir="rtl"
        className="fixed top-4 left-1/2 -translate-x-1/2 z-[100] flex flex-col gap-2 w-[min(92vw,420px)] pointer-events-none"
      >
        {toasts.map((t) => {
          const s = KIND_STYLES[t.kind];
          return (
            <div
              key={t.id}
              className={`pointer-events-auto animate-fade-in-up flex items-start gap-3 rounded-2xl border px-4 py-3 shadow-lg backdrop-blur-md ${s.wrap}`}
              role="status"
            >
              <span className="mt-0.5 text-lg shrink-0">{s.icon}</span>
              <p className="text-sm font-medium leading-6 flex-1">{t.message}</p>
              <button
                onClick={() => dismiss(t.id)}
                aria-label="بستن"
                className="opacity-60 hover:opacity-100 transition shrink-0"
              >
                <FaTimes size={12} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
};
