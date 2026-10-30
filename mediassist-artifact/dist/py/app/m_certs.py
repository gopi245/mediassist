"""Certificates printed on the branch letterhead, pre-filled from the patient's record: medical (rest / leave),
fitness, discharge, birth record and medical certificate of cause of death. Each gets a number and is kept, so it
can be printed again and checked later. The birth and death certificates are the hospital's record for the
registrar; the legal registration is done by the local registrar under the RBD Act."""
import json

from .core import all_access, audit, clean, need, need_branch, now_str, one, pcode, qget, route, rows, valid_day

KINDS = {"medical": "Medical certificate", "fitness": "Fitness certificate", "discharge": "Discharge certificate",
         "birth": "Birth record", "death": "Medical certificate of cause of death"}
# fields each kind keeps (all optional unless listed in REQUIRED)
FIELDS = {"medical": ("diagnosis", "from", "to", "resume", "remarks"),
          "fitness": ("purpose", "findings", "remarks"),
          "discharge": ("diagnosis", "admitted", "discharged", "condition", "remarks"),
          "birth": ("baby_gender", "born_at", "weight_kg", "delivery", "father", "place", "remarks"),
          "death": ("died_at", "cause_immediate", "cause_antecedent", "cause_underlying", "other_conditions", "manner", "remarks")}
REQUIRED = {"medical": ("diagnosis", "from", "to"), "fitness": ("purpose",), "discharge": ("diagnosis",),
            "birth": ("baby_gender", "born_at"), "death": ("died_at", "cause_immediate")}
LABELS = {"diagnosis": "Diagnosis", "from": "Unfit from", "to": "Unfit up to", "resume": "Fit to resume duty from", "remarks": "Remarks",
          "purpose": "Fit for", "findings": "Examination findings", "admitted": "Admitted on", "discharged": "Discharged on", "condition": "Condition at discharge",
          "baby_gender": "Baby's sex", "born_at": "Date and time of birth", "weight_kg": "Birth weight (kg)", "delivery": "Type of delivery",
          "father": "Father's name", "place": "Place of birth", "died_at": "Date and time of death", "cause_immediate": "Immediate cause",
          "cause_antecedent": "Antecedent cause", "cause_underlying": "Underlying cause", "other_conditions": "Other significant conditions", "manner": "Manner of death"}


def suggest(c, pid):
    """Pre-fill: latest diagnosis and the latest admission."""
    v = one(c, "SELECT diagnosis, icd FROM visits WHERE patient_id=? AND diagnosis IS NOT NULL AND diagnosis<>'' ORDER BY id DESC LIMIT 1", (pid,))
    a = one(c, "SELECT id, ip_no, admitted_at, discharged_at, diagnosis, status FROM admissions WHERE patient_id=? ORDER BY id DESC LIMIT 1", (pid,))
    return {"diagnosis": (a and a["diagnosis"]) or (v and v["diagnosis"]) or "", "admission": a}


@route("GET", r"/api/patients/(\d+)/certificates", "patients_read")
def api_certs(h, c, b, q, pid):
    pid = int(pid)
    out = rows(c.execute("SELECT ct.id, ct.cert_no, ct.kind, ct.issued_at, ct.branch_id, u.name dname FROM certificates ct LEFT JOIN users u ON u.id=ct.doctor_id "
                         "WHERE ct.patient_id=? ORDER BY ct.id DESC", (pid,)))
    for x in out:
        x["title"] = KINDS.get(x["kind"], x["kind"])
    return {"rows": out, "kinds": KINDS, "fields": FIELDS, "required": REQUIRED, "labels": LABELS, "suggest": suggest(c, pid)}


@route("POST", "/api/certificates", "certificates")
def api_cert_new(h, c, b, q):
    br = need_branch(h, c, "hospital")
    kind = clean(b, "kind", 12)
    need(kind in KINDS, "Choose a certificate type")
    pid = int(b.get("patient_id") or 0)
    p = one(c, "SELECT * FROM patients WHERE id=?", (pid,))
    need(p and not p["erased_at"], "Patient not found", 404)
    data = {k: clean(b, k, 500) for k in FIELDS[kind]}
    missing = [LABELS[k] for k in REQUIRED[kind] if not data[k]]
    need(not missing, "Fill in: " + ", ".join(missing))
    for k in ("from", "to", "resume", "admitted", "discharged"):
        if data.get(k):
            valid_day(data[k][:10], LABELS[k])
    if kind == "medical":
        need(data["to"] >= data["from"], "'Unfit up to' must be on or after 'Unfit from'")
    if kind == "birth":
        need(p["gender"] == "Female", "A birth record is issued on the mother's record")
    adm = None
    if kind == "discharge":
        adm = one(c, "SELECT * FROM admissions WHERE patient_id=? ORDER BY id DESC LIMIT 1", (pid,))
    doctor_id = int(b.get("doctor_id") or 0) or (h.user["id"] if h.user["role"] == "doctor" else None)
    if doctor_id:
        need(one(c, "SELECT 1 FROM users WHERE id=? AND role IN ('doctor','owner')", (doctor_id,)), "Choose a doctor")
    n = c.execute("SELECT COUNT(*) FROM certificates WHERE branch_id=?", (br["id"],)).fetchone()[0] + 1
    cert_no = f"{br['code']}/C/{n:05d}"
    while one(c, "SELECT 1 FROM certificates WHERE cert_no=?", (cert_no,)):
        n += 1
        cert_no = f"{br['code']}/C/{n:05d}"
    cur = c.execute("INSERT INTO certificates(branch_id,cert_no,kind,patient_id,admission_id,doctor_id,issued_at,data,user_id) VALUES(?,?,?,?,?,?,?,?,?)",
                    (br["id"], cert_no, kind, pid, adm["id"] if adm else None, doctor_id, now_str(), json.dumps(data), h.user["id"]))
    audit(c, h, "certificate.issue", f"{cert_no} {kind} {pcode(pid)}")
    return {"ok": True, "id": cur.lastrowid, "cert_no": cert_no}


def cert_pdf(c, cid):
    from .m_pdf import INK, MUTED, TEAL, Pdf, _age, _br, _dt, letterhead
    ct = one(c, "SELECT ct.*, u.name dname, u.reg_no dreg FROM certificates ct LEFT JOIN users u ON u.id=ct.doctor_id WHERE ct.id=?", (cid,))
    need(ct, "Certificate not found", 404)
    p, br = one(c, "SELECT * FROM patients WHERE id=?", (ct["patient_id"],)), _br(c, ct["branch_id"])
    d = {k: "" for k in LABELS} | json.loads(ct["data"])
    title = KINDS[ct["kind"]]
    pdf = Pdf(f"{title} {ct['cert_no']} - {p['name']}")
    letterhead(pdf, c, br, title.upper(), [f"Certificate no. {ct['cert_no']}", f"Issued {_dt(ct['issued_at'])}"])
    who = [("Name", p["name"]), ("Patient ID", pcode(p["id"])), ("Age / Gender", _age(p)), ("Address", p["address"] or "-")]
    if ct["kind"] == "birth":
        who[0] = ("Mother", p["name"])
    if ct["kind"] == "discharge" and ct["admission_id"]:
        a = one(c, "SELECT ip_no FROM admissions WHERE id=?", (ct["admission_id"],))
        who.append(("IP number", a["ip_no"] if a else "-"))
    pdf.kv_box(who)
    sal = "Mrs." if p["gender"] == "Female" else "Mr." if p["gender"] == "Male" else ""
    name = f"{sal} {p['name']}".strip()
    he, him, needs, is_ = {"Male": ("he", "him", "needs", "is"), "Female": ("she", "her", "needs", "is")}.get(p["gender"], ("they", "them", "need", "are"))
    body = {
        "medical": f"This is to certify that {name}, aged {p['age'] if p['age'] is not None else '-'}, was examined by me and is suffering from "
                   f"{d['diagnosis']}. In my opinion, {he} {needs} rest and {is_} unfit for duty from {_dt(d['from'])} to {_dt(d['to'])}"
                   + (f", and {is_} fit to resume duty from {_dt(d['resume'])}" if d.get("resume") else "") + ".",
        "fitness": f"This is to certify that I have examined {name}, aged {p['age'] if p['age'] is not None else '-'}, and found {him} physically and mentally "
                   f"fit for {d['purpose']}.",
        "discharge": f"This is to certify that {name} was admitted to {br['name']}" + (f" on {_dt(d['admitted'])}" if d.get("admitted") else "")
                     + f" and treated for {d['diagnosis']}." + (f" {he.capitalize()} {'was' if is_ == 'is' else 'were'} discharged on {_dt(d['discharged'])}" if d.get("discharged") else "")
                     + (f" in {d['condition']} condition." if d.get("condition") else "."),
        "birth": f"This is to record that {name} gave birth to a {d['baby_gender'].lower()} child on {_dt(d['born_at'])} at {d.get('place') or br['name']}.",
        "death": f"This is to certify that {name}, aged {p['age'] if p['age'] is not None else '-'}, died on {_dt(d['died_at'])} at {br['name']}.",
    }[ct["kind"]]
    pdf.y -= 6
    pdf.para(body, 11, gap=12)
    skip = {"medical": ("diagnosis", "from", "to", "resume"), "fitness": ("purpose",), "discharge": ("admitted", "discharged", "condition", "diagnosis"),
            "birth": ("baby_gender", "born_at", "place"), "death": ("died_at",)}[ct["kind"]]
    rest = [(LABELS[k], d[k]) for k in FIELDS[ct["kind"]] if d.get(k) and k not in skip]
    if ct["kind"] == "death":
        pdf.text(pdf.M, pdf.y - 11, "Cause of death", 11, True, TEAL)
        pdf.y -= 20
    for k, v in rest:
        pdf.need_space(30)
        pdf.text(pdf.M, pdf.y - 9, k.upper(), 7.5, True, MUTED)
        pdf.y -= 12
        pdf.para(v, 10.5, gap=8)
    if ct["kind"] in ("birth", "death"):
        pdf.y -= 4
        pdf.para("This is the hospital's record for the Registrar of Births and Deaths. The legal certificate is issued by the registrar "
                 "after registration under the Registration of Births and Deaths Act, 1969.", 8.5, color=MUTED)
    pdf.need_space(70)
    pdf.y -= 40
    pdf.line(pdf.W - pdf.M - 200, pdf.y, pdf.W - pdf.M, pdf.y, INK)
    pdf.text(pdf.W - pdf.M, pdf.y - 12, ct["dname"] or "Doctor", 10, True, INK, "right")
    pdf.text(pdf.W - pdf.M, pdf.y - 24, ("Reg. " + ct["dreg"]) if ct["dreg"] else "Signature and seal", 8, False, MUTED, "right")
    pdf.text(pdf.M, pdf.y - 12, "Place: " + (br.get("address") or br["name"]).split(",")[-1].strip(), 9, False, MUTED)
    pdf.text(pdf.M, pdf.y - 24, "Date: " + _dt(ct["issued_at"][:10]), 9, False, MUTED)
    return pdf.bytes(f"{br['name']} - {ct['cert_no']} - check this certificate with the hospital quoting its number"), f"{title.replace(' ', '-')}-{ct['cert_no']}.pdf", ct


@route("GET", "/api/certificates", "certificates")
def api_cert_list(h, c, b, q):
    """Recent certificates at this branch (register)."""
    need(h.branch or all_access(h.user), "Choose a branch")
    sql = ("SELECT ct.id, ct.cert_no, ct.kind, ct.issued_at, ct.patient_id, p.name pname, u.name dname FROM certificates ct JOIN patients p ON p.id=ct.patient_id "
           "LEFT JOIN users u ON u.id=ct.doctor_id")
    args = []
    if h.branch:
        sql += " WHERE ct.branch_id=?"
        args.append(h.branch)
    out = rows(c.execute(sql + " ORDER BY ct.id DESC LIMIT " + str(min(int(qget(q, "limit") or 100), 500)), args))
    for x in out:
        x["title"], x["code"] = KINDS.get(x["kind"], x["kind"]), pcode(x["patient_id"])
    return out
