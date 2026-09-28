import React from "react";

const base = "animate-pulse rounded-lg bg-gray-200/70 dark:bg-gray-700/50";

export const Skeleton: React.FC<{ className?: string }> = ({ className = "" }) => (
  <div className={`${base} ${className}`} />
);

export const SkeletonCards: React.FC<{ count?: number }> = ({ count = 6 }) => (
  <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
    {Array.from({ length: count }).map((_, i) => (
      <div
        key={i}
        className="rounded-2xl border border-gray-200/70 dark:border-gray-700/50 bg-white/60 dark:bg-gray-800/40 p-4"
      >
        <Skeleton className="h-3 w-20 mb-3" />
        <Skeleton className="h-5 w-28 mb-2" />
        <Skeleton className="h-2.5 w-16" />
      </div>
    ))}
  </div>
);

export const SkeletonTable: React.FC<{ rows?: number; cols?: number }> = ({
  rows = 6,
  cols = 6,
}) => (
  <div className="rounded-2xl border border-gray-200/70 dark:border-gray-700/50 bg-white/60 dark:bg-gray-800/40 p-4">
    <Skeleton className="h-4 w-32 mb-4" />
    <div className="flex flex-col gap-2">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="grid gap-3" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
          {Array.from({ length: cols }).map((__, c) => (
            <Skeleton key={c} className="h-4 w-full" />
          ))}
        </div>
      ))}
    </div>
  </div>
);

export const SkeletonChart: React.FC<{ height?: number }> = ({ height = 260 }) => (
  <div className="rounded-2xl border border-gray-200/70 dark:border-gray-700/50 bg-white/60 dark:bg-gray-800/40 p-4">
    <Skeleton className="h-4 w-24 mb-4" />
    <Skeleton className="w-full" />
    <div style={{ height }} className={`${base} w-full`} />
  </div>
);
