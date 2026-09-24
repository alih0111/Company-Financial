# Integrity Test Plan (v1.1)

> Test caseهای آینده (SQL/pytest) برای اثبات محدودیت‌های integrity. اجرای این تست‌ها در **test database** آینده انجام می‌شود؛ اینجا فقط طراحی.
> الگو: هر تست یک تراکنش است که باید `COMMIT` شود (پذیرش) یا `RAISE` (رد). برای pytest از `pytest.raises(DBAPIError)` استفاده شود.

## Fixtures پایه (seed)
- دو company (`c1`, `c2`)؛ security `s1(c1, ins=111)`, `s2(c2, ins=222)`.
- report `r1(c1)`, `r2(c2)`؛ report_version `rv1(r1, v1)`, `rv2(r2, v1)`.
- portfolio `p1`, `p2`؛ participant `pa1(p1)`, `pa2(p2)`؛ account `ac1(p1, pa1)`, `ac2(p2, pa2)`؛ asset `a1` (stock, security=s1), `a2` (gold).

## Test cases

| # | هدف | تست | انتظار |
| --- | --- | --- | --- |
| T01 | security متعلق به company اشتباه | `UPDATE core.securities SET company_id=c2 WHERE id=s1` (یا insert child با جفت نامطابق) | **reject** (FK/consistency) |
| T02 | report_version متعلق به report اشتباه | insert `financial_statements(report_id=r1, report_version_id=rv2, ...)` | **reject** (composite FK) |
| T03 | دو current ناسازگار | insert دو report_version با `version_no=1` برای یک report | **reject** (`uq_report_versions_no`) |
| T04 | account از portfolio دیگر در transaction | insert `transactions(portfolio_id=p1, account_id=ac2, ...)` | **reject** (composite FK) |
| T05 | participant از portfolio دیگر | insert `transactions(portfolio_id=p1, participant_id=pa2, ...)` | **reject** (composite FK) |
| T06 | self reversal | insert `transactions(id=X, reverses_tx_id=X, ...)` | **reject** (CHECK) |
| T07 | duplicate reversal | دو transaction با `reverses_tx_id=t0` | **reject** (partial unique) |
| T08 | reversal در portfolio دیگر | `transactions(portfolio_id=p2, reverses_tx_id=t0_in_p1)` | **reject** (composite FK) |
| T09 | mutation raw payload | `UPDATE raw.report_payloads ...` / `DELETE` | **reject** (trigger) |
| T10 | mutation financial fact | `UPDATE/DELETE fundamentals.financial_facts` | **reject** (trigger) |
| T11 | mutation transaction | `UPDATE/DELETE portfolio.transactions` | **reject** (trigger) |
| T12 | duplicate daily price business key | insert دو `daily_prices(security_id=s1, trade_date=d)` | **reject** (`uq_daily_prices_security_date`) |
| T13 | invalid fiscal_month | insert `monthly_activities(fiscal_month=13, ...)` | **reject** (CHECK) |
| T14 | نسخه‌ی جدید financial statement بدون conflict | insert statement/report_version جدید (version_no=2) + facts | **accept** |
| T15 | report correction/supersession تاریخچه حفظ شود | insert `reports(B, supersedes_report_id=A)`؛ A باقی | **accept**؛ A و B هر دو موجود |
| T16 | self-supersede | `reports(A, supersedes_report_id=A)` | **reject** (CHECK) |
| T17 | security_id متعلق به company اشتباه در reports | `reports(company_id=c1, security_id=s2)` | **reject** (composite FK) |
| T18 | security_id متعلق به company اشتباه در monthly_activities | `monthly_activities(company_id=c1, security_id=s2, ...)` | **reject** (composite FK) |
| T19 | asset_id + غیرمجاز برای نوع نقدی/الزامی برای دارایی | `transactions(type='buy', asset_id=NULL)` | **reject** (CHECK) |
| T20 | reversal همان portfolio پذیرفته | `transactions(portfolio_id=p1, reverses_tx_id=t0, type='adjustment')` | **accept** |
| T21 | opening_position/cash پذیرفته | insert `opening_position` و `opening_cash` با metadata | **accept** |
| T22 | یکباری بودن reverse | reverse کردن تکراری t0 (بار دوم) | **reject** (partial unique) |
| T23 | account.participant از portfolio دیگر | `accounts(portfolio_id=p1, participant_id=pa2)` | **reject** (composite FK) |
| T24 | two primary securities for one company | دو security با `is_primary=true` برای c1 | **reject** (partial unique) |
| T25 | tsetmc_ins_code تکراری | دو security با ins=111 | **reject** (partial unique) |
| T26 | valid_to < valid_from | security با تاریخ معکوس | **reject** (CHECK) |
| T27 | currency_unit نامعتبر | `monthly_activities(reported_currency_unit='billion_rial')` | **reject** (CHECK) |

## نمونه‌ی اسکلت pytest
```python
import pytest
from sqlalchemy.exc import DBAPIError

def test_report_version_belongs_to_report(db_session):
    # T02
    with pytest.raises(DBAPIError):
        db_session.execute(
            "INSERT INTO fundamentals.financial_statements"
            "(company_id, report_id, report_version_id, statement_type, period_end_date) "
            "VALUES (:c1, :r1, :rv2, 'income_statement', '2026-06-21')",
            {"c1": C1, "r1": R1, "rv2": RV2},
        )
        db_session.flush()
```

## خروجی مورد انتظار
همه‌ی تست‌های reject باید با خطای DB (نه خطای application) رد شوند؛ این ثابت می‌کند integrity در سطح schema تضمین شده است.
