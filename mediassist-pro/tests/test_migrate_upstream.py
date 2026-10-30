"""A database created by the upstream code (migrations 6-9 = rooms, certificates, lab ranges, daily charges) must come
through the merged migration list without errors and end with every column from both histories."""
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import schema  # noqa: E402

UPSTREAM_6_TO_9 = [schema.MIGRATIONS[15], schema.MIGRATIONS[16], schema.MIGRATIONS[17], schema.MIGRATIONS[18]]


class UpstreamNumbering(unittest.TestCase):
    def test_reconciles_both_histories(self):
        d = tempfile.mkdtemp()
        c = sqlite3.connect(os.path.join(d, "u.db"))
        c.execute("CREATE TABLE schema_version(v INTEGER NOT NULL)")
        c.execute("INSERT INTO schema_version VALUES(0)")
        # replay history as the upstream server did: common 1-5, then its own 6-9 (the clinician column under its old name)
        for i, sql in enumerate(schema.MIGRATIONS[:5] + [s.replace("clin_interpretation", "interpretation") for s in UPSTREAM_6_TO_9], start=1):
            for stmt in [s for s in sql.split(";\n") if s.strip()]:
                c.execute(stmt)
            c.execute("UPDATE schema_version SET v=?", (i,))
        c.commit()
        self.assertEqual(c.execute("SELECT v FROM schema_version").fetchone()[0], 9)
        self.assertTrue(schema.has_column(c, "beds", "room") and not schema.has_column(c, "users", "last_totp"))
        c.isolation_level = None
        self.assertEqual(schema.migrate(c), len(schema.MIGRATIONS))
        self.assertEqual(c.execute("SELECT v FROM schema_version").fetchone()[0], len(schema.MIGRATIONS))
        for table, col in (("users", "last_totp"), ("beds", "room"), ("beds", "status_at"), ("lab_orders", "interp_source"), ("lab_orders", "clin_interpretation"),
                           ("lab_orders", "interpretation"), ("branches", "upi_id"), ("admissions", "vitals_every_h"), ("patients", "abha_address")):
            self.assertTrue(schema.has_column(c, table, col), f"{table}.{col}")
        for t in ("certificates", "lab_ranges", "adm_daily", "referrals", "dental_chart", "io_chart", "growth_ref"):
            self.assertTrue(c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone(), t)
        # running again is a no-op
        self.assertEqual(schema.migrate(c), len(schema.MIGRATIONS))

    def test_fresh_database(self):
        d = tempfile.mkdtemp()
        c = sqlite3.connect(os.path.join(d, "f.db"))
        c.isolation_level = None
        self.assertEqual(schema.migrate(c), len(schema.MIGRATIONS))
        self.assertTrue(schema.has_column(c, "lab_orders", "clin_interpretation"))


if __name__ == "__main__":
    unittest.main()
