"""First-run setup: schema, settings, reference data, owner login, optional demo data."""
import json
import os
import random
import secrets
from datetime import datetime, timedelta
from types import SimpleNamespace

from .core import BASE, DATA_DIR, DEFAULT_SETTINGS, add_days, db, now_str, one, today
from .refdata import ICD10, LAB_TESTS, MEDICINES, SERVICES, TEMPLATES
from .schema import migrate


def seed_reference(c):
    if not one(c, "SELECT 1 FROM medicines"):
        c.executemany("INSERT INTO medicines(name,generic,form,schedule,gst_pct,reorder_level,pack_size,strength_mg,max_daily_mg,ped_mg_per_kg_day,renal_caution,"
                      "pregnancy_avoid,cold_chain,barcode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", MEDICINES)
    if not one(c, "SELECT 1 FROM icd10"):
        c.executemany("INSERT INTO icd10(code,title) VALUES(?,?)", ICD10)
    if not one(c, "SELECT 1 FROM services"):
        c.executemany("INSERT INTO services(name,cat,rate_p,gst_pct) VALUES(?,?,?,?)", [(n, cat, r * 100, g) for n, cat, r, g in SERVICES])
    if not one(c, "SELECT 1 FROM lab_tests"):
        for code, name, sample, rate, tat, params in LAB_TESTS:
            s = c.execute("INSERT INTO services(name,cat,rate_p,gst_pct) VALUES(?,?,?,0)", (f"Lab: {name}", "Laboratory", rate * 100))
            t = c.execute("INSERT INTO lab_tests(code,name,sample,service_id,tat_hours) VALUES(?,?,?,?,?)", (code, name, sample, s.lastrowid, tat))
            for i, (pn, unit, lo, hi, clo, chi, ref) in enumerate(params):
                c.execute("INSERT INTO lab_params(test_id,name,unit,low,high,crit_low,crit_high,ref_text,sort) VALUES(?,?,?,?,?,?,?,?,?)",
                          (t.lastrowid, pn, unit, lo, hi, clo, chi, ref or None, i))
    if not one(c, "SELECT 1 FROM templates"):
        for name, dx, icd, advice, items, tests, fu in TEMPLATES:
            its = []
            for mname, freq, days in items:
                m = one(c, "SELECT id FROM medicines WHERE name=?", (mname,))
                if m:
                    its.append({"medicine_id": m["id"], "freq": freq, "days": days})
            tids = [r[0] for r in c.execute(f"SELECT id FROM lab_tests WHERE code IN ({','.join('?' * len(tests))})", tests)] if tests else []
            c.execute("INSERT INTO templates(name,diagnosis,icd,advice,items,tests,followup_days) VALUES(?,?,?,?,?,?,?)", (name, dx, icd, advice, json.dumps(its), json.dumps(tids), fu))


def init(demo=False, quiet=False):
    os.makedirs(DATA_DIR, exist_ok=True)
    c = db()
    migrate(c)
    for k, v in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v))
    c.execute("BEGIN IMMEDIATE")
    seed_reference(c)
    c.execute("COMMIT")
    if one(c, "SELECT 1 FROM users"):
        return None
    from .m_admin import make_user
    pw = secrets.token_urlsafe(9)
    make_user(c, {"username": "owner", "name": "Owner", "role": "owner", "password": pw})
    note = f"Owner login\n  Username: owner\n  Password: {pw}\n"
    if demo:
        note += load_demo(c, pw)
    path = os.path.join(BASE, "FIRST-LOGIN.txt")
    with open(path, "w") as f:
        f.write(note + "\nSign in, change the password (top right), turn on two-step sign-in, then delete this file.\n")
    if not quiet:
        print(f"\n  First run: logins saved in {path}\n")
    return pw


def load_demo(c, pw):
    from .m_admin import make_user
    from .m_billing import create_invoice
    from .m_pharmacy import create_bill, default_rack
    rnd = random.Random(7)
    c.execute("UPDATE settings SET value='Sunrise Healthcare Group' WHERE key='org_name'")
    for code, name, kind in (("CH", "City Hospital", "hospital+pharmacy"), ("NH", "North Hospital", "hospital+pharmacy"), ("TC", "Town Clinic", "hospital"),
                             ("MS", "Main Street Medicals", "pharmacy")):
        c.execute("INSERT INTO branches(code,name,kind,address,phone,gstin,dl_no) VALUES(?,?,?,?,?,?,?)",
                  (code, name, kind, f"{name} Road, Hyderabad", "04012345678", "36ABCDE1234F1Z5", f"TS/HYD/20B-{rnd.randint(1000, 9999)}"))
    staff = [("dr.rao", "Dr. Rao", "doctor", 1, "TSMC-12345", 30), ("dr.khan", "Dr. Khan", "doctor", 2, "TSMC-24680", 30), ("dr.meena", "Dr. Meena", "doctor", 3, "TSMC-67890", 40),
             ("nurse.ch", "Sister Mary", "nurse", 1, "", 0), ("reception.ch", "Anita", "reception", 1, "", 0), ("pharma.ch", "Suresh", "pharmacist", 1, "", 0),
             ("pharma.ms", "Imran", "pharmacist", 4, "", 0), ("lab.ch", "Ravi Teja", "lab_tech", 1, "", 0), ("manager.ch", "Priya", "manager", 1, "", 0),
             ("accounts", "Lakshman", "accountant", None, "", 0)]
    for u, n, r, b, reg, pct in staff:
        make_user(c, {"username": u, "name": n, "role": r, "branch_id": b, "reg_no": reg, "password": pw, "payout_pct": pct})
    c.execute("INSERT INTO suppliers(name,phone,gstin) VALUES('Apollo Distributors','9800000001','36AAACA1234F1Z5'),('MedPlus Wholesale','9800000002','36AAACM5678F1Z5')")
    for bid in (1, 2):
        for ward, kind, n in (("General", "general", 6), ("Private", "private", 3), ("ICU", "icu", 2)):
            sid = one(c, "SELECT id FROM services WHERE name=?", ({"general": "General ward bed, per day", "private": "Private room, per day", "icu": "ICU bed, per day"}[kind],))["id"]
            for i in range(1, n + 1):
                c.execute("INSERT INTO beds(branch_id,ward,number,kind,service_id) VALUES(?,?,?,?,?)", (bid, ward, f"{ward[0]}{i}", kind, sid))
    meds = [dict(r) for r in c.execute("SELECT * FROM medicines")]
    for bid in (1, 2, 4):
        for m in meds:
            mrp = rnd.choice([2, 3, 5, 8, 12, 25, 40, 95]) * 100 if m["form"] in ("Tablet", "Capsule") else rnd.choice([45, 85, 120, 450]) * 100
            for _ in range(rnd.choice([1, 2])):
                exp = add_days(today(), rnd.choice([-5, 20, 45, 80, 200, 400, 600]))
                c.execute("INSERT INTO batches(branch_id,medicine_id,batch,expiry,qty,mrp_p,cost_p,rack,received_at) VALUES(?,?,?,?,?,?,?,?,?)",
                          (bid, m["id"], f"B{rnd.randint(1000, 9999)}", exp, rnd.choice([30, 60, 150, 300, 500]), mrp, int(mrp * 0.7), default_rack(c, m["id"]), now_str()))
    people = [("Ravi Kumar", 62, "Male", "asthma", "penicillin", 72), ("Lakshmi Devi", 28, "Female", "", "", 58), ("Arjun Singh", 35, "Male", "", "", 70),
              ("Fatima Begum", 54, "Female", "kidney disease", "sulfa", 64), ("John Mathew", 70, "Male", "type 2 diabetes, hypertension", "nsaid", 80),
              ("Meena Kumari", 8, "Female", "", "", 24), ("Sai Krishna", 41, "Male", "", "", 76), ("Ayesha Khan", 33, "Female", "", "", 61),
              ("Venkat Reddy", 58, "Male", "hypertension", "", 82), ("Priyanka Sharma", 25, "Female", "", "", 55)]
    for i, (n, a, g, cond, al, wt) in enumerate(people):
        c.execute("INSERT INTO patients(name,age,gender,phone,address,allergies,conditions,weight,branch_id,created_at,consent_at,whatsapp_ok) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
                  (n, a, g, f"98765{43210 + i}", "Hyderabad", al, cond, wt, 1 + (i % 3 == 1), add_days(today(), -30) + " 10:00", add_days(today(), -30) + " 10:00"))
    c.execute("UPDATE patients SET lmp=? WHERE name='Lakshmi Devi'", (add_days(today(), -150),))
    owner = dict(one(c, "SELECT * FROM users WHERE username='owner'"))
    otc = [m for m in meds if m["schedule"] == "OTC" and m["form"] in ("Tablet", "Sachet")]
    docs = {1: 2, 2: 3, 3: 4}
    dx = [("Viral fever", "B34.9"), ("Acute bronchitis", "J20.9"), ("Essential hypertension", "I10"), ("Type 2 diabetes mellitus", "E11.9"), ("Gastritis", "K29.7"),
          ("Low back pain", "M54.5"), ("Allergic rhinitis", "J30.4"), ("Urinary tract infection", "N39.0"), ("Migraine", "G43.9")]
    consult = one(c, "SELECT * FROM services WHERE name='OPD consultation, general'")
    extras = [dict(r) for r in c.execute("SELECT * FROM services WHERE cat IN ('Procedure','Diagnostics','Imaging','Laboratory')")]
    for back in range(30, 0, -1):
        day = add_days(today(), -back)
        for bid in (1, 2, 4):
            h = SimpleNamespace(user=owner, branch=bid)
            for _ in range(rnd.randint(2, 6)):
                m = rnd.choice(otc)
                try:
                    r = create_bill(c, h, {"customer": "Walk-in", "items": [{"medicine_id": m["id"], "qty": rnd.randint(1, 10)}], "pay_mode": rnd.choice(["cash", "upi", "card"]), "override": True})
                    c.execute("UPDATE bills SET created_at=? WHERE id=?", (f"{day} {rnd.randint(9, 20):02d}:{rnd.randint(0, 59):02d}", r["id"]))
                except Exception:
                    pass
        for bid in (1, 2, 3):
            h = SimpleNamespace(user=owner, branch=bid)
            for _ in range(rnd.randint(2, 5)):
                p = rnd.randint(1, len(people))
                t = f"{day} {rnd.choice([9, 10, 11, 12, 17, 18, 19]):02d}:{rnd.randint(0, 59):02d}"
                d, icd = rnd.choice(dx)
                v = c.execute("INSERT INTO visits(patient_id,branch_id,doctor_id,created_at,complaint,triage,diagnosis,icd,status,completed_at,temp,pulse,bp_sys,bp_dia) "
                              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (p, bid, docs[bid], t, "follow-up" if rnd.random() < .3 else "fever, body ache", rnd.choice(["normal"] * 6 + ["urgent"]),
                                                                        d, icd, "done", t, 37.0 + rnd.random() * 1.5, rnd.randint(70, 105), rnd.randint(110, 165), rnd.randint(70, 95)))
                c.execute("INSERT INTO vitals(patient_id,at,source,ref_id,bp_sys,bp_dia,pulse) VALUES(?,?,?,?,?,?,?)", (p, t, "opd", v.lastrowid, rnd.randint(110, 165), rnd.randint(70, 95), rnd.randint(70, 105)))
                items = [{"service_id": consult["id"]}] + [{"service_id": e["id"]} for e in rnd.sample(extras, rnd.randint(0, 2))]
                inv = create_invoice(c, h, p, items, doctor_id=docs[bid], visit_id=v.lastrowid)
                c.execute("UPDATE invoices SET created_at=? WHERE id=?", (t, inv["id"]))
                roll = rnd.random()
                pay = inv["total_p"] if roll < .75 else inv["total_p"] // 2 if roll < .9 else 0
                if pay:
                    c.execute("INSERT INTO payments(branch_id,invoice_id,at,mode,amount_p,ref,user_id,kind) VALUES(?,?,?,?,?,?,?,?)",
                              (bid, inv["id"], t, rnd.choice(["cash", "cash", "upi", "card"]), pay, "", owner["id"], "payment"))
    from .safety import triage
    for pid, comp, vit in ((1, "breathless, chest pain", (37.2, 118, 165, 90, 91)), (3, "fever, body ache", (38.6, 96, 120, 80, 98)), (5, "knee pain", (36.9, 76, 130, 85, 99))):
        lvl, why = triage({"complaint": comp, "temp": vit[0], "pulse": vit[1], "bp_sys": vit[2], "spo2": vit[4]})
        c.execute("INSERT INTO visits(patient_id,branch_id,created_at,complaint,temp,pulse,bp_sys,bp_dia,spo2,triage,triage_reasons) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (pid, 1, now_str(), comp, *vit, lvl, why))
    for i, (pid, slot) in enumerate(((7, "17:00"), (8, "17:10"), (9, "17:20"))):
        c.execute("INSERT INTO appointments(branch_id,patient_id,doctor_id,day,slot,token,status,source,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (1, pid, 2, today(), slot, i + 1, "booked", "phone", now_str()))
    bed = one(c, "SELECT * FROM beds WHERE branch_id=1 AND ward='General' ORDER BY id")
    at = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    a = c.execute("INSERT INTO admissions(branch_id,ip_no,patient_id,bed_id,doctor_id,admitted_at,reason,diagnosis,icd,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (1, "CH/IP/00001", 9, bed["id"], 2, at, "High BP with headache", "Hypertensive urgency", "I10", "admitted"))
    c.execute("INSERT INTO bed_moves(admission_id,bed_id,from_at) VALUES(?,?,?)", (a.lastrowid, bed["id"], at))
    c.execute("UPDATE beds SET status='occupied' WHERE id=?", (bed["id"],))
    c.execute("INSERT INTO payments(branch_id,admission_id,at,mode,amount_p,ref,user_id,kind) VALUES(1,?,?,'cash',1000000,'',?, 'deposit')", (a.lastrowid, at, owner["id"]))
    telma = one(c, "SELECT id FROM medicines WHERE name='Telma 40'")
    c.execute("INSERT INTO mar_orders(admission_id,medicine_id,dose,route,freq,start_at,ordered_by,active) VALUES(?,?,?,?,?,?,?,1)", (a.lastrowid, telma["id"], "1", "oral", "OD", at, 2))
    c.execute("INSERT INTO ipd_notes(admission_id,at,user_id,kind,text) VALUES(?,?,?,?,?)", (a.lastrowid, at, 2, "round", "BP 190/110 on admission. Started Telma 40 OD. Monitor BP 4-hourly."))
    # supplier bills still to pay: one overdue, one due this week, one later
    for bid in (1, 2, 4):
        for sup, inv, days_ago, due_in, amt in ((1, f"APD/{bid}/2291", 34, -4, 1842050), (2, f"MPW/{bid}/0715", 25, 3, 960000), (1, f"APD/{bid}/2350", 6, 24, 2315075)):
            c.execute("INSERT INTO purchases(branch_id,supplier_id,invoice_no,created_at,user_id,total_p,gst_p,due_date,paid_p) VALUES(?,?,?,?,?,?,?,?,0)",
                      (bid, sup, inv, (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M"), owner["id"], amt, round(amt * 0.12),
                       (datetime.now() + timedelta(days=due_in)).strftime("%Y-%m-%d")))
    c.execute("DELETE FROM audit")
    return ("\nDemo staff logins (same password as owner):\n  " +
            "\n  ".join(f"{u:<14} {r:<11} {['All branches', 'City Hospital', 'North Hospital', 'Town Clinic', 'Main Street Medicals'][b or 0]}" for u, n, r, b, _, _ in staff) + "\n")
