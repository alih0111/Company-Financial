import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FaPaperPlane, FaRobot, FaUser } from "react-icons/fa";
import {
  sendChatMessage,
  sendChatMessageStream,
  type ChatMessage,
  type ChatProgressEvent,
} from "../utils/api";

const WELCOME_MESSAGE =
  "سلام! 👋 من دستیار تحلیل همین سامانه هستم و جواب‌هایم بر اساس داده‌ی امتیاز کمی شرکت‌های بازار است.\n\n" +
  "می‌توانی این‌ها را از من بپرسی:\n" +
  "• «بهترین سهم‌ها برای سرمایه‌گذاری چی هست؟»\n" +
  "• «تحلیل فولاد» (اسم هر شرکت)\n" +
  "• «مقایسه فولاد و فملی»\n" +
  "• «وضعیت بازار چطوره؟»";

const QUICK_PROMPTS = [
  "بهترین سهم‌ها برای سرمایه‌گذاری چی هست؟",
  "وضعیت بازار چطوره؟",
  "تحلیل فولاد",
  "کمک",
];

// برچسب فارسی ابزارها برای پیشرفت زنده (هماهنگ با toolLabelsFa سمت سرور)
const TOOL_LABELS: Record<string, string> = {
  search_companies: "جست‌وجوی شرکت",
  screen_companies: "غربال بازار",
  get_company_profile: "پروفایل بنیادی شرکت",
  get_company_financials: "صورت‌های مالی",
  get_monthly_sales: "فروش ماهانه",
  get_price_stats: "آمار ریسک قیمت",
  get_my_portfolio: "سبد شما",
  compare_companies: "مقایسه شرکت‌ها",
  build_portfolio: "ساخت سبد",
};

const toolLabel = (tool?: string) =>
  (tool && TOOL_LABELS[tool]) || tool || "تحلیل";

const TypingDots = () => (
  <div className="flex items-center gap-1 px-4 py-3">
    {[0, 1, 2].map((i) => (
      <span
        key={i}
        className="w-2 h-2 rounded-full bg-emerald-500/70 animate-bounce"
        style={{ animationDelay: `${i * 150}ms` }}
      />
    ))}
  </div>
);

const ChatPage = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: WELCOME_MESSAGE },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, sending, progress]);

  const onStreamEvent = (e: ChatProgressEvent) => {
    if (e.kind === "tool_start") {
      setProgress(`${toolLabel(e.tool)}…`);
    } else if (e.kind === "tool_done") {
      setProgress(null);
    } else if (e.kind === "round") {
      setProgress("در حال تحلیل…");
    } else if (e.kind === "notice") {
      setProgress(e.message || null);
    }
  };

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    const nextMessages: ChatMessage[] = [
      ...messages,
      { role: "user", content: trimmed },
    ];
    setMessages(nextMessages);
    setInput("");
    setSending(true);
    setError(null);
    setProgress("در حال شروع…");

    try {
      let res;
      try {
        // مسیر اصلی: استریم پیشرفت ابزارها
        res = await sendChatMessageStream(nextMessages, onStreamEvent);
      } catch (streamErr: any) {
        // fallback: همان اندپوینت همگام قبلی
        setProgress(null);
        res = await sendChatMessage(nextMessages);
        void streamErr;
      }
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.reply },
      ]);
    } catch (e: any) {
      setError(e?.message || "خطا در ارتباط با دستیار");
    } finally {
      setSending(false);
      setProgress(null);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-11rem)] min-h-[420px]" dir="rtl">
      {/* هدر چت */}
      <div className="flex items-center gap-3 pb-3 border-b border-gray-200/80 dark:border-gray-700/60">
        <div className="w-10 h-10 rounded-full bg-emerald-500/15 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
          <FaRobot />
        </div>
        <div>
          <h2 className="font-bold text-gray-800 dark:text-gray-100">
            دستیار سرمایه‌گذاری
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            تحلیل بر اساس امتیاز کمی شرکت‌های بازار
          </p>
        </div>
      </div>

      {/* پیام‌ها */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto py-4 space-y-3 scroll-smooth"
      >
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex items-end gap-2 ${
              m.role === "user" ? "justify-end" : "justify-start"
            }`}
          >
            {m.role === "assistant" && (
              <div className="w-7 h-7 shrink-0 rounded-full bg-emerald-500/15 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
                <FaRobot size={12} />
              </div>
            )}
            <div
              className={`max-w-[85%] leading-6 rounded-2xl px-4 py-2.5 text-sm shadow-sm ${
                m.role === "user"
                  ? "bg-emerald-600 text-white rounded-bl-md"
                  : "bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 border border-gray-200/80 dark:border-gray-700/60 rounded-br-md"
              }`}
            >
              {m.role === "assistant" ? (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    table: (props) => (
                      <table className="w-full text-xs border-collapse my-2" {...props} />
                    ),
                    th: (props) => (
                      <th className="border border-gray-300/60 dark:border-gray-600/60 px-2 py-1 bg-gray-100/70 dark:bg-gray-700/50" {...props} />
                    ),
                    td: (props) => (
                      <td className="border border-gray-300/60 dark:border-gray-600/60 px-2 py-1" {...props} />
                    ),
                    a: (props) => <a className="text-emerald-600 dark:text-emerald-400 underline" {...props} />,
                    p: (props) => <p className="my-1.5" {...props} />,
                    ul: (props) => <ul className="list-disc pr-4 my-1.5" {...props} />,
                    ol: (props) => <ol className="list-decimal pr-4 my-1.5" {...props} />,
                  }}
                >
                  {m.content}
                </ReactMarkdown>
              ) : (
                m.content
              )}
            </div>
            {m.role === "user" && (
              <div className="w-7 h-7 shrink-0 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-gray-500 dark:text-gray-300">
                <FaUser size={11} />
              </div>
            )}
          </div>
        ))}
        {sending && (
          <div className="flex flex-col items-start gap-1">
            <div className="flex justify-end">
              <div className="bg-white dark:bg-gray-800 border border-gray-200/80 dark:border-gray-700/60 rounded-2xl rounded-br-md shadow-sm">
                <TypingDots />
              </div>
            </div>
            {progress && (
              <div className="text-xs text-emerald-700 dark:text-emerald-300 bg-emerald-500/10 rounded-full px-3 py-1 mr-10">
                {progress}
              </div>
            )}
          </div>
        )}
        {error && (
          <div className="text-center text-xs text-red-500 dark:text-red-400 py-1">
            {error}
          </div>
        )}
      </div>

      {/* پیشنهادهای سریع */}
      <div className="flex flex-wrap gap-2 pb-2">
        {QUICK_PROMPTS.map((q) => (
          <button
            key={q}
            onClick={() => send(q)}
            disabled={sending}
            className="text-xs px-3 py-1.5 rounded-full border border-emerald-500/40 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-500/10 transition-colors disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>

      {/* ورودی */}
      <div className="flex items-center gap-2 pt-2 border-t border-gray-200/80 dark:border-gray-700/60">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="سوال خود را بنویسید…"
          className="flex-1 bg-white dark:bg-gray-800 border border-gray-200/80 dark:border-gray-700/60 rounded-full px-4 py-2.5 text-sm text-gray-800 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
        />
        <button
          onClick={() => send(input)}
          disabled={sending || !input.trim()}
          className="w-10 h-10 shrink-0 rounded-full bg-emerald-600 hover:bg-emerald-700 text-white flex items-center justify-center transition-colors disabled:opacity-40"
          aria-label="ارسال"
        >
          <FaPaperPlane size={14} />
        </button>
      </div>

      <p className="text-[10px] text-gray-400 dark:text-gray-500 text-center pt-2">
        پاسخ‌ها بر اساس داده‌های کمی سامانه است و توصیه‌ی خرید/فروش نیست.
      </p>
    </div>
  );
};

export default ChatPage;
