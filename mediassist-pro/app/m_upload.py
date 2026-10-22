"""Upload from the phone: the computer shows a QR code, the phone opens a camera page and the photos land in
Documents (and on the computer's screen). The QR link is single-purpose, tied to the staff member and branch
that made it, accepts at most 10 files and stops working after 15 minutes."""
import json
import secrets
import time

from .core import audit, clean, get_settings, need, now_str, one, opt_num, qget, route, rows

TTL = 15 * 60
MAX_FILES = 10
PURPOSES = {"stock": ("stock", "Stock photo or supplier bill"), "doc": ("other", "Hospital document")}


@route("POST", "/api/upload-links", "documents")
def api_make_link(h, c, b, q):
    purpose = clean(b, "purpose", 10) or "doc"
    need(purpose in PURPOSES, "Unknown upload type")
    links = {k: opt_num(b.get(k), int, k) for k in ("patient_id", "medicine_id") if b.get(k)}
    tok = secrets.token_urlsafe(18)
    c.execute("INSERT INTO upload_links(token,branch_id,user_id,created_at,expires,purpose,links) VALUES(?,?,?,?,?,?,?)",
              (tok, h.branch or None, h.user["id"], now_str(), time.time() + TTL, purpose, json.dumps(links)))
    base = (get_settings(c).get("public_url") or "").rstrip("/") or ("http://" + (h.headers.get("Host") or "localhost"))
    host = (h.headers.get("Host") or "").split(":")[0]
    return {"token": tok, "url": f"{base}/up?k={tok}", "expires_in": TTL, "label": PURPOSES[purpose][1],
            "local_only": not get_settings(c).get("public_url") and host in ("localhost", "127.0.0.1", "")}


@route("GET", r"/api/upload-links/([\w-]{16,64})", "documents")
def api_link_status(h, c, b, q, tok):
    r = one(c, "SELECT * FROM upload_links WHERE token=? AND user_id=?", (tok, h.user["id"]))
    need(r, "Upload link not found", 404)
    docs = rows(c.execute("SELECT id, mime, filename, created_at FROM documents WHERE id IN (SELECT doc_id FROM upload_files WHERE token=?) ORDER BY id", (tok,)))
    return {"docs": docs, "expired": r["expires"] < time.time(), "left": max(0, int(r["expires"] - time.time()))}


def _live(c, h, q):
    from .m_appointments import rate_limit
    rate_limit("upload:" + h.client_ip, n=60, window=3600)
    tok = qget(q, "k").strip()
    r = one(c, "SELECT * FROM upload_links WHERE token=?", (tok,)) if 16 <= len(tok) <= 64 else None
    need(r and r["expires"] >= time.time(), "This QR code has expired. Make a new one on the computer.", 404)
    return r


@route("GET", "/api/public/upload")
def api_up_info(h, c, b, q):
    r = _live(c, h, q)
    br = one(c, "SELECT name FROM branches WHERE id=?", (r["branch_id"],)) if r["branch_id"] else None
    n = c.execute("SELECT COUNT(*) FROM upload_files WHERE token=?", (r["token"],)).fetchone()[0]
    return {"label": PURPOSES[r["purpose"]][1], "branch": br["name"] if br else "", "sent": n, "max": MAX_FILES, "left": int(r["expires"] - time.time())}


@route("POST", "/api/public/upload")
def api_up_file(h, c, b, q):
    r = _live(c, h, q)
    need(c.execute("SELECT COUNT(*) FROM upload_files WHERE token=?", (r["token"],)).fetchone()[0] < MAX_FILES,
         f"Only {MAX_FILES} photos per QR code. Make a new one on the computer.")
    u = one(c, "SELECT * FROM users WHERE id=? AND active=1", (r["user_id"],))
    need(u, "This QR code is no longer valid.", 404)
    from .m_docs import api_upload
    links = json.loads(r["links"] or "{}")

    class AsStaff:  # the upload is saved as the staff member who made the QR code, at their branch
        user, branch = u, r["branch_id"]
    body = {**links, "mime": b.get("mime"), "data": b.get("data"), "filename": clean(b, "filename", 120) or "phone-photo",
            "doc_type": PURPOSES[r["purpose"]][0], "note": "Sent from phone"}
    res = api_upload(AsStaff, c, body, {})
    c.execute("INSERT INTO upload_files(token,doc_id,at) VALUES(?,?,?)", (r["token"], res["id"], now_str()))
    audit(c, AsStaff, "doc.phone_upload", f"#{res['id']} via QR")
    return {"ok": True, "sent": c.execute("SELECT COUNT(*) FROM upload_files WHERE token=?", (r["token"],)).fetchone()[0]}
