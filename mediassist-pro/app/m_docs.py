"""Documents: photos and PDFs of bills, invoices, prescriptions, lab and scan reports, IDs and
insurance papers, linked to patient / doctor / branch / bill / invoice / admission / lab order /
claim / stock. Optional AI reader (Claude) extracts fields from a photo."""
import base64
import json
import os
import re
import secrets

from .core import (UPLOAD_DIR, ApiError, all_access, as_int, audit, clean, get_settings, need, now_str, one, opt_num, pcode, qget, route,
                   rows, today, valid_day)

DOC_TYPES = {"bill": "Pharmacy bill", "invoice": "Supplier invoice", "rx": "Prescription", "lab": "Lab report", "scan": "Scan / X-ray",
             "id": "ID / insurance", "stock": "Stock photo", "claim": "Insurance claim paper", "discharge": "Discharge paper", "consent": "Consent form", "other": "Other"}
MIMES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}
MAX_BYTES = 15 * 1024 * 1024
LINKS = ("patient_id", "doctor_id", "bill_id", "invoice_id", "admission_id", "lab_order_id", "claim_id", "medicine_id", "batch_id")


def link_fields(c, b):
    out = {k: opt_num(b.get(k), int, k.replace("_id", "")) for k in LINKS}
    checks = {"patient_id": "patients", "doctor_id": "users", "bill_id": "bills", "invoice_id": "invoices", "admission_id": "admissions",
              "lab_order_id": "lab_orders", "claim_id": "claims", "medicine_id": "medicines", "batch_id": "batches"}
    for k, t in checks.items():
        if out[k]:
            need(one(c, f"SELECT 1 FROM {t} WHERE id=?", (out[k],)), f"Linked {k.replace('_id', '')} not found", 404)
    t = clean(b, "doc_type", 12) or "other"
    need(t in DOC_TYPES, "Unknown document type")
    d = clean(b, "doc_date", 10) or today()
    valid_day(d, "document date")
    return out, t, d


@route("POST", "/api/documents", "documents")
def api_upload(h, c, b, q):
    mime = clean(b, "mime", 40)
    need(mime in MIMES, "Upload a JPG, PNG, WebP photo or a PDF")
    try:
        data = base64.b64decode(str(b.get("data") or ""), validate=True)
    except (ValueError, TypeError):
        raise ApiError(400, "The file could not be read")
    need(0 < len(data) <= MAX_BYTES, "Files must be under 15 MB")
    sig = {"image/jpeg": b"\xff\xd8", "image/png": b"\x89PNG", "application/pdf": b"%PDF", "image/webp": b"RIFF"}[mime]
    need(data.startswith(sig), "The file content doesn't match its type")
    links, dtype, ddate = link_fields(c, b)
    sub = os.path.join(UPLOAD_DIR, today()[:7])
    os.makedirs(sub, exist_ok=True)
    name = secrets.token_hex(12) + MIMES[mime]
    with open(os.path.join(sub, name), "wb") as f:
        f.write(data)
    rel = os.path.join(today()[:7], name)
    cur = c.execute(f"INSERT INTO documents(branch_id,{','.join(LINKS)},doc_type,doc_date,note,filename,mime,size,path,created_at,user_id) "
                    f"VALUES({','.join('?' * (len(LINKS) + 10))})",
                    (h.branch or None, *links.values(), dtype, ddate, clean(b, "note", 300), clean(b, "filename", 120), mime, len(data), rel, now_str(), h.user["id"]))
    audit(c, h, "doc.upload", f"#{cur.lastrowid} {DOC_TYPES[dtype]}" + (f" {pcode(links['patient_id'])}" if links["patient_id"] else ""))
    sent = share_doc(c, h, cur.lastrowid, links["patient_id"], dtype) if b.get("share") else None
    return {"ok": True, "id": cur.lastrowid, "shared": sent is not None, "sent": sent}


def share_doc(c, h, did, pid, dtype):
    """Show the document in the patient's portal and message them. Only documents linked to a patient can be shared."""
    need(pid, "Link the document to a patient before sending it to them")
    c.execute("UPDATE documents SET shared_at=COALESCE(shared_at, ?) WHERE id=?", (now_str(), did))
    audit(c, h, "doc.share", f"#{did} {pcode(pid)}")
    from .m_portal import share
    br = one(c, "SELECT name FROM branches WHERE id=?", (h.branch,)) if h.branch else None
    return share(c, pid, f"{br['name'] + ': y' if br else 'Y'}our {DOC_TYPES[dtype].lower()} has been added to your records.", h.user["id"]) or []


def visible(h, d):
    return all_access(h.user) or d["branch_id"] in (None, h.user["branch_id"])


@route("GET", "/api/documents", "documents")
def api_docs(h, c, b, q):
    sql = ("SELECT d.*, p.name pname, u.name dname, bl.bill_no, i.inv_no, a.ip_no, m.name mname, bt.batch bname, br.code bcode FROM documents d "
           "LEFT JOIN patients p ON p.id=d.patient_id LEFT JOIN users u ON u.id=d.doctor_id LEFT JOIN bills bl ON bl.id=d.bill_id "
           "LEFT JOIN invoices i ON i.id=d.invoice_id LEFT JOIN admissions a ON a.id=d.admission_id LEFT JOIN medicines m ON m.id=d.medicine_id "
           "LEFT JOIN batches bt ON bt.id=d.batch_id LEFT JOIN branches br ON br.id=d.branch_id WHERE 1=1")
    args = []
    if not all_access(h.user):
        sql += " AND (d.branch_id IS NULL OR d.branch_id=?)"
        args.append(h.user["branch_id"])
    for k in LINKS:
        v = qget(q, k)
        if v:
            sql += f" AND d.{k}=?"
            args.append(as_int(v, k))
    t, term = qget(q, "type"), qget(q, "q").strip()
    if t:
        sql += " AND d.doc_type=?"
        args.append(t)
    if term:
        sql += " AND (p.name LIKE ? OR bl.bill_no LIKE ? OR i.inv_no LIKE ? OR m.name LIKE ? OR d.note LIKE ?)"
        args += [f"%{term}%"] * 5
    out = rows(c.execute(sql + " ORDER BY d.id DESC LIMIT 300", args))
    for d in out:
        d["type_label"] = DOC_TYPES.get(d["doc_type"], d["doc_type"])
        d["code"] = pcode(d["patient_id"]) if d["patient_id"] else None
    return {"types": DOC_TYPES, "rows": out}


@route("GET", r"/api/documents/(\d+)/file", "documents")
def api_doc_file(h, c, b, q, did):
    d = one(c, "SELECT * FROM documents WHERE id=?", (int(did),))
    need(d and visible(h, d), "Document not found", 404)
    path = os.path.normpath(os.path.join(UPLOAD_DIR, d["path"]))
    need(path.startswith(os.path.normpath(UPLOAD_DIR)) and os.path.exists(path), "File missing on the server", 404)
    with open(path, "rb") as f:
        h.download = (d["filename"] or f"document-{d['id']}{MIMES.get(d['mime'], '')}", f.read(), d["mime"])
    h.inline = True
    return None


@route("POST", r"/api/documents/(\d+)", "documents")
def api_doc_update(h, c, b, q, did):
    d = one(c, "SELECT * FROM documents WHERE id=?", (int(did),))
    need(d and visible(h, d), "Document not found", 404)
    links, dtype, ddate = link_fields(c, b)
    if d["shared_at"] and links["patient_id"] != d["patient_id"]:  # moved to another patient: stop showing it to the first one
        c.execute("UPDATE documents SET shared_at=NULL WHERE id=?", (d["id"],))
        d["shared_at"] = None
    c.execute(f"UPDATE documents SET {','.join(k + '=?' for k in LINKS)}, doc_type=?, doc_date=?, note=? WHERE id=?",
              (*links.values(), dtype, ddate, clean(b, "note", 300), d["id"]))
    if b.get("share") and not d["shared_at"]:
        share_doc(c, h, d["id"], links["patient_id"], dtype)
    elif b.get("share") is False and d["shared_at"]:
        c.execute("UPDATE documents SET shared_at=NULL WHERE id=?", (d["id"],))
        audit(c, h, "doc.unshare", f"#{d['id']}")
    audit(c, h, "doc.assign", f"#{d['id']} {DOC_TYPES[dtype]} " + " ".join(f"{k}={v}" for k, v in links.items() if v))
    return {"ok": True}


@route("POST", r"/api/documents/(\d+)/delete", "documents")
def api_doc_delete(h, c, b, q, did):
    d = one(c, "SELECT * FROM documents WHERE id=?", (int(did),))
    need(d and visible(h, d), "Document not found", 404)
    need(d["user_id"] == h.user["id"] or h.user["role"] in ("owner", "manager"), "Only the uploader or a manager can delete a document", 403)
    path = os.path.normpath(os.path.join(UPLOAD_DIR, d["path"]))
    if path.startswith(os.path.normpath(UPLOAD_DIR)) and os.path.exists(path):
        os.remove(path)
    c.execute("DELETE FROM documents WHERE id=?", (d["id"],))
    audit(c, h, "doc.delete", f"#{d['id']} {DOC_TYPES.get(d['doc_type'])}")
    return {"ok": True}


# ---------------------------------------------------------------- AI reader (optional)
AI_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": list(DOC_TYPES)},
        "date": {"type": "string", "description": "YYYY-MM-DD, or empty"},
        "patient_name": {"type": "string"}, "doctor_name": {"type": "string"}, "supplier": {"type": "string"},
        "document_no": {"type": "string"}, "total": {"type": "number"}, "summary": {"type": "string"},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "medicine": {"type": "string"}, "batch": {"type": "string"}, "expiry": {"type": "string", "description": "YYYY-MM or YYYY-MM-DD"},
            "qty": {"type": "number"}, "mrp": {"type": "number"}, "cost": {"type": "number"}},
            "required": ["medicine", "batch", "expiry", "qty", "mrp", "cost"], "additionalProperties": False}},
    },
    "required": ["doc_type", "date", "patient_name", "doctor_name", "supplier", "document_no", "total", "summary", "items"],
    "additionalProperties": False,
}


@route("GET", "/api/ai/status", "documents")
def api_ai_status(h, c, b, q):
    try:
        import anthropic  # noqa: F401
        sdk = True
    except ImportError:
        sdk = False
    return {"sdk": sdk, "key": bool(get_settings(c).get("anthropic_api_key")), "ready": sdk and bool(get_settings(c).get("anthropic_api_key"))}


@route("POST", "/api/ai/read-document", "documents")
def api_ai_read(h, c, b, q):
    key = get_settings(c).get("anthropic_api_key")
    need(key, "AI reading is off. Add an Anthropic API key in Admin > Settings.")
    try:
        import anthropic
    except ImportError:
        raise ApiError(400, "AI reading needs the Anthropic SDK on the server: run  pip install anthropic  and restart.")
    mime = clean(b, "mime", 40)
    need(mime in MIMES, "Upload a photo or PDF")
    data = str(b.get("data") or "")
    need(len(data) <= MAX_BYTES * 4 // 3 + 4, "Files must be under 15 MB")
    meds = ", ".join(r[0] for r in c.execute("SELECT name FROM medicines WHERE active=1 ORDER BY name"))
    source = {"type": "base64", "media_type": mime, "data": data}
    block = {"type": "document", "source": source} if mime == "application/pdf" else {"type": "image", "source": source}
    prompt = ("This is a document photographed or scanned at an Indian hospital, clinic or pharmacy. Extract its details.\n"
              "doc_type: bill = pharmacy sale bill to a patient; invoice = distributor or supplier purchase invoice; rx = doctor's prescription; "
              "lab = lab test report; scan = X-ray or scan report; id = ID or insurance card; claim = insurance claim paper; discharge = discharge summary; "
              "stock = photo of medicines on a shelf, rack or in a carton (list each medicine and batch once; qty = how many strips, bottles or boxes you can count).\n"
              "mrp and cost are rupees per unit (one strip, bottle or vial as printed). Use empty strings, 0 or an empty list for anything not visible. Do not guess.\n"
              f"Brands this group stocks (use this spelling when the printed name matches one): {meds}.")
    client = anthropic.Anthropic(api_key=key)
    try:
        resp = client.beta.messages.create(
            model="claude-opus-5-5", max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": AI_SCHEMA}},
            messages=[{"role": "user", "content": [block, {"type": "text", "text": prompt}]}],
        )
    except anthropic.AuthenticationError:
        raise ApiError(400, "The Anthropic API key was rejected. Check it in Admin > Settings.")
    except anthropic.RateLimitError:
        raise ApiError(429, "The AI service is busy. Try again in a minute.")
    except anthropic.BadRequestError as e:
        raise ApiError(400, f"The AI couldn't read this file: {e.message}")
    except anthropic.APIStatusError as e:
        raise ApiError(502, f"AI service error ({e.status_code}). Try again later.")
    except anthropic.APIConnectionError:
        raise ApiError(502, "No connection to the AI service. Check the internet connection.")
    if resp.stop_reason == "refusal":
        raise ApiError(400, "The AI declined to read this document. Fill in the details by hand.")
    need(resp.stop_reason != "max_tokens", "The document is too long for the AI reader. Fill in the details by hand.")
    text = next((blk.text for blk in resp.content if blk.type == "text"), "")
    try:
        out = json.loads(text)
    except ValueError:
        raise ApiError(502, "The AI's answer couldn't be read. Try again.")
    match_all(c, out)
    audit(c, h, "ai.read", f"{out.get('doc_type')} {len(out.get('items', []))} items")
    return out


# ---------------------------------------------------------------- matching (local, no AI)
def _words(s):
    return [w for w in re.split(r"[^a-z0-9]+", (s or "").lower().replace("dr.", "")) if len(w) > 1]


def best_match(c, name, table, col, extra=""):
    w = set(_words(name))
    if not w:
        return None
    top, score = None, 0
    for r in rows(c.execute(f"SELECT id, {col} n FROM {table} WHERE 1=1 {extra} LIMIT 5000")):
        rw = set(_words(r["n"]))
        common = w & rw
        hit = len(common)
        sc = hit / max(1, min(len(w), len(rw)))
        # a shared strength alone ("10") is not a match: at least one word must be a name
        if any(not x.isdigit() for x in common) and sc > score:
            top, score = r, sc
    return top if score >= 0.5 else None


def match_all(c, out):
    """Match what was read to our own records here, so patient names never go to the AI service."""
    p = best_match(c, out.get("patient_name"), "patients", "name", "AND erased_at IS NULL")
    d = best_match(c, out.get("doctor_name"), "users", "name", "AND role IN ('doctor','owner')")
    out["match"] = {"patient": {"id": p["id"], "name": p["n"], "code": pcode(p["id"])} if p else None, "doctor": {"id": d["id"], "name": d["n"]} if d else None,
                    "bill": one(c, "SELECT id, bill_no FROM bills WHERE bill_no=?", (out.get("document_no") or "",)),
                    "invoice": one(c, "SELECT id, inv_no FROM invoices WHERE inv_no=?", (out.get("document_no") or "",))}
    for it in out.get("items", []):
        m = best_match(c, it.get("medicine"), "medicines", "name")
        it["medicine_id"], it["matched"] = (m["id"], m["n"]) if m else (None, None)
    return out


@route("POST", "/api/ai/match", "documents")
def api_ai_match(h, c, b, q):
    """For a reader that runs outside this server (the in-browser demo): match the items it read to our records."""
    out = {k: b.get(k) for k in ("doc_type", "date", "patient_name", "doctor_name", "supplier", "document_no", "total", "summary")}
    out["items"] = [dict(i) for i in (b.get("items") or [])[:300] if isinstance(i, dict)]
    return match_all(c, out)
