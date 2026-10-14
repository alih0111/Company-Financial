"""One bounded public probe of a missing report, metadata only, no bypass."""
import json
import re
import urllib.parse
import urllib.request
import collect_financial_history as H

def main():
    catalog = H.C.read(H.OUT / "catalog_versions.json")
    for row in catalog:
        letter = row["letter"]
        path = H.OUT / "reports" / (row["company_id"] + "_" + str(letter["TracingNo"]) + ".json")
        if path.exists():
            continue
        url = letter.get("ExcelUrl")
        if not url:
            serial = urllib.parse.parse_qs(urllib.parse.urlsplit(letter.get("Url", "")).query).get("LetterSerial", [None])[0]
            if not serial:
                continue
            url = "https://excel.codal.ir/service/Excel/GetAll/" + urllib.parse.quote(serial, safe="") + "/0"
        result = {"symbol": row["symbol"], "tracing_no": str(letter["TracingNo"])}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.codal.ir/"})
            with urllib.request.urlopen(req, timeout=10) as response:
                body = response.read()
                text = body.decode("utf8", "replace")
                result.update({"http_status": response.status, "content_type": response.headers.get("Content-Type"),
                               "bytes": len(body), "zip_format": body.startswith(b"PK"), "legacy_excel_format": body.startswith(bytes.fromhex("D0CF11E0")),
                               "has_table": "<table" in text.lower(), "has_captcha": "captcha" in text.lower(),
                               "text_preview": re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", text))[:220],
                               "contains_server_error": any(x in text.lower() for x in ("internal server error", "not found", "access denied"))})
        except Exception as exc:
            result["error"] = str(exc)
        H.C.write(H.OUT / "missing_report_probe.json", result)
        print(json.dumps(result, ensure_ascii=False))
        break

if __name__ == "__main__":
    main()
