# v3.7 Compatibility — `vw_AIStockMetrics` → Canonical v1

> هدف: بعد از migration، یک implementation جدید در `analytics` بسازیم و خروجی را با v3.7 مقایسه کنیم.
> Design artifact؛ هیچ view/DB تغییر نکرده است. نسخه‌ی production در `canonical_design_inputs/sql/vw_AIStockMetrics_production.sql`.

## Inputهای v3.7 و منبع جدید

| v3.7 input (legacy) | منبع canonical v1 |
| --- | --- |
| `mahane.CompanyID` | `fundamentals.monthly_activities.company_id` |
| `mahane.CompanyName` | `core.companies.display_name` |
| `mahane.ReportDate` | `fundamentals.monthly_activities.period_end_date` (+ jalali/fiscal) |
| `mahane.Value3` | `fundamentals.monthly_activities.sales_amount_rial` (canonical rial) |
| `miandore2.Num1_Value1` (EPS) | `financial_facts` metric `eps` (rial_per_share), period 1/current |
| `miandore2.Product1` (NetProfit mixed) | **حذف** → `financial_facts` metric `net_profit` (rial) |
| `miandore2.RevenueNew` | `financial_facts` metric `revenue` (rial) |
| `miandore2.OperatingProfitNew` | `financial_facts` metric `operating_profit` (rial) |
| `miandore2.FinanceCostsNew` | `financial_facts` metric `finance_cost` (rial) |
| `miandore2.OtherNonOpNew` | `financial_facts` metric `other_non_operating` (rial) |
| `miandore2.NetProfitAmount` | `financial_facts` metric `net_profit` (rial) |
| `miandore2.NetProfitAmountLY/FYPrev` | `net_profit` period 2 / 3 |
| `miandore2.OperatingProfitFYPrev` | `operating_profit` period 3 |
| `miandore2.RevenueLastYear/FYPrev` | `revenue` period 2 / 3 |
| `miandore2.OperatingCashFlow/LY/FYPrev` | `financial_facts` metric `operating_cash_flow` periods 1/2/3 |
| `miandore2.TotalAssets/LY` | `total_assets` (balance_sheet) |
| `miandore2.CurrentAssets/LY` | `current_assets` |
| `miandore2.TotalLiabilities/LY` | `total_liabilities` |
| `miandore2.CurrentLiabilities/LY` | `current_liabilities` |
| `miandore2.TotalEquity/LY` | `total_equity` |
| `MarketPriceHistory.ClosingPrice/LastPrice/High/Low` | `market.daily_prices.closing_price_rial/last_price_rial/high_price_rial/low_price_rial` |
| `MarketPriceHistory.TradeValue/Volume/TradeCount` | `market.daily_prices.trade_value_rial/volume/trade_count` |
| `MarketPriceHistory.GregorianDate` | `market.daily_prices.trade_date` |
| `MarketPriceHistory.CompanyID` | `core.securities` → `security_id` → `company_id` |
| `fn_JalaliKey(ReportDate)` | `date`/`fiscal_year`/`fiscal_month` (پیش‌محاسبه، بدون UDF روی هر ردیف) |
| `FullPE` (اختیاری) | حذف از canonical؛ P/E در analytics از `price ÷ (TTM net_profit ÷ shares)` |

## heuristicهایی که در schema جدید حذف می‌شوند

| heuristic v3.7 | چرا لازم بود | جایگزین در v1 |
| --- | --- | --- |
| `NPUnitRatio` (توان-۱۰ بین NetProfitAmount و Product1) | `Product1` مقیاس مخلوط داشت | حذف؛ `net_profit` و `eps` جدا و واحددار ذخیره می‌شوند |
| `OpK` / تشخیص per-share | `OperatingProfit` گاهی per-share و گاهی مبلغی | حذف؛ `operating_profit` همیشه rial و هم‌واحد |
| `OpAbs` / `OpAmt` / `OpLYAmt` / `OpFYPrevAmt` | جبران مخلوط واحد برای نسبت‌ها | حذف؛ نسبت‌ها مستقیم از مقادیر rial |
| `TTMEPS` ضرب/تقسیم دستی به مقیاس EPS | اختلاف مقیاس TTM و EPS | ساده‌تر: `TTM_net_profit / shares` یا `operating_eps` هم‌واحد |
| `DataQualityScore` با `GETDATE()` و offset 621/622 | نبود تاریخ میلادی/cutoff | `date` میلادی + `source_cutoff_at` در `analytics.metric_snapshots` |
| نمایش `LatestEPSReport` = EPS × (NetProfit/NetProfitCum) | جبران مقیاس | حذف؛ EPS خالص گزارش‌شده در `financial_facts` |

## Business logicکه باید حفظ شود (بازپیاده‌سازی در analytics)

| منطق | شرح | مکان جدید |
| --- | --- | --- |
| TTM | `TTM = current + FYPrev − LY` (تجمعی) برای سود عملیاتی/خالص/درآمد/جریان نقدی | analytics (metric materialization) |
| Point-in-time | مقدار در تاریخ X با cutoff داده | `analytics.metric_snapshots.source_cutoff_at` |
| Ranking | رتبه‌ی درصدی (midrank/NULL=0.3) | `analytics.factor_scores.percentile` |
| Penalties | GrowthPenalty/ProfitabilityPenalty/ValuationPenalty/MarketPenalty | `analytics.company_scores.details` / factor rows |
| DataQuality | تازگی گزارش + تازگی قیمت | bounded in analytics |
| Weights | جدول زیر | `analytics.factor_scores.weight` |
| ScoreVersion | نسخه‌بندی الگوریتم | `analytics.score_runs.score_version='v3.7'` |

### وزن‌های v3.7 (برای parity)
| دسته | فاکتور : وزن |
| --- | --- |
| Growth (36) | SalesGrowth 10، SalesGrowth3M 6، RevenueGrowth 5، OperatingProfitGrowth 5، NetProfitGrowth 10 |
| Profitability (26) | OperatingMargin 4، NetMargin 4، ROE 6، MarginTrend 3، InterestCoverage 3، CashConversion 2، EarningsQuality 4 |
| Valuation (16) | PE 11، PS 3، PB 2 |
| Market (11) | Liquidity 3، Leverage 2، CurrentRatio 2، Stability 1، LowVolatility 2، Momentum 1 |
| Formula | `QuantScore = DataQualityScore × (GrowthScore + ProfitabilityScore + ValuationScore + MarketScore)` |

## برنامه‌ی مقایسه (Parity)
1. `analytics.score_runs(score_version='v3.7', as_of_date=...)` بساز.
2. مقادیر خام هر فاکتور را با همان ورودی v3.7 (از داده‌ی مهاجرت‌شده) بازتولید کن.
3. `factor_scores` و `company_scores` را با خروجی view v3.7 join و diff کن.
4. انتظار **bit-for-bit** نداریم؛ tolerance و علت اختلاف (واحد، rounding، نسخه‌ی داده) در `validation_plan.md` ثبت می‌شود.
