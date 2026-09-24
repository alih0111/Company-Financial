# Integrity Test Plan (v1.2)

> Test caseهای DB-level برای test database آینده. هر reject باید با خطای DB (`DBAPIError`) رخ دهد، نه validation اپلیکیشن.
> الگو: هر تست در یک تراکنش.

## Fixtures (seed)
- companies `c1`,`c2`؛ securities `s1(c1,ins=111)`, `s2(c2,ins=222)`.
- reports `r1(c1)`, `r2(c2)`, `r3`. report_versions `rv1(r1,v1)`, `rv2(r2,v1)`, `rv1b(r1,v2)`.
- parse_runs `pr1(rv1,'miansql','v1',completed)`, `pr2(rv1,'miansql','v2',completed)`, `prx(rv2,...)`.
- portfolios `p1`,`p2`؛ participants `pa1(p1)`,`pa2(p2)`؛ accounts `ac1(p1,pa1)`,`ac2(p2,pa2)`؛ assets `a1(stock,security=s1)`,`a2(gold)`.
- price observations A(v1,T1,100) و B(v2,T2,80) برای `(s1,D)`.

## A. Provenance / versioning
| # | تست | انتظار |
| --- | --- | --- |
| P01 | همان `rv1` با parser v1 و v2 → دو parse_run | **accept** |
| P02 | دو parse_run با همان `(rv1,'miansql','v1')` و status completed | **reject** (partial unique) |
| P03 | insert دو report_version با `(r1,version_no=1)` | **reject** (`uq_report_versions_no`) |
| P04 | insert محتوای یکسان fetch (`r1,content_hash`) | **reject/idempotent** (`uq_report_versions_hash`) |
| P05 | mutation report_version (UPDATE) | **reject** (trigger) |
| P06 | mutation parse_run identity (تغییر parser_version) | **reject** (trigger) |
| P07 | parse_run lifecycle: running→completed (set finished_at) | **accept** |
| P08 | monthly_activity با `parse_run_id` که متعلق به report_version دیگری است | **reject** (composite FK) |
| P09 | monthly_activity با `(parse_run_id, report_version_id)` نامطابق | **reject** (composite FK) |
| P10 | financial_statement با `(report_version_id, report_id)` نامطابق | **reject** (composite FK) |
| P11 | mutation monthly_activity (UPDATE/DELETE) | **reject** (trigger) |
| P12 | mutation financial_statement | **reject** (trigger) |
| P13 | mutation financial_fact | **reject** (trigger) |

## B. Company/Security consistency
| # | تست | انتظار |
| --- | --- | --- |
| C01 | `reports(company_id=c1, security_id=s2)` | **reject** (composite FK) |
| C02 | `monthly_activities(company_id=c1, security_id=s2, ...)` | **reject** |
| C03 | `securities` با دو `is_primary=true` برای c1 | **reject** (partial unique) |
| C04 | دو security با `ins=111` | **reject** (partial unique) |
| C05 | `security.valid_to < valid_from` | **reject** (CHECK) |
| C06 | تغییر `company_id` یک security که child دارد (مثلاً update به c2) | **reject** (FK/composite) |
| C07 | `reports` با تغییر `source_report_id` پس از insert | **reject** (trigger) |

## C. Supersedes
| # | تست | انتظار |
| --- | --- | --- |
| S01 | `r3.supersedes = r3` | **reject** (CHECK) |
| S02 | `r1→r2`, `r2→r1` | **reject** (cycle trigger) |
| S03 | `r1→r2→r3→r1` | **reject** (cycle trigger) |
| S04 | `r3.supersedes = r1` (valid) | **accept**؛ r1 باقی |

## D. Market
| # | تست | انتظار |
| --- | --- | --- |
| M01 | observation v1 و v2 برای `(s1,D)` | **accept** (هر دو) |
| M02 | observation یکسان (همان observation_hash) دوباره | **reject/idempotent** |
| M03 | mutation price_observation | **reject** (trigger) |
| M04 | `daily_prices` view = نسخه‌ی latest (B) | **accept**؛ مقدار=80 |
| M05 | point-in-time با cutoff < T2 → A (100) | **accept** |
| M06 | `price_observations(security_id=s1, trade_date NULL)` | **reject** (NOT NULL) |
| M07 | `vendor_snapshots(security_id=s1, company_id=c2)` | **reject** (composite FK) |
| M08 | `vendor_snapshots(security_id=s1, company_id=NULL)` | **reject** (CHECK) |

## E. Analytics
| # | تست | انتظار |
| --- | --- | --- |
| A01 | `company_scores(company_id=c1, primary_security_id=s2)` | **reject** (composite FK) |
| A02 | mutation company_score | **reject** (trigger) |
| A03 | mutation factor_score | **reject** (trigger) |
| A04 | mutation metric_snapshot | **reject** (trigger) |
| A05 | score_run lifecycle running→completed | **accept** |
| A06 | تغییر `score_version` یک score_run موجود | **reject** (trigger) |
| A07 | metric_snapshot وارد backtest با `collected_at > source_cutoff_at` نشود | **accept/قاعده‌ی query** |

## F. Portfolio / Ledger
| # | تست | انتظار |
| --- | --- | --- |
| L01 | `transactions(portfolio_id=p1, account_id=ac2)` | **reject** (composite FK) |
| L02 | `transactions(portfolio_id=p1, participant_id=pa2)` | **reject** |
| L03 | `accounts(portfolio_id=p1, participant_id=pa2)` | **reject** |
| L04 | `transactions(account_id=NULL)` | **reject** (NOT NULL) |
| L05 | `buy` با `quantity_delta<=0` یا `cash_delta_rial>=0` | **reject** (sign CHECK) |
| L06 | `buy` با `trade_date=NULL` | **reject** (CHECK) |
| L07 | `opening_position` بدون `cost_basis_rial` | **reject** (CHECK) |
| L08 | `opening_position` با `effective_date` و `trade_date=NULL` | **accept** |
| L09 | cash balance = `SUM(cash_delta_rial)` (مثال 76,400,000) | **accept** |
| L10 | position qty = `SUM(quantity_delta)` (مثال 120) | **accept** |
| L11 | opening_position cost basis در avg cost rebuild لحاظ شود | **accept** |
| L12 | reversal self (`reverses_tx_id=id`) | **reject** (CHECK) |
| L13 | reversal دوباره‌ی یک original | **reject** (partial unique) |
| L14 | reversal در portfolio دیگر | **reject** (composite FK/trigger) |
| L15 | reversal یک reversal | **reject** (trigger) |
| L16 | reversal ناموجود | **reject** (trigger) |
| L17 | reversal اثرها را دقیقاً inverse کند (`qty=-orig`, `cash=-orig`) | **accept** (trigger) |
| L18 | reversal با account/asset جعلی که override شود | **accept** (trigger آن‌ها را از original ست می‌کند) |
| L19 | mutation transaction | **reject** (trigger) |
| L20 | `asset_price_snapshots` دو رکورد `(a2, date)` | **reject** (unique) |

## نمونه‌ی اسکلت pytest
```python
import pytest
from sqlalchemy.exc import DBAPIError

def test_monthly_activity_parse_run_chain(db_session):
    # P09: parse_run belongs to rv1, but report_version_id says rv2
    with pytest.raises(DBAPIError):
        db_session.execute(
            "INSERT INTO fundamentals.monthly_activities"
            "(company_id, report_id, report_version_id, parse_run_id, period_end_date) "
            "VALUES (:c1,:r1,:rv2,:pr1,'2026-06-21')",
            {"c1": C1, "r1": R1, "rv2": RV2, "pr1": PR1},
        )
        db_session.flush()

def test_reversal_inverse(db_session):
    # L17: after inserting reversal, deltas must be negation of original
    db_session.execute(
        "INSERT INTO portfolio.transactions"
        "(portfolio_id, account_id, transaction_type, effective_date, reverses_tx_id) "
        "VALUES (:p1,:ac1,'reversal',CURRENT_DATE,:buy1)",
        {"p1": P1, "ac1": AC1, "buy1": BUY1},
    )
    row = db_session.execute(
        "SELECT quantity_delta, cash_delta_rial FROM portfolio.transactions WHERE reverses_tx_id=:buy1",
        {"buy1": BUY1},
    ).one()
    assert row.quantity_delta == -ORIG_QTY and row.cash_delta_rial == -ORIG_CASH
```

## جمع‌بندی
تعداد نهایی: **۵۲ test case** (P01–P13، C01–C07، S01–S04، M01–M08، A01–A07، L01–L20).
همه‌ی rejectها در سطح DB اجرا می‌شوند.
