"""Inpatients: beds, admission, transfers, rounds and nursing notes, medication orders and
administration record (MAR), ward charges, running bill, discharge summary and final invoice."""
import json
import re
import math
from datetime import datetime

from .core import (ApiError, P, R, add_days, as_int, audit, clean, in_tx, need, need_branch, now_str, one, opt_num, pcode, qget, route, rows,
                   rs, today, valid_day)
from .safety import dose_units, safety_check

BED_KINDS = {"general": "General ward bed, per day", "private": "Private room, per day", "icu": "ICU bed, per day"}


def adm_or_404(c, h, aid):
    a = one(c, "SELECT * FROM admissions WHERE id=? AND branch_id=?", (aid, h.branch))
    need(a, "Admission not found at this branch", 404)
    return a


def svc_by_name(c, name):
    return one(c, "SELECT * FROM services WHERE name=?", (name,))


# ---------------------------------------------------------------- beds
@route("GET", "/api/beds", "patients_read")
def api_beds(h, c, b, q):
    br = need_branch(h, c, "hospital")
    out = rows(c.execute("SELECT bd.*, a.id adm_id, a.ip_no, a.admitted_at, a.diagnosis, p.name pname, p.age, p.gender, p.id pid, u.name dname FROM beds bd "
                         "LEFT JOIN admissions a ON a.bed_id=bd.id AND a.status='admitted' LEFT JOIN patients p ON p.id=a.patient_id "
                         "LEFT JOIN users u ON u.id=a.doctor_id WHERE bd.branch_id=? ORDER BY bd.ward, bd.number", (br["id"],)))
    for x in out:
        x["code"] = pcode(x["pid"]) if x["pid"] else None
    return out


@route("POST", "/api/beds", "stock_admin")
def api_bed_save(h, c, b, q):
    br = need_branch(h, c, "hospital")
    kind = clean(b, "kind", 10)
    need(kind in BED_KINDS, "Bed type must be general, private or icu")
    ward, number = clean(b, "ward", 30), clean(b, "number", 10)
    need(ward and number, "Enter the ward and bed number")
    s = svc_by_name(c, BED_KINDS[kind])
    try:
        c.execute("INSERT INTO beds(branch_id,ward,number,kind,service_id) VALUES(?,?,?,?,?)", (br["id"], ward, number, kind, s["id"] if s else None))
    except Exception:
        raise ApiError(400, "That bed already exists")
    audit(c, h, "bed.add", f"{ward}-{number} {kind}")
    return {"ok": True}


@route("POST", r"/api/beds/(\d+)/status", "ipd_nursing")
def api_bed_status(h, c, b, q, bid):
    st = clean(b, "status", 12)
    need(st in ("free", "cleaning", "blocked"), "Status must be free, cleaning or blocked")
    bd = one(c, "SELECT * FROM beds WHERE id=? AND branch_id=?", (int(bid), h.branch))
    need(bd and bd["status"] != "occupied", "An occupied bed can't be changed. Transfer or discharge the patient first.")
    c.execute("UPDATE beds SET status=? WHERE id=?", (st, bd["id"]))
    return {"ok": True}


# ---------------------------------------------------------------- admission
@route("POST", "/api/admissions", "ipd")
def api_admit(h, c, b, q):
    br = need_branch(h, c, "hospital")
    pid = as_int(b.get("patient_id"), "patient")
    need(one(c, "SELECT 1 FROM patients WHERE id=?", (pid,)), "Patient not found", 404)
    need(not one(c, "SELECT 1 FROM admissions WHERE patient_id=? AND status='admitted'", (pid,)), "This patient is already admitted")
    bed = one(c, "SELECT * FROM beds WHERE id=? AND branch_id=?", (as_int(b.get("bed_id"), "bed"), br["id"]))
    need(bed and bed["status"] == "free", "Choose a free bed")
    deposit = P(b.get("deposit"), "deposit")
    mode = clean(b, "mode", 10) or "cash"
    need(mode in ("cash", "upi", "card"), "Invalid payment mode")
    need(not deposit or mode == "cash" or clean(b, "ref", 40), "Enter the UPI or card reference for the deposit")

    def run():
        n = c.execute("SELECT COUNT(*) FROM admissions WHERE branch_id=?", (br["id"],)).fetchone()[0] + 1
        ip = f"{br['code']}/IP/{n:05d}"
        cur = c.execute("INSERT INTO admissions(branch_id,ip_no,patient_id,bed_id,doctor_id,admitted_at,reason,diagnosis,icd,status,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (br["id"], ip, pid, bed["id"], opt_num(b.get("doctor_id"), int) or (h.user["id"] if h.user["role"] == "doctor" else None), now_str(),
                         clean(b, "reason", 300), clean(b, "diagnosis", 300), clean(b, "icd", 10).upper() or None, "admitted", h.user["id"]))
        aid = cur.lastrowid
        c.execute("INSERT INTO bed_moves(admission_id,bed_id,from_at) VALUES(?,?,?)", (aid, bed["id"], now_str()))
        c.execute("UPDATE beds SET status='occupied' WHERE id=?", (bed["id"],))
        if deposit:
            c.execute("INSERT INTO payments(branch_id,admission_id,at,mode,amount_p,ref,user_id,kind) VALUES(?,?,?,?,?,?,?,?)",
                      (br["id"], aid, now_str(), mode, deposit, clean(b, "ref", 40), h.user["id"], "deposit"))
        audit(c, h, "ipd.admit", f"{ip} {pcode(pid)} bed {bed['ward']}-{bed['number']}{' deposit ' + rs(deposit) if deposit else ''}")
        return {"ok": True, "id": aid, "ip_no": ip}
    r = in_tx(c, run)
    from .m_alerts import on_admit
    on_admit(c, h, r["id"])
    return r


@route("GET", "/api/admissions", "patients_read")
def api_admissions(h, c, b, q):
    br = need_branch(h, c, "hospital")
    st = qget(q, "status", "admitted")
    out = rows(c.execute("SELECT a.*, p.name pname, p.age, p.gender, p.allergies, bd.ward, bd.number bed, u.name dname FROM admissions a JOIN patients p ON p.id=a.patient_id "
                         "LEFT JOIN beds bd ON bd.id=a.bed_id LEFT JOIN users u ON u.id=a.doctor_id WHERE a.branch_id=? AND a.status=? ORDER BY a.id DESC LIMIT 100", (br["id"], st)))
    for a in out:
        a["code"] = pcode(a["patient_id"])
    return out


def bed_lines(c, a, until=None):
    """Bed and nursing charges: each calendar day started counts as one day (hospital convention),
    charged at the bed the patient occupied for the most part of that stay segment."""
    lines = []
    end = until or now_str()
    nursing = one(c, "SELECT * FROM services WHERE name='Nursing charges, per day'")
    total_days = 0
    for mv in rows(c.execute("SELECT bm.*, bd.kind, bd.ward, bd.number, bd.service_id FROM bed_moves bm JOIN beds bd ON bd.id=bm.bed_id WHERE admission_id=? ORDER BY bm.id", (a["id"],))):
        start, stop = datetime.strptime(mv["from_at"], "%Y-%m-%d %H:%M"), datetime.strptime(mv["to_at"] or end, "%Y-%m-%d %H:%M")
        days = max(1, math.ceil((stop - start).total_seconds() / 86400 - 0.25)) if not lines else max(0, math.ceil((stop - start).total_seconds() / 86400 - 0.25))
        if not days:
            continue
        s = one(c, "SELECT * FROM services WHERE id=?", (mv["service_id"],)) if mv["service_id"] else None
        rate = s["rate_p"] if s else 0
        lines.append({"name": f"{(s or {}).get('name', 'Bed')} ({mv['ward']}-{mv['number']})", "cat": "Inpatient", "qty": days, "rate_p": rate, "amount_p": days * rate,
                      "service_id": s["id"] if s else None})
        total_days += days
    if nursing and total_days:
        lines.append({"name": nursing["name"], "cat": "Inpatient", "qty": total_days, "rate_p": nursing["rate_p"], "amount_p": total_days * nursing["rate_p"], "service_id": nursing["id"]})
    return lines, total_days


def running_bill(c, a):
    lines, days = bed_lines(c, a, a["discharged_at"])
    for ch in rows(c.execute("SELECT * FROM ipd_charges WHERE admission_id=? ORDER BY id", (a["id"],))):
        lines.append({"name": ch["name"], "cat": ch["cat"], "qty": ch["qty"], "rate_p": ch["rate_p"], "amount_p": ch["amount_p"], "service_id": ch["service_id"], "at": ch["at"]})
    for o in rows(c.execute("SELECT o.id, t.name, s.rate_p, s.id sid FROM lab_orders o JOIN lab_order_items i ON i.order_id=o.id JOIN lab_tests t ON t.id=i.test_id "
                            "LEFT JOIN services s ON s.id=t.service_id WHERE o.admission_id=? AND o.status<>'cancelled' AND o.invoice_id IS NULL", (a["id"],))):
        lines.append({"name": f"Lab: {o['name']}", "cat": "Laboratory", "qty": 1, "rate_p": o["rate_p"] or 0, "amount_p": o["rate_p"] or 0, "service_id": o["sid"], "ref": f"LAB{o['id']}"})
    pharm = c.execute("SELECT COALESCE(SUM(total_p-returned_p),0) FROM bills WHERE admission_id=? AND pay_mode='credit'", (a["id"],)).fetchone()[0]
    total = sum(x["amount_p"] for x in lines)
    deposits = c.execute("SELECT COALESCE(SUM(amount_p),0) FROM payments WHERE admission_id=? AND kind='deposit'", (a["id"],)).fetchone()[0]
    return {"lines": lines, "days": days, "total": R(total), "total_p": total, "pharmacy_credit": R(pharm), "deposits": R(deposits), "deposits_p": deposits,
            "balance": R(total + pharm - deposits)}


@route("GET", r"/api/admissions/(\d+)", "patients_read")
def api_admission(h, c, b, q, aid):
    a = one(c, "SELECT a.*, p.name pname, p.age, p.gender, p.phone, p.allergies, p.conditions, p.weight, p.blood_group, bd.ward, bd.number bed, "
               "u.name dname, u.reg_no dreg, br.name bname, br.address baddr, br.phone bphone FROM admissions a JOIN patients p ON p.id=a.patient_id "
               "LEFT JOIN beds bd ON bd.id=a.bed_id LEFT JOIN users u ON u.id=a.doctor_id JOIN branches br ON br.id=a.branch_id WHERE a.id=?", (int(aid),))
    need(a and (a["branch_id"] == h.branch or h.user["role"] == "owner"), "Admission not found", 404)
    a["code"] = pcode(a["patient_id"])
    a["notes"] = rows(c.execute("SELECT n.*, u.name uname, u.role urole FROM ipd_notes n LEFT JOIN users u ON u.id=n.user_id WHERE admission_id=? ORDER BY n.id DESC", (a["id"],)))
    a["vitals"] = rows(c.execute("SELECT * FROM vitals WHERE patient_id=? AND at>=? ORDER BY at DESC LIMIT 60", (a["patient_id"], a["admitted_at"])))
    mar_day = qget(q, "mar_day") or None
    if mar_day:
        valid_day(mar_day, "MAR day")
    a["mar_day"] = mar_day or today()
    a["mar"] = mar_today(c, a["id"], mar_day)
    a["labs"] = rows(c.execute("SELECT o.id, o.status, o.created_at, (SELECT group_concat(t.name, ', ') FROM lab_order_items i JOIN lab_tests t ON t.id=i.test_id WHERE i.order_id=o.id) tests "
                               "FROM lab_orders o WHERE admission_id=? ORDER BY o.id DESC", (a["id"],)))
    a["bill"] = running_bill(c, a)
    a["procedures"] = rows(c.execute("SELECT pr.*, u.name surgeon FROM procedures pr LEFT JOIN users u ON u.id=pr.surgeon_id WHERE admission_id=? ORDER BY pr.id DESC", (a["id"],)))
    a["imaging"] = rows(c.execute("SELECT * FROM imaging WHERE admission_id=? ORDER BY id DESC", (a["id"],)))
    a["rx"] = rows(c.execute("SELECT r.*, m.name FROM rx_items r JOIN medicines m ON m.id=r.medicine_id WHERE r.admission_id=?", (a["id"],)))
    a["summary"] = json.loads(a["summary"]) if a["summary"] else None
    a["moves"] = rows(c.execute("SELECT bm.*, bd.ward, bd.number FROM bed_moves bm JOIN beds bd ON bd.id=bm.bed_id WHERE admission_id=? ORDER BY bm.id", (a["id"],)))
    return a


@route("POST", r"/api/admissions/(\d+)/transfer", "ipd")
def api_transfer_bed(h, c, b, q, aid):
    a = adm_or_404(c, h, int(aid))
    need(a["status"] == "admitted", "Patient is not admitted")
    bed = one(c, "SELECT * FROM beds WHERE id=? AND branch_id=?", (as_int(b.get("bed_id"), "bed"), h.branch))
    need(bed and bed["status"] == "free", "Choose a free bed")

    def run():
        c.execute("UPDATE bed_moves SET to_at=? WHERE admission_id=? AND to_at IS NULL", (now_str(), a["id"]))
        c.execute("INSERT INTO bed_moves(admission_id,bed_id,from_at) VALUES(?,?,?)", (a["id"], bed["id"], now_str()))
        c.execute("UPDATE beds SET status='cleaning' WHERE id=?", (a["bed_id"],))
        c.execute("UPDATE beds SET status='occupied' WHERE id=?", (bed["id"],))
        c.execute("UPDATE admissions SET bed_id=? WHERE id=?", (bed["id"], a["id"]))
        audit(c, h, "ipd.transfer", f"{a['ip_no']} -> {bed['ward']}-{bed['number']}")
    in_tx(c, run)
    return {"ok": True}


@route("POST", r"/api/admissions/(\d+)/notes", "ipd")
def api_note(h, c, b, q, aid):
    a = adm_or_404(c, h, int(aid))
    kind = clean(b, "kind", 10) or ("round" if h.user["role"] == "doctor" else "nursing")
    need(kind in ("round", "nursing", "procedure"), "Unknown note type")
    text = clean(b, "text", 4000)
    vit = {k: b.get(k) for k in ("temp", "pulse", "bp_sys", "bp_dia", "spo2", "sugar", "weight")}
    need(text or any(v not in (None, "") for v in vit.values()), "Write a note or enter vitals")
    from .m_clinical import add_vitals
    add_vitals(c, h, a["patient_id"], vit, "ipd", a["id"])
    if text:
        c.execute("INSERT INTO ipd_notes(admission_id,at,user_id,kind,text) VALUES(?,?,?,?,?)", (a["id"], now_str(), h.user["id"], kind, text))
    if kind == "round" and h.user["role"] == "doctor":
        s = one(c, "SELECT * FROM services WHERE name='Doctor visit (IPD)'")
        charge = b.get("charge_visit", True)
        if isinstance(charge, str):
            charge = charge.lower() not in ("0", "false", "no", "")
        if s and charge:
            c.execute("INSERT INTO ipd_charges(admission_id,at,service_id,name,cat,qty,rate_p,amount_p,user_id,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (a["id"], now_str(), s["id"], f"{s['name']}: {h.user['name']}", s["cat"], 1, s["rate_p"], s["rate_p"], h.user["id"], "round"))
    audit(c, h, "ipd.note", f"{a['ip_no']} {kind}")
    return {"ok": True}


@route("POST", r"/api/admissions/(\d+)/charges", "ipd")
def api_charge(h, c, b, q, aid):
    a = adm_or_404(c, h, int(aid))
    need(a["status"] == "admitted", "Patient is already discharged")
    s = one(c, "SELECT * FROM services WHERE id=? AND active=1", (as_int(b.get("service_id"), "service"),))
    need(s, "Service not found", 404)
    qty = opt_num(b.get("qty"), float, "quantity") or 1
    need(0 < qty <= 100, "Quantity must be between 1 and 100")
    c.execute("INSERT INTO ipd_charges(admission_id,at,service_id,name,cat,qty,rate_p,amount_p,user_id,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (a["id"], now_str(), s["id"], s["name"], s["cat"], qty, s["rate_p"], round(qty * s["rate_p"]), h.user["id"], "manual"))
    audit(c, h, "ipd.charge", f"{a['ip_no']} {s['name']} x{qty:g}")
    return {"ok": True}


@route("POST", r"/api/admissions/(\d+)/deposit", "hbilling")
def api_deposit(h, c, b, q, aid):
    a = adm_or_404(c, h, int(aid))
    amt, mode = P(b.get("amount"), "amount"), clean(b, "mode", 10) or "cash"
    need(amt > 0, "Enter an amount")
    need(mode in ("cash", "upi", "card"), "Invalid payment mode")
    need(mode == "cash" or clean(b, "ref", 40), "Enter the transaction reference")

    def run():
        need(one(c, "SELECT 1 FROM admissions WHERE id=? AND status='admitted'", (a["id"],)), "Patient is already discharged")
        c.execute("INSERT INTO payments(branch_id,admission_id,at,mode,amount_p,ref,user_id,kind) VALUES(?,?,?,?,?,?,?,?)",
                  (h.branch, a["id"], now_str(), mode, amt, clean(b, "ref", 40), h.user["id"], "deposit"))
        audit(c, h, "ipd.deposit", f"{a['ip_no']} {rs(amt)} {mode}")
    in_tx(c, run)
    return {"ok": True}


# ---------------------------------------------------------------- medication orders & MAR
def due_times(mo):
    if mo["times"]:
        return [t.strip() for t in mo["times"].split(",") if t.strip()]
    return {"OD": ["09:00"], "BD": ["09:00", "21:00"], "TDS": ["08:00", "14:00", "20:00"], "QID": ["06:00", "12:00", "18:00", "23:00"],
            "HS": ["22:00"], "STAT": ["now"], "SOS": []}.get((mo["freq"] or "").upper(), ["09:00"])


def mar_today(c, aid, day=None):
    """Dose chart for one day (default today); earlier days show what was given, held or missed."""
    day = day or today()
    out = []
    for mo in rows(c.execute("SELECT mo.*, m.name, m.generic, u.name oname FROM mar_orders mo JOIN medicines m ON m.id=mo.medicine_id LEFT JOIN users u ON u.id=mo.ordered_by "
                             "WHERE admission_id=? ORDER BY mo.active DESC, mo.id", (aid,))):
        given = rows(c.execute("SELECT ma.*, u.name uname FROM mar_admin ma LEFT JOIN users u ON u.id=ma.user_id WHERE mar_id=? AND ma.at LIKE ? ORDER BY ma.id", (mo["id"], day + "%")))
        ran = mo["start_at"][:10] <= day and (not mo["stop_at"] or mo["stop_at"][:10] >= day)
        mo["slots"] = [{"due": t, "record": next((g for g in given if g["due"] == t), None)} for t in due_times(mo)] if ran else []
        mo["extra"] = [g for g in given if g["due"] not in due_times(mo)]
        out.append(mo)
    return out


@route("POST", r"/api/admissions/(\d+)/mar", "ipd")
def api_mar_order(h, c, b, q, aid):
    a = adm_or_404(c, h, int(aid))
    need(h.user["role"] in ("doctor", "owner"), "Only doctors can order medicines", 403)
    m = one(c, "SELECT * FROM medicines WHERE id=? AND active=1", (as_int(b.get("medicine_id"), "medicine"),))
    need(m, "Medicine not found", 404)
    freq = clean(b, "freq", 10).upper() or "OD"
    p = one(c, "SELECT * FROM patients WHERE id=?", (a["patient_id"],))
    from .m_clinical import current_meds, latest_creatinine
    warnings = safety_check(p, [{"med": m, "freq": freq if "-" in freq else {"OD": "1-0-0", "BD": "1-0-1", "TDS": "1-1-1", "QID": "1-1-1-1"}.get(freq, "1-0-0"),
                                 "dose": clean(b, "dose", 20), "days": 1}], current_meds(c, p["id"]), latest_creatinine(c, p["id"]))
    if warnings and not b.get("override"):
        raise ApiError(409, "Safety warnings: review before ordering", warnings=warnings)
    times = clean(b, "times", 60)
    for t in [x.strip() for x in times.split(",") if x.strip()]:
        need(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t), f"Time {t!r} must be HH:MM (00:00-23:59)")
    days = opt_num(b.get("days"), int, "days")
    stop_at = add_days(today(), days - 1) + " 23:59" if days and days > 0 else None
    c.execute("INSERT INTO mar_orders(admission_id,medicine_id,dose,route,freq,times,start_at,stop_at,ordered_by,active) VALUES(?,?,?,?,?,?,?,?,?,1)",
              (a["id"], m["id"], clean(b, "dose", 20) or "1", clean(b, "route", 20) or "oral", freq, times or None, now_str(), stop_at, h.user["id"]))
    reason = clean(b, "override_reason", 300)
    audit(c, h, "mar.order", f"{a['ip_no']} {m['name']} {clean(b, 'dose', 20)} {freq}" + (f" {days}d" if days else "")
          + ((" OVERRIDE" + (f" ({reason})" if reason else "") + ": " + " ".join(w["text"] for w in warnings)) if warnings else ""))
    return {"ok": True}


@route("POST", r"/api/mar/(\d+)/stop", "ipd")
def api_mar_stop(h, c, b, q, mid):
    need(h.user["role"] in ("doctor", "owner"), "Only doctors can stop medicines", 403)
    mo = one(c, "SELECT mo.*, a.branch_id, a.ip_no, m.name FROM mar_orders mo JOIN admissions a ON a.id=mo.admission_id JOIN medicines m ON m.id=mo.medicine_id WHERE mo.id=?", (int(mid),))
    need(mo and (mo["branch_id"] == h.branch or h.user["role"] == "owner"), "Medicine order not found", 404)
    c.execute("UPDATE mar_orders SET active=0, stop_at=? WHERE id=?", (now_str(), mo["id"]))
    audit(c, h, "mar.stop", f"{mo['ip_no']} {mo['name']} {mo['dose']} {mo['freq']}")
    return {"ok": True}


@route("POST", r"/api/mar/(\d+)/give", "ipd_nursing")
def api_mar_give(h, c, b, q, mid):
    mo = one(c, "SELECT mo.*, a.branch_id, a.ip_no, a.id aid, a.status astatus FROM mar_orders mo JOIN admissions a ON a.id=mo.admission_id WHERE mo.id=?", (int(mid),))
    need(mo and mo["branch_id"] == h.branch and mo["active"] and mo["astatus"] == "admitted", "Medicine order not active")
    st = clean(b, "status", 10) or "given"
    need(st in ("given", "held", "refused"), "Status must be given, held or refused")
    due = clean(b, "due", 5) or "extra"
    need(st == "given" or clean(b, "note", 200), "Write why the dose was held or refused")

    def run():
        need(not one(c, "SELECT 1 FROM mar_admin WHERE mar_id=? AND due=? AND at LIKE ?", (mo["id"], due, today() + "%")) or due == "extra", "This dose is already recorded")
        c.execute("INSERT INTO mar_admin(mar_id,due,at,status,user_id,note) VALUES(?,?,?,?,?,?)", (mo["id"], due, now_str(), st, h.user["id"], clean(b, "note", 200)))
        msg = None
        if st == "given":
            from .m_pharmacy import move, usable_batches
            m = one(c, "SELECT * FROM medicines WHERE id=?", (mo["medicine_id"],))
            units = max(1, math.ceil(dose_units(mo["dose"]))) if m["form"] in ("Tablet", "Capsule") else 1
            bs = usable_batches(c, h.branch, m["id"])
            if sum(x["qty"] for x in bs) >= units:
                left, amt = units, 0
                for bt in bs:
                    if not left:
                        break
                    take = min(left, bt["qty"])
                    c.execute("UPDATE batches SET qty=qty-? WHERE id=?", (take, bt["id"]))
                    move(c, h, bt, -take, "ward_issue", mo["ip_no"])
                    amt += take * bt["mrp_p"]
                    left -= take
                c.execute("INSERT INTO ipd_charges(admission_id,at,name,cat,qty,rate_p,amount_p,user_id,source) VALUES(?,?,?,?,?,?,?,?,?)",
                          (mo["aid"], now_str(), f"Medicine: {m['name']}", "Pharmacy", units, amt // units, amt, h.user["id"], "mar"))
            else:
                msg = f"Not enough {m['name']} in this branch's pharmacy to charge it. Dose recorded; ask the pharmacy to issue stock."
        audit(c, h, "mar.give", f"{mo['ip_no']} order {mo['id']} {due} {st}")
        return msg
    msg = in_tx(c, run)
    return {"ok": True, "warning": msg}


# ---------------------------------------------------------------- discharge
@route("POST", r"/api/admissions/(\d+)/discharge", "ipd")
def api_discharge(h, c, b, q, aid):
    a = adm_or_404(c, h, int(aid))
    need(a["status"] == "admitted", "Patient is already discharged")
    need(h.user["role"] in ("doctor", "owner"), "Only a doctor can discharge", 403)
    dtype = clean(b, "discharge_type", 12) or "normal"
    need(dtype in ("normal", "lama", "referred", "death"), "Unknown discharge type")
    summary = {k: clean(b, k, 3000) for k in ("final_diagnosis", "icd", "history", "course", "procedures", "investigations", "condition", "medications", "advice", "followup")}
    need(summary["final_diagnosis"], "Enter the final diagnosis")
    if summary["followup"]:
        valid_day(summary["followup"], "follow-up date")
    pending = c.execute("SELECT COUNT(*) FROM lab_orders WHERE admission_id=? AND status IN ('ordered','collected')", (a["id"],)).fetchone()[0]
    if dtype in ("normal", "referred"):
        need(not pending or b.get("ignore_pending"), f"{pending} lab order(s) still have no result. Wait for them, cancel them in the lab, or tick 'discharge anyway'.")
    if dtype == "referred":
        need(clean(b, "to_facility", 150) and clean(b, "referral_reason", 1000), "A referral needs the receiving facility and the reason")
    # discharge medicines are a real prescription: safety-checked, dispensable at any pharmacy, visible as current medicines
    from .m_clinical import check_items
    from .safety import qty_for
    p = one(c, "SELECT * FROM patients WHERE id=?", (a["patient_id"],))
    raw = (b.get("items") or [])[:30]
    items, warnings = check_items(c, p, raw)
    if warnings and not b.get("override"):
        raise ApiError(409, "Safety warnings: review before discharging", warnings=warnings)
    reason = clean(b, "override_reason", 300)

    def run():
        end = now_str()
        c.execute("UPDATE bed_moves SET to_at=? WHERE admission_id=? AND to_at IS NULL", (end, a["id"]))
        a2 = dict(a, discharged_at=end)
        bill = running_bill(c, a2)
        c.execute("UPDATE mar_orders SET active=0, stop_at=? WHERE admission_id=? AND active=1", (end, a["id"]))
        c.execute("DELETE FROM rx_items WHERE admission_id=?", (a["id"],))
        for it, rawi in zip(items, raw):
            qty = opt_num(rawi.get("qty"), int, "qty") or qty_for(it["med"], it["freq"], it["days"], it["dose"])
            c.execute("INSERT INTO rx_items(admission_id,medicine_id,dose,freq,days,qty,instructions) VALUES(?,?,?,?,?,?,?)",
                      (a["id"], it["med"]["id"], it["dose"], it["freq"], it["days"], qty, clean(rawi, "instructions", 200)))
        if items and not summary["medications"]:
            summary["medications"] = "; ".join(f"{it['med']['name']} {it['dose']} {it['freq']} x {it['days']}d" for it in items)
        # unsettled pharmacy credit bills from this stay go on the final invoice
        for bl in rows(c.execute("SELECT * FROM bills WHERE admission_id=? AND pay_mode='credit' AND settled_at IS NULL AND total_p-returned_p>0", (a["id"],))):
            bill["lines"].append({"service_id": None, "name": f"Pharmacy bill {bl['bill_no']} (credit)", "cat": "Pharmacy credit", "qty": 1, "rate_p": bl["total_p"] - bl["returned_p"], "ref": bl["bill_no"]})
        from .m_billing import create_invoice
        inv = create_invoice(c, h, a["patient_id"], [{"service_id": x.get("service_id"), "name": x["name"], "cat": x["cat"], "qty": x["qty"], "rate_p": x["rate_p"],
                                                      "disc_p": 0, "ref": x.get("ref")} for x in bill["lines"]],
                             doctor_id=a["doctor_id"], admission_id=a["id"], kind="ipd", notes=f"Inpatient bill {a['ip_no']}")
        c.execute("UPDATE bills SET settled_at=?, settled_mode='invoice', settled_invoice_id=? WHERE admission_id=? AND pay_mode='credit' AND settled_at IS NULL", (end, inv["id"], a["id"]))
        if dtype == "referred":
            from .m_care import create_referral
            create_referral(c, h, a["patient_id"], {"to_facility": b.get("to_facility"), "to_doctor": b.get("to_doctor"), "reason": b.get("referral_reason"),
                                                     "urgency": b.get("referral_urgency") or "urgent", "summary": f"{summary['final_diagnosis']}. {summary['course'] or ''}",
                                                     "treatment_given": summary["medications"], "transport": b.get("transport")}, admission_id=a["id"])
        c.execute("UPDATE payments SET invoice_id=?, kind='payment' WHERE admission_id=? AND kind='deposit'", (inv["id"], a["id"]))
        c.execute("UPDATE lab_orders SET invoice_id=? WHERE admission_id=? AND invoice_id IS NULL AND status<>'cancelled'", (inv["id"], a["id"]))
        c.execute("UPDATE admissions SET status='discharged', discharged_at=?, discharge_type=?, summary=?, diagnosis=?, icd=?, invoice_id=? WHERE id=?",
                  (end, dtype, json.dumps(summary), summary["final_diagnosis"], summary["icd"] or a["icd"], inv["id"], a["id"]))
        c.execute("UPDATE beds SET status='cleaning' WHERE id=?", (a["bed_id"],))
        if dtype == "death":
            c.execute("UPDATE lab_orders SET status='cancelled' WHERE admission_id=? AND status IN ('ordered','collected')", (a["id"],))
        if summary["followup"] and dtype != "death":
            c.execute("INSERT INTO visits(patient_id,branch_id,doctor_id,created_at,created_by,complaint,triage,diagnosis,followup,status,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (a["patient_id"], a["branch_id"], a["doctor_id"], end, h.user["id"], "Discharge", "normal", summary["final_diagnosis"], summary["followup"], "done", end))
        audit(c, h, "ipd.discharge", f"{a['ip_no']} {dtype} invoice {inv['inv_no']} {rs(inv['total_p'])} rx={len(items)}"
              + ((" OVERRIDE" + (f" ({reason})" if reason else "") + ": " + " ".join(w["text"] for w in warnings)) if warnings else ""))
        return inv
    inv = in_tx(c, run)
    from .m_portal import share
    if dtype != "death":  # the family gets the bill from the desk, not a "your summary is ready" message
        share(c, a["patient_id"], f"Your discharge summary ({a['ip_no']}) and final bill {inv['inv_no']} are ready.", h.user["id"], pdf=("invoice", inv["id"]))
    return {"ok": True, "invoice_id": inv["id"], "inv_no": inv["inv_no"]}
