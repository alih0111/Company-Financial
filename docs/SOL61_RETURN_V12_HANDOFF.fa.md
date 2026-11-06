# تحویل V12

Run id: `v12_20261018T183000Z`.

## بازتولید

از ریشهٔ مخزن با محیط `.venv`:

```powershell
.venv/Scripts/python.exe -B -m ranking_research.return_v12.run audit
.venv/Scripts/python.exe -B -m ranking_research.return_v12.run diagnose-v11
.venv/Scripts/python.exe -B -m ranking_research.return_v12.run register
.venv/Scripts/python.exe -B -m ranking_research.return_v12.run search-weights --resume
.venv/Scripts/python.exe -B -m ranking_research.return_v12.run search-policy --resume
.venv/Scripts/python.exe -B -m ranking_research.return_v12.run validate
.venv/Scripts/python.exe -B -m ranking_research.return_v12.run finalize
cd client; npm run build
```

خروجی‌ها در `ranking_research/output/return_v12/v12_20261018T183000Z/` هستند. `--resume` فقط با hashهای یکسان ورودی/کد/registry مجاز است. هیچ سفارش واقعی ارسال نشده است.
