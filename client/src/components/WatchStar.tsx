// ستاره‌ی افزودن/حذف به دیده‌بان — مشترک بین هدر نمودار قیمت و چیپ‌های صفحه بازار.
// span است (نه button) تا داخل دکمه‌های والد هم مجاز باشد؛ کلیک از والد جدا می‌شود.

import React, { useEffect, useState } from "react";
import { FaStar } from "react-icons/fa";
import { isWatched, subscribeWatchlist, toggleWatch, type WatchKind } from "../utils/watchlist";

interface Props {
  itemKey: string;
  label?: string;
  kind?: WatchKind;
  size?: number;
  className?: string;
}

const WatchStar: React.FC<Props> = ({
  itemKey,
  label,
  kind = "stock",
  size = 10,
  className = "",
}) => {
  // تیک رندر: با تغییر storage (این تب یا تب دیگر) ستاره‌ها هم‌گام می‌شوند
  const [, setTick] = useState(0);
  useEffect(() => subscribeWatchlist(() => setTick((t) => t + 1)), []);

  const active = isWatched(itemKey);
  const name = label ?? itemKey;
  return (
    <span
      role="button"
      tabIndex={0}
      aria-label={active ? `حذف ${name} از دیده‌بان` : `افزودن ${name} به دیده‌بان`}
      title={active ? "حذف از دیده‌بان" : "افزودن به دیده‌بان"}
      onClick={(e) => {
        e.stopPropagation();
        toggleWatch({ key: itemKey, label: name, kind });
      }}
      className={`shrink-0 p-0.5 transition-colors cursor-pointer ${
        active
          ? "text-amber-400"
          : "text-gray-300 dark:text-gray-600 hover:text-amber-400"
      } ${className}`}
    >
      <FaStar size={size} />
    </span>
  );
};

export default WatchStar;
