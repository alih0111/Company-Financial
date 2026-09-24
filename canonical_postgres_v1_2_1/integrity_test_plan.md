# Integrity Test Plan (v1.2.1)

> Test caseهای DB-level برای test database آینده. هر reject باید با خطای DB (`DBAPIError`) رخ دهد.
> شماره‌گذاری توسط `preflight_check.py` شمارش می‌شود؛ عدد README از همان اسکریپت می‌آید.

## Fixtures (seed)
- companies `c1`,`c2`؛ securities `s1(c1,ins=111)`, `s2(c2,ins=222)`.
- reports `r1(c1)`, `r2(c2)`, `r3`. report_versions `rv1(r1,v1)`, `rv2(r2,v1)`, `rv1b(r1,v2)`.
- parse_runs `pr1(rv1,'miansql','v1',completed)`, `pr2(rv1,'miansql','v2',completed)`, `prx(rv2,...)`.
- portfolios `p1`,`p2`؛ participants `pa1(p1)`,`pa2(p2)`؛ accounts `ac1(p1,pa1)`,`ac2(p2,pa2)`؛ assets `a1(stock,security=s1)`,`a2(gold)`.
- price observations A(v1,T1,100) و B(v2,T2,80) برای `(s1,D)`.

## A. Provenance / versioning (P01–P17)
| # | تست | انتظار |
| --- | --- | --- |
| P01 | همان `rv1` با parser v1 و v2 → دو parse_run | accept |
| P02 | دو parse_run با همان `(rv1,'miansql','v1')` و completed | reject (partial unique) |
| P03 | دو report_version با `(r1,version_no=1)` | reject (`uq_report_versions_no`) |
| P04 | محتوای یکسان fetch (`r1,content_hash`) | reject/idempotent (`uq_report_versions_hash`) |
| P05 | mutation report_version (UPDATE) | reject (trigger) |
| P06 | mutation parse_run identity (تغییر parser_version) | reject (trigger) |
| P07 | parse_run lifecycle running→completed (finished_at set) | accept |
| P08 | monthly_activity با parse_run متعلق به report_version دیگر | reject (composite FK) |
| P09 | monthly_activity با `(parse_run_id, report_version_id)` نامطابق | reject (composite FK) |
| P10 | financial_statement با `(report_version_id, report_id)` نامطابق | reject (composite FK) |
| P11 | mutation monthly_activity | reject (trigger) |
| P12 | mutation financial_statement | reject (trigger) |
| P13 | mutation financial_fact | reject (trigger) |
| P14 | parse_run running→completed | accept |
| P15 | parse_run completed→running | reject (terminal) |
| P16 | parse_run completed→failed | reject (terminal) |
| P17 | parse_run failed→running | reject (terminal) |

## B. Company/Security/Report consistency (C01–C09)
| # | تست | انتظار |
| --- | --- | --- |
| C01 | `reports(company_id=c1, security_id=s2)` | reject (composite FK) |
| C02 | `monthly_activities(company_id=c1, security_id=s2, ...)` | reject |
| C03 | دو `is_primary=true` برای c1 | reject (partial unique) |
| C04 | دو security با `ins=111` | reject (partial unique) |
| C05 | `security.valid_to < valid_from` | reject (CHECK) |
| C06 | تغییر `company_id` یک security که child دارد | reject (FK) |
| C07 | تغییر `source_report_id` بعد از insert | reject (trigger) |
| C08 | report متعلق به c1 ولی `monthly_activities.company_id=c2` | reject (composite FK) |
| C09 | report متعلق به c1 ولی `financial_statements.company_id=c2` | reject (composite FK) |

## C. Supersedes (S01–S04)
| # | تست | انتظار |
| --- | --- | --- |
| S01 | `r3.supersedes = r3` | reject (CHECK) |
| S02 | `r1→r2`, `r2→r1` | reject (cycle trigger) |
| S03 | `r1→r2→r3→r1` | reject (cycle trigger) |
| S04 | `r3.supersedes = r1` (valid) | accept |

## D. Market (M01–M09)
| # | تست | انتظار |
| --- | --- | --- |
| M01 | observation v1 و v2 برای `(s1,D)` | accept (هر دو) |
| M02 | observation یکسان (همان identity+hash) دوباره | reject/idempotent |
| M03 | mutation price_observation | reject (trigger) |
| M04 | `daily_prices` view = نسخه‌ی latest (B) | accept؛ مقدار=80 |
| M05 | point-in-time با cutoff < T2 → A (100) | accept |
| M06 | `price_observations(security_id=s1, trade_date NULL)` | reject (NOT NULL) |
| M07 | `vendor_snapshots(security_id=s1, company_id=c2)` | reject (composite FK) |
| M08 | `vendor_snapshots(security_id=s1, company_id=NULL)` | reject (CHECK) |
| M09 | دو security مختلف، same date/values → two rows | accept (scoped hash) |

## E. Analytics (A01–A11)
| # | تست | انتظار |
| --- | --- | --- |
| A01 | `company_scores(company_id=c1, primary_security_id=s2)` | reject (composite FK) |
| A02 | mutation company_score | reject (trigger) |
| A03 | mutation factor_score | reject (trigger) |
| A04 | mutation metric_snapshot | reject (trigger) |
| A05 | score_run lifecycle running→completed | accept |
| A06 | تغییر `score_version` یک score_run موجود | reject (trigger) |
| A07 | metric_snapshot با `collected_at > source_cutoff_at` در backtest وارد نشود | accept (query rule) |
| A08 | score_run running→completed | accept |
| A09 | score_run completed→running | reject (terminal) |
| A10 | score_run completed→failed | reject (terminal) |
| A11 | score_run failed→running | reject (terminal) |

## F. Portfolio / Ledger (L01–L24)
| # | تست | انتظار |
| --- | --- | --- |
| L01 | `transactions(portfolio_id=p1, account_id=ac2)` | reject (composite FK) |
| L02 | `transactions(portfolio_id=p1, participant_id=pa2)` | reject |
| L03 | `accounts(portfolio_id=p1, participant_id=pa2)` | reject |
| L04 | `transactions(account_id=NULL)` | reject (NOT NULL) |
| L05 | `buy` با sign اشتباه | reject (sign CHECK) |
| L06 | `buy` با `trade_date=NULL` | reject (CHECK) |
| L07 | `opening_position` بدون `cost_basis_rial` | reject (CHECK) |
| L08 | `opening_position` با `effective_date` و `trade_date=NULL` | accept |
| L09 | cash balance = `SUM(cash_delta_rial)` | accept |
| L10 | position qty = `SUM(quantity_delta)` | accept |
| L11 | opening_position cost basis در avg cost rebuild | accept |
| L12 | reversal self (`reverses_tx_id=id`) | reject (CHECK) |
| L13 | reversal دوباره‌ی یک original | reject (partial unique) |
| L14 | reversal در portfolio دیگر | reject (composite FK/trigger) |
| L15 | reversal یک reversal | reject (trigger) |
| L16 | reversal ناموجود | reject (trigger) |
| L17 | reversal اثرها را inverse کند (`qty=-orig`,`cash=-orig`) | accept (trigger) |
| L18 | reversal account/asset/participant را از original inherit کند | accept (trigger) |
| L19 | mutation transaction | reject (trigger) |
| L20 | `asset_price_snapshots` دو رکورد `(a2,date)` | reject (unique) |
| L21 | opening_position + reversal → quantity = 0 | accept |
| L22 | opening_position + reversal → cost basis = 0 | accept |
| L23 | buy + reversal → economic state مثل عدم وجود buy (`effective_transactions`) | accept |
| L24 | `quantity` قابل نوشتن نیست (derived) و = `abs(quantity_delta)` | reject insert quantity / accept derived |

## نمونه‌ی اسکلت pytest
```python
import pytest
from sqlalchemy.exc import DBAPIError

def test_report_company_consistency(db_session):
    # C08
    with pytest.raises(DBAPIError):
        db_session.execute(
            "INSERT INTO fundamentals.monthly_activities"
            "(company_id, report_id, report_version_id, parse_run_id, period_end_date) "
            "VALUES (:c2,:r1,:rv1,:pr1,'2026-06-21')",
            {"c2": C2, "r1": R1, "rv1": RV1, "pr1": PR1},
        )
        db_session.flush()

def test_parse_run_terminal(db_session):
    # P15
    with pytest.raises(DBAPIError):
        db_session.execute(
            "UPDATE ingestion.parse_runs SET status='running', finished_at=NULL WHERE id=:pr1",
            {"pr1": PR1},
        )
        db_session.flush()

def test_reversal_cancels_opening(db_session):
    # L21/L22
    db_session.execute(
        "INSERT INTO portfolio.transactions"
        "(portfolio_id, account_id, transaction_type, effective_date, reverses_tx_id) "
        "VALUES (:p1,:ac1,'reversal',CURRENT_DATE,:op)",
        {"p1": P1, "ac1": AC1, "op": OPEN1},
    )
    row = db_session.execute(
        "SELECT SUM(quantity_delta) q, SUM(cash_delta_rial) c, SUM(COALESCE(cost_basis_rial,0)) cb "
        "FROM portfolio.effective_transactions WHERE portfolio_id=:p1",
        {"p1": P1},
    ).one()
    assert row.q == 0 and row.cb == 0
```
