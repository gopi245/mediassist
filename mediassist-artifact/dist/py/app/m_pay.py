"""Collecting money through the patient's phone: a UPI link and QR on every bill and invoice (works with any UPI
app, no account needed beyond the branch's UPI ID), optional Razorpay payment links with a webhook that marks the
invoice paid, and a WhatsApp payment request for dues."""
import hashlib
import hmac
import json
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .core import ApiError, P, R, audit, clean, get_settings, in_tx, need, need_branch, now_str, one, pcode, qget, route, rows, rs


def upi_link(vpa, payee, amount_p, note, ref):
    """upi://pay deep link: opens any UPI app with the amount filled in. Also the text to put in a QR code."""
    if not vpa:
        return None
    q = {"pa": vpa, "pn": payee[:50], "am": f"{amount_p / 100:.2f}", "cu": "INR", "tn": note[:50]}
    if ref:
        q["tr"] = ref[:35]
    return "upi://pay?" + urlencode(q, quote_via=quote)


def razorpay_link(s, amount_p, desc, ref, name, phone, callback):
    """Create a Razorpay payment link. Needs razorpay_key_id and razorpay_key_secret in Settings."""
    kid, sec = s.get("razorpay_key_id"), s.get("razorpay_key_secret")
    need(kid and sec, "Razorpay is not set up (Admin > Settings > Payments). The UPI QR still works.")
    body = {"amount": amount_p, "currency": "INR", "description": desc[:120], "reference_id": ref[:40], "accept_partial": False,
            "customer": {"name": name[:60], "contact": "+91" + phone[-10:] if phone else None}, "notify": {"sms": False, "email": False}, "reminder_enable": False,
            "notes": {"ref": ref}}
    if callback:
        body["callback_url"], body["callback_method"] = callback, "get"
    req = Request("https://api.razorpay.com/v1/payment_links", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    import base64
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{kid}:{sec}".encode()).decode())
    try:
        with urlopen(req, timeout=30) as r:
            out = json.load(r)
            return out["short_url"], out["id"]
    except HTTPError as e:
        raise ApiError(502, "Razorpay: " + (json.loads(e.read() or b"{}").get("error", {}).get("description") or str(e)))
    except URLError as e:
        raise ApiError(502, f"No connection to Razorpay ({e.reason})")


def pay_options(c, kind, row, br):
    """What the patient can pay with for one bill or invoice: UPI link/QR text and the stored Razorpay link."""
    due = row["due_p"] if "due_p" in row.keys() else max(0, row["total_p"] - row.get("returned_p", 0))
    ref = row["inv_no"] if kind == "invoice" else row["bill_no"]
    link = upi_link(br["upi_id"], br["name"], due, f"{ref}", ref.replace("/", "-"))
    return {"due": R(due), "upi_id": br["upi_id"], "upi_link": link, "pay_link": row["pay_link"] if "pay_link" in row.keys() else None,
            "razorpay": bool(get_settings(c).get("razorpay_key_id"))}


def _invoice(c, h, iid):
    from .m_billing import inv_state
    inv = one(c, "SELECT * FROM invoices WHERE id=? AND branch_id=?", (int(iid), h.branch))
    need(inv and not inv["cancelled_at"], "Invoice not found", 404)
    st = inv_state(c, inv)
    return dict(inv, due_p=st["patient_due_p"]), st


@route("GET", r"/api/invoices/(\d+)/pay-options", "hbilling")
def api_inv_pay_options(h, c, b, q, iid):
    inv, _ = _invoice(c, h, iid)
    br = one(c, "SELECT * FROM branches WHERE id=?", (h.branch,))
    return pay_options(c, "invoice", inv, br)


@route("GET", r"/api/bills/(\d+)/pay-options", "billing")
def api_bill_pay_options(h, c, b, q, bid):
    bl = one(c, "SELECT * FROM bills WHERE id=? AND branch_id=?", (int(bid), h.branch))
    need(bl, "Bill not found", 404)
    br = one(c, "SELECT * FROM branches WHERE id=?", (h.branch,))
    row = dict(bl, due_p=(bl["total_p"] - bl["returned_p"]) if bl["pay_mode"] == "credit" and not bl["settled_at"] else 0)
    return pay_options(c, "bill", row, br)


@route("POST", r"/api/invoices/(\d+)/paylink", "hbilling")
def api_inv_paylink(h, c, b, q, iid):
    """Create (or reuse) a Razorpay link for the patient's due and, if asked, send it with the UPI link on WhatsApp."""
    inv, st = _invoice(c, h, iid)
    need(inv["due_p"] > 0, "Nothing is due on this invoice")
    s = get_settings(c)
    br = one(c, "SELECT * FROM branches WHERE id=?", (h.branch,))
    p = one(c, "SELECT * FROM patients WHERE id=?", (inv["patient_id"],))
    link = inv["pay_link"]
    if not link and s.get("razorpay_key_id"):
        cb = (s.get("public_url") or "").rstrip("/")
        link, lid = razorpay_link(s, inv["due_p"], f"{br['name']} invoice {inv['inv_no']}", inv["inv_no"], p["name"], p["phone"], f"{cb}/my" if cb else None)
        c.execute("UPDATE invoices SET pay_link=?, pay_link_id=? WHERE id=?", (link, lid, inv["id"]))
        audit(c, h, "invoice.paylink", f"{inv['inv_no']} {rs(inv['due_p'])} {lid}")
    upi = upi_link(br["upi_id"], br["name"], inv["due_p"], inv["inv_no"], inv["inv_no"].replace("/", "-"))
    sent = None
    if b.get("send"):
        need(link or upi, "Set the branch UPI ID (Admin > Branches) or Razorpay keys first")
        from .notify import send_patient
        text = (f"{br['name']}: {rs(inv['due_p'])} is due on invoice {inv['inv_no']}." +
                (f"\nPay online: {link}" if link else "") + (f"\nOr pay by UPI to {br['upi_id']} ({br['name']}). UPI link: {upi}" if upi else "") +
                "\nReply with the UPI reference once paid.")
        sent = send_patient(c, inv["patient_id"], "payment_request", text)
        audit(c, h, "invoice.payrequest", f"{inv['inv_no']} {rs(inv['due_p'])}")
    return {"pay_link": link, "upi_link": upi, "due": R(inv["due_p"]), "sent": sent}


@route("POST", "/api/public/razorpay", None)
def api_razorpay_webhook(h, c, b, q):
    """Razorpay calls this when a payment link is paid. The signature header is checked with the webhook secret;
    the matching invoice gets a UPI/online payment for the amount, once."""
    s = get_settings(c)
    secret = s.get("razorpay_webhook_secret")
    need(secret, "Webhook secret not set", 403)
    raw = getattr(h, "raw_body", None) or json.dumps(b).encode()
    sig = h.headers.get("X-Razorpay-Signature", "")
    need(hmac.compare_digest(hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), sig), "Bad signature", 403)
    event = b.get("event", "")
    if event != "payment_link.paid":
        return {"ok": True, "ignored": event}
    pl = ((b.get("payload") or {}).get("payment_link") or {}).get("entity") or {}
    pay = ((b.get("payload") or {}).get("payment") or {}).get("entity") or {}
    inv = one(c, "SELECT * FROM invoices WHERE pay_link_id=?", (pl.get("id"),))
    need(inv, "Unknown payment link", 404)
    pid = pay.get("id") or pl.get("id")

    def run():
        if one(c, "SELECT 1 FROM payments WHERE invoice_id=? AND ref=?", (inv["id"], pid)):
            return "duplicate"
        amt = int(pay.get("amount") or pl.get("amount_paid") or 0)
        need(amt > 0, "No amount")
        c.execute("INSERT INTO payments(branch_id,invoice_id,at,mode,amount_p,ref,user_id,kind) VALUES(?,?,?,?,?,?,?,?)",
                  (inv["branch_id"], inv["id"], now_str(), "upi" if (pay.get("method") or "upi") == "upi" else "card", amt, pid, None, "payment"))
        c.execute("INSERT INTO audit(at,user_id,branch_id,action,detail) VALUES(?,?,?,?,?)", (now_str(), None, inv["branch_id"], "invoice.payment", f"{inv['inv_no']} {rs(amt)} online {pid}"))
        return "recorded"
    return {"ok": True, "result": in_tx(c, run)}


# ---------------------------------------------------------------- getting started checklist
@route("GET", "/api/setup/checklist", "admin")
def api_checklist(h, c, b, q):
    """What is still to be set up, with where to do it. Shown on the owner's dashboard until everything is done."""
    s = get_settings(c)
    n = lambda sql, *a: c.execute(sql, a).fetchone()[0]  # noqa: E731
    items = [
        ("branches", "Add your branches", n("SELECT COUNT(*) FROM branches WHERE active=1") > 0, "admin", "branches"),
        ("staff", "Add doctors and staff with their own logins", n("SELECT COUNT(*) FROM users WHERE active=1 AND role<>'owner'") > 0, "admin", "staff"),
        ("doctor_reg", "Every doctor has a registration number (printed on prescriptions)", n("SELECT COUNT(*) FROM users WHERE role='doctor' AND active=1 AND (reg_no IS NULL OR reg_no='')") == 0, "admin", "staff"),
        ("services", "Set your service rates", n("SELECT COUNT(*) FROM services WHERE active=1") > 0, "hbilling", "rates"),
        ("beds", "Add wards and beds", n("SELECT COUNT(*) FROM beds") > 0 or n("SELECT COUNT(*) FROM branches WHERE kind LIKE '%hospital%' AND active=1") == 0, "ipd", ""),
        ("stock", "Load opening stock with racks", n("SELECT COUNT(*) FROM batches WHERE qty>0") > 0 or n("SELECT COUNT(*) FROM branches WHERE kind LIKE '%pharmacy%' AND active=1") == 0, "admin", "import"),
        ("gstin", "GSTIN on every pharmacy branch", n("SELECT COUNT(*) FROM branches WHERE active=1 AND kind LIKE '%pharmacy%' AND (gstin IS NULL OR gstin='')") == 0, "admin", "branches"),
        ("upi", "UPI ID on each branch, so bills carry a pay-by-UPI QR", n("SELECT COUNT(*) FROM branches WHERE active=1 AND (upi_id IS NULL OR upi_id='')") == 0, "admin", "branches"),
        ("public_url", "Public HTTPS address (patient links, PDFs on WhatsApp, online booking)", bool(s.get("public_url")), "admin", "settings"),
        ("whatsapp", "WhatsApp gateway (Meta Cloud API or Twilio)", bool(s.get("meta_token") and s.get("meta_phone_id")) or bool(s.get("twilio_sid") and s.get("twilio_token")), "admin", "settings"),
        ("email", "Email for reports (SMTP)", bool(s.get("smtp_user") and s.get("smtp_pass")), "admin", "settings"),
        ("ai", "AI key for the assistant, lab explanations and voice casesheet (optional)", bool(s.get("anthropic_api_key")), "admin", "settings"),
        ("2fa", "Two-step sign-in on the owner account", n("SELECT COUNT(*) FROM users WHERE role='owner' AND totp_secret IS NOT NULL") > 0, "me", ""),
        ("backup", "A backup has run", bool(s.get("last_backup")), "admin", "backups"),
        ("growth", "WHO growth tables loaded (for children's charts, optional)", n("SELECT COUNT(*) FROM growth_ref") > 0, "admin", "import"),
    ]
    out = [{"key": k, "title": t, "done": bool(d), "view": v, "param": p, "optional": k in ("ai", "growth", "email")} for k, t, d, v, p in items]
    return {"items": out, "done": sum(1 for x in out if x["done"]), "total": len(out), "required_left": sum(1 for x in out if not x["done"] and not x["optional"])}
