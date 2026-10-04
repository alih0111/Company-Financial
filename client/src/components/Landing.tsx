import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  FaChartLine,
  FaTable,
  FaBriefcase,
  FaUsers,
  FaShieldAlt,
  FaMoon,
  FaSun,
  FaArrowLeft,
  FaSignInAlt,
  FaBullseye,
  FaDatabase,
  FaLayerGroup,
  FaBolt,
  FaDollarSign,
  FaCoins,
  FaGem,
} from "react-icons/fa";
import { getAuthStatus } from "../hooks/useGetUser";
import { API_BASE } from "../config";

interface LandingProps {
  darkMode: boolean;
  toggleDarkMode: () => void;
}

interface AccessCard {
  to: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  gradient: string;
  ring: string;
  adminOnly?: boolean;
}

const AccessCard: React.FC<{ card: AccessCard; index: number }> = ({
  card,
  index,
}) => (
  <Link
    to={card.to}
    className="group relative flex flex-col gap-4 rounded-3xl border border-gray-200/70 dark:border-gray-700/50 bg-white/70 dark:bg-gray-800/40 backdrop-blur-xl p-6 shadow-lg shadow-emerald-500/5 hover:shadow-2xl hover:shadow-emerald-500/15 hover:-translate-y-1.5 transition-all duration-300 animate-fade-in-up overflow-hidden"
    style={{ animationDelay: `${index * 90}ms` }}
  >
    {/* هاله‌ی رنگی گوشه‌ی کارت هنگام hover */}
    <div
      className={`pointer-events-none absolute -top-16 -left-16 h-40 w-40 rounded-full blur-3xl opacity-0 group-hover:opacity-25 transition-opacity duration-500 ${card.gradient}`}
    />
    <div
      className={`flex items-center justify-center w-14 h-14 rounded-2xl ring-1 ${card.ring} ${card.gradient} text-white text-2xl shadow-md transition-transform duration-300 group-hover:scale-110 group-hover:rotate-3`}
    >
      {card.icon}
    </div>
    <div>
      <h3 className="text-lg font-bold text-gray-800 dark:text-white">
        {card.title}
      </h3>
      <p className="mt-1 text-sm leading-6 text-gray-500 dark:text-gray-400">
        {card.description}
      </p>
    </div>
    <span className="mt-auto inline-flex items-center gap-2 text-sm font-semibold text-emerald-600 dark:text-emerald-400">
      ورود به بخش
      <FaArrowLeft className="transition-transform duration-300 group-hover:-translate-x-1" />
    </span>
  </Link>
);

// ── ماک‌آپ شیشه‌ای داشبورد در هیرو ──
const HeroPreview: React.FC = () => {
  // مسیر نمودار تزئینی (نرمال‌شده در 0..100)
  const pts = [8, 14, 11, 22, 18, 30, 26, 38, 34, 48, 44, 58, 66, 62, 78, 90];
  const W = 320;
  const H = 110;
  const toXY = (v: number, i: number): [number, number] => [
    (i / (pts.length - 1)) * W,
    H - (v / 100) * H,
  ];
  const line = pts.map((v, i) => toXY(v, i).join(",")).join(" L");
  const area = `M0,${H} L${line} L${W},${H} Z`;

  return (
    <div
      className="relative animate-fade-in-up"
      style={{ animationDelay: "200ms" }}
    >
      {/* کارت اصلی — اسپارک‌لاین بازار */}
      <div className="relative rounded-3xl border border-gray-200/70 dark:border-gray-700/50 bg-white/80 dark:bg-gray-800/60 backdrop-blur-xl shadow-2xl shadow-emerald-500/10 p-5 animate-float">
        <div className="flex items-center gap-2 mb-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/25">
            <FaChartLine size={13} />
          </span>
          <div>
            <p className="text-xs font-bold text-gray-800 dark:text-white">
              نمای کلی بازار
            </p>
            <p className="text-[10px] text-gray-400">امتیاز کوانت بنیادی</p>
          </div>
          <span className="mr-auto inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-1 text-[10px] font-bold text-emerald-600 dark:text-emerald-400 ring-1 ring-emerald-500/20">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse-glow" />
            زنده
          </span>
        </div>

        <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-28">
          <defs>
            <linearGradient id="heroSpark" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="heroStroke" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#10b981" />
              <stop offset="100%" stopColor="#14b8a6" />
            </linearGradient>
          </defs>
          <path d={area} fill="url(#heroSpark)" />
          <path
            d={`M${line}`}
            fill="none"
            stroke="url(#heroStroke)"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle
            cx={W}
            cy={H - (pts[pts.length - 1] / 100) * H}
            r="4"
            fill="#10b981"
          />
          <circle
            cx={W}
            cy={H - (pts[pts.length - 1] / 100) * H}
            r="8"
            fill="none"
            stroke="#10b981"
            strokeOpacity="0.3"
            strokeWidth="2"
          />
        </svg>

        <div className="mt-3 grid grid-cols-3 gap-2">
          {[
            {
              label: "امتیاز",
              value: "۸۲٫۵",
              tone: "text-emerald-600 dark:text-emerald-400",
            },
            {
              label: "رشد سود",
              value: "+۳۴٪",
              tone: "text-emerald-600 dark:text-emerald-400",
            },
            {
              label: "P/E",
              value: "۶٫۱",
              tone: "text-amber-600 dark:text-amber-400",
            },
          ].map((s) => (
            <div
              key={s.label}
              className="rounded-xl bg-gray-50/80 dark:bg-gray-900/40 border border-gray-100 dark:border-gray-700/40 px-2 py-2 text-center"
            >
              <p className="text-[10px] text-gray-400">{s.label}</p>
              <p className={`text-sm font-black tabular-nums ${s.tone}`}>
                {s.value}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* کارت شناور کوچک — رتبه‌ی شرکت */}
      <div
        className="absolute -bottom-6 -right-4 sm:-right-8 rounded-2xl border border-gray-200/70 dark:border-gray-700/50 bg-white/90 dark:bg-gray-800/80 backdrop-blur-xl shadow-xl shadow-indigo-500/10 px-4 py-3 animate-float"
        style={{ animationDelay: "0.8s" }}
      >
        <p className="text-[10px] text-gray-400">رتبه در بازار</p>
        <p className="text-lg font-black tabular-nums text-indigo-600 dark:text-indigo-400">
          ۹۳٪
        </p>
      </div>

      {/* کارت شناور کوچک — سیگنال */}
      <div
        className="absolute -top-5 -left-3 sm:-left-6 rounded-2xl border border-gray-200/70 dark:border-gray-700/50 bg-white/90 dark:bg-gray-800/80 backdrop-blur-xl shadow-xl shadow-emerald-500/10 px-4 py-3 animate-float"
        style={{ animationDelay: "1.6s" }}
      >
        <p className="text-[10px] text-gray-400">سیگنال مدل</p>
        <p className="text-sm font-black text-emerald-600 dark:text-emerald-400">
          خرید قوی ↑
        </p>
      </div>
    </div>
  );
};

// ── بازار در یک نگاه: کارت‌های کلیدی + نوار متحرک آهسته ──
interface TickerItem {
  key: string;
  title: string;
  price: number;
  unit: string;
  change_pct: number;
  source: string;
  group?: string;
}

const FALLBACK_TICKER = [
  { s: "فولاد", c: 2.4 },
  { s: "فملی", c: -1.1 },
  { s: "شپنا", c: 3.8 },
  { s: "خودرو", c: -0.6 },
  { s: "طلا", c: 1.9 },
  { s: "وبملت", c: 0.8 },
  { s: "شستا", c: 2.2 },
  { s: "پارسان", c: -1.7 },
  { s: "فول mob", c: 4.1 },
  { s: "کگل", c: 1.2 },
];

const faInt = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 0 });
const faOne = new Intl.NumberFormat("fa-IR", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const faTwo = new Intl.NumberFormat("fa-IR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const faPct = new Intl.NumberFormat("fa-IR", {
  maximumFractionDigits: 2,
});

// قیمت‌های بزرگ (سکه، طلای ۱۸ عیار و...) فشرده نمایش داده می‌شوند.
const formatTickerPrice = (item: TickerItem): string => {
  if (item.unit === "دلار") return faTwo.format(item.price);
  if (item.unit === "تومان" && item.price >= 10_000_000)
    return `${faOne.format(item.price / 1_000_000)} میلیون`;
  return faInt.format(item.price);
};

const changeNode = (pct: number) => (
  <>
    <span
      className={
        pct >= 0
          ? "text-emerald-600 dark:text-emerald-400"
          : "text-red-500 dark:text-red-400"
      }
    >
      {(pct >= 0 ? "+" : "−") + faPct.format(Math.abs(pct)) + "٪"}
    </span>
    <span className={pct >= 0 ? "text-emerald-500" : "text-red-500"}>
      {pct >= 0 ? "▲" : "▼"}
    </span>
  </>
);

// این آیتم‌ها به‌جای نوار متحرک، کارت برجسته می‌گیرند.
const HIGHLIGHT_CARDS: Record<
  string,
  { icon: React.ReactNode; gradient: string; ring: string }
> = {
  tedex: {
    icon: <FaChartLine />,
    gradient: "bg-gradient-to-br from-emerald-500 to-teal-600",
    ring: "ring-emerald-500/30",
  },
  price_dollar_rl: {
    icon: <FaDollarSign />,
    gradient: "bg-gradient-to-br from-indigo-500 to-violet-600",
    ring: "ring-indigo-500/30",
  },
  geram18: {
    icon: <FaGem />,
    gradient: "bg-gradient-to-br from-amber-500 to-orange-600",
    ring: "ring-amber-500/30",
  },
  sekee: {
    icon: <FaCoins />,
    gradient: "bg-gradient-to-br from-yellow-500 to-amber-600",
    ring: "ring-yellow-500/30",
  },
};

// کد گروه صنعت TSETMC → نام فارسی صنعت
const INDUSTRY_FA: Record<string, string> = {
  "13": "معدنی",
  "23": "پالایشی",
  "27": "فلزات اساسی",
  "34": "خودروسازی",
  "39": "سرمایه‌گذاری",
  "43": "دارویی",
  "44": "پتروشیمی",
  "57": "بانکی",
  "68": "صندوق طلا",
};

// ترتیب نمایش گروه‌ها در نوار
const INDUSTRY_ORDER = [
  "بانکی",
  "فلزات اساسی",
  "معدنی",
  "پالایشی",
  "پتروشیمی",
  "خودروسازی",
  "دارویی",
  "سرمایه‌گذاری",
  "صندوق طلا",
];

const INDUSTRY_STYLE: Record<string, string> = {
  بانکی:
    "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 ring-indigo-500/25",
  "فلزات اساسی":
    "bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-amber-500/25",
  معدنی:
    "bg-orange-500/10 text-orange-600 dark:text-orange-400 ring-orange-500/25",
  پالایشی: "bg-sky-500/10 text-sky-600 dark:text-sky-400 ring-sky-500/25",
  پتروشیمی: "bg-teal-500/10 text-teal-600 dark:text-teal-400 ring-teal-500/25",
  خودروسازی:
    "bg-violet-500/10 text-violet-600 dark:text-violet-400 ring-violet-500/25",
  دارویی:
    "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/25",
  سرمایه‌گذاری:
    "bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-400 ring-fuchsia-500/25",
  "صندوق طلا":
    "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400 ring-yellow-500/25",
};

const TAPE_SPEED_PX_PER_SEC = 30;

// آیتم‌های نوار را بر اساس صنعت گروه‌بندی و مرتب می‌کند.
const buildTapeGroups = (items: TickerItem[]) => {
  const byName = new Map<string, TickerItem[]>();
  for (const t of items) {
    const name = INDUSTRY_FA[t.group ?? ""] ?? "سایر";
    const list = byName.get(name);
    if (list) list.push(t);
    else byName.set(name, [t]);
  }
  return [...byName.entries()]
    .map(([name, list]) => ({ name, items: list }))
    .sort((a, b) => {
      const ia = INDUSTRY_ORDER.indexOf(a.name);
      const ib = INDUSTRY_ORDER.indexOf(b.name);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
};

const TickerTape: React.FC = () => {
  const [items, setItems] = useState<TickerItem[] | null>(null);
  const [live, setLive] = useState<"loading" | "live" | "off">("loading");
  const marqueeRef = React.useRef<HTMLDivElement>(null);
  const offsetRef = React.useRef(0); // موقعیت فعلی نوار (scrollLeft)
  const hoverPauseRef = React.useRef(false);
  const draggingRef = React.useRef<{
    startX: number;
    startScroll: number;
  } | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/market/ticker`);
        if (!res.ok) throw new Error(String(res.status));
        const data = (await res.json()) as { items?: TickerItem[] };
        if (!alive) return;
        if (data.items && data.items.length > 0) {
          setItems(data.items);
          setLive("live");
        } else {
          setLive("off");
        }
      } catch {
        if (alive) setLive("off");
      }
    };
    load();
    const timer = setInterval(load, 60_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  // اسکرول خودکار با تایمر و محاسبه‌ی dt — سرعت ثابت و مستقل از تعداد آیتم‌ها؛
  // در تب مخفی rAF معلق می‌شود، به همین دلیل از setInterval استفاده می‌کنیم.
  // هنگام hover یا کشیدن با موس متوقف می‌شود.
  useEffect(() => {
    const el = marqueeRef.current;
    if (!el) return;
    let last = performance.now();
    const id = window.setInterval(() => {
      const now = performance.now();
      const dt = Math.min((now - last) / 1000, 0.5);
      last = now;
      const half = el.scrollWidth / 2; // عرض یک ستِ کامل از محتوا
      if (half > 0 && !hoverPauseRef.current && !draggingRef.current) {
        offsetRef.current -= TAPE_SPEED_PX_PER_SEC * dt; // حرکت به سمت راست (حس RTL)
        if (offsetRef.current < 0) offsetRef.current += half;
        if (offsetRef.current > half) offsetRef.current -= half;
        el.scrollLeft = offsetRef.current;
      }
    }, 16);
    return () => window.clearInterval(id);
  }, [live]);

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = marqueeRef.current;
    if (!el) return;
    draggingRef.current = { startX: e.clientX, startScroll: el.scrollLeft };
    // با PointerEvent سینتتیک (و بعضی حالت‌های نادر) ممکن است خطا بدهد؛ بحرانی نیست
    try {
      el.setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = marqueeRef.current;
    const d = draggingRef.current;
    if (!el || !d) return;
    const half = el.scrollWidth / 2;
    if (half <= 0) return;
    // محتوا دنبال موس حرکت می‌کند؛ اسکرول در محدوده‌ی محتوای تکرارشده wrap می‌شود
    let s = d.startScroll - (e.clientX - d.startX);
    s = ((s % half) + half) % half;
    offsetRef.current = s;
    el.scrollLeft = s;
  };
  const endDrag = () => {
    draggingRef.current = null;
  };

  const isLive = live === "live" && items !== null;
  const highlightItems = isLive
    ? items!.filter((t) => HIGHLIGHT_CARDS[t.key])
    : [];
  // نوار متحرک فقط سهام + صندوق‌های مثقال و عیار؛ بقیه (سکه‌ها، یورو، صندوق طلا/کهربا و...) نمایش داده نمی‌شوند
  const TAPE_EXCLUDE = new Set(["tedex", "طلا", "کهربا"]);
  const tapeItems = isLive
    ? items!.filter((t) => t.source === "tsetmc" && !TAPE_EXCLUDE.has(t.key))
    : [];
  const tapeGroups = isLive ? buildTapeGroups(tapeItems) : [];

  return (
    <div className="relative z-10 mx-auto max-w-7xl px-6">
      {isLive && highlightItems.length > 0 && (
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {highlightItems.map((t) => {
            const card = HIGHLIGHT_CARDS[t.key];
            return (
              <div
                key={t.key}
                className="flex items-center gap-3 rounded-2xl border border-gray-200/70 dark:border-gray-700/50 bg-white/60 dark:bg-gray-800/40 px-4 py-3.5 backdrop-blur-xl shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all duration-200"
              >
                <span
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white text-base ring-1 shadow-md ${card.ring} ${card.gradient}`}
                >
                  {card.icon}
                </span>
                <div className="min-w-0">
                  <p className="text-[11px] font-medium text-gray-500 dark:text-gray-400">
                    {t.title}
                  </p>
                  <p className="text-base sm:text-lg font-black tabular-nums text-gray-800 dark:text-white leading-tight">
                    {formatTickerPrice(t)}
                    <span className="mr-1 text-[10px] font-medium text-gray-400">
                      {t.unit}
                    </span>
                  </p>
                  <p className="mt-0.5 flex items-center gap-1.5 text-[11px] font-bold tabular-nums">
                    {changeNode(t.change_pct)}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {(!isLive || tapeItems.length > 0) && (
        <div
          ref={marqueeRef}
          dir="ltr"
          className="ticker-mask overflow-hidden rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/50 dark:bg-gray-800/30 backdrop-blur py-2.5 cursor-grab select-none active:cursor-grabbing"
          style={{ touchAction: "pan-y" }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onMouseEnter={() => (hoverPauseRef.current = true)}
          onMouseLeave={() => (hoverPauseRef.current = false)}
        >
          <div className="flex w-max gap-8 px-4">
            {isLive
              ? [...tapeGroups, ...tapeGroups].map((g, gi) => (
                  <React.Fragment key={`${g.name}-${gi}`}>
                    {g.items.map((t) => (
                      <span
                        key={`${t.key}-${gi}`}
                        className="flex items-center gap-2 text-xs font-bold tabular-nums whitespace-nowrap"
                      >
                        <span className="text-gray-800 dark:text-gray-100">
                          {formatTickerPrice(t)}
                          {/* <span className="mr-0.5 text-[9px] font-medium text-gray-400">
                            {t.unit}
                          </span> */}
                        </span>
                        <span className="text-gray-600 dark:text-gray-300">
                          {t.title}
                        </span>
                        {changeNode(t.change_pct)}
                      </span>
                    ))}
                    <span
                      className={`inline-flex shrink-0 items-center self-center rounded-full px-2.5 py-1 text-[10px] font-bold whitespace-nowrap ring-1 ${
                        INDUSTRY_STYLE[g.name] ??
                        "bg-gray-500/10 text-gray-500 ring-gray-500/20"
                      }`}
                    >
                      {g.name}
                    </span>
                  </React.Fragment>
                ))
              : [...FALLBACK_TICKER, ...FALLBACK_TICKER].map((t, i) => (
                  <span
                    key={`fb-${i}`}
                    className="flex items-center gap-2 text-xs font-bold tabular-nums whitespace-nowrap"
                  >
                    <span className="text-gray-600 dark:text-gray-300">
                      {t.s}
                    </span>
                    <span
                      className={
                        t.c >= 0
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-red-500 dark:text-red-400"
                      }
                    >
                      {t.c >= 0 ? "+" : ""}
                      {t.c.toFixed(1)}٪
                    </span>
                    <span
                      className={t.c >= 0 ? "text-emerald-500" : "text-red-500"}
                    >
                      {t.c >= 0 ? "▲" : "▼"}
                    </span>
                  </span>
                ))}
          </div>
        </div>
      )}
      <p className="mt-1.5 flex items-center justify-center gap-1.5 text-[10px] text-gray-400 dark:text-gray-500">
        {isLive ? (
          <>
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse-glow" />
            <span className="text-emerald-600/80 dark:text-emerald-400/80">
              داده‌ی زنده
            </span>
            از TSETMC و TGJU — به‌روزرسانی خودکار هر دقیقه
          </>
        ) : (
          "نوار نمایشی — برای دیدن داده‌ی واقعی وارد داشبورد شوید"
        )}
      </p>
    </div>
  );
};

const Landing: React.FC<LandingProps> = ({ darkMode, toggleDarkMode }) => {
  const { isAdmin, username } = getAuthStatus();
  const isLoggedIn = Boolean(username);

  const cards: AccessCard[] = [
    {
      to: "/dashboard",
      title: "داشبورد شرکت",
      description:
        "تحلیل بنیادی هر نماد: سود، فروش، امتیاز کوانت و نمودارهای تحلیلی.",
      icon: <FaChartLine />,
      gradient: "bg-gradient-to-br from-emerald-500 to-teal-600",
      ring: "ring-emerald-500/30",
    },
    {
      to: "/Table",
      title: "جدول داده",
      description:
        "غربال و مقایسهٔ تمام شرکت‌های بورسی در یک جدول جامع و قابل مرتب‌سازی.",
      icon: <FaTable />,
      gradient: "bg-gradient-to-br from-indigo-500 to-violet-600",
      ring: "ring-indigo-500/30",
    },
    {
      to: "/portfolio",
      title: "پورتفولیو",
      description:
        "مدیریت دارایی‌های سهامی، ترکیب سبد و ارزیابی عملکرد سرمایه‌گذاری.",
      icon: <FaBriefcase />,
      gradient: "bg-gradient-to-br from-amber-500 to-orange-600",
      ring: "ring-amber-500/30",
    },
    {
      to: "/assets",
      title: "دارایی خانواده",
      description:
        "سبد اشخاص، قیمت‌ها و اتصال کارگزاری برای مدیریت یکپارچهٔ دارایی‌ها.",
      icon: <FaUsers />,
      gradient: "bg-gradient-to-br from-fuchsia-500 to-purple-600",
      ring: "ring-fuchsia-500/30",
      adminOnly: true,
    },
  ];

  const visibleCards = cards.filter((c) => !c.adminOnly || isAdmin);

  const stats = [
    { label: "شرکت‌های پوشش‌داده‌شده", value: "۲۷۳", icon: <FaDatabase /> },
    { label: "امتیازدهی بنیادی", value: "PIT-safe", icon: <FaBullseye /> },
    { label: "فاکتورهای مدل", value: "+۵٬۰۰۰", icon: <FaLayerGroup /> },
    { label: "به‌روزرسانی داده", value: "خودکار", icon: <FaBolt /> },
  ];

  return (
    <div dir="rtl" className="relative min-h-screen overflow-hidden">
      {/* ── Decorative background: aurora + grid ── */}
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute inset-0 bg-grid-soft [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,black,transparent)]" />
        <div className="absolute -top-32 -right-24 h-96 w-96 rounded-full bg-emerald-400/20 dark:bg-emerald-500/10 blur-3xl animate-aurora" />
        <div
          className="absolute top-40 -left-24 h-96 w-96 rounded-full bg-teal-400/20 dark:bg-teal-500/10 blur-3xl animate-aurora"
          style={{ animationDelay: "1.2s" }}
        />
        <div
          className="absolute bottom-0 left-1/3 h-80 w-80 rounded-full bg-indigo-400/10 dark:bg-indigo-500/10 blur-3xl animate-aurora"
          style={{ animationDelay: "0.6s" }}
        />
      </div>

      {/* ── Top Navigation ── */}
      <header className="relative z-20 mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-500/25 text-xl">
            <FaChartLine />
          </div>
          <div className="leading-tight">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-emerald-600/80 dark:text-emerald-400/80">
              RFA
            </p>
            <h1 className="text-lg font-bold text-gray-800 dark:text-white">
              بینش شرکت‌ها
            </h1>
          </div>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <button
            onClick={toggleDarkMode}
            aria-label={darkMode ? "حالت روشن" : "حالت تاریک"}
            className="flex h-10 w-10 items-center justify-center rounded-xl border border-gray-200 dark:border-gray-700 bg-white/60 dark:bg-gray-700/50 text-gray-600 dark:text-gray-200 transition hover:scale-105 hover:shadow-md"
          >
            {darkMode ? (
              <FaSun className="text-amber-400" />
            ) : (
              <FaMoon className="text-emerald-600" />
            )}
          </button>

          {isLoggedIn ? (
            <Link
              to="/dashboard"
              className="flex h-10 items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 px-4 text-sm font-semibold text-white shadow-md shadow-emerald-500/20 transition hover:scale-[1.03] hover:shadow-lg"
            >
              <FaChartLine size={12} />
              {username || "داشبورد"}
            </Link>
          ) : (
            <>
              <Link
                to="/register"
                className="hidden h-10 items-center rounded-xl border border-gray-200 dark:border-gray-700 bg-white/60 dark:bg-gray-700/50 px-4 text-sm font-semibold text-gray-700 dark:text-gray-200 transition hover:scale-[1.03] hover:shadow-md sm:flex"
              >
                ثبت‌نام
              </Link>
              <Link
                to="/login"
                className="flex h-10 items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 px-4 text-sm font-semibold text-white shadow-md shadow-emerald-500/20 transition hover:scale-[1.03] hover:shadow-lg"
              >
                <FaSignInAlt size={12} />
                ورود
              </Link>
            </>
          )}
        </div>
      </header>

      {/* ── Hero (دو ستونه) ── */}
      <section className="relative z-10 mx-auto max-w-7xl px-6 pt-10 pb-12 sm:pt-16">
        <div className="grid grid-cols-1 items-center gap-14 lg:grid-cols-2">
          <div className="text-center lg:text-right">
            <span className="animate-fade-in-up inline-flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-4 py-1.5 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
              <FaShieldAlt size={11} />
              سامانهٔ بنیادی و کوانت شرکت‌های بورسی
            </span>

            <h2
              className="animate-fade-in-up mt-6 text-4xl font-black leading-tight text-gray-800 dark:text-white sm:text-5xl"
              style={{ animationDelay: "80ms" }}
            >
              تصمیم‌های سرمایه‌گذاری،
              <span className="text-gradient-emerald"> هوشمندتر و مستندتر</span>
            </h2>

            <p
              className="animate-fade-in-up mx-auto mt-6 max-w-xl text-base leading-8 text-gray-500 dark:text-gray-400 sm:text-lg lg:mx-0"
              style={{ animationDelay: "160ms" }}
            >
              داده‌های بنیادی، صورت‌های مالی و قیمت بازار را یکپارچه می‌کنیم و
              با مدل امتیازدهی نسخه‌دار و PIT-safe، تصویری شفاف از عملکرد هر
              شرکت به شما می‌دهیم.
            </p>

            <div
              className="animate-fade-in-up mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row lg:justify-start"
              style={{ animationDelay: "240ms" }}
            >
              <Link
                to={isLoggedIn ? "/dashboard" : "/login"}
                className="group flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-emerald-500 to-teal-600 px-8 text-base font-bold text-white shadow-lg shadow-emerald-500/25 transition hover:scale-[1.03] hover:shadow-xl hover:shadow-emerald-500/30 sm:w-auto"
              >
                {isLoggedIn ? "ورود به داشبورد" : "ورود به سیستم"}
                <FaArrowLeft className="transition-transform duration-300 group-hover:-translate-x-1" />
              </Link>
              <a
                href="#access"
                className="flex h-12 w-full items-center justify-center gap-2 rounded-2xl border border-gray-200 dark:border-gray-700 bg-white/70 dark:bg-gray-800/40 px-8 text-base font-semibold text-gray-700 dark:text-gray-200 backdrop-blur transition hover:scale-[1.03] hover:shadow-md sm:w-auto"
              >
                مشاهدهٔ بخش‌ها
              </a>
            </div>

            {/* ── Stats bar ── */}
            <div
              className="animate-fade-in-up mt-12 grid max-w-xl grid-cols-2 gap-3 sm:grid-cols-4 mx-auto lg:mx-0"
              style={{ animationDelay: "320ms" }}
            >
              {stats.map((s) => (
                <div
                  key={s.label}
                  className="flex flex-col items-center gap-2 rounded-2xl border border-gray-200/70 dark:border-gray-700/50 bg-white/60 dark:bg-gray-800/40 px-3 py-4 backdrop-blur-xl shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all duration-200"
                >
                  <span className="text-xl text-emerald-600 dark:text-emerald-400">
                    {s.icon}
                  </span>
                  <span className="text-lg font-black tabular-nums text-gray-800 dark:text-white">
                    {s.value}
                  </span>
                  <span className="text-[10px] font-medium text-gray-500 dark:text-gray-400 text-center leading-4">
                    {s.label}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* ستون ویژوال */}
          <div className="hidden lg:flex justify-center pb-8">
            <HeroPreview />
          </div>
        </div>
      </section>

      {/* ── Ticker tape ── */}
      <div className="mb-14">
        <TickerTape />
      </div>

      {/* ── Access cards ── */}
      <section
        id="access"
        className="relative z-10 mx-auto max-w-7xl px-6 pb-20"
      >
        <div className="mb-8 text-center">
          <h3 className="text-2xl font-bold text-gray-800 dark:text-white sm:text-3xl">
            به کجا می‌خواهید بروید؟
          </h3>
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            یکی از بخش‌ها را انتخاب کنید و مستقیم وارد شوید.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {visibleCards.map((card, i) => (
            <AccessCard key={card.to} card={card} index={i} />
          ))}
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="relative z-10 border-t border-gray-200/70 dark:border-gray-700/50">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-6 py-8 text-center sm:flex-row sm:text-right">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            RFA — سامانهٔ تحلیل بنیادی و کوانت شرکت‌های بورسی
          </p>
          <p className="text-xs text-gray-400 dark:text-gray-500">
            داده‌ها به‌صورت نسخه‌دار و قابل ردیابی محاسبه می‌شوند.
          </p>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
