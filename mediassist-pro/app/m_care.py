"""Clinical records beyond the consultation: referrals (with a letter), procedures and operation notes with
informed consent, imaging orders and reports, antenatal visits, critical-result acknowledgement, lab sample
rejection and amended reports, and settlement of pharmacy credit bills."""
import json
import math

from .core import (ApiError, R, all_access, as_int, audit, can, clean, in_tx, need, need_branch, now_str, one, opt_num, pcode, qget,
                   route, rows, rs, today, valid_day)

URGENCY = ("routine", "urgent", "emergency")
MODALITIES = ("X-ray", "USG", "CT", "MRI", "ECG", "Echo", "Endoscopy", "Other")
ANAESTHESIA = ("none", "local", "regional", "spinal", "general", "sedation")


def patient_ok(c, h, pid):
    p = one(c, "SELECT * FROM patients WHERE id=?", (pid,))
    need(p, "Patient not found", 404)
    return p


def same_branch(h, row):
    need(row and (row["branch_id"] == h.branch or all_access(h.user)), "Not found in this branch", 404)
    return row


# ---------------------------------------------------------------- referrals
def create_referral(c, h, pid, b, visit_id=None, admission_id=None):
    br = need_branch(h, c, "hospital")
    p = patient_ok(c, h, pid)
    to = clean(b, "to_facility", 150)
    reason = clean(b, "reason", 1000)
    need(to and reason, "Enter where the patient is referred and why")
    urg = clean(b, "urgency", 10) or "routine"
    need(urg in URGENCY, "Urgency must be routine, urgent or emergency")
    vit = one(c, "SELECT temp,pulse,bp_sys,bp_dia,spo2,resp_rate,gcs,sugar FROM vitals WHERE patient_id=? ORDER BY at DESC LIMIT 1", (pid,))
    cur = c.execute("INSERT INTO referrals(branch_id,patient_id,visit_id,admission_id,at,by_user,to_facility,to_doctor,specialty,urgency,reason,summary,vitals,"
                    "treatment_given,transport,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'sent')",
                    (br["id"], pid, visit_id, admission_id, now_str(), h.user["id"], to, clean(b, "to_doctor", 100), clean(b, "specialty", 60), urg, reason,
                     clean(b, "summary", 3000), json.dumps(dict(vit)) if vit else None, clean(b, "treatment_given", 1000), clean(b, "transport", 40)))
    audit(c, h, "referral.create", f"{pcode(pid)} -> {to} ({urg}): {reason[:80]}")
    return cur.lastrowid


@route("POST", r"/api/patients/(\d+)/referrals", "consult")
def api_referral(h, c, b, q, pid):
    rid = in_tx(c, lambda: create_referral(c, h, int(pid), b, opt_num(b.get("visit_id"), int, "visit"), opt_num(b.get("admission_id"), int, "admission")))
    if b.get("notify", True):
        from .m_portal import share
        r = one(c, "SELECT to_facility FROM referrals WHERE id=?", (rid,))
        share(c, int(pid), f"Your doctor has referred you to {r['to_facility']}. The referral letter is in your records.", h.user["id"], pdf=("referral", rid))
    return {"ok": True, "id": rid}


@route("GET", r"/api/patients/(\d+)/referrals", "patients_read")
def api_referrals(h, c, b, q, pid):
    return rows(c.execute("SELECT r.*, u.name by_name, br.name bname FROM referrals r LEFT JOIN users u ON u.id=r.by_user JOIN branches br ON br.id=r.branch_id "
                          "WHERE r.patient_id=? ORDER BY r.id DESC", (int(pid),)))


@route("POST", r"/api/referrals/(\d+)/outcome", "consult")
def api_referral_outcome(h, c, b, q, rid):
    r = same_branch(h, one(c, "SELECT * FROM referrals WHERE id=?", (int(rid),)))
    st = clean(b, "status", 12)
    need(st in ("sent", "accepted", "seen", "returned", "declined"), "Unknown referral status")
    c.execute("UPDATE referrals SET status=?, outcome=? WHERE id=?", (st, clean(b, "outcome", 1000), r["id"]))
    audit(c, h, "referral.outcome", f"REF{r['id']} {st}")
    return {"ok": True}


# ---------------------------------------------------------------- procedures and operation notes
@route("POST", r"/api/patients/(\d+)/procedures", "consult")
def api_procedure(h, c, b, q, pid):
    br = need_branch(h, c, "hospital")
    pid = int(pid)
    patient_ok(c, h, pid)
    name = clean(b, "name", 150)
    need(name, "Enter the procedure name")
    kind = clean(b, "kind", 10) or "minor"
    need(kind in ("minor", "major", "daycare", "bedside"), "Kind must be minor, major, daycare or bedside")
    an = clean(b, "anaesthesia", 12) or "none"
    need(an in ANAESTHESIA, "Unknown anaesthesia type")
    consent_by, rel = clean(b, "consent_by", 100), clean(b, "consent_relation", 40)
    need(consent_by and rel, "Record who gave informed consent (the patient, or a relative with their relationship)")
    need(b.get("consent_explained"), "Tick that the procedure, risks and alternatives were explained before consent")
    adm = opt_num(b.get("admission_id"), int, "admission")
    if adm:
        a = one(c, "SELECT * FROM admissions WHERE id=? AND patient_id=?", (adm, pid))
        need(a, "Admission not found for this patient", 404)
    started, ended = clean(b, "started_at", 16), clean(b, "ended_at", 16)

    def run():
        cur = c.execute("INSERT INTO procedures(branch_id,patient_id,admission_id,visit_id,name,kind,surgeon_id,assistant,anaesthetist,anaesthesia,started_at,ended_at,"
                        "indication,findings,technique,implants,blood_loss,complications,post_op,consent_by,consent_relation,consent_at,consent_text,consent_witness,created_by,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (br["id"], pid, adm, opt_num(b.get("visit_id"), int, "visit"), name, kind, opt_num(b.get("surgeon_id"), int, "surgeon") or h.user["id"],
                         clean(b, "assistant", 100), clean(b, "anaesthetist", 100), an, started or now_str()[:16], ended or None,
                         clean(b, "indication", 1000), clean(b, "findings", 3000), clean(b, "technique", 3000), clean(b, "implants", 300), clean(b, "blood_loss", 40),
                         clean(b, "complications", 1000), clean(b, "post_op", 2000), consent_by, rel, now_str(), clean(b, "consent_text", 2000),
                         clean(b, "consent_witness", 100), h.user["id"], now_str()))
        sid = opt_num(b.get("service_id"), int, "service")
        if adm and sid:  # bill it on the running inpatient bill
            s = one(c, "SELECT * FROM services WHERE id=? AND active=1", (sid,))
            need(s, "Service not found", 404)
            c.execute("INSERT INTO ipd_charges(admission_id,at,service_id,name,cat,qty,rate_p,amount_p,user_id,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (adm, now_str(), s["id"], s["name"], s["cat"], 1, s["rate_p"], s["rate_p"], h.user["id"], "procedure"))
        audit(c, h, "procedure.record", f"{pcode(pid)} {name} ({kind}, {an}) consent by {consent_by} ({rel})")
        return cur.lastrowid
    return {"ok": True, "id": in_tx(c, run)}


@route("GET", r"/api/patients/(\d+)/procedures", "patients_read")
def api_procedures(h, c, b, q, pid):
    return rows(c.execute("SELECT pr.*, u.name surgeon, br.name bname FROM procedures pr LEFT JOIN users u ON u.id=pr.surgeon_id JOIN branches br ON br.id=pr.branch_id "
                          "WHERE pr.patient_id=? ORDER BY pr.id DESC", (int(pid),)))


# ---------------------------------------------------------------- imaging
@route("POST", r"/api/patients/(\d+)/imaging", "visit_create")
def api_imaging_order(h, c, b, q, pid):
    br = need_branch(h, c, "hospital")
    pid = int(pid)
    patient_ok(c, h, pid)
    mod, study = clean(b, "modality", 20), clean(b, "study", 150)
    need(mod in MODALITIES, "Choose the modality")
    need(study, "Enter the study, e.g. Chest PA")
    cur = c.execute("INSERT INTO imaging(branch_id,patient_id,visit_id,admission_id,modality,study,ordered_by,ordered_at,indication,status) VALUES(?,?,?,?,?,?,?,?,?,'ordered')",
                    (br["id"], pid, opt_num(b.get("visit_id"), int, "visit"), opt_num(b.get("admission_id"), int, "admission"), mod, study, h.user["id"], now_str(),
                     clean(b, "indication", 500)))
    audit(c, h, "imaging.order", f"{pcode(pid)} {mod} {study}")
    return {"ok": True, "id": cur.lastrowid}


@route("POST", r"/api/imaging/(\d+)/report", "any")
def api_imaging_report(h, c, b, q, iid):
    need(can(h, "consult") or can(h, "lab"), "Only doctors and technicians can report imaging", 403)
    im = same_branch(h, one(c, "SELECT * FROM imaging WHERE id=?", (int(iid),)))
    findings, impression = clean(b, "findings", 4000), clean(b, "impression", 1000)
    need(findings or impression, "Enter the findings or the impression")
    c.execute("UPDATE imaging SET findings=?, impression=?, reported_by=?, reported_at=?, status='reported', document_id=? WHERE id=?",
              (findings, impression, clean(b, "reported_by", 100) or h.user["name"], now_str(), opt_num(b.get("document_id"), int, "document"), im["id"]))
    audit(c, h, "imaging.report", f"IMG{im['id']} {im['modality']} {im['study']}")
    if impression and im["ordered_by"] and im["ordered_by"] != h.user["id"]:
        from .notify import notify_staff
        notify_staff(c, im["ordered_by"], f"Imaging reported: {im['modality']} {im['study']} for {pcode(im['patient_id'])}. Impression: {impression[:200]}")
    return {"ok": True}


@route("POST", r"/api/imaging/(\d+)/cancel", "visit_create")
def api_imaging_cancel(h, c, b, q, iid):
    im = same_branch(h, one(c, "SELECT * FROM imaging WHERE id=?", (int(iid),)))
    need(im["status"] == "ordered", "Only unreported studies can be cancelled")
    c.execute("UPDATE imaging SET status='cancelled' WHERE id=?", (im["id"],))
    audit(c, h, "imaging.cancel", f"IMG{im['id']} {clean(b, 'reason', 200)}")
    return {"ok": True}


@route("GET", "/api/imaging", "patients_read")
def api_imaging_list(h, c, b, q):
    need_branch(h, c, "hospital")
    st = qget(q, "status", "ordered")
    need(st in ("ordered", "reported", "cancelled"), "Unknown status")
    return [dict(r, code=pcode(r["patient_id"])) for r in rows(c.execute(
        "SELECT im.*, p.name pname, p.age, p.gender, u.name oname FROM imaging im JOIN patients p ON p.id=im.patient_id LEFT JOIN users u ON u.id=im.ordered_by "
        "WHERE im.branch_id=? AND im.status=? AND im.ordered_at>=? ORDER BY im.id DESC LIMIT 200", (h.branch, st, qget(q, "since") or "0")))]


@route("GET", r"/api/patients/(\d+)/imaging", "patients_read")
def api_imaging_for(h, c, b, q, pid):
    return rows(c.execute("SELECT im.*, u.name oname, br.name bname FROM imaging im LEFT JOIN users u ON u.id=im.ordered_by JOIN branches br ON br.id=im.branch_id "
                          "WHERE im.patient_id=? ORDER BY im.id DESC", (int(pid),)))


# ---------------------------------------------------------------- antenatal care
def anc_risks(r, p):
    out = []
    if r["bp_sys"] and r["bp_dia"] and (r["bp_sys"] >= 140 or r["bp_dia"] >= 90):
        out.append("high BP" + (" with proteinuria: pre-eclampsia?" if (r["urine_albumin"] or "").lower() not in ("", "nil", "negative", "absent", "trace") else ""))
    if r["hb"] is not None and r["hb"] < 11:
        out.append("anaemia" if r["hb"] >= 7 else "severe anaemia")
    if r["ga_weeks"] and r["ga_weeks"] >= 37 and (r["presentation"] or "").lower() not in ("", "cephalic", "vertex"):
        out.append(f"{r['presentation']} presentation at term")
    if r["fhr"] and (r["fhr"] < 110 or r["fhr"] > 160):
        out.append(f"FHR {r['fhr']}")
    if r["ga_weeks"] and r["fundal_cm"] and abs(r["fundal_cm"] - r["ga_weeks"]) > 3:
        out.append("fundal height does not match dates")
    if (r["urine_sugar"] or "").lower() not in ("", "nil", "negative", "absent"):
        out.append("glycosuria: screen for GDM")
    if p.get("age") and (p["age"] < 18 or p["age"] >= 35):
        out.append("age " + str(p["age"]))
    if (p.get("gravida") or 0) >= 5:
        out.append("grand multipara")
    return out


@route("POST", r"/api/patients/(\d+)/anc", "visit_create")
def api_anc_add(h, c, b, q, pid):
    pid = int(pid)
    p = patient_ok(c, h, pid)
    from .m_clinical import pregnancy_info
    preg = pregnancy_info(p)
    r = {"ga_weeks": opt_num(b.get("ga_weeks"), int, "gestational age") or (preg["weeks"] if preg else None),
         "weight": opt_num(b.get("weight"), float, "weight"), "bp_sys": opt_num(b.get("bp_sys"), int, "BP"), "bp_dia": opt_num(b.get("bp_dia"), int, "BP"),
         "fundal_cm": opt_num(b.get("fundal_cm"), float, "fundal height"), "fhr": opt_num(b.get("fhr"), int, "FHR"), "presentation": clean(b, "presentation", 20),
         "urine_albumin": clean(b, "urine_albumin", 10), "urine_sugar": clean(b, "urine_sugar", 10), "hb": opt_num(b.get("hb"), float, "Hb"),
         "oedema": 1 if b.get("oedema") else 0, "complaints": clean(b, "complaints", 500), "plan": clean(b, "plan", 1000), "next_visit": clean(b, "next_visit", 10) or None}
    if r["next_visit"]:
        valid_day(r["next_visit"], "next visit")
    need(any(v not in (None, "", 0) for k, v in r.items() if k not in ("ga_weeks", "oedema")), "Enter at least one finding")
    risk = ", ".join(anc_risks(r, p))
    for k in ("gravida", "para"):
        if b.get(k) not in (None, ""):
            c.execute(f"UPDATE patients SET {k}=? WHERE id=?", (opt_num(b.get(k), int, k), pid))
    cur = c.execute("INSERT INTO anc_visits(patient_id,visit_id,at,by_user,ga_weeks,weight,bp_sys,bp_dia,fundal_cm,fhr,presentation,urine_albumin,urine_sugar,hb,oedema,complaints,risk,plan,next_visit) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, opt_num(b.get("visit_id"), int, "visit"), now_str(), h.user["id"], r["ga_weeks"], r["weight"], r["bp_sys"], r["bp_dia"], r["fundal_cm"], r["fhr"],
                     r["presentation"], r["urine_albumin"], r["urine_sugar"], r["hb"], r["oedema"], r["complaints"], risk, r["plan"], r["next_visit"]))
    if r["weight"] or r["bp_sys"]:
        c.execute("INSERT INTO vitals(patient_id,at,source,ref_id,bp_sys,bp_dia,weight,recorded_by) VALUES(?,?,?,?,?,?,?,?)",
                  (pid, now_str(), "anc", cur.lastrowid, r["bp_sys"], r["bp_dia"], r["weight"], h.user["id"]))
    audit(c, h, "anc.visit", f"{pcode(pid)} {r['ga_weeks'] or '?'}w" + (f" RISK: {risk}" if risk else ""))
    return {"ok": True, "id": cur.lastrowid, "risk": risk}


@route("GET", r"/api/patients/(\d+)/anc", "patients_read")
def api_anc_list(h, c, b, q, pid):
    return rows(c.execute("SELECT a.*, u.name by_name FROM anc_visits a LEFT JOIN users u ON u.id=a.by_user WHERE a.patient_id=? ORDER BY a.id DESC", (int(pid),)))


# ---------------------------------------------------------------- growth reference (WHO medians, rounded; a guide, not a diagnosis)
WHO_MEDIAN_WEIGHT = {  # years -> kg
    "M": {0: 3.3, 0.5: 7.9, 1: 9.6, 2: 12.2, 3: 14.3, 4: 16.3, 5: 18.3, 6: 20.5, 7: 22.9, 8: 25.4, 9: 28.1, 10: 31.2},
    "F": {0: 3.2, 0.5: 7.3, 1: 8.9, 2: 11.5, 3: 13.9, 4: 16.1, 5: 18.2, 6: 20.2, 7: 22.4, 8: 25.0, 9: 28.2, 10: 31.9},
}


def lms_at(table, months):
    """Interpolate (L, M, S) at an age from a sorted list of (age_months, l, m, s)."""
    if not table or months < table[0][0] or months > table[-1][0]:
        return None
    lo = table[0]
    for row in table:
        if row[0] == months:
            return row[1:]
        if row[0] > months:
            f = (months - lo[0]) / (row[0] - lo[0])
            return tuple(lo[i] + (row[i] - lo[i]) * f for i in (1, 2, 3))
        lo = row
    return None


def zscore(value, lms):
    l, m, s = lms
    if l == 0:
        return math.log(value / m) / s
    return ((value / m) ** l - 1) / (l * s)


def value_at(z, lms):
    l, m, s = lms
    return m * math.exp(s * z) if l == 0 else m * (1 + l * s * z) ** (1 / l)


def zlabel(z):
    if z is None:
        return None
    return "below -3 SD" if z < -3 else "below -2 SD" if z < -2 else "above +3 SD" if z > 3 else "above +2 SD" if z > 2 else "normal range"


def growth_table(c, sex, kind):
    return [tuple(r) for r in c.execute("SELECT age_months,l,m,s FROM growth_ref WHERE sex=? AND kind=? ORDER BY age_months", (sex, kind))]


@route("GET", r"/api/patients/(\d+)/growth", "patients_read")
def api_growth(h, c, b, q, pid):
    """Weight/height/BMI over time. With WHO LMS tables loaded (Admin > Import data) each point gets a z-score and
    the chart shows the -2 SD, median and +2 SD curves; without them a rounded WHO median is drawn as a guide."""
    p = patient_ok(c, h, int(pid))
    sex = "F" if (p["gender"] or "").lower().startswith("f") else "M"
    wfa, hfa = growth_table(c, sex, "wfa"), growth_table(c, sex, "hfa")
    pts = rows(c.execute("SELECT at, weight, height FROM vitals WHERE patient_id=? AND (weight IS NOT NULL OR height IS NOT NULL) ORDER BY at", (p["id"],)))
    out = []
    from datetime import date
    for r in pts:
        age = months = None
        if p["dob"]:
            days = (date.fromisoformat(r["at"][:10]) - date.fromisoformat(p["dob"])).days
            age, months = round(days / 365.25, 2), days / 30.4375
        bmi = round(r["weight"] / (r["height"] / 100) ** 2, 1) if r["weight"] and r["height"] else None
        zw = zh = None
        if months is not None:
            lw, lh = lms_at(wfa, months), lms_at(hfa, months)
            zw = round(zscore(r["weight"], lw), 2) if r["weight"] and lw else None
            zh = round(zscore(r["height"], lh), 2) if r["height"] and lh else None
        out.append({"at": r["at"], "age": age, "weight": r["weight"], "height": r["height"], "bmi": bmi, "z_weight": zw, "z_height": zh,
                    "flag": zlabel(zw) if zw is not None else None})
    res = {"points": out, "sex": sex, "has_who": bool(wfa)}
    if wfa:
        curves = []
        m = wfa[0][0]
        while m <= wfa[-1][0]:
            lms = lms_at(wfa, m)
            curves.append({"months": round(m, 1), "age": round(m / 12, 2), "p3": round(value_at(-1.881, lms), 2), "p50": round(lms[1], 2), "p97": round(value_at(1.881, lms), 2)})
            m += 1 if wfa[-1][0] <= 60 else 3
        res["curves"] = curves
        res["note"] = "WHO growth standards (LMS tables loaded by the administrator): 3rd, 50th and 97th percentile weight-for-age."
    else:
        res["reference"] = [{"age": a, "weight": w} for a, w in sorted(WHO_MEDIAN_WEIGHT[sex].items())]
        res["note"] = "Reference line is a rounded WHO median weight-for-age. Load the WHO LMS tables in Admin > Import data for real percentiles and z-scores."
    return res


@route("POST", "/api/import/growth", "admin")
def api_import_growth(h, c, b, q):
    """Load a WHO growth-standard table (CSV from who.int: columns Month or Day, L, M, S) for one sex and measure."""
    import csv
    import io
    sex, kind = clean(b, "sex", 1).upper(), clean(b, "kind", 3).lower()
    need(sex in ("M", "F"), "Sex must be M or F")
    need(kind in ("wfa", "hfa"), "Kind must be wfa (weight-for-age) or hfa (height-for-age)")
    text = str(b.get("csv") or "").lstrip("\ufeff")
    rd = csv.DictReader(io.StringIO(text), delimiter="\t" if "\t" in text.splitlines()[0] else ",")
    need(rd.fieldnames, "The file has no header row")
    cols = {(k or "").strip().lower(): k for k in rd.fieldnames}
    age_col = next((cols[k] for k in ("month", "months", "age_months", "agemos", "day", "days", "age") if k in cols), None)
    need(age_col and all(k in cols for k in ("l", "m", "s")), "Expected columns Month (or Day), L, M, S")
    per_day = age_col.strip().lower() in ("day", "days")
    rows_ = []
    for r in rd:
        try:
            a = float(r[age_col])
            rows_.append((sex, kind, round(a / 30.4375, 3) if per_day else a, float(r[cols["l"]]), float(r[cols["m"]]), float(r[cols["s"]])))
        except (TypeError, ValueError):
            continue
    need(len(rows_) >= 12, "Fewer than 12 usable rows: is this a WHO LMS table?")

    def run():
        c.executemany("INSERT INTO growth_ref(sex,kind,age_months,l,m,s) VALUES(?,?,?,?,?,?) ON CONFLICT(sex,kind,age_months) DO UPDATE SET l=excluded.l, m=excluded.m, s=excluded.s", rows_)
        audit(c, h, "import.growth", f"{sex} {kind} {len(rows_)} rows")
        return len(rows_)
    return {"ok": True, "rows": in_tx(c, run), "range_months": [rows_[0][2], rows_[-1][2]]}


# ---------------------------------------------------------------- critical results: acknowledgement
@route("GET", "/api/lab/critical", "consult")
def api_critical(h, c, b, q):
    """Verified or resulted orders with a critical value that no doctor has acknowledged yet: mine, or unassigned ones in my branch."""
    need_branch(h, c, "hospital")
    out = []
    for o in rows(c.execute("SELECT o.*, p.name pname FROM lab_orders o JOIN patients p ON p.id=o.patient_id WHERE o.branch_id=? AND o.status IN ('resulted','verified') "
                            "AND o.crit_ack_at IS NULL AND (o.doctor_id=? OR o.doctor_id IS NULL OR ?) AND EXISTS "
                            "(SELECT 1 FROM lab_order_items i JOIN lab_results r ON r.order_item_id=i.id WHERE i.order_id=o.id AND r.flag IN ('LL','HH')) ORDER BY o.id DESC",
                            (h.branch, h.user["id"], 1 if all_access(h.user) else 0))):
        vals = rows(c.execute("SELECT lp.name, r.value, lp.unit, r.flag FROM lab_order_items i JOIN lab_results r ON r.order_item_id=i.id JOIN lab_params lp ON lp.id=r.param_id "
                              "WHERE i.order_id=? AND r.flag IN ('LL','HH')", (o["id"],)))
        out.append({"id": o["id"], "pname": o["pname"], "code": pcode(o["patient_id"]), "at": o["resulted_at"] or o["created_at"], "status": o["status"],
                    "assigned": o["doctor_id"] == h.user["id"], "values": vals})
    return out


@route("POST", r"/api/lab/orders/(\d+)/ack", "consult")
def api_ack(h, c, b, q, oid):
    o = same_branch(h, one(c, "SELECT * FROM lab_orders WHERE id=?", (int(oid),)))
    need(not o["crit_ack_at"], "Already acknowledged")
    c.execute("UPDATE lab_orders SET crit_ack_by=?, crit_ack_at=?, doctor_id=COALESCE(doctor_id, ?) WHERE id=?", (h.user["id"], now_str(), h.user["id"], o["id"]))
    audit(c, h, "lab.critical_ack", f"LAB{o['id']} {clean(b, 'action', 300)}")
    return {"ok": True}


# ---------------------------------------------------------------- lab: sample rejection and amended reports
@route("POST", r"/api/lab/orders/(\d+)/reject", "lab")
def api_reject_sample(h, c, b, q, oid):
    o = one(c, "SELECT * FROM lab_orders WHERE id=? AND branch_id=?", (int(oid), h.branch))
    need(o and o["status"] == "collected", "Only a collected sample can be rejected")
    reason = clean(b, "reason", 200)
    need(reason, "Say why the sample was rejected (haemolysed, clotted, insufficient, unlabelled...)")
    c.execute("DELETE FROM lab_results WHERE order_item_id IN (SELECT id FROM lab_order_items WHERE order_id=?)", (o["id"],))
    c.execute("UPDATE lab_orders SET status='ordered', collected_at=NULL, collected_by=NULL, rejections=rejections+1, reject_note=? WHERE id=?",
              (f"{now_str()[:16]} {h.user['name']}: {reason}" + (f"\n{o['reject_note']}" if o["reject_note"] else ""), o["id"]))
    audit(c, h, "lab.reject_sample", f"LAB{o['id']} {reason}")
    if o["doctor_id"]:
        from .notify import notify_staff
        notify_staff(c, o["doctor_id"], f"Lab sample rejected for {pcode(o['patient_id'])}, LAB{o['id']}: {reason}. A fresh sample is needed.")
    return {"ok": True}


@route("POST", r"/api/lab/orders/(\d+)/amend", "lab_verify")
def api_amend(h, c, b, q, oid):
    o = one(c, "SELECT * FROM lab_orders WHERE id=? AND branch_id=?", (int(oid), h.branch))
    need(o and o["status"] == "verified", "Only a verified report can be amended")
    reason = clean(b, "reason", 300)
    need(reason, "Say why the report is being amended")
    c.execute("UPDATE lab_orders SET status='resulted', amended_at=?, amend_reason=?, verified_at=NULL, verified_by=NULL, interp_reviewed_by=NULL, interp_reviewed_at=NULL WHERE id=?", (now_str(), reason, o["id"]))
    audit(c, h, "lab.amend", f"LAB{o['id']} {reason}")
    return {"ok": True}


# ---------------------------------------------------------------- pharmacy credit bills
@route("GET", "/api/bills/credit", "hbilling")
def api_credit_bills(h, c, b, q):
    need_branch(h, c)
    pid = opt_num(qget(q, "patient_id"), int, "patient")
    sql = ("SELECT b.id, b.bill_no, b.created_at, b.total_p, b.returned_p, b.patient_id, b.admission_id, p.name pname FROM bills b LEFT JOIN patients p ON p.id=b.patient_id "
           "WHERE b.pay_mode='credit' AND b.settled_at IS NULL AND b.branch_id=?")
    args = [h.branch]
    if pid:
        sql += " AND b.patient_id=?"
        args.append(pid)
    return [dict(r, code=pcode(r["patient_id"]) if r["patient_id"] else "", due=R(r["total_p"] - r["returned_p"])) for r in rows(c.execute(sql + " ORDER BY b.id DESC LIMIT 300", args))]


@route("POST", r"/api/bills/(\d+)/settle", "any")
def api_settle_bill(h, c, b, q, bid):
    need(can(h, "hbilling") or can(h, "billing"), "Your role can't do this", 403)  # hospital billing desk or the pharmacy counter
    mode, ref = clean(b, "mode", 10) or "cash", clean(b, "ref", 40)
    need(mode in ("cash", "upi", "card"), "Invalid payment mode")
    need(mode == "cash" or ref, "Enter the transaction reference")

    def run():
        bl = one(c, "SELECT * FROM bills WHERE id=? AND branch_id=?", (int(bid), h.branch))
        need(bl, "Bill not found", 404)
        need(bl["pay_mode"] == "credit" and not bl["settled_at"], "This bill is not an open credit bill")
        if bl["admission_id"] and not can(h, "hbilling"):
            st = one(c, "SELECT ip_no, status FROM admissions WHERE id=?", (bl["admission_id"],))
            need(not st or st["status"] != "admitted", f"This bill goes on the inpatient bill for {st['ip_no'] if st else 'the stay'}. Collect it at discharge.")
        c.execute("UPDATE bills SET settled_at=?, settled_mode=?, settled_invoice_id=NULL WHERE id=?", (now_str(), mode, bl["id"]))
        audit(c, h, "bill.settle", f"{bl['bill_no']} {rs(bl['total_p'] - bl['returned_p'])} {mode} {ref}")
        return R(bl["total_p"] - bl["returned_p"])
    return {"ok": True, "amount": in_tx(c, run)}


# ---------------------------------------------------------------- adverse drug reactions
SEVERITIES = ("mild", "moderate", "severe")


@route("POST", r"/api/patients/(\d+)/reactions", "any")
def api_reaction_add(h, c, b, q, pid):
    """Record a reaction to a medicine. It shows at every consultation and the prescribing check warns if that
    drug (or anything containing the same ingredient) is prescribed again."""
    need(can(h, "patients_write") or can(h, "ipd_nursing"), "Your role can't do this", 403)  # the nurse who sees the reaction records it
    pid = int(pid)
    patient_ok(c, h, pid)
    mid = opt_num(b.get("medicine_id"), int, "medicine")
    m = one(c, "SELECT name, generic FROM medicines WHERE id=?", (mid,)) if mid else None
    drug = clean(b, "drug", 100) or (m["name"] if m else "")
    reaction = clean(b, "reaction", 300)
    need(drug and reaction, "Enter the medicine and what happened")
    sev = clean(b, "severity", 10) or "moderate"
    need(sev in SEVERITIES, "Severity must be mild, moderate or severe")
    when = clean(b, "reacted_on", 10) or None
    if when:
        valid_day(when, "date")
    cur = c.execute("INSERT INTO adverse_reactions(patient_id,medicine_id,drug,reaction,severity,reacted_on,visit_id,notes,recorded_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (pid, mid, drug, reaction, sev, when, opt_num(b.get("visit_id"), int, "visit"), clean(b, "notes", 500), h.user["id"], now_str()))
    if sev == "severe" or b.get("add_allergy"):  # a severe reaction is an allergy for prescribing purposes
        p = one(c, "SELECT allergies FROM patients WHERE id=?", (pid,))
        word = (m["generic"].split()[0] if m and m["generic"] else drug).lower()
        if word not in (p["allergies"] or "").lower():
            c.execute("UPDATE patients SET allergies=? WHERE id=?", (((p["allergies"] + ", ") if p["allergies"] else "") + word, pid))
    audit(c, h, "reaction.record", f"{pcode(pid)} {drug}: {reaction} ({sev})")
    return {"ok": True, "id": cur.lastrowid}


@route("GET", r"/api/patients/(\d+)/reactions", "patients_read")
def api_reactions(h, c, b, q, pid):
    return reactions_of(c, int(pid))


def reactions_of(c, pid):
    return rows(c.execute("SELECT r.*, m.generic, u.name by_name FROM adverse_reactions r LEFT JOIN medicines m ON m.id=r.medicine_id LEFT JOIN users u ON u.id=r.recorded_by "
                          "WHERE r.patient_id=? ORDER BY r.id DESC", (pid,)))


@route("POST", r"/api/reactions/(\d+)/delete", "patients_write")
def api_reaction_delete(h, c, b, q, rid):
    r = one(c, "SELECT * FROM adverse_reactions WHERE id=?", (int(rid),))
    need(r, "Not found", 404)
    need(clean(b, "reason", 200), "Say why this record is wrong")
    c.execute("DELETE FROM adverse_reactions WHERE id=?", (r["id"],))
    audit(c, h, "reaction.delete", f"{pcode(r['patient_id'])} {r['drug']}: {clean(b, 'reason', 200)}")
    return {"ok": True}
