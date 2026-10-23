"""End-to-end API tests. Run:  python -m unittest discover -s tests -v
Starts a server on a temporary database with demo data and exercises every module."""
import base64
import http.cookiejar
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="mediassist-test-")
os.environ["MEDIASSIST_DATA"] = TMP
os.environ["MEDIASSIST_DB"] = os.path.join(TMP, "test.db")
sys.path.insert(0, ROOT)

import server  # noqa: E402
from app import core  # noqa: E402
from app.setup import init  # noqa: E402

PORT = 8799
PW = None
SRV = None


def setUpModule():
    global PW, SRV
    PW = init(demo=True, quiet=True)
    try:
        os.remove(os.path.join(ROOT, "FIRST-LOGIN.txt"))
    except OSError:
        pass
    core.reset_conn()
    SRV = server.ThreadingHTTPServer(("127.0.0.1", PORT), server.Handler)
    threading.Thread(target=SRV.serve_forever, daemon=True).start()


def tearDownModule():
    SRV.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)


class Client:
    def __init__(self, username=None):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        if username:
            st, r = self.post("/api/login", {"username": username, "password": PW})
            assert st == 200, r

    def call(self, path, body=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with self.op.open(req) as r:
                data = r.read()
                ct = r.headers.get("Content-Type", "")
                return r.status, (json.loads(data) if "json" in ct and data[:1] in b"[{n" else data)
        except urllib.error.HTTPError as e:
            data = e.read()
            return e.code, json.loads(data) if data[:1] == b"{" else data

    def get(self, path):
        return self.call(path)

    def post(self, path, body, headers=None):
        return self.call(path, body, headers)

    def ok(self, path, body=None):
        st, r = self.call(path, body)
        assert st == 200, f"{path} -> {st} {r}"
        return r

    def branch(self, bid):
        self.ok("/api/branch", {"branch_id": bid})


class T01Auth(unittest.TestCase):
    def test_login_lockout_and_2fa(self):
        c = Client()
        for _ in range(5):
            st, _ = c.post("/api/login", {"username": "reception.ch", "password": "wrong"})
            self.assertEqual(st, 401)
        st, r = c.post("/api/login", {"username": "reception.ch", "password": PW})
        self.assertEqual(st, 429, "locked after 5 failures")
        core.db().execute("UPDATE users SET locked_until=0 WHERE username='reception.ch'")
        core.reset_conn()
        own = Client("owner")
        setup = own.ok("/api/2fa/setup", {})
        own.ok("/api/2fa/enable", {"code": core.totp(setup["secret"])})
        c2 = Client()
        st, r = c2.post("/api/login", {"username": "owner", "password": PW})
        self.assertTrue(r["mfa_required"])
        self.assertEqual(c2.get("/api/patients")[0], 401)
        self.assertEqual(c2.post("/api/2fa/verify", {"code": "000000"})[0], 401)
        c2.ok("/api/2fa/verify", {"code": core.totp(setup["secret"])})
        self.assertEqual(c2.get("/api/patients")[0], 200)
        c2.ok("/api/2fa/disable", {"code": core.totp(setup["secret"])})

    def test_roles_and_csrf(self):
        ph = Client("pharma.ms")
        self.assertEqual(ph.post("/api/visits", {"patient_id": 1})[0], 403)
        self.assertEqual(ph.post("/api/branch", {"branch_id": 1})[0], 403)
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/patients", data=b"name=x", headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            ph.op.open(req)
        self.assertEqual(e.exception.code, 415)


class T02Clinical(unittest.TestCase):
    def test_register_consult_safety(self):
        rec = Client("reception.ch")
        st, r = rec.post("/api/patients", {"name": "Kiran", "phone": "9123456780", "age": 40})
        self.assertEqual(st, 400, "consent required")
        r = rec.ok("/api/patients", {"name": "Kiran", "phone": "9123456780", "age": 40, "gender": "Male", "allergies": "penicillin", "conditions": "asthma",
                                      "weight": 70, "consent": True})
        pid = r["id"]
        self.assertEqual(rec.post("/api/patients", {"name": "K", "phone": "9123456780", "consent": True})[0], 409)
        self.assertEqual(rec.post("/api/patients", {"name": "X", "phone": "9123456781", "abha": "123", "consent": True})[0], 400, "ABHA must be 14 digits")
        v = rec.ok("/api/visits", {"patient_id": pid, "complaint": "severe breathless", "spo2": 89, "pulse": 125})
        self.assertEqual(v["triage"], "critical")
        doc = Client("dr.rao")
        meds = {m["name"]: m for m in doc.ok("/api/medicines")}
        items = [{"medicine_id": meds["Amoxyclav 625"]["id"], "freq": "1-0-1", "days": 5}, {"medicine_id": meds["Brufen 400"]["id"], "freq": "1-1-1", "days": 3}]
        st, r = doc.post(f"/api/visits/{v['id']}/complete", {"diagnosis": "LRTI", "icd": "J20.9", "items": items})
        self.assertEqual(st, 409)
        texts = " ".join(w["text"] for w in r["warnings"])
        self.assertIn("allergic to penicillin", texts)
        self.assertIn("asthma", texts)
        dose = doc.ok("/api/rx/check", {"patient_id": pid, "items": [{"medicine_id": meds["Dolo 650"]["id"], "freq": "2-2-2-2", "dose": "1"}]})
        self.assertTrue(any("above the usual maximum" in w["text"] for w in dose["warnings"]), dose)
        tests = {t["code"]: t["id"] for t in doc.ok("/api/lab/tests")}
        r = doc.ok(f"/api/visits/{v['id']}/complete", {"diagnosis": "LRTI", "icd": "J20.9", "add_problem": True, "followup": core.add_days(core.today(), 5),
                                                      "items": [{"medicine_id": meds["Azithral 500"]["id"], "freq": "OD", "days": 3},
                                                                {"medicine_id": meds["Dolo 650"]["id"], "freq": "SOS", "days": 3, "qty": 6}],
                                                      "lab_tests": [tests["CBC"], tests["CRP"]]})
        self.assertTrue(r["lab_order_id"])
        prof = doc.ok(f"/api/patients/{pid}")
        self.assertEqual(prof["problems"][0]["icd"], "J20.9")
        self.assertEqual(len(prof["labs"]), 1)
        type(self).pid, type(self).vid, type(self).order = pid, v["id"], r["lab_order_id"]

    def test_child_dose_and_pregnancy(self):
        doc = Client("dr.rao")
        meds = {m["name"]: m for m in doc.ok("/api/medicines")}
        r = doc.ok("/api/rx/check", {"patient_id": 6, "items": [{"medicine_id": meds["Dolo 650"]["id"], "freq": "1-1-1", "dose": "1"},
                                                                {"medicine_id": meds["Ecosprin 75"]["id"], "freq": "OD"}]})
        t = " ".join(w["text"] for w in r["warnings"])
        self.assertIn("above the child limit", t)
        self.assertIn("Reye", t)
        r = doc.ok("/api/rx/check", {"patient_id": 2, "items": [{"medicine_id": meds["Telma 40"]["id"], "freq": "OD"}]})
        self.assertTrue(any("pregnancy" in w["text"] for w in r["warnings"]))
        prof = doc.ok("/api/patients/2")
        self.assertEqual(prof["pregnancy"]["trimester"], 2)


class T03Lab(unittest.TestCase):
    def test_lab_flow(self):
        if not hasattr(T02Clinical, "order"):
            T02Clinical("test_register_consult_safety").test_register_consult_safety()
        lab = Client("lab.ch")
        oid = T02Clinical.order
        st, _ = lab.post(f"/api/lab/orders/{oid}/results", {"values": {}})
        self.assertEqual(st, 400, "must collect first")
        lab.ok(f"/api/lab/orders/{oid}/collect", {})
        o = lab.ok(f"/api/lab/orders/{oid}")
        vals = {}
        for t in o["tests"]:
            for p in t["params"]:
                vals[f"{t['item_id']}:{p['id']}"] = {"Haemoglobin": "6.1", "Total WBC": "14", "CRP": "48"}.get(p["name"], "50")
        r = lab.ok(f"/api/lab/orders/{oid}/results", {"values": vals, "submit": True})
        self.assertTrue(r["critical"])
        o = lab.ok(f"/api/lab/orders/{oid}")
        flags = {p["name"]: p["flag"] for t in o["tests"] for p in t["params"]}
        self.assertEqual(flags["Haemoglobin"], "LL")
        self.assertEqual(flags["Total WBC"], "H")
        self.assertEqual(lab.post(f"/api/lab/orders/{oid}/verify", {})[0], 403, "lab tech can't verify")
        doc = Client("dr.rao")
        doc.ok(f"/api/lab/orders/{oid}/verify", {})
        self.assertEqual(doc.ok(f"/api/lab/orders/{oid}")["status"], "verified")
        alerts = doc.ok("/api/alerts")
        self.assertTrue(any("CRITICAL" in a["body"] for a in alerts))


class T04Appointments(unittest.TestCase):
    def test_booking_checkin_tokens(self):
        rec = Client("reception.ch")
        day = core.add_days(core.today(), 1)
        slots = rec.ok(f"/api/appointments/slots?doctor_id=2&day={day}")
        self.assertTrue(slots)
        a = rec.ok("/api/appointments", {"patient_id": 4, "doctor_id": 2, "day": day, "slot": slots[0]})
        self.assertEqual(rec.post("/api/appointments", {"patient_id": 3, "doctor_id": 2, "day": day, "slot": slots[0]})[0], 400, "slot taken")
        self.assertNotIn(slots[0], rec.ok(f"/api/appointments/slots?doctor_id=2&day={day}"))
        self.assertEqual(rec.post(f"/api/appointments/{a['id']}/checkin", {})[0], 400, "not today")
        today_appt = [x for x in rec.ok("/api/appointments") if x["status"] == "booked"][0]
        r = rec.ok(f"/api/appointments/{today_appt['id']}/checkin", {"temp": 37})
        doc = Client("dr.rao")
        doc.ok(f"/api/visits/{r['visit_id']}/start", {})
        pub = Client()
        tok = pub.ok("/api/public/tokens?branch=CH")
        self.assertEqual(tok["doctors"][0]["now"], today_appt["token"])
        self.assertNotIn("pname", json.dumps(tok))
        info = pub.ok(f"/api/public/booking?branch=CH&doctor_id=2&day={day}")
        b = pub.ok("/api/public/book", {"branch": "CH", "name": "Online Person", "phone": "9000011111", "consent": True, "doctor_id": 2, "day": day, "slot": info["slots"][0]})
        self.assertTrue(b["token"])
        from app.m_appointments import send_reminders
        n = send_reminders(core.db())
        core.reset_conn()
        self.assertGreaterEqual(n, 2)


class T05Pharmacy(unittest.TestCase):
    def test_strip_sale_rx_offline_and_returns(self):
        if not hasattr(T02Clinical, "pid"):
            T02Clinical("test_register_consult_safety").test_register_consult_safety()
        ph = Client("pharma.ch")
        pend = ph.ok(f"/api/rx/pending?patient_id={T02Clinical.pid}")[0]
        lines = [{"medicine_id": i["medicine_id"], "qty": i["remaining"], "rx_item_id": i["id"]} for i in pend["items"]]
        st, r = ph.post("/api/bills", {"patient_id": T02Clinical.pid, "visit_id": pend["visit_id"], "items": lines, "pay_mode": "upi"})
        if st == 409:
            r = ph.ok("/api/bills", {"patient_id": T02Clinical.pid, "visit_id": pend["visit_id"], "items": lines, "pay_mode": "upi", "override": True})
        elif st != 200:
            self.skipTest(f"stock-dependent: {r}")
        bill = ph.ok(f"/api/bills/{r['id']}")
        self.assertAlmostEqual(sum(i["net"] for i in bill["items"]), bill["total"], places=2)
        meds = {m["name"]: m for m in ph.ok("/api/medicines")}
        pan = meds["Pan 40"]
        before = pan["stock"]
        key = "offline-test-1"
        body = {"customer": "Walk", "doctor_name": "Dr Out", "doctor_reg": "TSMC-1", "items": [{"medicine_id": pan["id"], "qty": 1, "unit": "strip"}], "offline_key": key}
        b1 = ph.ok("/api/bills", body)
        b2 = ph.ok("/api/bills", body)
        self.assertEqual(b1["id"], b2["id"], "offline replay must not double-bill")
        after = {m["name"]: m for m in ph.ok("/api/medicines")}["Pan 40"]["stock"]
        self.assertEqual(before - after, pan["pack_size"], "one strip = pack size")
        ret = ph.ok(f"/api/bills/{b1['id']}/return", {"items": [{"bill_item_id": ph.ok(f"/api/bills/{b1['id']}")["items"][0]["id"], "qty": 2}], "reason": "extra"})
        self.assertTrue(ret["credit_note"].startswith("CH/CN/"))
        st, r = ph.post("/api/bills", {"customer": "x", "items": [{"medicine_id": meds["Azithral 500"]["id"], "qty": 3}]})
        self.assertIn("Schedule H", r["error"])
        look = ph.ok("/api/stock/lookup?barcode=8901234500073")
        self.assertEqual(look["medicine"]["name"], "Pan 40")
        self.assertTrue(look["batches"][0]["rack"])

    def test_po_grn_returns_cold_chain_count(self):
        mgr = Client("manager.ch")
        st = mgr.ok("/api/stock")
        self.assertTrue(st["reorder"])
        sug = st["reorder"][0]
        po = mgr.ok("/api/purchase-orders", {"supplier_id": 1, "items": [{"medicine_id": sug["medicine_id"], "qty": sug["order"]}], "send": True})
        g = mgr.ok("/api/purchases", {"supplier_id": 1, "po_id": po["id"], "invoice_no": "INV-77",
                                      "lines": [{"medicine_id": sug["medicine_id"], "batch": "NEW77", "expiry": core.add_days(core.today(), 400), "qty": sug["order"], "cost": 2, "mrp": 3}]})
        self.assertTrue(g["id"])
        self.assertEqual([p for p in mgr.ok("/api/purchase-orders") if p["id"] == po["id"]][0]["status"], "received")
        self.assertEqual(mgr.post("/api/purchases", {"lines": [{"medicine_id": 1, "expiry": "2020-01-01", "qty": 1, "cost": 1, "mrp": 2}]})[0], 400)
        exp = [b for b in mgr.ok("/api/stock")["batches"] if b["days_left"] < 0][0]
        sr = mgr.ok("/api/supplier-returns", {"supplier_id": 1, "reason": "expired", "items": [{"batch_id": exp["id"], "qty": exp["qty"]}]})
        mgr.ok(f"/api/supplier-returns/{sr['id']}/credit", {"credit_note_no": "CN-555"})
        t = mgr.ok("/api/temp-logs", {"temp_c": 11})
        self.assertFalse(t["in_range"])
        self.assertEqual(mgr.ok("/api/temp-logs")["excursions"][0]["temp_c"], 11)
        for path in ("/api/supplier-returns", "/api/purchase-orders", "/api/stock-counts", "/api/suppliers", "/api/beds", "/api/claims", "/api/closing",
                     "/api/expenses", "/api/feedback", "/api/messages", "/api/analytics", "/api/audit", "/api/errors", "/api/backups", "/api/settings", "/api/users"):
            st, r = Client("owner").get(path) if path in ("/api/expenses", "/api/feedback", "/api/messages", "/api/analytics", "/api/audit", "/api/errors", "/api/backups", "/api/settings", "/api/users") else mgr.get(path)
            self.assertNotEqual(st, 500, path)
        cnt = mgr.ok("/api/stock-counts", {"rack": "A1"})
        items = mgr.ok("/api/stock-counts")[0]["items"]
        self.assertTrue(items)
        r = mgr.ok(f"/api/stock-counts/{cnt['id']}", {"items": [{"id": items[0]["id"], "counted": max(0, items[0]["system_qty"] - 3)}], "close": True})
        self.assertEqual(r["adjusted"], 1)

    def test_edit_stock_and_stock_photo(self):
        ph = Client("pharma.ch")
        d = ph.ok("/api/stock/edit")
        m = [x for x in d["medicines"] if x["batches"] and x["pack_size"] > 1][0]
        bt = m["batches"][0]
        r = ph.ok("/api/stock/update", {"reason": "count", "lines": [{"batch_id": bt["id"], "unit": "unit", "qty": 7, "rack": "z9-1", "mrp": bt["mrp"] + 1, "batch": bt["batch"]}]})
        self.assertEqual(r["changed"], 1)
        nb = [x for x in ph.ok("/api/stock/edit")["medicines"] if x["id"] == m["id"]][0]["batches"]
        nb = [x for x in nb if x["id"] == bt["id"]][0]
        self.assertEqual((nb["qty"], nb["rack"], nb["mrp"]), (7, "Z9-1", bt["mrp"] + 1))
        mv = core.db().execute("SELECT change, reason FROM stock_moves WHERE batch_id=? ORDER BY id DESC LIMIT 1", (bt["id"],)).fetchone()
        self.assertEqual((mv[0], mv[1]), (7 - bt["qty"], "adjust:count"))
        # photo of a shelf: kept as a stock photo, then a new batch added in strips with cost copied from the last batch
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()
        doc = ph.ok("/api/documents", {"doc_type": "stock", "medicine_id": m["id"], "mime": "image/png", "data": png, "note": "rack A1"})
        r = ph.ok("/api/stock/update", {"reason": "photo", "doc_id": doc["id"], "lines": [{"medicine_id": m["id"], "batch": "PH1", "expiry": core.add_days(core.today(), 300), "qty": 2, "unit": "pack", "mrp": round(m["last"]["mrp"] * m["pack_size"] + 1, 2)}]})
        self.assertEqual(r["added"], 1)
        nb = [x for x in ph.ok("/api/stock/edit")["medicines"] if x["id"] == m["id"]][0]["batches"]
        self.assertEqual([x["qty"] for x in nb if x["batch"] == "PH1"], [2 * m["pack_size"]])
        self.assertEqual(ph.ok("/api/documents?type=stock")["rows"][0]["id"], doc["id"])
        # refused: expired batch, unknown reason, a role without stock rights
        self.assertEqual(ph.post("/api/stock/update", {"reason": "count", "lines": [{"medicine_id": m["id"], "expiry": "2020-01-01", "qty": 1, "mrp": 5}]})[0], 400)
        self.assertEqual(ph.post("/api/stock/update", {"reason": "because", "lines": [{"batch_id": bt["id"], "qty": 1}]})[0], 400)
        self.assertEqual(Client("reception.ch").post("/api/stock/update", {"reason": "count", "lines": [{"batch_id": bt["id"], "qty": 1}]})[0], 403)
        # matching for the in-browser reader happens on our side
        mt = ph.ok("/api/ai/match", {"items": [{"medicine": m["name"].upper(), "qty": 1}]})
        self.assertEqual(mt["items"][0]["medicine_id"], m["id"])
        self.assertIsNone(ph.ok("/api/ai/match", {"items": [{"medicine": "Unknownol 10"}]})["items"][0]["medicine_id"])


class T06IpdBilling(unittest.TestCase):
    def test_admit_mar_discharge_claim(self):
        rec = Client("reception.ch")
        beds = [b for b in rec.ok("/api/beds") if b["status"] == "free" and b["kind"] == "private"]
        doc = Client("dr.rao")
        a = doc.ok("/api/admissions", {"patient_id": 7, "bed_id": beds[0]["id"], "reason": "Dengue", "diagnosis": "Dengue fever", "icd": "A90", "deposit": 5000})
        meds = {m["name"]: m for m in doc.ok("/api/medicines")}
        doc.ok(f"/api/admissions/{a['id']}/mar", {"medicine_id": meds["Dolo 650"]["id"], "dose": "1", "freq": "TDS"})
        nurse = Client("nurse.ch")
        adm = nurse.ok(f"/api/admissions/{a['id']}")
        mo = adm["mar"][0]
        nurse.ok(f"/api/mar/{mo['id']}/give", {"due": mo["slots"][0]["due"]})
        self.assertEqual(nurse.post(f"/api/mar/{mo['id']}/give", {"due": mo["slots"][0]["due"]})[0], 400, "dose already recorded")
        self.assertEqual(nurse.post(f"/api/mar/{mo['id']}/give", {"due": mo["slots"][1]["due"], "status": "held"})[0], 400, "reason needed")
        nurse.ok(f"/api/admissions/{a['id']}/notes", {"text": "Febrile, taking orally", "temp": 38.4, "pulse": 98})
        doc.ok(f"/api/admissions/{a['id']}/notes", {"text": "Platelets falling, continue fluids"})
        svc = [s for s in doc.ok("/api/services") if s["name"] == "Nebulisation"][0]
        doc.ok(f"/api/admissions/{a['id']}/charges", {"service_id": svc["id"], "qty": 2})
        bill = doc.ok(f"/api/admissions/{a['id']}")["bill"]
        names = " ".join(x["name"] for x in bill["lines"])
        for part in ("Private room", "Nursing", "Medicine: Dolo 650", "Doctor visit", "Nebulisation"):
            self.assertIn(part, names)
        self.assertEqual(bill["deposits"], 5000)
        d = doc.ok(f"/api/admissions/{a['id']}/discharge", {"final_diagnosis": "Dengue fever without warning signs", "icd": "A90", "course": "Improved",
                                                             "medications": "Dolo 650 SOS", "advice": "Fluids", "followup": core.add_days(core.today(), 7)})
        inv = rec.ok(f"/api/invoices/{d['invoice_id']}")
        self.assertEqual(inv["paid_p"], 500000)
        self.assertEqual(inv["kind"], "ipd")
        cl = rec.ok(f"/api/invoices/{inv['id']}/claim", {"tpa": "Star Health", "policy": "SH-1", "requested": (inv["total_p"] - 500000) / 100, "icd": "A90"})
        self.assertEqual(rec.post(f"/api/claims/{cl['id']}", {"status": "settled", "settled": 10})[0], 400, "must be approved first")
        rec.ok(f"/api/claims/{cl['id']}", {"status": "query", "note": "Need discharge summary"})
        rec.ok(f"/api/claims/{cl['id']}", {"status": "approved", "approved": (inv["total_p"] - 500000) / 100 - 100})
        rec.ok(f"/api/claims/{cl['id']}", {"status": "settled", "settled": (inv["total_p"] - 500000) / 100 - 100})
        inv = rec.ok(f"/api/invoices/{inv['id']}")
        self.assertEqual(inv["due_p"], 10000, "Rs 100 short-paid by insurer becomes patient due")
        rec.ok(f"/api/invoices/{inv['id']}/pay", {"amount": 100, "mode": "upi", "ref": "UPI1"})
        self.assertEqual(rec.ok(f"/api/invoices/{inv['id']}")["status"], "paid")

    def test_excess_deposit_refund(self):
        rec = Client("reception.ch")
        beds = [b for b in rec.ok("/api/beds") if b["status"] == "free" and b["kind"] == "general"]
        doc = Client("dr.rao")
        a = doc.ok("/api/admissions", {"patient_id": 8, "bed_id": beds[0]["id"], "reason": "Observation", "deposit": 20000})
        d = doc.ok(f"/api/admissions/{a['id']}/discharge", {"final_diagnosis": "Observation, no illness found"})
        inv = rec.ok(f"/api/invoices/{d['invoice_id']}")
        self.assertGreater(inv["excess_p"], 0)
        self.assertEqual(inv["status"], "paid")
        mgr = Client("manager.ch")
        self.assertEqual(mgr.post(f"/api/invoices/{inv['id']}/refund", {"amount": inv["excess_p"] / 100 + 1, "reason": "x", "excess": True})[0], 400)
        mgr.ok(f"/api/invoices/{inv['id']}/refund", {"amount": inv["excess_p"] / 100, "reason": "Excess deposit returned", "excess": True})
        after = rec.ok(f"/api/invoices/{inv['id']}")
        self.assertEqual(after["excess_p"], 0)
        self.assertEqual(after["total_p"], inv["total_p"], "excess refund must not change the bill total")

    def test_opd_invoice_refund_closing(self):
        rec = Client("reception.ch")
        unb = rec.ok("/api/patients/1/unbilled")
        svcs = {s["name"]: s for s in rec.ok("/api/services")}
        inv = rec.ok("/api/invoices", {"patient_id": 1, "items": [{"service_id": svcs["OPD consultation, general"]["id"]}, {"service_id": svcs["ECG"]["id"]}],
                                        "discount": 50, "pay_now": 300, "mode": "cash"})
        self.assertEqual(inv["status"], "partial")
        self.assertEqual(rec.post("/api/invoices", {"patient_id": 1, "items": [{"service_id": svcs["ECG"]["id"], "rate": 1}]})[0], 400, "reception can't change rates")
        self.assertEqual(rec.post(f"/api/invoices/{inv['id']}/refund", {"amount": 10, "reason": "x"})[0], 403)
        mgr = Client("manager.ch")
        r = mgr.ok(f"/api/invoices/{inv['id']}/refund", {"amount": 100, "reason": "ECG not done"})
        self.assertTrue(r["credit_note"])
        cl = rec.ok("/api/closing")
        self.assertIn("cash", cl["by_mode"])
        r = rec.ok("/api/closing", {"counted": cl["expected_cash"] - 10})
        self.assertEqual(r["diff"], -10)


class T07AccountsReports(unittest.TestCase):
    def test_accounts(self):
        acc = Client("accounts")
        acc.branch(1)
        acc.ok("/api/expenses", {"category": "Electricity", "amount": 4500, "mode": "bank"})
        p = acc.ok(f"/api/pnl?period={core.today()[:7]}")
        self.assertIn("profit", p["total"])
        pay = acc.ok(f"/api/payouts?period={core.today()[:7]}")
        rao = [x for x in pay if x["name"] == "Dr. Rao"][0]
        self.assertGreater(rao["share"], 0)
        acc.ok("/api/payouts", {"doctor_id": rao["doctor_id"], "period": core.today()[:7]})
        st, data = acc.get(f"/api/gst?period={core.today()[:7]}&format=csv")
        self.assertIn(b"HSN summary", data)
        st, xml = acc.get(f"/api/tally?period={core.today()[:7]}")
        self.assertTrue(xml.startswith(b"<ENVELOPE>"))
        self.assertEqual(Client("pharma.ch").get("/api/pnl")[0], 403)

    def test_reports_dashboard_analytics(self):
        own = Client("owner")
        d = own.ok("/api/dashboard")
        self.assertEqual(d["mode"], "org")
        self.assertEqual(len(d["trend"]), 14)
        r = own.ok(f"/api/reports/daily?date={core.add_days(core.today(), -1)}")
        self.assertIn("daily report", r["text"])
        self.assertGreater(r["seen"], 0)
        a = own.ok("/api/analytics?days=30")
        self.assertEqual(len(a["heat"]), 7)
        res = own.ok("/api/reports/send", {"kind": "all"})
        self.assertTrue(res)
        own.branch(1)
        self.assertEqual(own.ok("/api/dashboard")["mode"], "branch")


class T08AdminDocs(unittest.TestCase):
    def test_documents_import_backup_dpdp(self):
        own = Client("owner")
        own.branch(1)
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 200).decode()
        d = own.ok("/api/documents", {"mime": "image/png", "data": png, "doc_type": "lab", "patient_id": 3, "filename": "cbc.png"})
        self.assertEqual(own.post("/api/documents", {"mime": "image/png", "data": base64.b64encode(b"<html>").decode()})[0], 400)
        lst = own.ok("/api/documents?patient_id=3")["rows"]
        self.assertEqual(lst[0]["id"], d["id"])
        st, data = own.get(f"/api/documents/{d['id']}/file")
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertEqual(Client("pharma.ms").get(f"/api/documents/{d['id']}/file")[0], 404, "other branch can't read")
        r = own.ok("/api/import/patients", {"csv": "name,phone,age\nImported One,9555500001,30\nBad,12,\n"})
        self.assertEqual(r["added"], 1)
        self.assertEqual(len(r["errors"]), 1)
        r = own.ok("/api/import/stock", {"csv": f"medicine,batch,expiry,qty,mrp,cost,rack\nNew Brand 10,X1,{core.add_days(core.today(), 300)},50,4,3,Z1-1\n"})
        self.assertEqual(r["new_medicines"], 1)
        b = own.ok("/api/backups", {})
        self.assertTrue(any(x["name"] == b["name"] for x in own.ok("/api/backups")))
        st, ex = own.get("/api/patients/3/export")
        self.assertIn("visits", ex)
        self.assertEqual(own.post("/api/patients/10/erase", {"confirm": "wrong"})[0], 400)
        own.ok("/api/patients/10/erase", {"confirm": "P00010", "reason": "Patient request"})
        self.assertTrue(own.ok("/api/patients/10")["name"].startswith("Erased"))
        aud = own.ok("/api/audit?q=erase")
        self.assertTrue(aud)

    def test_patient_portal(self):
        own, rec, anon = Client("owner"), Client("reception.ch"), Client()
        own.branch(1)
        core.db().execute("UPDATE patients SET whatsapp_ok=1 WHERE id=4")
        self.assertFalse(rec.ok("/api/patients/4/portal")["active"])
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"1" * 80).decode()
        self.assertEqual(own.post("/api/documents", {"mime": "image/png", "data": png, "doc_type": "scan", "share": True})[0], 400, "sharing needs a patient")
        shared = own.ok("/api/documents", {"mime": "image/png", "data": png, "doc_type": "scan", "patient_id": 4, "share": True, "note": "Chest X-ray"})
        private = own.ok("/api/documents", {"mime": "image/png", "data": png, "doc_type": "other", "patient_id": 4})
        self.assertTrue(shared["shared"])
        st = rec.ok("/api/patients/4/portal")
        self.assertTrue(st["active"])
        self.assertTrue(any(m["kind"] == "portal" for m in st["sent"]), "the patient was messaged (logged even without WhatsApp set up)")
        tok = st["token"]
        p = anon.ok(f"/api/portal?t={tok}")
        self.assertEqual(p["patient"]["code"], "P00004")
        kinds = {r["kind"] for r in p["records"]}
        self.assertIn("doc", kinds)
        self.assertIn("rx", kinds)
        self.assertEqual([r["doc_id"] for r in p["records"] if r["kind"] == "doc"], [shared["id"]], "unshared documents stay private")
        st_, data = anon.get(f"/api/portal/file/{shared['id']}?t={tok}")
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertEqual(anon.get(f"/api/portal/file/{private['id']}?t={tok}")[0], 404)
        self.assertEqual(anon.get("/api/portal?t=" + "x" * 24)[0], 404)
        # moving a shared document to another patient takes it out of the first patient's page
        own.ok(f"/api/documents/{shared['id']}", {"doc_type": "scan", "patient_id": 5})
        self.assertFalse([r for r in anon.ok(f"/api/portal?t={tok}")["records"] if r["kind"] == "doc"])
        # a new link stops the old one; switching off stops everything
        new = rec.ok("/api/patients/4/portal", {"fresh": True})["token"]
        self.assertNotEqual(new, tok)
        self.assertEqual(anon.get(f"/api/portal?t={tok}")[0], 404)
        self.assertEqual(anon.get(f"/api/portal?t={new}")[0], 200)
        rec.ok("/api/patients/4/portal/revoke", {})
        self.assertEqual(anon.get(f"/api/portal?t={new}")[0], 404)
        # a pharmacy bill for a registered patient messages them with a fresh link
        ph = Client("pharma.ch")
        med = [m for m in ph.ok("/api/medicines") if m["stock"] > 5 and m["schedule"] == "OTC"][0]
        ph.ok("/api/bills", {"patient_id": 4, "items": [{"medicine_id": med["id"], "qty": 1, "unit": "unit"}], "pay_mode": "cash", "override": True})
        st = rec.ok("/api/patients/4/portal")
        self.assertTrue(st["active"])
        self.assertTrue(any(r["kind"] == "bill" for r in anon.ok(f"/api/portal?t={st['token']}")["records"]))

    def test_ai_assistant(self):
        import types, json as _json
        doc, ph, rec, acc = Client("dr.rao"), Client("pharma.ch"), Client("reception.ch"), Client("accounts")
        self.assertTrue(ph.ok("/api/assistant/info")["enabled"])
        self.assertFalse(rec.ok("/api/assistant/info")["enabled"], "not for reception")
        # tools run as the signed-in user
        med = ph.ok("/api/assistant/tool", {"name": "find_medicine", "input": {"name": "dolo"}})
        self.assertTrue(med["ok"])
        r = _json.loads(med["result"])["results"][0]
        self.assertIn("batches_here", r)
        self.assertTrue(all("rack" in b for b in r["batches_here"]))
        summ = doc.ok("/api/assistant/tool", {"name": "patient_summary", "input": {"patient": "P00004"}})
        self.assertIn("allergies", _json.loads(summ["result"]))
        safe = _json.loads(doc.ok("/api/assistant/tool", {"name": "check_safety", "input": {"medicines": ["Brufen 400"], "patient": "P00004"}})["result"])
        self.assertEqual(safe["checked"], ["Brufen 400"])
        denied = ph.ok("/api/assistant/tool", {"name": "money_report", "input": {}})
        self.assertFalse(denied["ok"])
        self.assertIn("can't see", denied["result"])
        self.assertTrue(ph.ok("/api/assistant/tool", {"name": "stock_alerts", "input": {}})["ok"])
        self.assertEqual(rec.post("/api/assistant/tool", {"name": "find_medicine", "input": {"name": "dolo"}})[0], 403)
        core.set_setting(core.db(), "assistant_patients", "0")
        self.assertIn("switched off", doc.ok("/api/assistant/tool", {"name": "patient_summary", "input": {"patient": "P00004"}})["result"])
        core.set_setting(core.db(), "assistant_patients", "1")
        # without an API key the server says how to turn it on
        st, err = ph.post("/api/assistant/ask", {"text": "stock of dolo?"})
        self.assertEqual(st, 400)
        self.assertIn("API key", err["error"])
        # with a stand-in for Claude: one tool call, then the answer; the conversation is kept for follow-ups
        calls = []

        class Block(types.SimpleNamespace):
            def model_dump(self, exclude_none=True):
                return {k: v for k, v in vars(self).items() if v is not None}

        class Msgs:
            def create(self, **kw):
                calls.append(kw)
                if len(calls) == 1:
                    return types.SimpleNamespace(stop_reason="tool_use", content=[Block(type="tool_use", id="tu1", name="find_medicine", input={"name": "dolo"})])
                return types.SimpleNamespace(stop_reason="end_turn", content=[Block(type="text", text="Dolo 650: 120 tablets in rack A1-2.")])

        fake = types.ModuleType("anthropic")
        fake.Anthropic = lambda api_key: types.SimpleNamespace(beta=types.SimpleNamespace(messages=Msgs()))
        for n in ("AuthenticationError", "RateLimitError", "BadRequestError", "APIStatusError", "APIConnectionError"):
            setattr(fake, n, type(n, (Exception,), {}))
        sys.modules["anthropic"] = fake
        try:
            core.set_setting(core.db(), "anthropic_api_key", "test-key")
            a = ph.ok("/api/assistant/ask", {"text": "How many Dolo 650 and where?", "voice": True})
            self.assertEqual(a["answer"], "Dolo 650: 120 tablets in rack A1-2.")
            self.assertEqual(calls[0]["model"], "claude-opus-5-5")
            self.assertIn("read aloud", calls[0]["messages"][0]["content"], "voice replies ask for spoken style")
            tr = next(m["content"][0] for m in calls[1]["messages"] if m["role"] == "user" and isinstance(m["content"], list))
            self.assertEqual((tr["type"], tr["tool_use_id"]), ("tool_result", "tu1"))
            self.assertIn("batches_here", tr["content"])
            ph.ok("/api/assistant/ask", {"text": "and in North Hospital?", "chat_id": a["chat_id"]})
            self.assertEqual([m["role"] for m in calls[-1]["messages"]], ["user", "assistant", "user", "assistant", "user", "assistant"], "follow-up carries the earlier turns")
            self.assertEqual(doc.post("/api/assistant/ask", {"text": "x", "chat_id": a["chat_id"]})[0], 404, "conversations are private")
        finally:
            del sys.modules["anthropic"]
            core.set_setting(core.db(), "anthropic_api_key", "")

    def test_doctor_alerts_and_briefing(self):
        rec, doc, own = Client("reception.ch"), Client("dr.rao"), Client("owner")
        c = core.db()
        alerts_before = len(doc.ok("/api/alerts"))
        # a critical patient arriving alerts the branch's doctors (shown in the app even without WhatsApp)
        p = rec.ok("/api/patients", {"name": "Alert Critical", "phone": "9447033333", "age": 66, "gender": "Male", "consent": True})["id"]
        v = rec.ok("/api/visits", {"patient_id": p, "complaint": "chest pain, sweating", "spo2": 86, "pulse": 130})
        self.assertEqual(v["triage"], "critical")
        al = doc.ok("/api/alerts")
        self.assertGreater(len(al), alerts_before)
        self.assertIn("CRITICAL patient", al[0]["body"])
        self.assertIn("Alert Critical", al[0]["body"])
        # waiting too long: one alert per visit, after 10 minutes for a critical patient
        from app.m_alerts import check_waits
        c.execute("UPDATE visits SET created_at=datetime('now','localtime','-15 minutes') WHERE id=?", (v["id"],))
        self.assertGreaterEqual(check_waits(c), 1)
        self.assertEqual(check_waits(c), 0, "only once per visit")
        self.assertIn("waiting", doc.ok("/api/alerts")[0]["body"])
        # switched off in settings: no alert
        core.set_setting(c, "alert_critical", "0")
        p2 = rec.ok("/api/patients", {"name": "Alert Off", "phone": "9447044444", "age": 70, "gender": "Female", "consent": True})["id"]
        n = len(doc.ok("/api/alerts"))
        rec.ok("/api/visits", {"patient_id": p2, "complaint": "breathless", "spo2": 85})
        self.assertEqual(len(doc.ok("/api/alerts")), n)
        core.set_setting(c, "alert_critical", "1")
        # morning briefing
        b = doc.ok("/api/briefing")
        self.assertTrue(b["text"].startswith("Good morning Dr. Rao"))
        self.assertIn("Yesterday:", b["text"])
        ob = own.ok("/api/briefing")
        self.assertIn("beds free", ob["text"])
        self.assertIn("net collected", ob["text"])
        self.assertEqual(rec.get("/api/briefing")[0], 403)
        self.assertTrue(own.ok("/api/briefing/send", {})["ok"])
        from app.m_alerts import briefing_due
        from datetime import datetime as dt
        self.assertTrue(briefing_due({"briefing_time": "08:00", "last_briefing": ""}, dt(2026, 1, 5, 8, 1)))
        self.assertFalse(briefing_due({"briefing_time": "08:00", "last_briefing": "2026-01-05"}, dt(2026, 1, 5, 9, 0)))
        self.assertFalse(briefing_due({"briefing_time": "08:00", "last_briefing": ""}, dt(2026, 1, 5, 7, 59)))

    def test_tracker_and_collections(self):
        rec, doc = Client("reception.ch"), Client("dr.rao")
        # a patient who has been waiting an hour for the doctor
        p1 = rec.ok("/api/patients", {"name": "Tracker Waiting", "phone": "9447011111", "age": 50, "gender": "Male", "consent": True})["id"]
        v1 = rec.ok("/api/visits", {"patient_id": p1, "complaint": "back pain"})["id"]
        core.db().execute("UPDATE visits SET created_at=datetime('now','localtime','-60 minutes') WHERE id=?", (v1,))
        # a patient seen with medicines prescribed, but not billed and not dispensed
        p2 = rec.ok("/api/patients", {"name": "Tracker Seen", "phone": "9447022222", "age": 30, "gender": "Female", "consent": True})["id"]
        v2 = rec.ok("/api/visits", {"patient_id": p2, "complaint": "cough"})["id"]
        med = [m for m in doc.ok("/api/medicines") if m["schedule"] == "OTC"][0]
        doc.ok(f"/api/visits/{v2}/complete", {"diagnosis": "Common cold", "items": [{"medicine_id": med["id"], "dose": "1", "freq": "BD", "days": 3}], "override": True})
        core.db().execute("UPDATE visits SET completed_at=datetime('now','localtime','-90 minutes') WHERE id=?", (v2,))
        t = rec.ok("/api/tracker")
        r1 = [r for r in t["opd"] if r["id"] == v1][0]
        self.assertTrue(any("for the doctor" in s for s in r1["stuck"]), r1["stuck"])
        self.assertEqual([s["state"] for s in r1["steps"] if s["key"] == "doctor"], ["late"])
        r2 = [r for r in t["opd"] if r["id"] == v2][0]
        self.assertIn("consultation not billed", r2["stuck"])
        self.assertTrue(any("not dispensed" in s for s in r2["stuck"]))
        self.assertEqual([s["state"] for s in r2["steps"] if s["key"] == "doctor"], ["done"])
        self.assertTrue(t["opd"][0]["stuck"], "stuck patients come first")
        self.assertGreaterEqual(t["counts"]["stuck"], 2)
        ipd = [r for r in t["ipd"] if r["ip_no"] == "CH/IP/00001"]
        self.assertTrue(ipd and any(s["key"] == "advance" for s in ipd[0]["steps"]))
        self.assertEqual(Client("pharma.ms").get("/api/tracker")[0], 400, "a pharmacy-only branch has no tracker")
        # evening report: collections with counts, the deductions and the net
        own = Client("owner")
        own.branch(1)
        rep = own.ok(f"/api/reports/daily?date={core.today()}")
        self.assertIn("*Collections:*", rep["text"])
        self.assertIn("*Net collected:*", rep["text"])
        self.assertIn("*Less:*", rep["text"])
        self.assertTrue(all("n" in x and "amount" in x for x in rep["collections"]["lines"]))

    def test_staff_watch(self):
        rec, mgr, ph = Client("reception.ch"), Client("manager.ch"), Client("pharma.ch")
        # reception bills and then cancels it herself
        svc = core.db().execute("SELECT id FROM services ORDER BY id LIMIT 1").fetchone()[0]
        inv = rec.ok("/api/invoices", {"patient_id": 2, "items": [{"service_id": svc, "qty": 1}]})
        rec.ok(f"/api/invoices/{inv['id']}/cancel", {"reason": "entered twice"})
        # pharmacist: 25% discount, then takes the whole bill back in cash
        med = [m for m in ph.ok("/api/medicines") if m["schedule"] == "OTC" and m["stock"] > 20][0]
        bill = ph.ok("/api/bills", {"customer": "Walk-in", "items": [{"medicine_id": med["id"], "qty": 4, "unit": "unit"}], "pay_mode": "cash", "discount": round(med["mrp"] * 4 * 0.25, 2), "override": True})
        bi = ph.ok(f"/api/bills/{bill['id']}")["items"]
        ph.ok(f"/api/bills/{bill['id']}/return", {"items": [{"bill_item_id": x["id"], "qty": x["qty"]} for x in bi], "reason": "customer changed mind"})
        # a non-expired batch written off as damaged
        bt = [b for b in ph.ok("/api/stock")["batches"] if b["days_left"] > 30 and b["qty"] > 3][0]
        ph.ok("/api/writeoff", {"batch_id": bt["id"], "qty": 2, "reason": "damaged"})
        w = mgr.ok("/api/watch?days=1")
        kinds = {x["kind"] for x in w["items"]}
        self.assertTrue({"cancel", "discount", "return", "writeoff"} <= kinds, kinds)
        cancel = [x for x in w["items"] if x["kind"] == "cancel" and x["ref"] == inv["inv_no"]][0]
        self.assertIn("same person billed and cancelled", cancel["reasons"])
        self.assertTrue(cancel["high"])
        self.assertEqual(cancel["user"], "Anita")
        ret = [x for x in w["items"] if x["kind"] == "return" and x["ref"] == bill["bill_no"]][0]
        self.assertIn("cash paid back", ret["reasons"])
        self.assertIn("same person sold and took it back", ret["reasons"])
        disc = [x for x in w["items"] if x["kind"] == "discount" and x["ref"] == bill["bill_no"]][0]
        self.assertIn("25% discount", disc["reasons"])
        wo = [x for x in w["items"] if x["kind"] == "writeoff"][0]
        self.assertIn("not expired", wo["reasons"])
        self.assertTrue(any(s["user"] == "Suresh" and s["flagged"] >= 3 for s in w["staff"]))
        self.assertEqual(rec.get("/api/watch?days=1")[0], 403, "reception can't see staff watch")
        self.assertEqual(ph.get("/api/watch?days=1")[0], 403)
        from app.m_watch import watch_lines
        lines = "\n".join(watch_lines(core.db(), [1], core.today()))
        self.assertIn("Staff watch", lines)
        self.assertIn("Anita", lines)

    def test_pdf_documents(self):
        own, ph, anon = Client("owner"), Client("pharma.ch"), Client()
        own.branch(1)
        c = core.db()
        bill = c.execute("SELECT id, patient_id FROM bills WHERE branch_id=1 AND patient_id IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        other = c.execute("SELECT id FROM bills WHERE branch_id<>1 ORDER BY id DESC LIMIT 1").fetchone()
        inv = c.execute("SELECT id FROM invoices WHERE branch_id=1 ORDER BY id DESC LIMIT 1").fetchone()
        visit = c.execute("SELECT id FROM visits WHERE status='done' AND branch_id=1 ORDER BY id DESC LIMIT 1").fetchone()
        for path in (f"/api/pdf/bill/{bill[0]}", f"/api/pdf/invoice/{inv[0]}", f"/api/pdf/rx/{visit[0]}"):
            st, data = ph.get(path) if "bill" in path else own.get(path)
            self.assertEqual(st, 200, path)
            self.assertTrue(data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF"), path)
        self.assertEqual(ph.get(f"/api/pdf/bill/{other[0]}")[0], 403, "another branch's bill")
        self.assertEqual(anon.get(f"/api/pdf/bill/{bill[0]}")[0], 401)
        # lab report: only once verified
        o = c.execute("SELECT id FROM lab_orders WHERE branch_id=1 AND status<>'verified' ORDER BY id DESC LIMIT 1").fetchone()
        if o:
            self.assertEqual(own.get(f"/api/pdf/lab/{o[0]}")[0], 409)
        # the patient's own link opens their PDFs, not anyone else's
        tok = own.ok(f"/api/patients/{bill[1]}/portal", {})["token"]
        recs = anon.ok(f"/api/portal?t={tok}")["records"]
        self.assertTrue(all(r.get("pdf") for r in recs if r["kind"] in ("bill", "invoice", "rx", "lab")))
        st, data = anon.get(f"/api/portal/pdf/bill/{bill[0]}?t={tok}")
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(anon.get(f"/api/portal/pdf/bill/{other[0]}?t={tok}")[0], 404)
        # the WhatsApp attachment link is only made for a public HTTPS address
        from app.m_portal import pdf_url
        self.assertIsNone(pdf_url(c, tok, "bill", bill[0]))
        core.set_setting(c, "public_url", "https://care.example.com")
        self.assertEqual(pdf_url(c, tok, "bill", bill[0]), f"https://care.example.com/api/portal/pdf/bill/{bill[0]}?t={tok}")
        core.set_setting(c, "public_url", "")
        # text the standard fonts can't show doesn't break the file
        from app.m_pdf import Pdf
        p = Pdf("Test ₹ – “quotes” ఆరోగ్యం")
        p.para("Rupee ₹100 – Telugu ఆరోగ్యం (brackets) \\ backslash")
        self.assertTrue(p.bytes("footer").startswith(b"%PDF"))

    def test_welcome_weekly_dues_and_phone_upload(self):
        rec, mgr, ph, anon = Client("reception.ch"), Client("manager.ch"), Client("pharma.ch"), Client()
        # welcome message on registration (logged even when WhatsApp isn't set up)
        r = rec.ok("/api/patients", {"name": "Welcome Test", "phone": "9876500011", "age": 40, "gender": "Female", "consent": True})
        self.assertTrue(r["welcome"] and r["welcome"][0]["channel"] == "whatsapp")
        body = core.db().execute("SELECT body FROM messages WHERE kind='welcome' AND patient_id=?", (r["id"],)).fetchone()[0]
        self.assertIn(r["code"], body)
        self.assertIn("/my?t=", body)
        # supplier dues: a new purchase is due in 30 days; part payment, then full
        med = [m for m in mgr.ok("/api/medicines") if m["schedule"] == "OTC"][0]
        g = mgr.ok("/api/purchases", {"supplier_id": 1, "invoice_no": "DUE-1", "due_date": core.add_days(core.today(), 3),
                                      "lines": [{"medicine_id": med["id"], "batch": "DUE1", "expiry": core.add_days(core.today(), 400), "qty": 10, "cost": 5, "mrp": 8}]})
        d = mgr.ok("/api/supplier-dues")
        row = [x for x in d["rows"] if x["id"] == g["id"]][0]
        self.assertEqual(row["days"], 3)
        self.assertGreaterEqual(d["this_week"], row["due"])
        self.assertEqual(mgr.post(f"/api/purchases/{g['id']}/pay", {"amount": row["due"] + 1, "mode": "cash"})[0], 400, "can't overpay")
        self.assertEqual(mgr.post(f"/api/purchases/{g['id']}/pay", {"amount": 10, "mode": "upi"})[0], 400, "UPI needs a reference")
        self.assertEqual(ph.post(f"/api/purchases/{g['id']}/pay", {"amount": 10, "mode": "cash"})[0], 403, "pharmacist can't pay suppliers")
        self.assertAlmostEqual(mgr.ok(f"/api/purchases/{g['id']}/pay", {"amount": 10, "mode": "cash"})["due"], row["due"] - 10)
        self.assertEqual(mgr.ok(f"/api/purchases/{g['id']}/pay", {"amount": row["due"] - 10, "mode": "bank", "ref": "UTR123"})["due"], 0)
        self.assertFalse([x for x in mgr.ok("/api/supplier-dues")["rows"] if x["id"] == g["id"]])
        # weekly summary
        w = ph.ok("/api/stock/weekly")
        for k in ("expiring", "non_moving", "low_stock", "supplier_dues", "text"):
            self.assertIn(k, w)
        self.assertIn("Supplier bills due this week", w["text"])
        self.assertTrue(mgr.ok("/api/stock/weekly/send", {})["ok"])
        from app.m_weekly import weekly_due
        self.assertFalse(weekly_due({"weekly_pharmacy": "0"}))
        # phone upload by QR
        link = ph.ok("/api/upload-links", {"purpose": "stock"})
        self.assertIn("/up?k=", link["url"])
        self.assertEqual(anon.ok(f"/api/public/upload?k={link['token']}")["sent"], 0)
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"2" * 90).decode()
        self.assertEqual(anon.ok(f"/api/public/upload?k={link['token']}", {"mime": "image/png", "data": png, "filename": "shelf.png"})["sent"], 1)
        got = ph.ok(f"/api/upload-links/{link['token']}")["docs"]
        self.assertEqual(len(got), 1)
        doc = [x for x in ph.ok("/api/documents?type=stock")["rows"] if x["id"] == got[0]["id"]][0]
        self.assertEqual(doc["note"], "Sent from phone")
        self.assertEqual(mgr.get(f"/api/upload-links/{link['token']}")[0], 404, "only the person who made the QR sees its uploads")
        self.assertEqual(anon.post("/api/public/upload?k=" + "y" * 24, {"mime": "image/png", "data": png})[0], 404)
        core.db().execute("UPDATE upload_links SET expires=0 WHERE token=?", (link["token"],))
        self.assertEqual(anon.post(f"/api/public/upload?k={link['token']}", {"mime": "image/png", "data": png})[0], 404, "expired")

    def test_idempotency_header_and_attendance_feedback(self):
        rec = Client("reception.ch")
        h = {"Idempotency-Key": "abc-123"}
        st1, r1 = rec.post("/api/patients", {"name": "Idem", "phone": "9444400001", "consent": True}, h)
        st2, r2 = rec.post("/api/patients", {"name": "Idem", "phone": "9444400001", "consent": True}, h)
        self.assertEqual(r1["id"], r2["id"])
        self.assertEqual(rec.ok("/api/attendance", {})["state"], "in")
        self.assertEqual(rec.ok("/api/attendance", {})["state"], "out")
        c = core.db()
        c.execute("INSERT INTO feedback(token,branch_id,patient_id,sent_at) VALUES('tok1',1,1,'x')")
        core.reset_conn()
        pub = Client()
        pub.ok("/api/public/feedback", {"t": "tok1", "rating": 2, "comment": "Long wait"})
        self.assertEqual(pub.post("/api/public/feedback", {"t": "tok1", "rating": 5})[0], 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)


def pdf_text(data):
    """Inflate the content streams of a small PDF so its text can be searched."""
    import re as _re
    import zlib
    return b"".join(zlib.decompress(m) for m in _re.findall(rb"stream\n(.*?)\nendstream", data, _re.S))


class T20CareRecords(unittest.TestCase):
    def test_emergency_note_referral_imaging_procedure_anc(self):
        rec, doc = Client("reception.ch"), Client("dr.rao")
        p = rec.ok("/api/patients", {"name": "Care Test", "phone": "9000022222", "age": 30, "gender": "Female", "consent": True, "force": True})
        v = rec.ok("/api/visits", {"patient_id": p["id"], "complaint": "fall from height", "emergency": True, "mlc": True, "mlc_no": "PS-12/24", "arrival": "ambulance",
                                   "pulse": 88, "bp_sys": 120, "bp_dia": 80, "resp_rate": 18, "gcs": 14, "pain": 7, "height": 160, "weight": 55, "temp": 98.6})
        self.assertEqual(v["triage"], "critical")
        self.assertIn("emergency", v["reasons"])
        self.assertEqual(rec.post("/api/visits", {"patient_id": p["id"], "gcs": 20})[0], 400, "GCS range checked")
        q = [x for x in rec.ok("/api/visits?status=waiting") if x["id"] == v["id"]][0]
        self.assertEqual((q["mlc"], q["mlc_no"], q["arrival"], q["temp"]), (1, "PS-12/24", "ambulance", 37.0))
        doc.ok(f"/api/visits/{v['id']}/start", {})
        doc.ok(f"/api/visits/{v['id']}/complete", {"diagnosis": "Fracture shaft of femur", "complaint": "fall from 2nd floor", "history": "Fell at 9 am, no LOC",
                                                    "examination": "Deformed right thigh, distal pulses present", "items": [], "lab_tests": []})
        vd = doc.ok(f"/api/visits/{v['id']}")["visit"]
        self.assertEqual((vd["history"], vd["complaint"]), ("Fell at 9 am, no LOC", "fall from 2nd floor"))
        self.assertIn(b"Examination:", pdf_text(doc.get(f"/api/pdf/rx/{v['id']}")[1]))
        # imaging: order, report, shows on the profile
        im = rec.ok(f"/api/patients/{p['id']}/imaging", {"modality": "X-ray", "study": "Right femur AP/lat", "indication": "fracture?", "visit_id": v["id"]})
        self.assertEqual(rec.post(f"/api/patients/{p['id']}/imaging", {"modality": "PET", "study": "x"})[0], 400)
        self.assertEqual(len(rec.ok("/api/imaging?status=ordered")), 1)
        doc.ok(f"/api/imaging/{im['id']}/report", {"findings": "Transverse fracture mid-shaft", "impression": "Fracture shaft femur"})
        prof = doc.ok(f"/api/patients/{p['id']}")
        self.assertEqual(prof["imaging"][0]["status"], "reported")
        # referral with a letter
        self.assertEqual(doc.post(f"/api/patients/{p['id']}/referrals", {"to_facility": "GH", "reason": ""})[0], 400)
        ref = doc.ok(f"/api/patients/{p['id']}/referrals", {"to_facility": "Government General Hospital", "to_doctor": "Ortho OPD", "urgency": "urgent",
                                                             "reason": "Needs intramedullary nailing", "summary": "Closed fracture, stable", "transport": "ambulance", "visit_id": v["id"]})
        st, pdf = doc.get(f"/api/pdf/referral/{ref['id']}")
        self.assertEqual(st, 200)
        self.assertTrue(pdf.startswith(b"%PDF"))
        doc.ok(f"/api/referrals/{ref['id']}/outcome", {"status": "seen", "outcome": "Operated on day 2"})
        self.assertEqual(doc.ok(f"/api/patients/{p['id']}/referrals")[0]["status"], "seen")
        # procedure needs consent
        self.assertEqual(doc.post(f"/api/patients/{p['id']}/procedures", {"name": "Splint", "consent_by": "self"})[0], 400, "relation + explained needed")
        pr = doc.ok(f"/api/patients/{p['id']}/procedures", {"name": "Thomas splint application", "kind": "minor", "anaesthesia": "none", "consent_by": "Care Test",
                                                             "consent_relation": "self", "consent_explained": True, "findings": "Reduced, splinted"})
        self.assertEqual(doc.ok(f"/api/patients/{p['id']}/procedures")[0]["id"], pr["id"])
        # antenatal: risk flags from BP and Hb
        rec.ok(f"/api/patients/{p['id']}", {"name": "Care Test", "phone": "9000022222", "age": 30, "gender": "Female", "lmp": core.add_days(core.today(), -140), "gravida": 2, "para": 1})
        a = rec.ok(f"/api/patients/{p['id']}/anc", {"weight": 58, "bp_sys": 150, "bp_dia": 95, "urine_albumin": "2+", "hb": 9.2, "fhr": 140, "fundal_cm": 20})
        self.assertIn("pre-eclampsia", a["risk"])
        self.assertIn("anaemia", a["risk"])
        anc = rec.ok(f"/api/patients/{p['id']}/anc")
        self.assertEqual(anc[0]["ga_weeks"], 20)
        self.assertEqual(rec.ok(f"/api/patients/{p['id']}")["gravida"], 2)
        g = rec.ok(f"/api/patients/{p['id']}/growth")
        self.assertTrue(g["reference"])

    def test_lab_reject_amend_ack(self):
        rec, lab, doc = Client("reception.ch"), Client("lab.ch"), Client("dr.rao")
        tests = {t["code"]: t for t in lab.ok("/api/lab/tests")}
        o = rec.ok("/api/lab/orders", {"patient_id": 7, "tests": [tests["CBC"]["id"]], "priority": "urgent"})  # walk-in: no doctor
        lab.ok(f"/api/lab/orders/{o['id']}/collect", {})
        self.assertEqual(lab.post(f"/api/lab/orders/{o['id']}/reject", {})[0], 400, "reason needed")
        lab.ok(f"/api/lab/orders/{o['id']}/reject", {"reason": "Haemolysed"})
        d = lab.ok(f"/api/lab/orders/{o['id']}")
        self.assertEqual((d["status"], d["rejections"]), ("ordered", 1))
        self.assertIn("Haemolysed", d["reject_note"])
        lab.ok(f"/api/lab/orders/{o['id']}/collect", {})
        d = lab.ok(f"/api/lab/orders/{o['id']}")
        vals = {f"{t['item_id']}:{p['id']}": ("5.5" if p["name"] == "Haemoglobin" else "8") for t in d["tests"] for p in t["params"]}
        self.assertTrue(lab.ok(f"/api/lab/orders/{o['id']}/results", {"values": vals, "submit": True})["critical"])
        crit = doc.ok("/api/lab/critical")
        mine = [x for x in crit if x["id"] == o["id"]]
        self.assertTrue(mine and not mine[0]["assigned"], "unassigned critical result is shown to every doctor in the branch")
        self.assertTrue(any("CRITICAL" in a["body"] and f"LAB{o['id']}" in a["body"] for a in doc.ok("/api/alerts")), "doctor alerted although no doctor ordered it")
        doc.ok(f"/api/lab/orders/{o['id']}/ack", {"action": "patient called"})
        self.assertFalse([x for x in doc.ok("/api/lab/critical") if x["id"] == o["id"]])
        self.assertEqual(doc.post(f"/api/lab/orders/{o['id']}/ack", {})[0], 400)
        doc.ok(f"/api/lab/orders/{o['id']}/verify", {})
        self.assertEqual(doc.post(f"/api/lab/orders/{o['id']}/amend", {})[0], 400)
        doc.ok(f"/api/lab/orders/{o['id']}/amend", {"reason": "Hb transcription error"})
        d = doc.ok(f"/api/lab/orders/{o['id']}")
        self.assertEqual(d["status"], "resulted")
        vals = {k: ("11.5" if v == "5.5" else v) for k, v in vals.items()}
        lab.ok(f"/api/lab/orders/{o['id']}/results", {"values": vals, "submit": True})
        doc.ok(f"/api/lab/orders/{o['id']}/verify", {})
        self.assertIn(b"AMENDED", pdf_text(doc.get(f"/api/pdf/lab/{o['id']}")[1]))

    def test_discharge_rx_and_credit_bills(self):
        rec, doc, ph = Client("reception.ch"), Client("dr.rao"), Client("pharma.ch")
        beds = [b for b in rec.ok("/api/beds") if b["status"] == "free"]
        a = doc.ok("/api/admissions", {"patient_id": 8, "bed_id": beds[0]["id"], "reason": "Pneumonia", "diagnosis": "Pneumonia", "icd": "J18.9", "deposit": 2000})
        meds = {m["name"]: m for m in ph.ok("/api/medicines")}
        # pharmacy sells on credit to the inpatient
        cb = ph.ok("/api/bills", {"patient_id": 8, "admission_id": a["id"], "pay_mode": "credit", "items": [{"medicine_id": meds["Dolo 650"]["id"], "qty": 4, "unit": "unit"}]})
        credit_total = cb["total"]
        self.assertTrue(credit_total > 0)
        self.assertEqual(doc.ok(f"/api/admissions/{a['id']}")["bill"]["pharmacy_credit"], credit_total)
        items = [{"medicine_id": meds["Azithral 500"]["id"], "dose": "1", "freq": "OD", "days": 3}]
        d = doc.ok(f"/api/admissions/{a['id']}/discharge", {"final_diagnosis": "Community-acquired pneumonia", "icd": "J18.9", "course": "Improved on antibiotics", "items": items,
                                                             "followup": core.add_days(core.today(), 5)})
        inv = rec.ok(f"/api/invoices/{d['invoice_id']}")
        names = " ".join(x["name"] for x in inv["items"])
        self.assertIn("Pharmacy bill", names, "credit bill is on the final invoice")
        self.assertIn("(credit)", names)
        adm = doc.ok(f"/api/admissions/{a['id']}")
        self.assertEqual(adm["rx"][0]["name"], "Azithral 500")
        self.assertIn("Azithral", adm["summary"]["medications"])
        # the discharge prescription is pending at any pharmacy and can be dispensed against
        pend = [x for x in ph.ok("/api/rx/pending?patient_id=8") if x.get("admission_id") == a["id"]]
        self.assertEqual(len(pend), 1)
        it = pend[0]["items"][0]
        ph.ok("/api/bills", {"patient_id": 8, "rx_admission_id": a["id"], "pay_mode": "cash", "items": [{"medicine_id": it["medicine_id"], "qty": it["remaining"], "unit": "unit", "rx_item_id": it["id"]}]})
        self.assertFalse([x for x in ph.ok("/api/rx/pending?patient_id=8") if x.get("admission_id") == a["id"]], "fully dispensed")
        self.assertEqual(ph.post("/api/bills", {"patient_id": 7, "rx_admission_id": a["id"], "pay_mode": "cash", "items": [{"medicine_id": it["medicine_id"], "qty": 1, "unit": "unit", "rx_item_id": it["id"]}]})[0], 400, "other patient's prescription")
        # OPD credit bill: shows as a due, settled at the hospital desk, counted as collected
        cb2 = ph.ok("/api/bills", {"patient_id": 7, "pay_mode": "credit", "items": [{"medicine_id": meds["Dolo 650"]["id"], "qty": 2, "unit": "unit"}]})
        u = rec.ok("/api/patients/7/unbilled")
        self.assertTrue(any(x["bill_id"] == cb2["id"] for x in u["credit_bills"]))
        before = rec.ok("/api/dashboard")["report"]
        self.assertEqual(rec.post(f"/api/bills/{cb2['id']}/settle", {"mode": "upi"})[0], 400, "reference needed")
        s = rec.ok(f"/api/bills/{cb2['id']}/settle", {"mode": "cash"})
        self.assertEqual(s["amount"], cb2["total"])
        self.assertEqual(rec.post(f"/api/bills/{cb2['id']}/settle", {"mode": "cash"})[0], 400, "not twice")
        after = rec.ok("/api/dashboard")["report"]
        self.assertAlmostEqual(after["collected"] - before["collected"], cb2["total"], places=2)
        self.assertAlmostEqual(before["dues"] - after["dues"], cb2["total"], places=2)
        self.assertFalse(any(x["bill_id"] == cb2["id"] for x in rec.ok("/api/patients/7/unbilled")["credit_bills"]))


class T21Operations(unittest.TestCase):
    def test_health_docs_and_alert_matching(self):
        pub = Client()
        st, hlt = pub.get("/api/health")
        self.assertEqual(st, 200)
        self.assertTrue(hlt["ok"] and hlt["schema"] == hlt["expected"])
        self.assertEqual(pub.get("/api/docs")[0], 401)
        doc = Client("dr.rao")
        routes = doc.ok("/api/docs")
        self.assertTrue(any(r["path"] == "/api/patients/{id}/referrals" and r["method"] == "POST" and r["permission"] == "consult" for r in routes))
        self.assertTrue(any(r["path"] == "/api/health" and r["permission"] == "public" for r in routes))
        # an alert is addressed by user id, so a namesake in another branch does not see it
        own = Client("owner")
        u = own.ok("/api/users", {"username": "dr.rao2", "name": "Dr. Rao", "role": "doctor", "branch_id": 2, "password": PW})
        other = Client("dr.rao2")
        before = len(other.ok("/api/alerts"))
        rec = Client("reception.ch")
        np_ = rec.ok("/api/patients", {"name": "Alert Case", "phone": "9000055555", "age": 50, "gender": "Male", "consent": True, "force": True})["id"]
        rec.ok("/api/visits", {"patient_id": np_, "complaint": "chest pain", "doctor_id": 2, "spo2": 85})
        self.assertTrue(any("CRITICAL" in a["body"] for a in doc.ok("/api/alerts")))
        self.assertEqual(len(other.ok("/api/alerts")), before, "namesake doctor in another branch gets nothing")

    def test_erase_scrubs_everything_and_documents_soft_delete(self):
        own = Client("owner")
        own.branch(1)
        pid = own.ok("/api/patients", {"name": "Erase Me", "phone": "9000033333", "age": 40, "gender": "Male", "consent": True, "force": True})["id"]
        own.ok(f"/api/patients/{pid}/portal", {})  # creates a records link and logs a message with the phone
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 200).decode()
        d = own.ok("/api/documents", {"mime": "image/png", "data": png, "doc_type": "lab", "patient_id": pid, "filename": "secret-name.png"})
        own.ok(f"/api/patients/{pid}/erase", {"confirm": f"P{pid:05d}", "reason": "Written request"})
        self.assertEqual(own.ok("/api/patients?q=P%05d" % pid), [], "erased patients are not found by ID lookup")
        self.assertEqual(own.post(f"/api/patients/{pid}", {"name": "Back", "phone": "9000033333"})[0], 400, "erased record can't be edited")
        msgs = [m for m in own.ok("/api/messages") if m.get("patient_id") == pid]
        self.assertTrue(msgs and all(m["to_addr"] == "erased" and "9000033333" not in (m["body"] or "") for m in msgs))
        self.assertIsNone(own.ok("/api/documents?patient_id=%d" % pid)["rows"][0]["filename"])
        # documents: delete hides, manager restores, nothing is removed from disk
        own.ok(f"/api/documents/{d['id']}/delete", {"reason": "wrong patient"})
        self.assertEqual(own.ok("/api/documents?patient_id=%d" % pid)["rows"], [])
        self.assertEqual(len(own.ok("/api/documents?patient_id=%d&deleted=1" % pid)["rows"]), 1)
        self.assertEqual(Client("nurse.ch").get(f"/api/documents/{d['id']}/file")[0], 404)
        own.ok(f"/api/documents/{d['id']}/restore", {})
        self.assertEqual(len(own.ok("/api/documents?patient_id=%d" % pid)["rows"]), 1)
        self.assertTrue(own.get(f"/api/documents/{d['id']}/file")[1].startswith(b"\x89PNG"))

    def test_growth_tables_and_zscores(self):
        own = Client("owner")
        # a small LMS table in the WHO layout (boys, weight-for-age, months 0-24, values close to the standard)
        rows_ = [(0, 0.3487, 3.3464, 0.14602), (6, 0.1562, 7.934, 0.11727), (12, 0.0937, 9.6479, 0.10938), (24, -0.0128, 12.1515, 0.10868)]
        csv_text = "Month,L,M,S\n" + "\n".join(f"{m},{l},{mm},{s}" for m, l, mm, s in rows_) + "\n"
        self.assertEqual(own.post("/api/import/growth", {"csv": csv_text, "sex": "M", "kind": "wfa"})[0], 400, "too few rows")
        full = "Month,L,M,S\n" + "\n".join(f"{m},{0.2},{3.3 + m * 0.37},{0.12}" for m in range(0, 25)) + "\n"
        r = own.ok("/api/import/growth", {"csv": full, "sex": "M", "kind": "wfa"})
        self.assertEqual(r["rows"], 25)
        rec = Client("reception.ch")
        dob = core.add_days(core.today(), -365)
        pid = rec.ok("/api/patients", {"name": "Baby Growth", "phone": "9000044444", "dob": dob, "gender": "Male", "weight": 5.5, "consent": True, "force": True})["id"]
        g = rec.ok(f"/api/patients/{pid}/growth")
        self.assertTrue(g["has_who"] and g["curves"])
        pt = g["points"][-1]
        self.assertLess(pt["z_weight"], -2, "5.5 kg at 12 months is well under the median of this table")
        self.assertEqual(pt["flag"], "below -2 SD" if pt["z_weight"] >= -3 else "below -3 SD")
        p50 = [c_ for c_ in g["curves"] if c_["months"] == 12][0]
        self.assertAlmostEqual(p50["p50"], 3.3 + 12 * 0.37, places=1)
        self.assertLess(p50["p3"], p50["p50"])
        self.assertGreater(p50["p97"], p50["p50"])

    def test_late_offline_bill_after_cash_closing(self):
        ph, rec = Client("pharma.ch"), Client("reception.ch")
        meds = {m["name"]: m for m in ph.ok("/api/medicines")}
        yday = core.add_days(core.today(), -1)
        rec.ok("/api/closing", {"date": yday, "counted": 0})
        b = ph.ok("/api/bills", {"pay_mode": "cash", "created_at": yday + " 18:30", "offline_key": "late-" + yday,
                                 "items": [{"medicine_id": meds["Dolo 650"]["id"], "qty": 1, "unit": "unit"}]})
        self.assertTrue(ph.ok(f"/api/bills/{b['id']}")["created_at"].startswith(core.today()), "a bill synced after the day was closed counts today")


class T22BedBoard(unittest.TestCase):
    def test_board_for_everyone_timers_and_expected_discharge(self):
        rec, doc, lab, own = Client("reception.ch"), Client("dr.rao"), Client("lab.ch"), Client("owner")
        board = rec.ok("/api/beds")
        self.assertTrue(board and all("minutes" in b for b in board))
        self.assertEqual(lab.get("/api/beds")[0], 200, "every signed-in role can see the board")
        self.assertTrue(len(own.ok("/api/beds?all=1")) >= len(board), "owner sees every branch")
        free = [b for b in board if b["status"] == "free"][0]
        a = doc.ok("/api/admissions", {"patient_id": 6, "bed_id": free["id"], "reason": "Observation", "diagnosis": "Gastroenteritis"})
        self.assertEqual(doc.post(f"/api/admissions/{a['id']}/plan", {"planned_discharge": "2020-13-45"})[0], 400)
        doc.ok(f"/api/admissions/{a['id']}/plan", {"planned_discharge": core.today()})
        b = [x for x in rec.ok("/api/beds") if x["id"] == free["id"]][0]
        self.assertEqual((b["status"], b["planned_discharge"]), ("occupied", core.today()))
        self.assertIsNotNone(b["minutes"], "status time is stamped when the bed is taken")
        doc.ok(f"/api/admissions/{a['id']}/discharge", {"final_diagnosis": "Gastroenteritis, resolved"})
        b = [x for x in rec.ok("/api/beds") if x["id"] == free["id"]][0]
        self.assertEqual(b["status"], "cleaning")
        self.assertEqual(Client("nurse.ch").post(f"/api/beds/{free['id']}/status", {"status": "blocked", "reason": "repair"})[0], 200)
        self.assertEqual(rec.post(f"/api/beds/{free['id']}/status", {"status": "free"})[0], 403, "reception can see but not change beds")
        Client("nurse.ch").ok(f"/api/beds/{free['id']}/status", {"status": "free"})
        self.assertEqual([x for x in rec.ok("/api/beds") if x["id"] == free["id"]][0]["status"], "free")
        d = rec.ok("/api/dashboard")
        self.assertIn("free", d["beds"])


class T23LabExplanation(unittest.TestCase):
    def test_plain_language_explanation_reviewed_by_doctor(self):
        rec, lab, doc = Client("reception.ch"), Client("lab.ch"), Client("dr.rao")
        tests = {t["code"]: t for t in lab.ok("/api/lab/tests")}
        o = rec.ok("/api/lab/orders", {"patient_id": 5, "tests": [tests["CBC"]["id"], tests["FBS"]["id"]]})
        lab.ok(f"/api/lab/orders/{o['id']}/collect", {})
        d = lab.ok(f"/api/lab/orders/{o['id']}")
        vals = {}
        for t in d["tests"]:
            for p in t["params"]:
                vals[f"{t['item_id']}:{p['id']}"] = {"Haemoglobin": "9.8", "Glucose fasting": "132", "Platelets": "210", "Total WBC": "7", "Neutrophils": "60", "Lymphocytes": "30"}[p["name"]]
        self.assertEqual(lab.post(f"/api/lab/orders/{o['id']}/interpret", {})[0], 400, "nothing to explain before submission")
        lab.ok(f"/api/lab/orders/{o['id']}/results", {"values": vals, "submit": True})
        d = lab.ok(f"/api/lab/orders/{o['id']}")
        self.assertIsNotNone(d["interp"])
        names = [f["param"] for f in d["interp"]["findings"]]
        self.assertEqual(sorted(names), ["Glucose fasting", "Haemoglobin"], "only out-of-range values are explained")
        hb = [f for f in d["interp"]["findings"] if f["param"] == "Haemoglobin"][0]
        self.assertIn("anaemia", hb["text"])
        self.assertIn("2 of 6 results are outside", d["interp"]["summary"])
        self.assertEqual(d["interp"]["source"], "rules")
        self.assertIsNone(d["interp_reviewed_at"], "not reviewed until the doctor verifies")
        self.assertEqual(lab.post(f"/api/lab/orders/{o['id']}/interpret", {"summary": "x"})[0], 403, "technician can't edit the wording")
        self.assertEqual(lab.post(f"/api/lab/orders/{o['id']}/interpret", {"ai": True})[0], 400, "no API key: clear message, rules kept")
        doc.ok(f"/api/lab/orders/{o['id']}/interpret", {"findings": [{"param": "Haemoglobin", "text": "Your haemoglobin is a little low. We will check your iron."}], "summary": "Two values need a word with the doctor; nothing urgent."})
        d = doc.ok(f"/api/lab/orders/{o['id']}")
        self.assertEqual(d["interp"]["source"], "doctor")
        self.assertIn("check your iron", [f for f in d["interp"]["findings"] if f["param"] == "Haemoglobin"][0]["text"])
        self.assertEqual(doc.get(f"/api/pdf/lab/{o['id']}")[0], 409, "no PDF before verification")
        doc.ok(f"/api/lab/orders/{o['id']}/verify", {})
        d = doc.ok(f"/api/lab/orders/{o['id']}")
        self.assertIsNotNone(d["interp_reviewed_at"])
        txt = pdf_text(doc.get(f"/api/pdf/lab/{o['id']}")[1])
        self.assertIn(b"What this means", txt)
        self.assertIn(b"check your iron", txt)
        doc.ok(f"/api/lab/orders/{o['id']}/interpret", {"patient": False})
        self.assertNotIn(b"What this means", pdf_text(doc.get(f"/api/pdf/lab/{o['id']}")[1]), "kept off the patient's report on request")
        msgs = [m for m in Client("owner").ok("/api/messages?kind=lab_report") if f"LAB{o['id']}" in (m["body"] or "")]
        self.assertTrue(msgs and "What this means" in msgs[0]["body"], "the WhatsApp text carried the explanation at verification")


class T24Suppliers(unittest.TestCase):
    def test_supplier_record_history_compare_and_trace(self):
        ph, mgr = Client("pharma.ch"), Client("manager.ch")
        meds = {m["name"]: m for m in ph.ok("/api/medicines")}
        s1 = ph.ok("/api/suppliers", {"name": "ABC Pharma Test", "phone": "9000001111", "gstin": "36AAAAA0000A1Z5"})["id"]
        s2 = ph.ok("/api/suppliers", {"name": "Sunrise Distributors Test"})["id"]
        exp = core.add_days(core.today(), 500)
        g1 = ph.ok("/api/purchases", {"supplier_id": s1, "invoice_no": "INV-0081", "lines": [{"medicine_id": meds["Cefixime 200"]["id"], "batch": "BTH-2487", "expiry": exp, "qty": 100, "cost": 12.5, "mrp": 20, "unit": "unit"}]})
        g2 = ph.ok("/api/purchases", {"supplier_id": s2, "invoice_no": "INV-0074", "lines": [{"medicine_id": meds["Cefixime 200"]["id"], "batch": "BTH-2190", "expiry": exp, "qty": 50, "cost": 13, "mrp": 20, "unit": "unit"}]})
        mgr.ok(f"/api/purchases/{g1['id']}/pay", {"amount": 1250, "mode": "bank", "ref": "UTR1"})
        ov = ph.ok("/api/suppliers/overview")
        a = [s for s in ov["suppliers"] if s["id"] == s1][0]
        b = [s for s in ov["suppliers"] if s["id"] == s2][0]
        self.assertEqual((a["status"], a["total"], a["paid"], a["pending"], a["items"], a["last_purchase"]), ("paid", 1250, 1250, 0, 1, core.today()))
        self.assertEqual((b["status"], b["pending"]), ("pending", 650))
        h = ph.ok(f"/api/suppliers/{s1}/history")
        self.assertEqual(h["purchases"][0]["invoice_no"], "INV-0081")
        line = h["purchases"][0]["lines"][0]
        self.assertEqual((line["batch"], line["qty_in"], line["cost"], line["medicine"]), ("BTH-2487", 100, 12.5, "Cefixime 200"))
        self.assertEqual(h["payments"][0]["amount"], 1250)
        cmp_ = ph.ok(f"/api/stock/compare?medicine_id={meds['Cefixime 200']['id']}")
        self.assertEqual(cmp_["suppliers"][0]["supplier"], "ABC Pharma Test", "cheapest first")
        self.assertEqual(cmp_["cheapest"], "ABC Pharma Test")
        self.assertAlmostEqual(cmp_["saving"], 0.5 * meds["Cefixime 200"]["pack_size"], places=2)
        tr = ph.ok(f"/api/batches/{line['batch_id']}/trace")
        self.assertEqual((tr["purchase"]["supplier"], tr["purchase"]["invoice_no"], tr["purchase"]["status"], tr["received"], tr["left"]), ("ABC Pharma Test", "INV-0081", "paid", 100, 100))
        sv = ph.ok("/api/stock")
        self.assertTrue(any(x.get("supplier") == "ABC Pharma Test" and x["batch"] == "BTH-2487" for x in sv["batches"]), "batch list names the supplier")
        ph.ok(f"/api/suppliers/{s1}", {"phone": "9000002222"})
        self.assertEqual(ph.ok(f"/api/suppliers/{s1}/history")["supplier"]["phone"], "9000002222")


class T25FindMedicine(unittest.TestCase):
    def test_partial_search_and_rack_map(self):
        ph, rec = Client("pharma.ch"), Client("reception.ch")
        self.assertEqual(ph.get("/api/stock/find?q=d")[0], 400, "two letters at least")
        l = ph.ok("/api/stock/find?q=parac")
        self.assertTrue(l and all("paracetamol" in (x["generic"] or "").lower() or "parac" in x["name"].lower() for x in l), "salt search finds brands")
        dolo = [x for x in l if x["name"] == "Dolo 650"][0]
        self.assertTrue(dolo["qty"] > 0 and dolo["rack"], "quantity and the rack to pick from")
        self.assertEqual(l[0]["qty"] > 0, True, "in-stock matches come first")
        self.assertEqual(ph.ok("/api/stock/find?q=dolo")[0]["name"], "Dolo 650", "brand prefix first")
        self.assertEqual(rec.ok("/api/stock/find?q=dolo")[0]["name"], "Dolo 650", "reception at a hospital+pharmacy branch searches too")
        r = ph.ok("/api/stock/racks")
        self.assertTrue(r["racks"] and all(x["items"] for x in r["racks"]))
        # take a rack away, see it reported, give it back in one click
        bid = ph.ok("/api/stock")["batches"][0]["id"]
        core.db().execute("UPDATE batches SET rack=NULL WHERE id=?", (bid,))  # as an import without racks would leave it
        r = ph.ok("/api/stock/racks")
        self.assertTrue(any(u["batch_id"] == bid for u in r["unassigned"]))
        self.assertGreaterEqual(ph.ok("/api/stock/racks/assign", {})["assigned"], 1)
        self.assertFalse(ph.ok("/api/stock/racks")["unassigned"])
