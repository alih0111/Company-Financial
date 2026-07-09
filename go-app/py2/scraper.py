from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from codal_ingestor.runner import run_scrape


def main() -> int:
    try:
        if len(sys.argv) != 5:
            raise ValueError(
                "usage: scraper.py <company> <row_limit> <base_url> <pages_json>"
            )
        result = run_scrape(
            report_type="profit-loss",
            company_name=sys.argv[1],
            row_limit=int(sys.argv[2]),
            base_url=sys.argv[3],
            pages=tuple(int(item) for item in json.loads(sys.argv[4])),
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
