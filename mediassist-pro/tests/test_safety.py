"""Unit tests for the clinical rules (no server needed)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.safety import daily_mg, dose_parse, egfr, ingredients, per_day, safety_check  # noqa: E402
from app.m_lab import flag_for  # noqa: E402

DOLO = {"id": 1, "name": "Dolo 650", "generic": "paracetamol", "form": "Tablet", "strength_mg": 650, "max_daily_mg": 4000, "ped_mg_per_kg_day": 60}
CROCIN_SYRUP = {"id": 2, "name": "Crocin Syrup", "generic": "paracetamol", "form": "Syrup", "strength_mg": None, "max_daily_mg": None, "ped_mg_per_kg_day": 60}
ULTRACET = {"id": 3, "name": "Ultracet", "generic": "tramadol paracetamol", "form": "Tablet", "strength_mg": 37.5, "max_daily_mg": 300}
BRUFEN = {"id": 4, "name": "Brufen 400", "generic": "ibuprofen", "form": "Tablet", "strength_mg": 400, "max_daily_mg": 2400, "renal_caution": 1}
METFORMIN = {"id": 5, "name": "Glycomet 500", "generic": "metformin", "form": "Tablet", "strength_mg": 500, "max_daily_mg": 2550, "renal_caution": 1}


class Parsing(unittest.TestCase):
    def test_frequency(self):
        self.assertEqual(per_day("1-0-1"), 2)
        self.assertEqual(per_day("TDS"), 3)
        self.assertEqual(per_day("Q6H"), 4)
        self.assertEqual(per_day("every 8 hours"), 3)
        self.assertEqual(per_day("4 hourly"), 6)
        self.assertEqual(per_day("SOS"), 0)
        self.assertEqual(per_day("twice"), 2)

    def test_dose_units(self):
        self.assertEqual(dose_parse("1"), (1, ""))
        self.assertEqual(dose_parse("1/2"), (0.5, ""))
        self.assertEqual(dose_parse("2 tab"), (2, ""))
        self.assertEqual(dose_parse("500 mg"), (500, "mg"))
        self.assertEqual(dose_parse("1 g"), (1000, "mg"))
        self.assertEqual(dose_parse("5 ml"), (5, "ml"))

    def test_daily_mg(self):
        self.assertEqual(daily_mg(DOLO, "1", "1-1-1"), 1950)
        self.assertEqual(daily_mg(DOLO, "500 mg", "QID"), 2000)  # mg is not multiplied by the strength
        self.assertEqual(daily_mg(CROCIN_SYRUP, "250 mg", "TDS"), 750)
        self.assertIsNone(daily_mg(CROCIN_SYRUP, "5 ml", "TDS"))

    def test_ingredients(self):
        self.assertEqual(ingredients(ULTRACET) & ingredients(DOLO), {"paracetamol"})

    def test_egfr(self):
        self.assertAlmostEqual(egfr(1.2, 70, 40, "F"), 28, delta=1)
        self.assertAlmostEqual(egfr(1.2, 25, 70, "M"), 93, delta=1)
        self.assertIsNone(egfr(1.2, None, 70, "M"))


class Checks(unittest.TestCase):
    def texts(self, *a, **k):
        return " | ".join(w["text"] for w in safety_check(*a, **k))

    def test_adult_max(self):
        self.assertIn("above the usual maximum", self.texts({"age": 40}, [{"med": DOLO, "dose": "2", "freq": "1-1-1-1"}]))
        self.assertNotIn("above", self.texts({"age": 40}, [{"med": DOLO, "dose": "500 mg", "freq": "1-1-1-1"}]))

    def test_child_syrup_in_mg(self):
        child = {"age": 4, "weight": 15}
        self.assertIn("above the child limit", self.texts(child, [{"med": CROCIN_SYRUP, "dose": "400 mg", "freq": "QID"}]))  # 1600 > 900
        self.assertNotIn("above", self.texts(child, [{"med": CROCIN_SYRUP, "dose": "200 mg", "freq": "QID"}]))
        self.assertIn("enter the dose in mg", self.texts(child, [{"med": CROCIN_SYRUP, "dose": "5 ml", "freq": "TDS"}]))

    def test_teenager_uses_weight_limit(self):
        self.assertIn("child limit", self.texts({"age": 13, "weight": 30}, [{"med": DOLO, "dose": "1", "freq": "1-1-1-1"}]))  # 2600 > 1800

    def test_duplicate_through_combination(self):
        self.assertIn("Duplicate", self.texts({"age": 40}, [{"med": ULTRACET, "dose": "1", "freq": "BD"}, {"med": DOLO, "dose": "1", "freq": "BD"}]))

    def test_condition_synonyms(self):
        self.assertIn("kidney", self.texts({"age": 60, "conditions": "renal failure"}, [{"med": BRUFEN, "dose": "1", "freq": "BD"}]))
        self.assertIn("metformin accumulates", self.texts({"age": 60, "conditions": "CKD stage 3"}, [{"med": METFORMIN, "dose": "1", "freq": "BD"}]))
        self.assertIn("heart failure", self.texts({"age": 60, "conditions": "CHF"}, [{"med": BRUFEN, "dose": "1", "freq": "BD"}]))

    def test_renal_uses_clearance(self):
        old_small = {"age": 75, "weight": 42, "gender": "F"}
        self.assertIn("kidney impairment", self.texts(old_small, [{"med": BRUFEN, "dose": "1", "freq": "BD"}], creatinine=1.3))
        young_big = {"age": 25, "weight": 80, "gender": "M"}
        self.assertNotIn("kidney impairment", self.texts(young_big, [{"med": BRUFEN, "dose": "1", "freq": "BD"}], creatinine=1.3))


class LabFlags(unittest.TestCase):
    P = {"ref_text": "Not seen", "low": None, "high": None, "crit_low": None, "crit_high": None}

    def test_text_synonyms(self):
        self.assertEqual(flag_for(self.P, None, "Absent"), "N")
        self.assertEqual(flag_for(self.P, None, "negative"), "N")
        self.assertEqual(flag_for(self.P, None, "Seen"), "A")
        self.assertEqual(flag_for(self.P, None, "Positive"), "A")
        self.assertEqual(flag_for(dict(self.P, ref_text="Negative"), None, "Non-reactive"), "N")


if __name__ == "__main__":
    unittest.main()
