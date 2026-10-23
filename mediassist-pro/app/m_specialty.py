"""Specialty records and standards: dental tooth chart (FDI numbering), physiotherapy plans and sessions with
pain progress, clinical catalogue importers (ICD-10, lab tests, medicine master) and FHIR R4 document bundles
for ABDM (prescription, diagnostic report, discharge summary)."""
import csv
import io
import json
import uuid

from .core import (R, all_access, as_int, audit, clean, get_settings, in_tx, need, need_branch, now_str, one, opt_num, pcode, qget, route, rows, today, valid_day)

ADULT_TEETH = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28, 48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
CHILD_TEETH = [55, 54, 53, 52, 51, 61, 62, 63, 64, 65, 85, 84, 83, 82, 81, 71, 72, 73, 74, 75]
TOOTH_STATES = ("caries", "filled", "missing", "crown", "root canal", "implant", "fracture", "mobile", "extracted", "sealant", "other")


# ---------------------------------------------------------------- dental
@route("GET", r"/api/patients/(\d+)/dental", "patients_read")
def api_dental(h, c, b, q, pid):
    entries = rows(c.execute("SELECT d.*, u.name uname FROM dental_chart d LEFT JOIN users u ON u.id=d.user_id WHERE d.patient_id=? ORDER BY d.id DESC", (int(pid),)))
    latest = {}
    for e in reversed(entries):  # oldest first: the newest entry per tooth wins
        latest[e["tooth"]] = e
    return {"teeth": ADULT_TEETH, "child_teeth": CHILD_TEETH, "states": TOOTH_STATES, "latest": {str(k): v for k, v in latest.items()}, "history": entries}


@route("POST", r"/api/patients/(\d+)/dental", "consult")
def api_dental_add(h, c, b, q, pid):
    pid = int(pid)
    need(one(c, "SELECT 1 FROM patients WHERE id=?", (pid,)), "Patient not found", 404)
    tooth = as_int(b.get("tooth"), "tooth")
    need(tooth in ADULT_TEETH or tooth in CHILD_TEETH, "Tooth number must be FDI (11-48 adult, 51-85 child)")
    state = clean(b, "state", 20)
    need(state in TOOTH_STATES, "Pick a finding")
    kind = clean(b, "kind", 10) or "finding"
    need(kind in ("finding", "treatment"), "Kind must be finding or treatment")
    c.execute("INSERT INTO dental_chart(patient_id,tooth,state,kind,procedure,surfaces,notes,at,visit_id,user_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (pid, tooth, state, kind, clean(b, "procedure", 100), clean(b, "surfaces", 10).upper(), clean(b, "notes", 500), now_str(), opt_num(b.get("visit_id"), int, "visit"), h.user["id"]))
    audit(c, h, "dental.chart", f"{pcode(pid)} tooth {tooth} {kind} {state}")
    return {"ok": True}


# ---------------------------------------------------------------- physiotherapy
@route("GET", r"/api/patients/(\d+)/physio", "patients_read")
def api_physio(h, c, b, q, pid):
    plans = rows(c.execute("SELECT p.*, u.name uname FROM physio_plans p LEFT JOIN users u ON u.id=p.user_id WHERE p.patient_id=? ORDER BY p.id DESC", (int(pid),)))
    for p in plans:
        p["sessions"] = rows(c.execute("SELECT s.*, u.name uname FROM physio_sessions s LEFT JOIN users u ON u.id=s.user_id WHERE s.plan_id=? ORDER BY s.at", (p["id"],)))
        p["done"] = len(p["sessions"])
        pains = [s["pain_after"] for s in p["sessions"] if s["pain_after"] is not None]
        p["pain_trend"] = pains
    return plans


@route("POST", r"/api/patients/(\d+)/physio", "visit_create")
def api_physio_plan(h, c, b, q, pid):
    pid = int(pid)
    need(one(c, "SELECT 1 FROM patients WHERE id=?", (pid,)), "Patient not found", 404)
    dx = clean(b, "diagnosis", 200)
    need(dx, "Enter the condition being treated")
    n = opt_num(b.get("planned_sessions"), int, "sessions") or 10
    need(1 <= n <= 100, "Planned sessions: 1 to 100")
    cur = c.execute("INSERT INTO physio_plans(patient_id,diagnosis,goals,planned_sessions,started,status,user_id,visit_id) VALUES(?,?,?,?,?,'active',?,?)",
                    (pid, dx, clean(b, "goals", 500), n, today(), h.user["id"], opt_num(b.get("visit_id"), int, "visit")))
    audit(c, h, "physio.plan", f"{pcode(pid)} {dx} {n} sessions")
    return {"ok": True, "id": cur.lastrowid}


@route("POST", r"/api/physio/(\d+)/session", "visit_create")
def api_physio_session(h, c, b, q, plan_id):
    p = one(c, "SELECT * FROM physio_plans WHERE id=?", (int(plan_id),))
    need(p and p["status"] == "active", "Plan not found or closed", 404)
    pb, pa = opt_num(b.get("pain_before"), int, "pain"), opt_num(b.get("pain_after"), int, "pain")
    for x in (pb, pa):
        need(x is None or 0 <= x <= 10, "Pain is 0 to 10")
    c.execute("INSERT INTO physio_sessions(plan_id,at,exercises,duration_min,pain_before,pain_after,rom,notes,user_id) VALUES(?,?,?,?,?,?,?,?,?)",
              (p["id"], now_str(), clean(b, "exercises", 1000), opt_num(b.get("duration_min"), int, "minutes"), pb, pa, clean(b, "rom", 300), clean(b, "notes", 500), h.user["id"]))
    done = c.execute("SELECT COUNT(*) FROM physio_sessions WHERE plan_id=?", (p["id"],)).fetchone()[0]
    if done >= p["planned_sessions"] and b.get("close_when_done", True):
        c.execute("UPDATE physio_plans SET status='completed' WHERE id=?", (p["id"],))
    sid = opt_num(b.get("service_id"), int, "service")
    if sid and h.branch:  # bill the session as a service on a new invoice line later: record it on the plan for billing
        c.execute("UPDATE physio_sessions SET service_id=? WHERE id=last_insert_rowid()", (sid,)) if False else None
    audit(c, h, "physio.session", f"plan {p['id']} session {done}/{p['planned_sessions']}")
    return {"ok": True, "done": done, "planned": p["planned_sessions"]}


@route("POST", r"/api/physio/(\d+)/close", "visit_create")
def api_physio_close(h, c, b, q, plan_id):
    p = one(c, "SELECT * FROM physio_plans WHERE id=?", (int(plan_id),))
    need(p, "Plan not found", 404)
    c.execute("UPDATE physio_plans SET status=?, outcome=? WHERE id=?", (clean(b, "status", 12) or "completed", clean(b, "outcome", 500), p["id"]))
    return {"ok": True}


# ---------------------------------------------------------------- catalogue importers
def _csv(text):
    text = text.lstrip("\ufeff")
    rd = csv.DictReader(io.StringIO(text), delimiter="\t" if "\t" in text.splitlines()[0] else ",")
    need(rd.fieldnames, "The file has no header row")
    out = []
    for r in rd:
        row = {}
        for k, v in r.items():
            if k is None:  # extra unquoted commas: keep the text on the last named column
                last = list(row)[-1] if row else None
                if last is not None:
                    row[last] = (row[last] + ", " + ", ".join(x.strip() for x in v)).strip(", ")
                continue
            row[k.strip().lower()] = (v if isinstance(v, str) else "").strip()
        out.append(row)
    return out


@route("POST", "/api/import/icd10", "admin")
def api_import_icd(h, c, b, q):
    """Full ICD-10 list from a CSV with columns code,title (the WHO release, India's version, or a CSV you export)."""
    data = _csv(str(b.get("csv") or ""))
    rows_ = []
    for r in data:
        code = (r.get("code") or r.get("icd") or r.get("icd10") or "").upper().strip()
        title = r.get("title") or r.get("description") or r.get("name") or ""
        if code and title and len(code) <= 10:
            rows_.append((code, title[:200]))
    need(rows_, "Expected columns code,title")

    def run():
        c.executemany("INSERT INTO icd10(code,title) VALUES(?,?) ON CONFLICT(code) DO UPDATE SET title=excluded.title", rows_)
        audit(c, h, "import.icd10", f"{len(rows_)} codes")
        return len(rows_)
    return {"ok": True, "codes": in_tx(c, run), "total": c.execute("SELECT COUNT(*) FROM icd10").fetchone()[0]}


@route("POST", "/api/import/lab-tests", "admin")
def api_import_lab_tests(h, c, b, q):
    """Lab catalogue from a CSV: one row per parameter: code,test,sample,rate,tat_hours,param,unit,low,high,crit_low,crit_high,ref_text.
    Rows with the same code form one test. Existing tests get new parameters added; ranges of existing parameters are updated."""
    data = _csv(str(b.get("csv") or ""))
    by = {}
    for r in data:
        code = (r.get("code") or "").upper().strip()
        if not code:
            continue
        t = by.setdefault(code, {"name": r.get("test") or r.get("name") or code, "sample": r.get("sample") or "", "rate": r.get("rate") or "0", "tat": r.get("tat_hours") or "24", "params": []})
        if r.get("param"):
            f = lambda k: float(r[k]) if r.get(k) not in (None, "") else None  # noqa: E731
            try:
                t["params"].append((r["param"], r.get("unit") or "", f("low"), f("high"), f("crit_low"), f("crit_high"), r.get("ref_text") or None))
            except ValueError:
                raise __import__("app.core", fromlist=["ApiError"]).ApiError(400, f"{code} {r['param']}: ranges must be numbers")
    need(by, "Expected columns code,test,param,unit,low,high")

    def run():
        n_t = n_p = 0
        for code, t in by.items():
            ex = one(c, "SELECT * FROM lab_tests WHERE code=?", (code,))
            if ex:
                tid = ex["id"]
            else:
                s = c.execute("INSERT INTO services(name,cat,rate_p,gst_pct) VALUES(?,?,?,0)", (f"Lab: {t['name']}", "Laboratory", int(float(t["rate"]) * 100)))
                tid = c.execute("INSERT INTO lab_tests(code,name,sample,service_id,tat_hours) VALUES(?,?,?,?,?)", (code, t["name"][:100], t["sample"][:40], s.lastrowid, int(float(t["tat"]) or 24))).lastrowid
                n_t += 1
            for i, (pn, unit, lo, hi, clo, chi, ref) in enumerate(t["params"]):
                pe = one(c, "SELECT id FROM lab_params WHERE test_id=? AND lower(name)=lower(?)", (tid, pn))
                if pe:
                    c.execute("UPDATE lab_params SET unit=?, low=?, high=?, crit_low=?, crit_high=?, ref_text=? WHERE id=?", (unit, lo, hi, clo, chi, ref, pe["id"]))
                else:
                    c.execute("INSERT INTO lab_params(test_id,name,unit,low,high,crit_low,crit_high,ref_text,sort) VALUES(?,?,?,?,?,?,?,?,?)", (tid, pn[:60], unit[:20], lo, hi, clo, chi, ref, i))
                    n_p += 1
        audit(c, h, "import.lab_tests", f"{n_t} tests, {n_p} parameters")
        return n_t, n_p
    n_t, n_p = in_tx(c, run)
    return {"ok": True, "tests_added": n_t, "params_added": n_p, "total_tests": c.execute("SELECT COUNT(*) FROM lab_tests").fetchone()[0]}


@route("POST", "/api/import/medicines", "admin")
def api_import_medicines(h, c, b, q):
    """Medicine master with clinical limits from a CSV: name,generic,form,schedule,gst,hsn,pack_size,strength_mg,max_daily_mg,ped_mg_per_kg_day,renal_caution,pregnancy_avoid,cold_chain,barcode.
    Existing brands (by name) are updated; the rest are added. Use it to load a licensed drug database export."""
    data = _csv(str(b.get("csv") or ""))
    need(data, "Empty file")

    def num(v, cast=float):
        try:
            return cast(v) if v not in (None, "") else None
        except ValueError:
            return None

    def run():
        added = updated = 0
        for r in data:
            name = (r.get("name") or r.get("brand") or r.get("medicine") or "")[:100]
            if not name:
                continue
            vals = (r.get("generic", "").lower()[:150], (r.get("form") or "Tablet")[:20], (r.get("schedule") or "OTC").upper()[:3], num(r.get("gst"), float) or 12,
                    (r.get("hsn") or "3004")[:10], num(r.get("pack_size"), int) or 1, num(r.get("strength_mg")), num(r.get("max_daily_mg")), num(r.get("ped_mg_per_kg_day")),
                    1 if str(r.get("renal_caution", "")).lower() in ("1", "yes", "true", "y") else 0, 1 if str(r.get("pregnancy_avoid", "")).lower() in ("1", "yes", "true", "y") else 0,
                    1 if str(r.get("cold_chain", "")).lower() in ("1", "yes", "true", "y") else 0, (r.get("barcode") or None))
            ex = one(c, "SELECT id FROM medicines WHERE lower(name)=lower(?)", (name,))
            if ex:
                c.execute("UPDATE medicines SET generic=?,form=?,schedule=?,gst_pct=?,hsn=?,pack_size=?,strength_mg=?,max_daily_mg=?,ped_mg_per_kg_day=?,renal_caution=?,pregnancy_avoid=?,cold_chain=?,barcode=COALESCE(?,barcode) WHERE id=?", (*vals, ex["id"]))
                updated += 1
            else:
                c.execute("INSERT INTO medicines(name,generic,form,schedule,gst_pct,hsn,pack_size,strength_mg,max_daily_mg,ped_mg_per_kg_day,renal_caution,pregnancy_avoid,cold_chain,barcode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (name, *vals))
                added += 1
        audit(c, h, "import.medicines", f"{added} added, {updated} updated")
        return added, updated
    a, u = in_tx(c, run)
    return {"ok": True, "added": a, "updated": u}


# ---------------------------------------------------------------- FHIR R4 bundles for ABDM (NRCeS profiles, simplified)
def _fhir_patient(p):
    ids = [{"system": "https://healthid.ndhm.gov.in", "value": p["abha"]}] if p.get("abha") else []
    if p.get("abha_address"):
        ids.append({"system": "https://healthid.abdm.gov.in", "value": p["abha_address"]})
    return {"resourceType": "Patient", "id": f"patient-{p['id']}", "identifier": ids + [{"system": "urn:mediassist:patient", "value": pcode(p["id"])}],
            "name": [{"text": p["name"]}], "gender": {"male": "male", "female": "female"}.get((p.get("gender") or "").lower(), "other"),
            "birthDate": p.get("dob"), "telecom": [{"system": "phone", "value": p["phone"]}] if p.get("phone") else []}


def _fhir_org(br):
    return {"resourceType": "Organization", "id": f"org-{br['id']}", "name": br["name"], "identifier": [{"system": "https://facility.ndhm.gov.in", "value": br.get("hfr_id") or ""}] if br.get("hfr_id") else [],
            "telecom": [{"system": "phone", "value": br["phone"]}] if br.get("phone") else [], "address": [{"text": br.get("address") or ""}]}


def _fhir_pract(u):
    return {"resourceType": "Practitioner", "id": f"pract-{u['id']}", "name": [{"text": u["name"]}],
            "identifier": [{"system": "https://doctor.ndhm.gov.in", "value": u.get("hpr_id") or u.get("reg_no") or ""}]}


def _bundle(kind, title, patient, org, pract, sections, extra, when):
    bid = str(uuid.uuid4())
    comp = {"resourceType": "Composition", "id": f"comp-{bid}", "status": "final", "type": {"text": title}, "date": when, "title": title,
            "subject": {"reference": f"Patient/{patient['id']}"}, "author": [{"reference": f"Practitioner/{pract['id']}"}] if pract else [{"reference": f"Organization/{org['id']}"}],
            "custodian": {"reference": f"Organization/{org['id']}"}, "section": sections}
    entries = [comp, patient, org] + ([pract] if pract else []) + extra
    return {"resourceType": "Bundle", "id": bid, "type": "document", "timestamp": when, "meta": {"profile": [f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/{kind}"]},
            "identifier": {"system": "urn:mediassist:bundle", "value": bid}, "entry": [{"fullUrl": f"urn:uuid:{e['resourceType']}-{e['id']}", "resource": e} for e in entries]}


def fhir_prescription(c, vid):
    v = one(c, "SELECT v.*, u.id uid, u.name uname, u.reg_no FROM visits v LEFT JOIN users u ON u.id=v.doctor_id WHERE v.id=?", (vid,))
    need(v and v["status"] == "done", "Prescription not found", 404)
    p, br = one(c, "SELECT * FROM patients WHERE id=?", (v["patient_id"],)), one(c, "SELECT * FROM branches WHERE id=?", (v["branch_id"],))
    pat, org = _fhir_patient(dict(p)), _fhir_org(dict(br))
    pr = _fhir_pract({"id": v["uid"], "name": v["uname"], "reg_no": v["reg_no"]}) if v["uid"] else None
    from .rx_words import how_to_take
    meds = []
    for i, r in enumerate(rows(c.execute("SELECT r.*, m.name, m.generic, m.form FROM rx_items r JOIN medicines m ON m.id=r.medicine_id WHERE r.visit_id=?", (vid,)))):
        meds.append({"resourceType": "MedicationRequest", "id": f"medreq-{r['id']}", "status": "active", "intent": "order",
                     "medicationCodeableConcept": {"text": r["name"] + (f" ({r['generic']})" if r["generic"] else "")}, "subject": {"reference": f"Patient/{pat['id']}"},
                     "authoredOn": (v["completed_at"] or v["created_at"])[:10], "requester": {"reference": f"Practitioner/{pr['id']}"} if pr else None,
                     "dosageInstruction": [{"text": how_to_take(dict(r), "en"), "patientInstruction": r["instructions"] or None, "timing": {"code": {"text": r["freq"]}}}],
                     "dispenseRequest": {"quantity": {"value": r["qty"]}, "expectedSupplyDuration": {"value": r["days"], "unit": "d"}}})
    cond = [{"resourceType": "Condition", "id": f"cond-{vid}", "code": {"text": v["diagnosis"], **({"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": v["icd"]}]} if v["icd"] else {})}, "subject": {"reference": f"Patient/{pat['id']}"}}] if v["diagnosis"] else []
    sections = [{"title": "Prescription record", "entry": [{"reference": f"MedicationRequest/{m['id']}"} for m in meds]}]
    if cond:
        sections.append({"title": "Diagnosis", "entry": [{"reference": f"Condition/{cond[0]['id']}"}]})
    return _bundle("PrescriptionRecord", "Prescription", pat, org, pr, sections, meds + cond, (v["completed_at"] or v["created_at"]).replace(" ", "T") + ":00+05:30")


def fhir_lab(c, oid):
    from .m_lab import order_detail
    o = order_detail(c, oid)
    need(o["status"] == "verified", "Report not verified", 409)
    p, br = one(c, "SELECT * FROM patients WHERE id=?", (o["patient_id"],)), one(c, "SELECT * FROM branches WHERE id=?", (o["branch_id"],))
    pat, org = _fhir_patient(dict(p)), _fhir_org(dict(br))
    vu = one(c, "SELECT * FROM users WHERE id=?", (o["verified_by"],))
    pr = _fhir_pract(dict(vu)) if vu else None
    obs, reports = [], []
    for t in o["tests"]:
        refs = []
        for pm in t["params"]:
            if pm["value"] in (None, ""):
                continue
            ob = {"resourceType": "Observation", "id": f"obs-{t['item_id']}-{pm['id']}", "status": "final", "code": {"text": pm["name"]}, "subject": {"reference": f"Patient/{pat['id']}"},
                  "effectiveDateTime": (o["resulted_at"] or o["created_at"])[:10]}
            try:
                ob["valueQuantity"] = {"value": float(pm["value"]), "unit": pm["unit"] or ""}
            except ValueError:
                ob["valueString"] = pm["value"]
            if pm["low"] is not None or pm["high"] is not None:
                ob["referenceRange"] = [{"low": {"value": pm["low"]} if pm["low"] is not None else None, "high": {"value": pm["high"]} if pm["high"] is not None else None}]
            if pm["flag"] and pm["flag"] != "N":
                ob["interpretation"] = [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation", "code": {"H": "H", "L": "L", "HH": "HH", "LL": "LL", "A": "A"}[pm["flag"]]}]}]
            obs.append(ob); refs.append({"reference": f"Observation/{ob['id']}"})
        reports.append({"resourceType": "DiagnosticReport", "id": f"dr-{t['item_id']}", "status": "final", "code": {"text": t["name"]}, "subject": {"reference": f"Patient/{pat['id']}"},
                        "issued": (o["verified_at"] or "").replace(" ", "T") + ":00+05:30", "result": refs, "conclusion": (o.get("interp") or {}).get("summary") if o.get("interp_patient") else None})
    sections = [{"title": "Diagnostic reports", "entry": [{"reference": f"DiagnosticReport/{r['id']}"} for r in reports]}]
    return _bundle("DiagnosticReportRecord", "Laboratory report", pat, org, pr, sections, reports + obs, (o["verified_at"] or now_str()).replace(" ", "T") + ":00+05:30")


def fhir_discharge(c, aid):
    a = one(c, "SELECT a.*, u.id uid, u.name uname, u.reg_no FROM admissions a LEFT JOIN users u ON u.id=a.doctor_id WHERE a.id=?", (aid,))
    need(a and a["status"] == "discharged", "Discharge summary not ready", 404)
    p, br = one(c, "SELECT * FROM patients WHERE id=?", (a["patient_id"],)), one(c, "SELECT * FROM branches WHERE id=?", (a["branch_id"],))
    pat, org = _fhir_patient(dict(p)), _fhir_org(dict(br))
    pr = _fhir_pract({"id": a["uid"], "name": a["uname"], "reg_no": a["reg_no"]}) if a["uid"] else None
    s = json.loads(a["summary"]) if a["summary"] else {}
    enc = {"resourceType": "Encounter", "id": f"enc-{aid}", "status": "finished", "class": {"code": "IMP", "display": "inpatient encounter"}, "subject": {"reference": f"Patient/{pat['id']}"},
           "period": {"start": a["admitted_at"].replace(" ", "T") + ":00+05:30", "end": a["discharged_at"].replace(" ", "T") + ":00+05:30"}, "hospitalization": {"dischargeDisposition": {"text": a["discharge_type"]}}}
    cond = {"resourceType": "Condition", "id": f"cond-adm-{aid}", "code": {"text": s.get("final_diagnosis") or a["diagnosis"] or "", **({"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": s.get("icd") or a["icd"]}]} if (s.get("icd") or a["icd"]) else {})}, "subject": {"reference": f"Patient/{pat['id']}"}}
    sections = [{"title": "Encounter", "entry": [{"reference": f"Encounter/{enc['id']}"}]}, {"title": "Final diagnosis", "entry": [{"reference": f"Condition/{cond['id']}"}]}]
    for key, title in (("history", "History"), ("course", "Course in hospital"), ("procedures", "Procedures"), ("investigations", "Investigations"), ("condition", "Condition at discharge"), ("medications", "Medications at discharge"), ("advice", "Advice"), ("followup", "Follow-up")):
        if s.get(key):
            sections.append({"title": title, "text": {"status": "generated", "div": '<div xmlns="http://www.w3.org/1999/xhtml">' + s[key] + "</div>"}})
    return _bundle("DischargeSummaryRecord", "Discharge summary", pat, org, pr, sections, [enc, cond], a["discharged_at"].replace(" ", "T") + ":00+05:30")


@route("GET", r"/api/fhir/(rx|lab|discharge)/(\d+)", "patients_read")
def api_fhir(h, c, b, q, kind, rid):
    """FHIR R4 document bundle (ABDM/NRCeS style) for a prescription, verified lab report or discharge summary: what a
    Health Information Provider pushes to the patient's ABHA account. Download or push through the ABDM gateway."""
    fn = {"rx": fhir_prescription, "lab": fhir_lab, "discharge": fhir_discharge}[kind]
    bundle = fn(c, int(rid))
    if qget(q, "download"):
        h.download = (f"fhir-{kind}-{rid}.json", json.dumps(bundle, indent=1), "application/fhir+json")
        return None
    return bundle


@route("GET", "/api/abdm/status", "admin")
def api_abdm_status(h, c, b, q):
    s = get_settings(c)
    return {"env": s.get("abdm_env") or "sandbox", "configured": bool(s.get("abdm_client_id") and s.get("abdm_client_secret")), "hip_id": s.get("abdm_hip_id") or "",
            "facilities_with_hfr": c.execute("SELECT COUNT(*) FROM branches WHERE hfr_id IS NOT NULL AND hfr_id<>''").fetchone()[0],
            "doctors_with_hpr": c.execute("SELECT COUNT(*) FROM users WHERE role='doctor' AND active=1 AND hpr_id IS NOT NULL AND hpr_id<>''").fetchone()[0],
            "patients_with_abha": c.execute("SELECT COUNT(*) FROM patients WHERE abha IS NOT NULL AND abha<>'' AND erased_at IS NULL").fetchone()[0],
            "milestones": {"M1": "ABHA capture at registration: ready (number and address stored, QR-ready). Verification with OTP needs sandbox credentials.",
                           "M2": "HIP: FHIR bundles for prescriptions, lab reports and discharge summaries are generated (/api/fhir). Gateway push and consent callbacks need sandbox credentials.",
                           "M3": "HIU: not built yet."}}
