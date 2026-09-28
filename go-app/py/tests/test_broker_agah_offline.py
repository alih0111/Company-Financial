# -*- coding: utf-8 -*-
"""تست آفلاین پارسرهای broker_agah (بدون مرورگر/شبکه).

ساختار fixtureها عین پاسخ‌های واقعی پنل آگاه است
(agah-dump/resp_024.json پرتفو و resp_009.json مانده)."""

from __future__ import annotations

import os
import sys
import unittest

GO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if GO not in sys.path:
    sys.path.insert(0, GO)

import broker_agah  # noqa: E402


PORTFOLIO = {
    "isSuccess": True,
    "message": "عملیات با موفقیت انجام شد",
    "errorCode": -1,
    "data": {
        "data": [
            {
                "securityId": 1757,
                "securityTitle": "کاسپین",
                "securityIsin": "IRO3KSPZ0006",
                "instrumentNscid": "IRO3KSPZ0001",
                "companyName": "داروسازی کاسپین تامین",
                "numberOfShares": 40764,
                "averageBuyPrice": 8895.84432,
                "calculatedAverageBuyPrice": 8928.15371,
                "calculatedHeadLinePrice": 9008,
                "calculatedTodayPrice": 37810,
                "calculatedAssetCost": 363947257.83444,
                "calculatedTodayCost": 1527723516,
                "calculatedGain": 1163776258.16556,
                "calculatedGainPercent": 319.7650849490946,
                "sectorTitle": "مواد و محصولات دارویی",
                "instrumentStateTitle": "مجاز",
                "isSecurityActive": True,
            },
            {
                "securityTitle": "رهیاب",
                "securityIsin": "IRO5RHYB0007",
                "instrumentNscid": "IRO5RHYB0001",
                "companyName": "رهیاب پیام گستران",
                "numberOfShares": 92,
                "averageBuyPrice": 7392.0,
                "calculatedAverageBuyPrice": 7418.81522,
                "calculatedHeadLinePrice": 7485,
                "calculatedTodayPrice": 6190,
                "calculatedAssetCost": 682531.00024,
                "calculatedTodayCost": 569480,
                "calculatedGain": -118062.00024,
                "calculatedGainPercent": -17.297675856481245,
                "sectorTitle": "اطلاعات و ارتباطات",
                "instrumentStateTitle": "ممنوع-متوقف",
                "isSecurityActive": True,
            },
        ],
        "assetSummary": {
            "numberOfShares": 40856,
            "calculatedAssetCost": 364629788.83468,
            "calculatedTodayCost": 1528292996,
            "calculatedGain": 1163658196.16532,
        },
        "totalCount": 2,
    },
    "problemDetail": None,
}

BALANCE = {
    "isSuccess": True,
    "message": "عملیات با موفقیت انجام شد",
    "errorCode": -1,
    "data": {
        "lastBalance": 77148,
        "adjustedBalanceT2": 77148,
        "tradableBalanceT1": 77148,
        "tradableBalanceT2": 77148,
        "payableBalanceWithAgahCreditT0": 0,
        "payableBalanceWithAgahCreditT1": 77148,
        "payableBalanceWithAgahCreditT2": 77148,
        "payableBalanceWithoutAgahCreditT0": 0,
        "block": 0,
        "credit": 0,
        "settlementDateT0": "2026-09-28T00:00:00+03:30",
    },
    "problemDetail": None,
}


class PortfolioApiTests(unittest.TestCase):
    def test_exact_fields(self):
        holdings, summary = broker_agah.extract_agah_portfolio([PORTFOLIO])
        self.assertEqual(len(holdings), 2)

        h = holdings[0]
        self.assertEqual(h["symbol"], "کاسپین")
        self.assertEqual(h["name"], "داروسازی کاسپین تامین")
        self.assertEqual(h["isin"], "IRO3KSPZ0006")
        self.assertEqual(h["nscid"], "IRO3KSPZ0001")
        self.assertEqual(h["quantity"], 40764)
        self.assertAlmostEqual(h["avg_buy_price"], 8895.84432)
        self.assertEqual(h["last_price"], 37810)
        self.assertAlmostEqual(h["cost_basis"], 363947257.83444)
        self.assertEqual(h["market_value"], 1527723516)
        self.assertAlmostEqual(h["gain"], 1163776258.16556)
        self.assertAlmostEqual(h["gain_percent"], 319.7650849490946)
        self.assertEqual(h["sector"], "مواد و محصولات دارویی")
        self.assertEqual(h["state"], "مجاز")
        self.assertTrue(h["is_active"])

        # نماد باید securityTitle باشد، نه companyName (رگرسیون قبلی)
        self.assertNotEqual(h["symbol"], h["name"])

    def test_negative_gain_supported(self):
        holdings, _ = broker_agah.extract_agah_portfolio([PORTFOLIO])
        self.assertAlmostEqual(holdings[1]["gain"], -118062.00024)
        self.assertLess(holdings[1]["gain_percent"], 0)

    def test_summary_returned(self):
        _, summary = broker_agah.extract_agah_portfolio([PORTFOLIO])
        self.assertIsInstance(summary, dict)
        self.assertAlmostEqual(summary["calculatedAssetCost"], 364629788.83468)

    def test_ignores_non_portfolio_payloads(self):
        holdings, summary = broker_agah.extract_agah_portfolio([BALANCE, {"data": []}, {"data": {"data": []}}])
        self.assertEqual(holdings, [])
        self.assertIsNone(summary)

    def test_zero_quantity_rows_skipped(self):
        obj = {
            "data": {
                "data": [dict(PORTFOLIO["data"]["data"][0], numberOfShares=0)],
                "totalCount": 1,
            }
        }
        holdings, _ = broker_agah.extract_agah_portfolio([obj])
        self.assertEqual(holdings, [])


class BalanceApiTests(unittest.TestCase):
    def test_exact_fields(self):
        bal = broker_agah.extract_agah_balance([BALANCE])
        self.assertIsNotNone(bal)
        self.assertEqual(bal["last_balance"], 77148)
        self.assertEqual(bal["tradable_t1"], 77148)
        self.assertEqual(bal["tradable_t2"], 77148)
        self.assertEqual(bal["payable_without_credit_t0"], 0)
        self.assertEqual(bal["credit"], 0)
        self.assertEqual(bal["block"], 0)

    def test_ignores_non_balance_payloads(self):
        self.assertIsNone(broker_agah.extract_agah_balance([PORTFOLIO, {"data": {"x": 1}}]))


class FuzzyFallbackTests(unittest.TestCase):
    def test_generic_json_still_parsed(self):
        payload = {"items": [{"ticker": "فولاد", "qty": "۱,۲۳۴", "averageprice": "900"}]}
        rows = broker_agah.parse_json_payloads([payload])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "فولاد")
        self.assertEqual(rows[0]["quantity"], 1234)
        self.assertAlmostEqual(rows[0]["avg_buy_price"], 900)

    def test_to_float_persian_and_units(self):
        self.assertEqual(broker_agah.to_float("۱۲٬۳۴۵ ریال"), 12345)
        self.assertAlmostEqual(broker_agah.to_float("8928.15371"), 8928.15371)
        self.assertIsNone(broker_agah.to_float("بدون عدد"))


if __name__ == "__main__":
    unittest.main()
