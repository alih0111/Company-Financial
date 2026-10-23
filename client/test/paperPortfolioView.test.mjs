import test from "node:test";
import assert from "node:assert/strict";
import { assessMarketState, estimateTarget, isPostDecisionPrice, sessionCountLabel } from "../src/components/paperPortfolioView.js";

test("Thursday decision and Friday review classify the weekly closure without counting expiry sessions", () => {
  const result = assessMarketState({
    checkedAtUtc: "2026-10-23T07:33:43Z",
    lastConfirmedSession: "2026-10-21",
    latestQuoteDate: "2026-10-21",
    calendarVerified: false,
  });
  assert.equal(result.state, "natural_weekly_closure");
  assert.equal(result.missedSession, null);
  assert.match(sessionCountLabel({ calendarVerified: false, observed: 0, expirySessions: 3 }), /نامعلوم/);
});

test("Saturday without a calendar remains unknown; a confirmed session without a quote is a separate state", () => {
  const unknown = assessMarketState({
    checkedAtUtc: "2026-10-24T07:30:00Z",
    lastConfirmedSession: "2026-10-21",
    calendarVerified: false,
  });
  assert.equal(unknown.state, "calendar_unknown");
  const missing = assessMarketState({
    checkedAtUtc: "2026-10-24T07:30:00Z",
    lastConfirmedSession: "2026-10-21",
    calendarVerified: false,
    confirmedSessions: ["2026-10-24"],
  });
  assert.equal(missing.state, "confirmed_session_missing_data");
  assert.equal(missing.missedSession, "2026-10-24");
});

test("market source errors do not get labeled as a routine closure", () => {
  assert.equal(assessMarketState({
    checkedAtUtc: "2026-10-23T07:33:43Z",
    lastConfirmedSession: "2026-10-21",
    calendarVerified: false,
    sourceError: true,
  }).state, "source_error");
});

test("a confirmed later market session with an older candidate quote is reported as missing data", () => {
  const result = assessMarketState({
    checkedAtUtc: "2026-10-25T07:30:00Z",
    lastConfirmedSession: "2026-10-24",
    latestQuoteDate: "2026-10-21",
    calendarVerified: false,
  });
  assert.equal(result.state, "confirmed_session_missing_data");
  assert.equal(result.missedSession, "2026-10-24");
});

test("pre-decision price is not eligible as the order reference, while target estimate uses rial-to-toman conversion", () => {
  assert.equal(isPostDecisionPrice("2026-10-21", "2026-10-22T18:07:30Z"), false);
  const target = estimateTarget({ cashToman: 100_000_000, priceRial: 39_840 });
  assert.equal(target.shares, 24_975);
  assert.ok(target.totalToman <= 100_000_000);
  assert.ok(target.remainingToman >= 0);
});

test("target calculation refuses missing or invalid reference prices", () => {
  assert.equal(estimateTarget({ cashToman: 100_000_000, priceRial: 0 }), null);
});
