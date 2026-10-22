"""Patient records portal. Each patient gets a private link (sent to their registered WhatsApp number) where they
see their own prescriptions, lab reports, bills, discharge papers and the documents staff shared with them. A new
record sends a WhatsApp message with the link the moment it is ready.

The link is the key: 144 random bits, only ever sent to the patient's own number, renewed with every new record,
expiring after `portal_days` without one, and revocable by staff. Every opening is counted and rate-limited."""
import json
import os
import secrets

from .core import (UPLOAD_DIR, R, add_days, audit, get_settings, need, now_str, one, pcode, qget, route, rows, today)

KIND_LABEL = {"rx": "Prescription", "lab": "Lab report", "bill": "Pharmacy bill", "invoice": "Hospital bill", "discharge": "Discharge summary", "doc": "Document", "referral": "Referral letter"}


def _days(c):
    try:
        return max(7, min(3650, int(get_settings(c).get("portal_days") or 180)))
    except ValueError:
        return 180


def link_for(c, pid, user_id=None, fresh=False):
    """The patient's current link, extended; a new one if there is none, or if `fresh` (the old one stops working)."""
    if fresh:
        c.execute("UPDATE portal_links SET revoked_at=? WHERE patient_id=? AND revoked_at IS NULL", (now_str(), pid))
    else:
        r = one(c, "SELECT token FROM portal_links WHERE patient_id=? AND revoked_at IS NULL AND expires>=? ORDER BY created_at DESC LIMIT 1", (pid, today()))
        if r:
            c.execute("UPDATE portal_links SET expires=? WHERE token=?", (add_days(today(), _days(c)), r["token"]))
            return r["token"]
    tok = secrets.token_urlsafe(18)
    c.execute("INSERT INTO portal_links(token,patient_id,created_at,created_by,expires) VALUES(?,?,?,?,?)", (tok, pid, now_str(), user_id, add_days(today(), _days(c))))
    return tok


def portal_url(c, tok):
    base = (get_settings(c).get("public_url") or "").rstrip("/")
    return f"{base}/my?t={tok}"


def pdf_url(c, tok, kind, rid):
    """Public address of a record's PDF for this patient, or None when the server has no public HTTPS address (Twilio must fetch it)."""
    base = (get_settings(c).get("public_url") or "").rstrip("/")
    return f"{base}/api/portal/pdf/{kind}/{rid}?t={tok}" if base.startswith("https://") else None


def share(c, pid, what, user_id=None, pdf=None):
    """Tell the patient a new record is ready, with their link (and the record's PDF attached when possible).
    Returns the delivery results (or None when switched off)."""
    if not pid or get_settings(c).get("portal_auto", "1") != "1":
        return None
    p = one(c, "SELECT erased_at, whatsapp_ok FROM patients WHERE id=?", (pid,))
    if not p or p["erased_at"] or not p["whatsapp_ok"]:
        return None
    from .notify import send_patient
    tok = link_for(c, pid, user_id)
    return send_patient(c, pid, "portal", f"{what}\nOpen your bills, reports and documents: {portal_url(c, tok)}",
                        media_url=pdf_url(c, tok, *pdf) if pdf else None)


def link_line(c, pid, user_id=None):
    """A line to add to a message the module already sends (lab reports), so the patient also gets the link."""
    if not pid or get_settings(c).get("portal_auto", "1") != "1":
        return ""
    return f"\nAll your reports and bills: {portal_url(c, link_for(c, pid, user_id))}"


# ---------------------------------------------------------------- staff side
def _status(c, pid):
    r = one(c, "SELECT * FROM portal_links WHERE patient_id=? AND revoked_at IS NULL AND expires>=? ORDER BY created_at DESC LIMIT 1", (pid, today()))
    sent = rows(c.execute("SELECT at, kind, ok, body FROM messages WHERE patient_id=? AND kind IN ('portal','lab_report') ORDER BY id DESC LIMIT 8", (pid,)))
    return {"active": bool(r), "url": portal_url(c, r["token"]) if r else None, "token": r["token"] if r else None,
            "created_at": r["created_at"] if r else None, "expires": r["expires"] if r else None, "last_used": r["last_used"] if r else None,
            "views": r["views"] if r else 0, "auto": get_settings(c).get("portal_auto", "1") == "1", "public_url": bool(get_settings(c).get("public_url")),
            "sent": [dict(m, body=(m["body"] or "").splitlines()[0][:120]) for m in sent]}


@route("GET", r"/api/patients/(\d+)/portal", "patients_read")
def api_portal_status(h, c, b, q, pid):
    need(one(c, "SELECT 1 FROM patients WHERE id=? AND erased_at IS NULL", (int(pid),)), "Patient not found", 404)
    return _status(c, int(pid))


@route("POST", r"/api/patients/(\d+)/portal", "patients_read")
def api_portal_send(h, c, b, q, pid):
    p = one(c, "SELECT p.*, br.name bname FROM patients p LEFT JOIN branches br ON br.id=p.branch_id WHERE p.id=? AND p.erased_at IS NULL", (int(pid),))
    need(p, "Patient not found", 404)
    tok = link_for(c, p["id"], h.user["id"], fresh=bool(b.get("fresh")))
    audit(c, h, "portal.link", f"{pcode(p['id'])}{' new link' if b.get('fresh') else ''}{' sent' if b.get('send') else ''}")
    sent = None
    if b.get("send"):
        from .notify import send_patient
        org = get_settings(c).get("org_name") or p["bname"] or "Your hospital"
        sent = send_patient(c, p["id"], "portal", f"{org}: your bills, lab reports and documents are here. Keep this link private.\n{portal_url(c, tok)}")
    return dict(_status(c, p["id"]), sent_now=sent)


@route("POST", r"/api/patients/(\d+)/portal/revoke", "patients_read")
def api_portal_revoke(h, c, b, q, pid):
    c.execute("UPDATE portal_links SET revoked_at=? WHERE patient_id=? AND revoked_at IS NULL", (now_str(), int(pid)))
    audit(c, h, "portal.revoke", pcode(int(pid)))
    return _status(c, int(pid))


# ---------------------------------------------------------------- patient side (no sign-in: the link is the key)
def _link(c, h, q):
    from .m_appointments import rate_limit
    rate_limit("portal:" + h.client_ip, n=120, window=3600)
    tok = qget(q, "t").strip()
    r = one(c, "SELECT * FROM portal_links WHERE token=?", (tok,)) if 16 <= len(tok) <= 64 else None
    need(r and not r["revoked_at"] and r["expires"] >= today(),
         "This link has expired or was switched off. Ask the hospital reception to send you a new one.", 404)
    return r


def records(c, pid):
    out = []
    for v in rows(c.execute("SELECT v.*, u.name dname, u.reg_no dreg, br.name bname FROM visits v LEFT JOIN users u ON u.id=v.doctor_id JOIN branches br ON br.id=v.branch_id "
                            "WHERE v.patient_id=? AND v.status='done' AND v.complaint IS NOT 'Discharge' ORDER BY v.completed_at DESC LIMIT 100", (pid,))):
        rx = rows(c.execute("SELECT m.name, r.dose, r.freq, r.days, r.qty, r.instructions FROM rx_items r JOIN medicines m ON m.id=r.medicine_id WHERE r.visit_id=?", (v["id"],)))
        out.append({"kind": "rx", "id": f"V{v['id']}", "pdf": f"rx/{v['id']}", "at": v["completed_at"] or v["created_at"], "branch": v["bname"], "title": v["diagnosis"] or "Consultation",
                    "doctor": v["dname"], "doctor_reg": v["dreg"], "followup": v["followup"], "items": rx,
                    "vitals": {k: v[k] for k in ("bp_sys", "bp_dia", "pulse", "temp", "spo2", "weight", "sugar") if v[k] is not None}})
    from .m_lab import order_detail
    for o in rows(c.execute("SELECT id FROM lab_orders WHERE patient_id=? AND status='verified' ORDER BY verified_at DESC LIMIT 100", (pid,))):
        d = order_detail(c, o["id"])
        out.append({"kind": "lab", "id": f"LAB{d['id']}", "pdf": f"lab/{d['id']}", "at": d["verified_at"], "branch": d["bname"], "title": ", ".join(t["name"] for t in d["tests"]),
                    "doctor": d["dname"], "verified_by": d["verified_name"], "abnormal": d["abnormal"], "critical": d["critical"],
                    "tests": [{"name": t["name"], "params": [{"name": p["name"], "value": p["value"], "unit": p["unit"], "flag": p["flag"], "range": p["range"]}
                                                           for p in t["params"] if p["value"] not in (None, "")]} for t in d["tests"]]})
    for bl in rows(c.execute("SELECT b.*, br.name bname FROM bills b JOIN branches br ON br.id=b.branch_id WHERE b.patient_id=? ORDER BY b.created_at DESC LIMIT 200", (pid,))):
        items = rows(c.execute("SELECT m.name, bi.qty, bi.returned, bi.net_p, bt.batch, bt.expiry FROM bill_items bi JOIN medicines m ON m.id=bi.medicine_id "
                               "JOIN batches bt ON bt.id=bi.batch_id WHERE bi.bill_id=?", (bl["id"],)))
        out.append({"kind": "bill", "id": bl["bill_no"], "pdf": f"bill/{bl['id']}", "at": bl["created_at"], "branch": bl["bname"], "title": f"Pharmacy bill {bl['bill_no']}",
                    "total": R(bl["total_p"]), "returned": R(bl["returned_p"]), "pay_mode": bl["pay_mode"],
                    "items": [{"name": i["name"], "qty": i["qty"] - (i["returned"] or 0), "amount": R(i["net_p"]), "batch": i["batch"], "expiry": i["expiry"]} for i in items]})
    from .m_billing import inv_state
    for inv in rows(c.execute("SELECT i.*, br.name bname FROM invoices i JOIN branches br ON br.id=i.branch_id WHERE i.patient_id=? ORDER BY i.created_at DESC LIMIT 200", (pid,))):
        st = inv_state(c, inv)
        out.append({"kind": "invoice", "id": inv["inv_no"], "pdf": f"invoice/{inv['id']}", "at": inv["created_at"], "branch": inv["bname"],
                    "title": {"ipd": "Inpatient bill", "lab": "Lab bill"}.get(inv["kind"], "OPD bill") + f" {inv['inv_no']}",
                    "total": R(inv["total_p"]), "status": st["status"], "paid": R(st["paid_p"]), "due": R(st["patient_due_p"]), "insurance": R(st["insurance_p"]), "cancelled": bool(inv["cancelled_at"]),
                    "items": [{"name": i["name"], "qty": i["qty"], "amount": R(i["amount_p"])} for i in rows(c.execute("SELECT name, qty, amount_p FROM invoice_items WHERE invoice_id=?", (inv["id"],)))]})
    for a in rows(c.execute("SELECT a.*, u.name dname, br.name bname FROM admissions a LEFT JOIN users u ON u.id=a.doctor_id JOIN branches br ON br.id=a.branch_id "
                            "WHERE a.patient_id=? AND a.status='discharged' ORDER BY a.discharged_at DESC", (pid,))):
        try:
            s = json.loads(a["summary"] or "{}")
        except ValueError:
            s = {}
        out.append({"kind": "discharge", "id": a["ip_no"], "at": a["discharged_at"], "branch": a["bname"], "title": f"Discharge summary {a['ip_no']}",
                    "doctor": a["dname"], "admitted_at": a["admitted_at"], "diagnosis": a["diagnosis"],
                    "summary": {k: s.get(k) for k in ("final_diagnosis", "course", "procedures", "condition", "medications", "advice", "followup") if s.get(k)}})
    from .m_docs import DOC_TYPES
    for d in rows(c.execute("SELECT d.*, br.name bname FROM documents d LEFT JOIN branches br ON br.id=d.branch_id WHERE d.patient_id=? AND d.shared_at IS NOT NULL ORDER BY d.shared_at DESC", (pid,))):
        out.append({"kind": "doc", "id": f"D{d['id']}", "doc_id": d["id"], "at": d["shared_at"], "branch": d["bname"], "title": DOC_TYPES.get(d["doc_type"], "Document"),
                    "note": d["note"], "doc_date": d["doc_date"], "mime": d["mime"]})
    out.sort(key=lambda x: x["at"] or "", reverse=True)
    return out


@route("GET", "/api/portal")
def api_portal(h, c, b, q):
    r = _link(c, h, q)
    c.execute("UPDATE portal_links SET last_used=?, views=views+1 WHERE token=?", (now_str(), r["token"]))
    p = one(c, "SELECT * FROM patients WHERE id=? AND erased_at IS NULL", (r["patient_id"],))
    need(p, "This link has expired or was switched off.", 404)
    s = get_settings(c)
    return {"org": s.get("org_name") or "", "patient": {"name": p["name"], "code": pcode(p["id"]), "age": p["age"], "gender": p["gender"], "blood_group": p["blood_group"],
                                                        "allergies": p["allergies"], "abha": p["abha"]},
            "records": records(c, p["id"]), "expires": r["expires"], "labels": KIND_LABEL}


@route("GET", r"/api/portal/pdf/(lab|bill|invoice|rx)/(\d+)")
def api_portal_pdf(h, c, b, q, kind, rid):
    r = _link(c, h, q)
    from .m_pdf import TABLES, make
    row = one(c, f"SELECT patient_id FROM {TABLES[kind]} WHERE id=?", (int(rid),))
    need(row and row["patient_id"] == r["patient_id"], "Document not found", 404)
    if kind == "lab":
        need(one(c, "SELECT 1 FROM lab_orders WHERE id=? AND status='verified'", (int(rid),)), "Report not ready", 404)
    data, name = make(c, kind, int(rid))
    h.download = (name, data, "application/pdf")
    h.inline = True
    return None


@route("GET", r"/api/portal/file/(\d+)")
def api_portal_file(h, c, b, q, did):
    r = _link(c, h, q)
    d = one(c, "SELECT * FROM documents WHERE id=? AND patient_id=? AND shared_at IS NOT NULL", (int(did), r["patient_id"]))
    need(d, "Document not found", 404)
    path = os.path.normpath(os.path.join(UPLOAD_DIR, d["path"]))
    need(path.startswith(os.path.normpath(UPLOAD_DIR)) and os.path.exists(path), "File missing", 404)
    with open(path, "rb") as f:
        h.download = (d["filename"] or f"document-{d['id']}", f.read(), d["mime"])
    h.inline = True
    return None

