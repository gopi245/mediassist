"""Outbound messages: WhatsApp (Twilio) and email (SMTP). Every message is logged in
`messages`; when a channel is not configured the message stays logged with a wa.me link
so staff can send it by hand."""
import base64
import json
import re
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .core import get_settings, now_str, one, route, rows, qget, need


def send_email(s, to, subject, body, attachments=()):
    import smtplib
    import ssl
    if not all(s.get(k) for k in ("smtp_host", "smtp_user", "smtp_pass")):
        raise RuntimeError("Email is not set up (Admin > Settings)")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, s.get("smtp_from") or s["smtp_user"], to
    msg.set_content(body)
    for name, text, mime in attachments:
        main, sub = (mime or "text/csv").split("/", 1)
        msg.add_attachment(text.encode("utf-8") if isinstance(text, str) else text, maintype=main, subtype=sub, filename=name)
    port, ctx = int(s.get("smtp_port") or 587), ssl.create_default_context()
    server = smtplib.SMTP_SSL(s["smtp_host"], port, context=ctx, timeout=30) if port == 465 else smtplib.SMTP(s["smtp_host"], port, timeout=30)
    with server:
        if port != 465:
            server.starttls(context=ctx)
        server.login(s["smtp_user"], s["smtp_pass"])
        server.send_message(msg)
    return "emailed " + to


def wa_number(n):
    d = re.sub(r"\D", "", n or "")
    if len(d) == 10:
        d = "91" + d  # default to India
    return d


def send_whatsapp(s, to, body, media_url=None):
    if not all(s.get(k) for k in ("twilio_sid", "twilio_token", "twilio_from")):
        raise RuntimeError("WhatsApp is not set up (Admin > Settings)")
    if len(body) > 1500:
        body = body[:1450] + "\n...(continued in the full report)"
    req = Request(f"https://api.twilio.com/2010-04-01/Accounts/{s['twilio_sid']}/Messages.json",
                  data=urlencode({"From": "whatsapp:+" + wa_number(s["twilio_from"]), "To": "whatsapp:+" + wa_number(to), "Body": body,
                                  **({"MediaUrl": media_url} if media_url else {})}).encode())
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{s['twilio_sid']}:{s['twilio_token']}".encode()).decode())
    try:
        with urlopen(req, timeout=30) as r:
            return "WhatsApp id " + json.load(r).get("sid", "?")
    except HTTPError as e:
        raise RuntimeError("Twilio: " + json.loads(e.read() or b"{}").get("message", str(e)))
    except URLError as e:
        raise RuntimeError(f"No internet connection ({e.reason})")


def log_message(c, kind, to, channel, body, ok, detail, patient_id=None):
    c.execute("INSERT INTO messages(at,kind,to_addr,channel,body,ok,detail,patient_id) VALUES(?,?,?,?,?,?,?,?)",
              (now_str(), kind, to, channel, body[:4000], 1 if ok else 0, detail[:500], patient_id))


def deliver(c, kind, body, email=None, whatsapp=None, subject=None, attachments=(), patient_id=None, media_url=None):
    s, results = get_settings(c), []
    for ch, to in (("whatsapp", whatsapp), ("email", email)):
        if not to:
            continue
        try:
            detail = send_whatsapp(s, to, body, media_url) if ch == "whatsapp" else send_email(s, to, subject or body.splitlines()[0], body, attachments)
            ok = True
        except Exception as e:
            ok, detail = False, str(e)
        log_message(c, kind, to, ch, body, ok, detail, patient_id)
        results.append({"channel": ch, "to": to, "ok": ok, "detail": detail,
                        "wa_link": f"https://wa.me/{wa_number(to)}?text={quote(body)}" if ch == "whatsapp" and not ok else None})
    return results


def send_patient(c, pid, kind, body, media_url=None):
    p = one(c, "SELECT phone, whatsapp_ok, erased_at FROM patients WHERE id=?", (pid,))
    if not p or p["erased_at"] or not p["whatsapp_ok"]:
        return []
    return deliver(c, kind, body, whatsapp=p["phone"], patient_id=pid, media_url=media_url)


def notify_staff(c, user_id, body):
    u = one(c, "SELECT * FROM users WHERE id=?", (user_id,)) if user_id else None
    if not u or not (u["whatsapp"] or u["email"]):
        log_message(c, "staff_alert", u["name"] if u else "-", "screen", body, True, "shown in the app only")
        return []
    return deliver(c, "staff_alert", body, email=u["email"], whatsapp=u["whatsapp"], subject="MediAssist alert")


@route("GET", "/api/messages", "reports")
def api_messages(h, c, b, q):
    kind = qget(q, "kind")
    sql, args = "SELECT * FROM messages", []
    if kind:
        sql += " WHERE kind=?"
        args.append(kind)
    out = rows(c.execute(sql + " ORDER BY id DESC LIMIT 200", args))
    for m in out:
        if not m["ok"] and m["channel"] == "whatsapp":
            m["wa_link"] = f"https://wa.me/{wa_number(m['to_addr'])}?text={quote(m['body'])}"
    return out


@route("GET", "/api/alerts", "any")
def api_alerts(h, c, b, q):
    """Staff alerts addressed to the signed-in user (e.g. critical lab values)."""
    return rows(c.execute("SELECT * FROM messages WHERE kind='staff_alert' AND (to_addr=? OR to_addr=? OR to_addr=?) ORDER BY id DESC LIMIT 20",
                          (h.user["name"], h.user["whatsapp"] or "-", h.user["email"] or "-")))
