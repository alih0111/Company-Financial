# تحویل V12.8

اجرای کامل آفلاین در `ranking_research/output/return_v12_8/v12_8_20261020T040000Z/` ثبت شد. گزارش: `docs/RETURN_V12_8_FINAL.fa.md`.

## یافتهٔ تصمیم

- w0 lift برندگان ۶۳جلسه‌ای: top10=1.558× و top20=1.627× تصادفی هم‌اندازه.
- پوشش وزنی w0 در snapshotهای یکتا: مشاهدهٔ معتبر 44.26٪؛ fallback 55.74٪.
- A=228,438,013 تومان؛ بدون trim=234,996,347؛ اختلاف=+6,558,334 تومان.
- عامل اصلی نامعلوم: علت سلولی missing و PIT join برای عوامل مالی غیر فروش؛ شواهد برای نسبت دادن ضعف اقتصادی به «داده» یا «رتبه» به‌تنهایی کافی نیست. دو سیاست هم تغییر تخصیص وجه و drift موجودی را باهم دارند.
- مسیر بعدی: ثبت زمان‌دار سیاست و معیارها برای ارزیابی دادهٔ آینده؛ اصلاح وزن‌ها از این شواهد توجیه نمی‌شود.

## مصنوعات

- `analysis_contract.json`, `pre_result_hashes.json`, `manifest.json`
- `winner_quality.csv` با N/W/K/H و lift/precision/recall برای جمع و شش بلوک
- `factor_weight_coverage.csv`, `factor_coverage_summary.csv`, `missing_reason_aggregate.csv`, `provenance_samples.csv`, `factor_score_decomposition.csv`
- `policy_comparison.csv`, `policy_trades.csv`, `policy_nav.csv`, `policy_decisions_candidate.csv`, `policy_block_results.csv`, `symbol_contributions.csv`, `independent_ledger_validation.json`, `policy_delta_reconciliation.json`
- صفحهٔ محلی: `client/public/research/return-v12-8.json` روی route قبلی؛ رتبه/preview و پیش‌فرض A/B/C تغییر نکرده‌اند.

## اعتبارسنجی

آزمون‌های V12.8 و مجموعهٔ مرتبط قبلی بدون deselect در گزارش اجرا شدند؛ build آفلاین در صورت موفقیت ثبت می‌شود. مرورگر/دانلود واقعی اجرا نشد. عملکرد تاریخی مستقل نیست.
