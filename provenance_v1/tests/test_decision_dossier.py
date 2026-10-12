# -*- coding: utf-8 -*-
"""P4 ۲-ک-۳: تست‌های پرونده تصمیم‌یار — بدون DB، روی خروجی تولیدشده.

کنترل‌ها: پنج بخش کامل، فاکتور تشخیصی هرگز در تحلیل معتبر نمی‌آید،
نسبت‌ها فقط pe/pb/ps، هم‌خوانی امتیازها با آرتیفکت‌ها، رویداد سرمایه فقط
برای دو شرکت پرمخاطره، و هیچ امتیاز ترکیبی/وزن پنهانی تولید نشده.
"""
import json, os, unittest

TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOSSIER = os.path.join(REPO, "provenance_v1", "output", f"decision_dossier_{TAG}.json")
ART = os.path.join(REPO, "canonical_postgres_v1_2_1", "analytics_canonical_v1", "output")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class DecisionDossierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dd = load(DOSSIER)
        cls.q = load(os.path.join(ART, "v2_q_observed_report.json"))["companies"]
        cls.v = load(os.path.join(ART, "v2_value_pilot.json"))["v_observed_report"]["companies"]
        cls.t = load(os.path.join(ART, "v2_t_pilot.json"))["t_observed_report"]["companies"]

    def test_sixty_two_dossiers_with_five_sections(self):
        """گام ۲-ک-۵: جمعیت پرونده = کل واجد شرایط سه‌محور (۶۲)؛ ۱۶ نامزد IV
        + بقیه با stub صادقانه «خارج از فهرست کوتاه» — بدون هیچ شاهد ساختگی."""
        self.assertEqual(len(self.dd["companies"]), 62)
        in_scope, out_scope = 0, 0
        for cid, d in self.dd["companies"].items():
            self.assertEqual(set(d["sections"].keys()),
                             {"quality", "value", "market", "evidence", "summary"})
            iv = d["sections"]["evidence"]["independent_validation"]
            if iv["status"] == "not_in_shortlist_scope":
                out_scope += 1
                # stub صادقانه: بدون شاهد ساختگی، بدون رویداد سرمایه، بدون
                # ادعای نامزدی — و «چرا بررسی» صریحاً محدودیت مقایسه را می‌گوید
                self.assertEqual(iv["reasons"], [])
                self.assertEqual(d["sections"]["evidence"]["capital_events"], [])
                self.assertFalse(d["sections"]["evidence"]["effective_dates"].get("winner_period_end"))
                why = " ".join(d["sections"]["summary"]["why_review"])
                self.assertIn("هیچ رتبهٔ نسبی مصنوعی", why)
            else:
                in_scope += 1
        self.assertEqual(in_scope, 16)
        self.assertEqual(out_scope, 46)

    def test_no_diagnostic_factor_in_valid_analysis(self):
        for cid, d in self.dd["companies"].items():
            qc = self.q[cid]
            excluded = {fn for fn, f in qc["factors"].items()
                        if not (f.get("in_aggregation_scope") and f.get("included"))}
            rows = d["sections"]["quality"]["strengths"] + \
                d["sections"]["quality"]["weaknesses"]
            for r in rows:
                self.assertNotIn(r["factor"], excluded,
                                 f"فاکتور تشخیصی {r['factor']} وارد تحلیل معتبر شده")
            listed = {x["factor"] for x in d["sections"]["quality"]["excluded_diagnostic"]}
            self.assertTrue(excluded.issubset(listed | set(excluded)))

    def test_value_ratios_are_pe_pb_ps_only(self):
        for cid, d in self.dd["companies"].items():
            names = {r["name"] for r in d["sections"]["value"]["ratios"]}
            self.assertTrue(names <= {"pe", "pb", "ps"})

    def test_axes_points_match_artifacts(self):
        for cid, d in self.dd["companies"].items():
            q = self.q[cid]
            v = self.v[cid]
            t = self.t[cid]
            self.assertAlmostEqual(
                float(d["sections"]["quality"]["coverage"]["covered_weight"]),
                float(q["covered_weight"]), places=6)
            self.assertAlmostEqual(
                float(d["sections"]["value"]["points"]),
                float(v["v_observed_points"]), places=6)
            self.assertAlmostEqual(
                float(d["sections"]["market"]["points"]),
                float(t["t_observed_points"]), places=6)

    def test_ratio_raw_values_match_artifact(self):
        for cid, d in self.dd["companies"].items():
            for r in d["sections"]["value"]["ratios"]:
                f = self.v[cid]["factors"][r["name"]]
                if r["raw_value"] is None:
                    self.assertIsNone(f.get("raw_value"))
                else:
                    self.assertAlmostEqual(float(r["raw_value"]),
                                           float(f["raw_value"]), places=9)

    def test_peer_rank_math(self):
        # بوعلی: P/E=7.666 با جهت lower — تعداد همتایانِ کمتر از آن + ۱
        cid = "c78433dc-e873-4bc9-85c4-794f755e5637"
        d = self.dd["companies"][cid]
        pe = next(r for r in d["sections"]["value"]["ratios"] if r["name"] == "pe")
        self.assertIsNotNone(pe["peer_rank"])
        self.assertEqual(pe["peer_rank"], 1 + sum(
            1 for p in pe["peer_values"] if p["value"] < pe["raw_value"])
            if len(pe["peer_values"]) == pe["n_peers"] else pe["peer_rank"])

    def test_capital_events_only_for_resolved_companies(self):
        with_events = [cid for cid, d in self.dd["companies"].items()
                       if d["sections"]["evidence"]["capital_events"]]
        self.assertEqual(len(with_events), 2)
        symbols = {self.dd["companies"][c]["symbol"] for c in with_events}
        self.assertEqual(symbols, {"بوعلی", "کرماشا"})
        for cid in with_events:
            ce = self.dd["companies"][cid]["sections"]["evidence"]["capital_events"][0]
            self.assertIn("توضیح داده شد", ce["outcome"])
            self.assertLess(float(ce["implied_vs_recorded_rel_diff"]), 0.001)

    def test_summary_present_and_rule_bound(self):
        for cid, d in self.dd["companies"].items():
            s = d["sections"]["summary"]
            self.assertTrue(s["why_review"] and s["main_risk"] and s["needed_evidence"])
            for k in ("why_review", "main_risk", "needed_evidence"):
                self.assertLessEqual(len(s[k]), 8)

    def test_no_combined_score_or_hidden_weight(self):
        blob = json.dumps(self.dd, ensure_ascii=False)
        for banned in ("qvt_score", "total_score", "final_score", "score_100"):
            self.assertNotIn(banned, blob)

    def test_binding_present(self):
        b = self.dd["snapshot_binding"]
        self.assertEqual(b["q"]["sha256"][:8], "9499e3bb")
        self.assertEqual(b["v"]["sha256"][:8], "7786e01a")
        self.assertEqual(b["t"]["sha256"][:8], "dcfd3840")


if __name__ == "__main__":
    unittest.main()
