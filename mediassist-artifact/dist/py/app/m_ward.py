"""Ward round and nursing depth: early-warning score (NEWS2) from the latest vitals, a vitals schedule with
overdue alerts, intake/output chart, structured shift handover; owner analytics (doctor productivity, bed
occupancy, average stay, pharmacy margin by supplier, patient retention, branch benchmarks); insurance claim
ageing and a TPA document pack."""
import io
import json
import zipfile
from datetime import datetime, timedelta

from .core import (R, add_days, all_access, as_int, audit, clean, in_tx, need, need_branch, now_str, one, opt_num, pcode, qget, route, rows, rs, today)


# ---------------------------------------------------------------- NEWS2
def news2(v):
    """National Early Warning Score 2 from one set of vitals. Returns (score, parts, band). Missing values score 0 and are listed."""
    if not v:
        return None
    s, parts, missing = 0, [], []

    def add(name, val, pts):
        nonlocal s
        if pts:
            parts.append(f"{name} {val} (+{pts})")
        s += pts
    rr = v.get("resp_rate")
    if rr is None:
        missing.append("RR")
    else:
        add("RR", rr, 3 if rr <= 8 else 1 if rr <= 11 else 0 if rr <= 20 else 2 if rr <= 24 else 3)
    sp = v.get("spo2")
    if sp is None:
        missing.append("SpO2")
    else:
        add("SpO2", sp, 3 if sp <= 91 else 2 if sp <= 93 else 1 if sp <= 95 else 0)
    sbp = v.get("bp_sys")
    if sbp is None:
        missing.append("BP")
    else:
        add("SBP", sbp, 3 if sbp <= 90 else 2 if sbp <= 100 else 1 if sbp <= 110 else 0 if sbp <= 219 else 3)
    hr = v.get("pulse")
    if hr is None:
        missing.append("pulse")
    else:
        add("Pulse", hr, 3 if hr <= 40 else 1 if hr <= 50 else 0 if hr <= 90 else 1 if hr <= 110 else 2 if hr <= 130 else 3)
    t = v.get("temp")
    if t is None:
        missing.append("temp")
    else:
        add("Temp", t, 3 if t <= 35.0 else 1 if t <= 36.0 else 0 if t <= 38.0 else 1 if t <= 39.0 else 2)
    g = v.get("gcs")
    if g is not None:
        add("Consciousness", f"GCS {g}", 0 if g >= 15 else 3)
    else:
        missing.append("GCS")
    single3 = any("(+3)" in p for p in parts)
    band = "high" if s >= 7 else "medium" if s >= 5 or single3 else "low-medium" if s >= 1 else "low"
    action = {"high": "Urgent doctor review now; consider ICU", "medium": "Doctor to review within 30 min; vitals hourly",
              "low-medium": "Vitals every 4-6 h; inform the doctor on rounds", "low": "Routine monitoring"}[band]
    return {"score": s, "parts": parts, "missing": missing, "band": band, "action": action, "at": v.get("at")}


def vitals_status(c, a):
    """Latest vitals of an admission, its NEWS2, and whether the next set is overdue per the plan."""
    v = one(c, "SELECT * FROM vitals WHERE patient_id=? AND at>=? ORDER BY at DESC LIMIT 1", (a["patient_id"], a["admitted_at"]))
    every = a["vitals_every_h"] if "vitals_every_h" in a.keys() and a["vitals_every_h"] else None
    due_at = overdue = None
    if every:
        last = datetime.strptime(v["at"][:16], "%Y-%m-%d %H:%M") if v else datetime.strptime(a["admitted_at"][:16], "%Y-%m-%d %H:%M")
        due_at = (last + timedelta(hours=every)).strftime("%Y-%m-%d %H:%M")
        overdue = due_at < now_str()
    return {"last": dict(v) if v else None, "news2": news2(dict(v)) if v else None, "every_h": every, "due_at": due_at, "overdue": overdue}


@route("POST", r"/api/admissions/(\d+)/vitals-plan", "ipd")
def api_vitals_plan(h, c, b, q, aid):
    from .m_ipd import adm_or_404
    a = adm_or_404(c, h, int(aid))
    every = opt_num(b.get("every_h"), int, "hours")
    need(every is None or 1 <= every <= 24, "Vitals every 1 to 24 hours, or blank for no schedule")
    c.execute("UPDATE admissions SET vitals_every_h=? WHERE id=?", (every, a["id"]))
    audit(c, h, "ipd.vitals_plan", f"{a['ip_no']} every {every or '-'} h")
    return {"ok": True}


# ---------------------------------------------------------------- intake / output
IO_KINDS = {"in": ("oral", "iv", "ng", "blood", "other"), "out": ("urine", "vomit", "drain", "stool", "other")}


@route("POST", r"/api/admissions/(\d+)/io", "ipd")
def api_io_add(h, c, b, q, aid):
    from .m_ipd import adm_or_404
    a = adm_or_404(c, h, int(aid))
    need(a["status"] == "admitted", "Patient is not admitted")
    kind, what = clean(b, "kind", 3), clean(b, "what", 10) or "other"
    need(kind in IO_KINDS and what in IO_KINDS[kind], "Kind must be in/out with a valid route")
    ml = opt_num(b.get("ml"), int, "ml")
    need(ml is not None and 0 < ml <= 10000, "Enter the volume in ml")
    c.execute("INSERT INTO io_chart(admission_id,at,kind,what,ml,user_id,note) VALUES(?,?,?,?,?,?,?)", (a["id"], clean(b, "at", 16) or now_str(), kind, what, ml, h.user["id"], clean(b, "note", 200)))
    audit(c, h, "ipd.io", f"{a['ip_no']} {kind} {what} {ml} ml")
    return {"ok": True}


def io_summary(c, aid):
    out = rows(c.execute("SELECT io.*, u.name uname FROM io_chart io LEFT JOIN users u ON u.id=io.user_id WHERE admission_id=? ORDER BY io.at DESC LIMIT 100", (aid,)))
    since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
    tin = sum(x["ml"] for x in out if x["kind"] == "in" and x["at"] >= since)
    tout = sum(x["ml"] for x in out if x["kind"] == "out" and x["at"] >= since)
    return {"rows": out, "in_24h": tin, "out_24h": tout, "balance_24h": tin - tout}


# ---------------------------------------------------------------- handover
@route("POST", r"/api/admissions/(\d+)/handover", "ipd")
def api_handover(h, c, b, q, aid):
    """Structured shift handover (SBAR): kept as a note the next shift reads first."""
    from .m_ipd import adm_or_404
    a = adm_or_404(c, h, int(aid))
    parts = [(k, clean(b, k, 1500)) for k in ("situation", "background", "assessment", "recommendation")]
    need(any(v for _, v in parts), "Write at least the situation")
    text = "\n".join(f"{k.capitalize()}: {v}" for k, v in parts if v)
    c.execute("INSERT INTO ipd_notes(admission_id,at,user_id,kind,text) VALUES(?,?,?,?,?)", (a["id"], now_str(), h.user["id"], "handover", text))
    audit(c, h, "ipd.handover", a["ip_no"])
    return {"ok": True}


# ---------------------------------------------------------------- ward watch: who needs eyes on them
@route("GET", "/api/ward/watch", "any")
def api_ward_watch(h, c, b, q):
    """Inpatients with a medium/high early-warning score, overdue vitals, or no vitals in 12 hours."""
    need(h.branch, "Choose a branch")
    out = []
    for a in rows(c.execute("SELECT a.*, p.name pname, bd.ward, bd.number bed FROM admissions a JOIN patients p ON p.id=a.patient_id LEFT JOIN beds bd ON bd.id=a.bed_id "
                            "WHERE a.branch_id=? AND a.status='admitted' ORDER BY bd.ward, bd.number", (h.branch,))):
        st = vitals_status(c, a)
        flags = []
        if st["news2"] and st["news2"]["band"] in ("medium", "high"):
            flags.append(f"NEWS2 {st['news2']['score']} ({st['news2']['band']})")
        if st["overdue"]:
            flags.append(f"vitals overdue since {st['due_at'][11:]}")
        last_at = st["last"]["at"] if st["last"] else a["admitted_at"]
        if last_at < (datetime.now() - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M"):
            flags.append("no vitals in 12 h")
        if flags:
            out.append({"admission_id": a["id"], "ip_no": a["ip_no"], "pname": a["pname"], "code": pcode(a["patient_id"]), "bed": f"{a['ward'] or ''} {a['bed'] or ''}".strip(),
                        "flags": flags, "score": st["news2"]["score"] if st["news2"] else None, "band": st["news2"]["band"] if st["news2"] else None})
    out.sort(key=lambda x: -(x["score"] or 0))
    return out


# ---------------------------------------------------------------- owner analytics
@route("GET", "/api/analytics/owner", "reports")
def api_owner_analytics(h, c, b, q):
    from .m_reports import bids_scope
    bids = bids_scope(c, h)
    days = as_int(qget(q, "days", "30"), "days", 7, 365)
    since = add_days(today(), -days)
    p = ",".join("?" * len(bids))
    # doctor productivity: visits, minutes per visit (arrival to completion), revenue billed under them
    docs = []
    for d in rows(c.execute(f"SELECT u.id, u.name, COUNT(*) n, AVG((julianday(v.completed_at)-julianday(v.created_at))*1440) mins FROM visits v JOIN users u ON u.id=v.doctor_id "
                            f"WHERE v.branch_id IN ({p}) AND v.status='done' AND v.completed_at>=? AND v.complaint IS NOT 'Discharge' GROUP BY u.id ORDER BY n DESC", (*bids, since))):
        rev = c.execute(f"SELECT COALESCE(SUM(total_p),0) FROM invoices WHERE doctor_id=? AND branch_id IN ({p}) AND cancelled_at IS NULL AND created_at>=?", (d["id"], *bids, since)).fetchone()[0]
        days_worked = c.execute(f"SELECT COUNT(DISTINCT substr(completed_at,1,10)) FROM visits WHERE doctor_id=? AND branch_id IN ({p}) AND status='done' AND completed_at>=?", (d["id"], *bids, since)).fetchone()[0]
        docs.append({"name": d["name"], "visits": d["n"], "per_day": round(d["n"] / days_worked, 1) if days_worked else 0, "minutes": round(d["mins"] or 0), "revenue": R(rev), "per_visit": R(rev / d["n"]) if d["n"] else 0})
    # beds: occupancy by ward over the period (bed-days used / bed-days available), average stay
    wards = []
    for w in rows(c.execute(f"SELECT bd.branch_id, bd.ward, COUNT(*) beds FROM beds bd WHERE bd.branch_id IN ({p}) GROUP BY bd.branch_id, bd.ward", bids)):
        used = c.execute("SELECT COALESCE(SUM(julianday(MIN(COALESCE(bm.to_at, ?), ?)) - julianday(MAX(bm.from_at, ?))),0) FROM bed_moves bm JOIN beds bd ON bd.id=bm.bed_id "
                         "WHERE bd.branch_id=? AND bd.ward=? AND bm.from_at<=? AND COALESCE(bm.to_at, ?)>=?",
                         (now_str(), now_str(), since + " 00:00", w["branch_id"], w["ward"], now_str(), now_str(), since + " 00:00")).fetchone()[0]
        avail = w["beds"] * days
        wards.append({"ward": w["ward"], "beds": w["beds"], "occupancy_pct": round(min(100, used / avail * 100)) if avail else 0})
    alos = c.execute(f"SELECT AVG(julianday(discharged_at)-julianday(admitted_at)), COUNT(*) FROM admissions WHERE branch_id IN ({p}) AND status='discharged' AND discharged_at>=?", (*bids, since)).fetchone()
    # pharmacy margin by supplier: sales at MRP minus cost of the batches sold
    sup = rows(c.execute(f"SELECT COALESCE(s.name,'(no supplier)') supplier, SUM((bi.qty-bi.returned)*bi.mrp_p) sales_p, SUM((bi.qty-bi.returned)*bt.cost_p) cost_p FROM bill_items bi "
                         f"JOIN bills b ON b.id=bi.bill_id JOIN batches bt ON bt.id=bi.batch_id LEFT JOIN purchases pu ON pu.id=bt.purchase_id LEFT JOIN suppliers s ON s.id=pu.supplier_id "
                         f"WHERE b.branch_id IN ({p}) AND b.created_at>=? GROUP BY s.id ORDER BY sales_p DESC", (*bids, since)))
    margin = [{"supplier": x["supplier"], "sales": R(x["sales_p"] or 0), "cost": R(x["cost_p"] or 0), "margin_pct": round((1 - (x["cost_p"] or 0) / x["sales_p"]) * 100, 1) if x["sales_p"] else 0} for x in sup]
    # retention: of patients first seen 90-180 days ago, how many came back within 90 days
    cohort = rows(c.execute(f"SELECT patient_id, MIN(created_at) first FROM visits WHERE branch_id IN ({p}) GROUP BY patient_id HAVING first BETWEEN ? AND ?", (*bids, add_days(today(), -180), add_days(today(), -90))))
    back = 0
    for r in cohort:
        if one(c, "SELECT 1 FROM visits WHERE patient_id=? AND created_at>? AND created_at<=?", (r["patient_id"], r["first"], add_days(r["first"][:10], 90))):
            back += 1
    # branch benchmarks
    bench = []
    for bid in bids:
        br = one(c, "SELECT code, name FROM branches WHERE id=?", (bid,))
        v = c.execute("SELECT COUNT(*) FROM visits WHERE branch_id=? AND status='done' AND completed_at>=? AND complaint IS NOT 'Discharge'", (bid, since)).fetchone()[0]
        rev = c.execute("SELECT COALESCE(SUM(total_p),0) FROM invoices WHERE branch_id=? AND cancelled_at IS NULL AND created_at>=?", (bid, since)).fetchone()[0]
        ph = c.execute("SELECT COALESCE(SUM(total_p-returned_p),0) FROM bills WHERE branch_id=? AND created_at>=?", (bid, since)).fetchone()[0]
        beds = c.execute("SELECT COUNT(*) FROM beds WHERE branch_id=?", (bid,)).fetchone()[0]
        bench.append({"code": br["code"], "name": br["name"], "visits": v, "hospital": R(rev), "pharmacy": R(ph), "per_visit": R(rev / v) if v else 0, "per_bed_day": R(rev / (beds * days)) if beds else None})
    return {"days": days, "doctors": docs, "wards": wards, "alos": round(alos[0], 1) if alos[0] else None, "discharges": alos[1], "margin": margin,
            "retention": {"cohort": len(cohort), "returned": back, "pct": round(back / len(cohort) * 100) if cohort else None}, "branches": bench}


# ---------------------------------------------------------------- insurance: ageing and TPA pack
@route("GET", "/api/claims/ageing", "hbilling")
def api_claim_ageing(h, c, b, q):
    need_branch(h, c, "hospital")
    buckets = {"0-7": 0, "8-15": 0, "16-30": 0, "31+": 0}
    amounts = dict.fromkeys(buckets, 0)
    by_tpa = {}
    for cl in rows(c.execute("SELECT cl.*, i.branch_id FROM claims cl JOIN invoices i ON i.id=cl.invoice_id WHERE i.branch_id=? AND cl.status IN ('preauth','query','approved')", (h.branch,))):
        age = (datetime.now() - datetime.strptime(cl["created_at"][:10], "%Y-%m-%d")).days
        k = "0-7" if age <= 7 else "8-15" if age <= 15 else "16-30" if age <= 30 else "31+"
        amt = cl["approved_p"] or cl["requested_p"]
        buckets[k] += 1
        amounts[k] += amt
        t = by_tpa.setdefault(cl["tpa"], {"tpa": cl["tpa"], "open": 0, "amount_p": 0, "oldest": 0})
        t["open"] += 1
        t["amount_p"] += amt
        t["oldest"] = max(t["oldest"], age)
    return {"buckets": [{"range": k, "count": buckets[k], "amount": R(amounts[k])} for k in buckets],
            "by_tpa": sorted([dict(x, amount=R(x["amount_p"])) for x in by_tpa.values()], key=lambda x: -x["amount_p"])}


def discharge_pdf(c, aid):
    """Discharge summary as a PDF (the screen had print only)."""
    from .m_pdf import INK, MUTED, TEAL, Pdf, _age, _br, _dt, _pt, letterhead
    a = one(c, "SELECT a.*, u.name dname, u.reg_no dreg FROM admissions a LEFT JOIN users u ON u.id=a.doctor_id WHERE a.id=?", (aid,))
    need(a and a["status"] == "discharged", "Discharge summary not ready", 404)
    br, p = _br(c, a["branch_id"]), _pt(c, a["patient_id"])
    s = json.loads(a["summary"]) if a["summary"] else {}
    pdf = Pdf(f"Discharge summary {a['ip_no']}")
    letterhead(pdf, c, br, "DISCHARGE SUMMARY", [a["ip_no"], "Admitted " + _dt(a["admitted_at"]), "Discharged " + _dt(a["discharged_at"]) + f" ({a['discharge_type']})"])
    pdf.kv_box([("Patient", p["name"]), ("Patient ID", pcode(p["id"])), ("Age / Gender", _age(p)), ("Treating doctor", (a["dname"] or "") + (f" (Reg. {a['dreg']})" if a["dreg"] else "")),
                ("Allergies", p["allergies"] or "None recorded"), ("Final diagnosis", (s.get("final_diagnosis") or a["diagnosis"] or "") + (f" ({s.get('icd')})" if s.get("icd") else ""))])
    for key, title in (("history", "History and presenting complaint"), ("course", "Course in hospital"), ("procedures", "Procedures"), ("investigations", "Key investigations"),
                       ("condition", "Condition at discharge"), ("advice", "Advice")):
        if s.get(key):
            pdf.need_space(40)
            pdf.text(pdf.M, pdf.y - 12, title, 11, True, TEAL)
            pdf.y -= 16
            pdf.para(s[key], 10)
    rx = rows(c.execute("SELECT r.*, m.name, m.form FROM rx_items r JOIN medicines m ON m.id=r.medicine_id WHERE r.admission_id=?", (aid,)))
    if rx or s.get("medications"):
        from .rx_words import how_to_take
        pdf.need_space(40)
        pdf.text(pdf.M, pdf.y - 12, "Medicines at discharge", 11, True, TEAL)
        pdf.y -= 16
        if rx:
            pdf.table([("Medicine", 170, "left"), ("Dose", 50, "left"), ("When", 60, "left"), ("Days", 35, "right"), ("How to take", 200, "left")],
                      [[x["name"], x["dose"] or "", x["freq"] or "", str(x["days"] or ""), how_to_take(x, "en")] for x in rx])
        if s.get("medications"):
            pdf.para(s["medications"], 10)
    if s.get("followup"):
        pdf.para("Follow-up on " + s["followup"], 10.5, True, TEAL)
    pdf.need_space(60)
    pdf.y -= 30
    pdf.line(pdf.W - pdf.M - 180, pdf.y, pdf.W - pdf.M, pdf.y, INK)
    pdf.text(pdf.W - pdf.M, pdf.y - 12, a["dname"] or "", 10, True, INK, "right")
    if a["dreg"]:
        pdf.text(pdf.W - pdf.M, pdf.y - 24, "Reg. " + a["dreg"], 8, False, MUTED, "right")
    return pdf.bytes(f"{br['name']} - discharge summary {a['ip_no']}"), f"Discharge-{a['ip_no'].replace('/', '-')}.pdf", a


@route("GET", r"/api/claims/(\d+)/pack", "hbilling")
def api_claim_pack(h, c, b, q, cid):
    """Everything the TPA asks for, in one zip: cover sheet, invoice, discharge summary, every verified lab report of the stay, prescriptions."""
    from .m_pdf import MUTED, Pdf, _age, _br, _dt, _pt, letterhead, make
    cl = one(c, "SELECT cl.*, i.branch_id, i.inv_no, i.visit_id, i.admission_id adm2, i.total_p FROM claims cl JOIN invoices i ON i.id=cl.invoice_id WHERE cl.id=?", (int(cid),))
    need(cl and (cl["branch_id"] == h.branch or all_access(h.user)), "Claim not found", 404)
    br, p = _br(c, cl["branch_id"]), _pt(c, cl["patient_id"])
    aid = cl["admission_id"] or cl["adm2"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        pdf = Pdf(f"Claim {cl['id']}")
        letterhead(pdf, c, br, "INSURANCE CLAIM COVER SHEET", [f"Claim ref {cl['claim_no'] or cl['id']}", _dt(cl["created_at"]), cl["status"].upper()])
        pdf.kv_box([("Patient", p["name"]), ("Patient ID", pcode(p["id"])), ("Age / Gender", _age(p)), ("Phone", p["phone"] or ""), ("TPA / insurer", cl["tpa"]), ("Policy", cl["policy"] or "-"),
                    ("Invoice", cl["inv_no"]), ("Invoice total", rs(cl["total_p"])), ("Requested", rs(cl["requested_p"])), ("Approved", rs(cl["approved_p"]) if cl["approved_p"] else "-"), ("ICD-10", cl["icd"] or "-"),
                    ("Admission", one(c, "SELECT ip_no FROM admissions WHERE id=?", (aid,))["ip_no"] if aid else "OPD")])
        docs = ["Cover sheet", "Invoice " + cl["inv_no"]]
        z.writestr("01-invoice.pdf", make(c, "invoice", cl["invoice_id"])[0])
        if aid:
            a = one(c, "SELECT status FROM admissions WHERE id=?", (aid,))
            if a and a["status"] == "discharged":
                z.writestr("02-discharge-summary.pdf", discharge_pdf(c, aid)[0])
                docs.append("Discharge summary")
        n = 3
        for o in rows(c.execute("SELECT id FROM lab_orders WHERE patient_id=? AND status='verified' AND (admission_id=? OR visit_id=? OR invoice_id=?) ORDER BY id", (p["id"], aid or -1, cl["visit_id"] or -1, cl["invoice_id"]))):
            z.writestr(f"{n:02d}-lab-LAB{o['id']}.pdf", make(c, "lab", o["id"])[0])
            docs.append(f"Lab report LAB{o['id']}")
            n += 1
        if cl["visit_id"]:
            z.writestr(f"{n:02d}-prescription.pdf", make(c, "rx", cl["visit_id"])[0])
            docs.append("Prescription")
        pdf.para("Documents enclosed: " + "; ".join(docs), 10)
        ev = rows(c.execute("SELECT e.*, u.name uname FROM claim_events e LEFT JOIN users u ON u.id=e.user_id WHERE claim_id=? ORDER BY e.id", (cl["id"],)))
        if ev:
            pdf.table([("When", 110, "left"), ("Status", 80, "left"), ("Note", 325, "left")], [[_dt(e["at"]), e["status"], e["note"] or ""] for e in ev])
        pdf.para("Generated by MediAssist. Reports are verified electronically.", 8, color=MUTED)
        z.writestr("00-cover-sheet.pdf", pdf.bytes(f"{br['name']} - claim pack"))
    audit(c, h, "claim.pack", f"claim {cl['id']} {cl['inv_no']} {len(docs)} documents")
    h.download = (f"Claim-{cl['inv_no'].replace('/', '-')}.zip", buf.getvalue(), "application/zip")
    return None
