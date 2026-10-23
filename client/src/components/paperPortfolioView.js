const tehranDate = (instant) => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tehran",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(instant));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
};

const utcWeekday = (date) => new Date(`${date}T12:00:00Z`).getUTCDay();

export function assessMarketState({
  checkedAtUtc,
  lastConfirmedSession,
  latestQuoteDate = null,
  calendarVerified,
  confirmedSessions = [],
  sourceError = false,
}) {
  if (sourceError) return { state: "source_error", missedSession: null };
  if (!lastConfirmedSession) return { state: "calendar_unknown", missedSession: null };
  if (latestQuoteDate && latestQuoteDate < lastConfirmedSession) {
    return { state: "confirmed_session_missing_data", missedSession: lastConfirmedSession };
  }

  const today = tehranDate(checkedAtUtc);
  const missedSession = confirmedSessions.find(
    (session) => session > lastConfirmedSession && session <= today,
  ) ?? null;
  if (missedSession) return { state: "confirmed_session_missing_data", missedSession };
  if (calendarVerified) return { state: "calendar_verified_waiting", missedSession: null };

  const dates = [];
  const cursor = new Date(`${lastConfirmedSession}T12:00:00Z`);
  const end = new Date(`${today}T12:00:00Z`);
  cursor.setUTCDate(cursor.getUTCDate() + 1);
  while (cursor <= end) {
    dates.push(cursor.getUTCDay());
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  if (dates.length > 0 && dates.every((day) => day === 4 || day === 5)) {
    return { state: "natural_weekly_closure", missedSession: null };
  }
  return { state: "calendar_unknown", missedSession: null };
}

export function estimateTarget({ cashToman, priceRial, feeRate = 0.005 }) {
  if (!Number.isFinite(cashToman) || !Number.isFinite(priceRial) || cashToman <= 0 || priceRial <= 0) {
    return null;
  }
  const sharePriceToman = priceRial / 10;
  const shares = Math.floor(cashToman / (sharePriceToman * (1 + feeRate)));
  const grossToman = shares * sharePriceToman;
  const feeToman = grossToman * feeRate;
  return {
    shares,
    grossToman,
    feeToman,
    totalToman: grossToman + feeToman,
    remainingToman: cashToman - grossToman - feeToman,
  };
}

export function sessionCountLabel({ calendarVerified, observed, expirySessions }) {
  if (!calendarVerified) return `نامعلوم؛ تقویم سفارش تأیید نشده (مهلت ${expirySessions} جلسهٔ رسمی)`;
  return `${observed}/${expirySessions}`;
}

export function isPostDecisionPrice(priceDate, decisionAtUtc) {
  if (!priceDate || !decisionAtUtc) return false;
  const decisionDate = tehranDate(decisionAtUtc);
  return priceDate >= decisionDate;
}
