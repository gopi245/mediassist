"""Patients and EMR (problems, vitals, vaccinations, pregnancy), ICD-10, templates,
OPD visits, consultation with safety checks and orders."""
import json
import re
from datetime import date, timedelta

from .core import (ApiError, add_days, all_access, as_int, audit, can, clean, in_tx, need, need_branch, now_str, one, opt_num,
                   pcode, qget, route, rows, today, valid_day)
from .safety import qty_for, safety_check, triage


def patient_or_404(c, pid):
    p = one(c, "SELECT * FROM patients WHERE id=?", (pid,))
    need(p, "Patient not found", 404)
    return p


def current_meds(c, pid, exclude_visit=None):
    out, seen = [], set()
    for r in c.execute("SELECT m.*, v.completed_at vdate, r.days FROM rx_items r JOIN visits v ON v.id=r.visit_id JOIN medicines m ON m.id=r.medicine_id "
                       "WHERE v.patient_id=? AND v.status='done' AND v.id IS NOT ?", (pid, exclude_visit)):
        r = dict(r)
        if r["vdate"] and add_days(r["vdate"], r["days"] or 30) >= today() and r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    for r in c.execute("SELECT m.* FROM mar_orders mo JOIN admissions a ON a.id=mo.admission_id JOIN medicines m ON m.id=mo.medicine_id "
                       "WHERE a.patient_id=? AND a.status='admitted' AND mo.active=1", (pid,)):
        r = dict(r)
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out


def latest_creatinine(c, pid):
    r = c.execute("SELECT lr.num FROM lab_results lr JOIN lab_params lp ON lp.id=lr.param_id JOIN lab_order_items oi ON oi.id=lr.order_item_id "
                  "JOIN lab_orders o ON o.id=oi.order_id WHERE o.patient_id=? AND lp.name='Creatinine' AND lr.num IS NOT NULL ORDER BY o.id DESC LIMIT 1",
                  (pid,)).fetchone()
    return r[0] if r else None


def check_items(c, p, items, exclude_visit=None):
    full = []
    for it in items:
        m = one(c, "SELECT * FROM medicines WHERE id=?", (as_int(it.get("medicine_id"), "medicine"),))
        need(m, "Medicine not found", 404)
        full.append({"med": m, "freq": clean(it, "freq", 20), "dose": clean(it, "dose", 20), "days": opt_num(it.get("days"), int)})
    return full, safety_check(p, full, current_meds(c, p["id"], exclude_visit) if p else [], latest_creatinine(c, p["id"]) if p else None)


# ---------------------------------------------------------------- patients
def patient_fields(b):
    name, phone = clean(b, "name", 100), re.sub(r"[^\d+]", "", clean(b, "phone", 20))
    need(name and len(phone) >= 10, "Name and a valid 10-digit phone number are required")
    dob = clean(b, "dob", 10) or None
    if dob:
        valid_day(dob, "date of birth")
    lmp = clean(b, "lmp", 10) or None
    if lmp:
        valid_day(lmp, "LMP date")
    abha = re.sub(r"[^\d]", "", clean(b, "abha", 20))
    need(not abha or len(abha) == 14, "ABHA number has 14 digits")
    age = opt_num(b.get("age"), int, "age")
    if dob and age is None:
        d = date.fromisoformat(dob)
        age = date.today().year - d.year - ((date.today().month, date.today().day) < (d.month, d.day))
    return dict(name=name, age=age, dob=dob, gender=clean(b, "gender", 10), phone=phone, address=clean(b, "address"),
                allergies=clean(b, "allergies"), conditions=clean(b, "conditions"), blood_group=clean(b, "blood_group", 5),
                abha=abha or None, weight=opt_num(b.get("weight"), float, "weight"), lmp=lmp, lang=clean(b, "lang", 5) or None)


@route("GET", "/api/patients", "patients_read")
def api_patients(h, c, b, q):
    term = qget(q, "q").strip()
    m = re.fullmatch(r"[Pp]0*(\d+)", term)
    if m:
        return [dict(r, code=pcode(r["id"])) for r in rows(c.execute("SELECT * FROM patients WHERE id=?", (int(m.group(1)),)))]
    like = f"%{term}%"
    rs_ = rows(c.execute("SELECT * FROM patients WHERE erased_at IS NULL AND (name LIKE ? OR phone LIKE ? OR abha LIKE ?) ORDER BY id DESC LIMIT 50",
                         (like, like, like)))
    return [dict(r, code=pcode(r["id"])) for r in rs_]


@route("POST", "/api/patients", "patients_write")
def api_add_patient(h, c, b, q):
    f = patient_fields(b)
    need(b.get("consent"), "Record the patient's consent to store their health data (DPDP Act) before registering")
    if not b.get("force"):
        dup = rows(c.execute("SELECT * FROM patients WHERE phone=? AND erased_at IS NULL", (f["phone"],)))
        if dup:
            raise ApiError(409, "A patient with this phone number already exists", matches=[dict(d, code=pcode(d["id"])) for d in dup])
    cols = list(f) + ["branch_id", "created_at", "created_by", "consent_at", "consent_by", "whatsapp_ok"]
    vals = list(f.values()) + [h.branch or None, now_str(), h.user["id"], now_str(), h.user["id"], 0 if b.get("whatsapp_ok") is False else 1]
    cur = c.execute(f"INSERT INTO patients({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
    if f["weight"]:
        c.execute("INSERT INTO vitals(patient_id,at,source,weight,recorded_by) VALUES(?,?,?,?,?)", (cur.lastrowid, now_str(), "registration", f["weight"], h.user["id"]))
    audit(c, h, "patient.create", f"{pcode(cur.lastrowid)} {f['name']}")
    return {"ok": True, "id": cur.lastrowid, "code": pcode(cur.lastrowid), "welcome": welcome(c, h, cur.lastrowid, f["name"])}


def welcome(c, h, pid, name):
    """Greet a newly registered patient on WhatsApp with their ID and records link. None when switched off or not allowed."""
    from .core import get_settings
    s = get_settings(c)
    if s.get("welcome_msg", "1") != "1":
        return None
    br = one(c, "SELECT name, phone FROM branches WHERE id=?", (h.branch,)) if h.branch else None
    place = br["name"] if br else (s.get("org_name") or "our hospital")
    from .m_portal import link_line
    from .notify import send_patient
    text = (f"Welcome to {place}, {name}! Your patient ID is {pcode(pid)}. Please mention it at every visit.{link_line(c, pid, h.user['id'])}"
            + (f"\nQuestions? Call {br['phone']}." if br and br["phone"] else ""))
    return send_patient(c, pid, "welcome", text)


@route("POST", r"/api/patients/(\d+)", "patients_write")
def api_edit_patient(h, c, b, q, pid):
    patient_or_404(c, int(pid))
    f = patient_fields(b)
    c.execute(f"UPDATE patients SET {','.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), int(pid)))
    audit(c, h, "patient.update", f"{pcode(int(pid))} allergies={f['allergies'] or '-'} conditions={f['conditions'] or '-'}")
    return {"ok": True}


def profile(c, pid):
    p = patient_or_404(c, pid)
    visits = []
    for v in rows(c.execute("SELECT v.*, u.name dname, br.name bname, br.code bcode FROM visits v LEFT JOIN users u ON u.id=v.doctor_id "
                            "JOIN branches br ON br.id=v.branch_id WHERE v.patient_id=? ORDER BY v.id DESC LIMIT 40", (pid,))):
        v["rx"] = rows(c.execute("SELECT r.*, m.name FROM rx_items r JOIN medicines m ON m.id=r.medicine_id WHERE visit_id=?", (v["id"],)))
        visits.append(v)
    labs = rows(c.execute("SELECT o.*, br.code bcode, (SELECT group_concat(t.name, ', ') FROM lab_order_items i JOIN lab_tests t ON t.id=i.test_id WHERE i.order_id=o.id) tests "
                          "FROM lab_orders o JOIN branches br ON br.id=o.branch_id WHERE o.patient_id=? ORDER BY o.id DESC LIMIT 30", (pid,)))
    return {**p, "code": pcode(pid), "visits": visits, "labs": labs,
            "problems": rows(c.execute("SELECT * FROM problems WHERE patient_id=? ORDER BY status, id DESC", (pid,))),
            "vitals": rows(c.execute("SELECT * FROM vitals WHERE patient_id=? ORDER BY at DESC LIMIT 60", (pid,))),
            "vaccinations": rows(c.execute("SELECT * FROM vaccinations WHERE patient_id=? ORDER BY given_on DESC", (pid,))),
            "admissions": rows(c.execute("SELECT a.*, br.code bcode, br.name bname, bd.ward, bd.room, bd.number bed, bd.kind bed_kind, bd.ac, u.name dname FROM admissions a "
                                         "JOIN branches br ON br.id=a.branch_id LEFT JOIN beds bd ON bd.id=a.bed_id LEFT JOIN users u ON u.id=a.doctor_id "
                                         "WHERE patient_id=? ORDER BY a.id DESC", (pid,))),
            "invoices": rows(c.execute("SELECT i.id,i.inv_no,i.created_at,i.total_p,i.cancelled_at,br.code bcode FROM invoices i JOIN branches br ON br.id=i.branch_id WHERE patient_id=? ORDER BY i.id DESC LIMIT 30", (pid,))),
            "bills": rows(c.execute("SELECT b.id,b.bill_no,b.created_at,b.total_p,b.returned_p,br.code bcode FROM bills b JOIN branches br ON br.id=b.branch_id WHERE patient_id=? ORDER BY b.id DESC LIMIT 30", (pid,))),
            "documents": rows(c.execute("SELECT id,doc_type,doc_date,note,mime,filename FROM documents WHERE patient_id=? ORDER BY id DESC", (pid,))),
            "appointments": rows(c.execute("SELECT a.*, u.name dname FROM appointments a LEFT JOIN users u ON u.id=a.doctor_id WHERE patient_id=? AND day>=? ORDER BY day, slot", (pid, today()))),
            "current_meds": [{"name": m["name"], "since": (m.get("vdate") or "")[:10], "days": m.get("days")} for m in current_meds(c, pid)],
            "pregnancy": pregnancy_info(p)}


def pregnancy_info(p):
    if not p.get("lmp"):
        return None
    lmp = date.fromisoformat(p["lmp"])
    days = (date.today() - lmp).days
    if days < 0 or days > 300:
        return None
    return {"edd": (lmp + timedelta(days=280)).isoformat(), "weeks": days // 7, "days": days % 7,
            "trimester": 1 if days < 98 else 2 if days < 196 else 3}


@route("GET", r"/api/patients/(\d+)", "patients_read")
def api_patient(h, c, b, q, pid):
    return profile(c, int(pid))


# ---------------------------------------------------------------- EMR pieces
@route("POST", r"/api/patients/(\d+)/problems", "patients_write")
def api_add_problem(h, c, b, q, pid):
    patient_or_404(c, int(pid))
    title, icd = clean(b, "title", 200), clean(b, "icd", 10).upper()
    if icd and not title:
        r = one(c, "SELECT title FROM icd10 WHERE code=?", (icd,))
        title = r["title"] if r else ""
    need(title, "Enter the problem or pick an ICD-10 code")
    c.execute("INSERT INTO problems(patient_id,icd,title,since,status,created_at,created_by) VALUES(?,?,?,?,?,?,?)",
              (int(pid), icd or None, title, clean(b, "since", 10) or today(), "active", now_str(), h.user["id"]))
    audit(c, h, "problem.add", f"{pcode(int(pid))} {icd} {title}")
    return {"ok": True}


@route("POST", r"/api/problems/(\d+)", "patients_write")
def api_problem_status(h, c, b, q, prid):
    st = clean(b, "status", 10)
    need(st in ("active", "resolved"), "Status must be active or resolved")
    c.execute("UPDATE problems SET status=? WHERE id=?", (st, int(prid)))
    return {"ok": True}


def add_vitals(c, h, pid, b, source, ref):
    vals = {k: opt_num(b.get(k), int if k in ("pulse", "bp_sys", "bp_dia", "spo2") else float, k) for k in ("temp", "pulse", "bp_sys", "bp_dia", "spo2", "weight", "sugar")}
    if any(v is not None for v in vals.values()):
        c.execute("INSERT INTO vitals(patient_id,at,source,ref_id,temp,pulse,bp_sys,bp_dia,spo2,weight,sugar,recorded_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (pid, now_str(), source, ref, *vals.values(), h.user["id"]))
        if vals["weight"]:
            c.execute("UPDATE patients SET weight=? WHERE id=?", (vals["weight"], pid))
    return vals


@route("POST", r"/api/patients/(\d+)/vitals", "visit_create")
def api_add_vitals(h, c, b, q, pid):
    patient_or_404(c, int(pid))
    add_vitals(c, h, int(pid), b, clean(b, "source", 20) or "manual", None)
    return {"ok": True}


@route("POST", r"/api/patients/(\d+)/vaccinations", "visit_create")
def api_add_vaccine(h, c, b, q, pid):
    patient_or_404(c, int(pid))
    vac = clean(b, "vaccine", 60)
    need(vac, "Choose the vaccine")
    given = valid_day(clean(b, "given_on", 10) or today(), "date given")
    due = clean(b, "due_next", 10) or None
    if due:
        valid_day(due, "next due date")
    c.execute("INSERT INTO vaccinations(patient_id,vaccine,dose,given_on,batch,given_by,due_next) VALUES(?,?,?,?,?,?,?)",
              (int(pid), vac, clean(b, "dose", 20), given, clean(b, "batch", 40), h.user["id"], due))
    audit(c, h, "vaccination.add", f"{pcode(int(pid))} {vac} {clean(b, 'dose', 20)}")
    return {"ok": True}


@route("GET", "/api/icd10", "patients_read")
def api_icd(h, c, b, q):
    t = f"%{qget(q, 'q').strip()}%"
    return rows(c.execute("SELECT * FROM icd10 WHERE code LIKE ? OR title LIKE ? ORDER BY code LIMIT 30", (t, t)))


@route("GET", "/api/templates", "patients_read")
def api_templates(h, c, b, q):
    out = []
    for t in rows(c.execute("SELECT * FROM templates ORDER BY name")):
        t["items"], t["tests"] = json.loads(t["items"] or "[]"), json.loads(t["tests"] or "[]")
        out.append(t)
    return out


@route("POST", "/api/templates", "consult")
def api_save_template(h, c, b, q):
    name = clean(b, "name", 80)
    need(name, "Name the template")
    items = [{"medicine_id": as_int(i.get("medicine_id"), "medicine"), "freq": clean(i, "freq", 20), "days": opt_num(i.get("days"), int), "dose": clean(i, "dose", 20),
              "instructions": clean(i, "instructions", 100)} for i in (b.get("items") or [])[:20]]
    tests = [as_int(t, "test") for t in (b.get("tests") or [])[:20]]
    c.execute("INSERT INTO templates(name,diagnosis,icd,advice,items,tests,followup_days) VALUES(?,?,?,?,?,?,?)",
              (name, clean(b, "diagnosis", 200), clean(b, "icd", 10), clean(b, "advice", 1000), json.dumps(items), json.dumps(tests), opt_num(b.get("followup_days"), int)))
    audit(c, h, "template.save", name)
    return {"ok": True}


# ---------------------------------------------------------------- OPD visits
def create_visit(c, h, pid, b, appointment_id=None, doctor_id=None):
    br = need_branch(h, c, "hospital")
    patient_or_404(c, pid)
    need(not one(c, "SELECT 1 FROM visits WHERE patient_id=? AND branch_id=? AND status IN ('waiting','in_consult')", (pid, br["id"])),
         "This patient is already in today's queue")
    v = {k: opt_num(b.get(k), int if k in ("pulse", "bp_sys", "bp_dia", "spo2") else float, k) for k in ("temp", "pulse", "bp_sys", "bp_dia", "spo2", "weight", "sugar")}
    v["complaint"] = clean(b, "complaint", 500)
    level, why = triage(v)
    cur = c.execute("INSERT INTO visits(patient_id,branch_id,doctor_id,appointment_id,created_at,created_by,complaint,temp,pulse,bp_sys,bp_dia,spo2,weight,sugar,triage,triage_reasons) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, br["id"], doctor_id or opt_num(b.get("doctor_id"), int), appointment_id, now_str(), h.user["id"], v["complaint"], v["temp"], v["pulse"],
                     v["bp_sys"], v["bp_dia"], v["spo2"], v["weight"], v["sugar"], level, why))
    add_vitals(c, h, pid, b, "opd", cur.lastrowid)
    audit(c, h, "visit.create", f"visit {cur.lastrowid} {pcode(pid)} triage={level}")
    return cur.lastrowid, level, why


@route("POST", "/api/visits", "visit_create")
def api_add_visit(h, c, b, q):
    vid, level, why = in_tx(c, lambda: create_visit(c, h, as_int(b.get("patient_id"), "patient"), b))
    from .m_alerts import on_visit
    on_visit(c, h, vid)
    return {"ok": True, "id": vid, "triage": level, "reasons": why}


@route("GET", "/api/visits", "patients_read")
def api_visits(h, c, b, q):
    need_branch(h, c)
    status, day = qget(q, "status", "waiting"), valid_day(qget(q, "date", today()))
    sql = ("SELECT v.*, p.name pname, p.age, p.gender, p.phone, p.allergies, u.name dname, a.token FROM visits v JOIN patients p ON p.id=v.patient_id "
           "LEFT JOIN users u ON u.id=v.doctor_id LEFT JOIN appointments a ON a.id=v.appointment_id WHERE v.branch_id=?")
    args = [h.branch]
    if status == "done":
        sql += " AND v.status='done' AND v.completed_at LIKE ?"
        args.append(day + "%")
    else:
        sql += " AND v.status IN ('waiting','in_consult')"
    out = rows(c.execute(sql, args))
    order = {"critical": 0, "urgent": 1, "normal": 2}
    out.sort(key=lambda r: (order.get(r["triage"], 3), r["created_at"]))
    for r in out:
        r["code"] = pcode(r["patient_id"])
    return out


RX_LANGS = {"hi": "Hindi", "te": "Telugu", "ta": "Tamil"}


@route("POST", r"/api/visits/(\d+)/rx-lang", "patients_read")
def api_rx_lang(h, c, b, q, vid):
    """AI-translated patient instructions for the printed prescription (medicine names stay in English)."""
    lang = clean(b, "lang", 5)
    need(lang in RX_LANGS, "Choose Hindi, Telugu or Tamil")
    v = one(c, "SELECT * FROM visits WHERE id=?", (int(vid),))
    need(v, "Visit not found", 404)
    items = rows(c.execute("SELECT r.*, m.name FROM rx_items r JOIN medicines m ON m.id=r.medicine_id WHERE r.visit_id=?", (v["id"],)))
    src = [{"medicine": x["name"], "dose": x["dose"] or "1", "frequency": x["freq"] or "", "days": x["days"], "instructions": x["instructions"] or ""} for x in items]
    from .m_assistant import ai_json
    out = ai_json(c, f"You translate prescription instructions into {RX_LANGS[lang]} for a patient in India who cannot read English. A frequency like 1-0-1 is "
                     "morning-afternoon-night tablet counts: write it out in words. Keep each medicine name exactly as given, in Latin script. Use simple spoken "
                     f'language a patient understands. Return {{"items": [one short {RX_LANGS[lang]} line per medicine, in the same order: how much, when, for how '
                     'many days, plus its instructions], "advice": "the advice translated, or an empty string"}',
                  json.dumps({"medicines": src, "advice": v["notes"] or ""}, ensure_ascii=False))
    need(isinstance(out, dict) and isinstance(out.get("items"), list) and len(out["items"]) == len(items), "The AI answer wasn't usable. Try again.")
    audit(c, h, "rx.translate", f"visit {vid} {lang}")
    return {"items": [str(x)[:300] for x in out["items"]], "advice": str(out.get("advice") or "")[:2000], "lang": RX_LANGS[lang]}


@route("GET", r"/api/visits/(\d+)", "patients_read")
def api_visit(h, c, b, q, vid):
    v = one(c, "SELECT v.*, u.name dname, u.reg_no dreg, br.name bname, br.address baddr, br.phone bphone, br.kind bkind FROM visits v "
               "LEFT JOIN users u ON u.id=v.doctor_id JOIN branches br ON br.id=v.branch_id WHERE v.id=?", (int(vid),))
    need(v, "Visit not found", 404)
    rx = rows(c.execute("SELECT r.*, m.name, m.generic, m.form, m.schedule FROM rx_items r JOIN medicines m ON m.id=r.medicine_id WHERE visit_id=?", (v["id"],)))
    labs = rows(c.execute("SELECT o.id, o.status, t.name, t.code FROM lab_orders o JOIN lab_order_items i ON i.order_id=o.id JOIN lab_tests t ON t.id=i.test_id WHERE o.visit_id=?", (v["id"],)))
    prof = profile(c, v["patient_id"])
    prof["current_meds"] = [{"name": m["name"], "since": (m.get("vdate") or "")[:10], "days": m.get("days")} for m in current_meds(c, v["patient_id"], v["id"])]
    return {"visit": v, "rx": rx, "labs": labs, "patient": prof, "creatinine": latest_creatinine(c, v["patient_id"])}


@route("POST", r"/api/visits/(\d+)/start", "consult")
def api_start(h, c, b, q, vid):
    c.execute("UPDATE visits SET status='in_consult', doctor_id=COALESCE(doctor_id, ?) WHERE id=? AND status='waiting'", (h.user["id"], int(vid)))
    c.execute("UPDATE appointments SET status='in_consult' WHERE id=(SELECT appointment_id FROM visits WHERE id=?)", (int(vid),))
    return {"ok": True}


@route("POST", "/api/rx/check", "patients_read")
def api_rx_check(h, c, b, q):
    p = one(c, "SELECT * FROM patients WHERE id=?", (as_int(b.get("patient_id"), "patient"),))
    if b.get("weight"):
        p = dict(p, weight=opt_num(b.get("weight"), float))
    _, warnings = check_items(c, p, (b.get("items") or [])[:30], opt_num(b.get("visit_id"), int))
    return {"warnings": warnings}


@route("POST", r"/api/visits/(\d+)/complete", "consult")
def api_complete(h, c, b, q, vid):
    v = one(c, "SELECT * FROM visits WHERE id=?", (int(vid),))
    need(v, "Visit not found", 404)
    need(v["branch_id"] == h.branch or all_access(h.user), "This visit belongs to another branch", 403)
    need(not one(c, "SELECT 1 FROM rx_items WHERE visit_id=? AND dispensed>0", (v["id"],)), "The pharmacy already dispensed this prescription, so it can't be changed")
    diagnosis, icd = clean(b, "diagnosis", 300), clean(b, "icd", 10).upper()
    need(diagnosis, "Enter a diagnosis")
    if icd:
        need(one(c, "SELECT 1 FROM icd10 WHERE code=?", (icd,)), "Unknown ICD-10 code")
    followup = clean(b, "followup", 10)
    if followup:
        valid_day(followup, "follow-up date")
    p = one(c, "SELECT * FROM patients WHERE id=?", (v["patient_id"],))
    if b.get("weight"):
        p = dict(p, weight=opt_num(b.get("weight"), float))
    items, warnings = check_items(c, p, (b.get("items") or [])[:30], v["id"])
    if warnings and not b.get("override"):
        raise ApiError(409, "Safety warnings: review before saving", warnings=warnings)
    tests = [as_int(t, "test") for t in (b.get("lab_tests") or [])[:20]]
    raw = (b.get("items") or [])[:30]

    def run():
        c.execute("DELETE FROM rx_items WHERE visit_id=?", (v["id"],))
        for it, rawi in zip(items, raw):
            qty = opt_num(rawi.get("qty"), int) or qty_for(it["med"], it["freq"], it["days"], it["dose"])
            c.execute("INSERT INTO rx_items(visit_id,medicine_id,dose,freq,days,qty,instructions) VALUES(?,?,?,?,?,?,?)",
                      (v["id"], it["med"]["id"], it["dose"], it["freq"], it["days"], qty, clean(rawi, "instructions", 200)))
        c.execute("UPDATE visits SET diagnosis=?, icd=?, notes=?, followup=?, doctor_id=?, status='done', completed_at=? WHERE id=?",
                  (diagnosis, icd or None, clean(b, "notes", 3000), followup or None, h.user["id"], v["completed_at"] or now_str(), v["id"]))
        c.execute("UPDATE appointments SET status='done' WHERE id=?", (v["appointment_id"],))
        if icd and b.get("add_problem") and not one(c, "SELECT 1 FROM problems WHERE patient_id=? AND icd=? AND status='active'", (p["id"], icd)):
            c.execute("INSERT INTO problems(patient_id,icd,title,since,status,created_at,created_by) VALUES(?,?,?,?,?,?,?)",
                      (p["id"], icd, diagnosis, today(), "active", now_str(), h.user["id"]))
        order_id = None
        if tests and not one(c, "SELECT 1 FROM lab_orders WHERE visit_id=?", (v["id"],)):
            from .m_lab import create_order
            order_id = create_order(c, h, p["id"], tests, visit_id=v["id"], doctor_id=h.user["id"], priority=clean(b, "lab_priority", 10) or "routine")
        audit(c, h, "visit.complete", f"visit {v['id']} {pcode(p['id'])} dx={diagnosis} {icd} rx={len(items)} labs={len(tests)}"
              + (" OVERRIDE: " + " ".join(w["text"] for w in warnings) if warnings else ""))
        return order_id
    order_id = in_tx(c, run)
    if not v["completed_at"]:  # first save only; corrections don't message again
        from .m_portal import share
        dname = one(c, "SELECT name FROM users WHERE id=?", (h.user["id"],))["name"]
        share(c, p["id"], f"Your prescription from {dname} is ready" + (f" (follow-up on {followup})." if followup else "."), h.user["id"], pdf=("rx", v["id"]))
    return {"ok": True, "lab_order_id": order_id}


@route("POST", r"/api/visits/(\d+)/cancel", "visit_create")
def api_cancel_visit(h, c, b, q, vid):
    c.execute("UPDATE visits SET status='cancelled' WHERE id=? AND status IN ('waiting','in_consult') AND branch_id=?", (int(vid), h.branch))
    audit(c, h, "visit.cancel", vid)
    return {"ok": True}


@route("GET", "/api/rx/pending", "patients_read")
def api_rx_pending(h, c, b, q):
    pid = as_int(qget(q, "patient_id"), "patient")
    out = []
    for v in rows(c.execute("SELECT v.*, u.name dname, br.name bname FROM visits v LEFT JOIN users u ON u.id=v.doctor_id JOIN branches br ON br.id=v.branch_id "
                            "WHERE v.patient_id=? AND v.status='done' AND v.completed_at>=? ORDER BY v.id DESC", (pid, add_days(today(), -30)))):
        items = rows(c.execute("SELECT r.*, m.name, m.schedule, m.pack_size FROM rx_items r JOIN medicines m ON m.id=r.medicine_id WHERE visit_id=? AND dispensed<qty", (v["id"],)))
        if items:
            out.append({"visit_id": v["id"], "date": v["completed_at"], "doctor": v["dname"], "branch": v["bname"], "diagnosis": v["diagnosis"],
                        "items": [dict(i, remaining=i["qty"] - i["dispensed"]) for i in items]})
    return out


@route("GET", "/api/followups", "patients_read")
def api_followups(h, c, b, q):
    day = valid_day(qget(q, "date", today()))
    return [dict(r, code=pcode(r["pid"])) for r in rows(c.execute(
        "SELECT v.id, v.followup, v.diagnosis, p.id pid, p.name, p.phone, u.name dname, br.code bcode FROM visits v JOIN patients p ON p.id=v.patient_id "
        "LEFT JOIN users u ON u.id=v.doctor_id JOIN branches br ON br.id=v.branch_id WHERE v.followup=? AND (v.branch_id=? OR ?=0) ORDER BY br.code",
        (day, h.branch, h.branch)))]
