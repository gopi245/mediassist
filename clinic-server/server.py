"""MediAssist clinic server.

Shared database for patients, medicine stock/expiry and dispensing, staff logins,
and an automatic end-of-day report to the doctor by email and WhatsApp.

Run:  python server.py        then open http://localhost:8000
Uses only the Python standard library (Python 3.9+).
"""
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import smtplib
import socket
import sqlite3
import ssl
import threading
import time
from contextlib import closing
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("CLINIC_DB", os.path.join(BASE, "clinic.db"))
PORT = int(os.environ.get("PORT", "8000"))
SESSION_HOURS = 12

ROLES = {
    "admin": {"patients_read", "patients_write", "meds", "dispense", "report", "admin"},
    "reception": {"patients_read", "patients_write", "report"},
    "pharmacy": {"patients_read", "meds", "dispense", "report"},
    "doctor": {"patients_read", "report"},
}
SECRET_SETTINGS = {"smtp_pass", "twilio_token"}
DEFAULT_SETTINGS = {
    "clinic_name": "My Clinic",
    "doctor_email": "",
    "doctor_whatsapp": "",
    "report_time": "20:00",
    "auto_send": "1",
    "low_stock_level": "50",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": "587",
    "smtp_user": "",
    "smtp_pass": "",
    "smtp_from": "",
    "twilio_sid": "",
    "twilio_token": "",
    "twilio_from": "",
    "last_auto": "",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT,
  role TEXT NOT NULL, salt TEXT NOT NULL, pw TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS patients(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, age INTEGER, gender TEXT, phone TEXT NOT NULL,
  address TEXT, allergies TEXT, dx TEXT, doctor TEXT, created_at TEXT NOT NULL, created_by INTEGER);
CREATE TABLE IF NOT EXISTS meds(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT, batch TEXT, qty INTEGER NOT NULL,
  expiry TEXT NOT NULL, opened TEXT, price REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sales(
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, patient_id INTEGER NOT NULL REFERENCES patients(id),
  med TEXT NOT NULL, qty INTEGER NOT NULL, price REAL, total REAL, dose TEXT, batches TEXT, user_id INTEGER);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS report_log(
  id INTEGER PRIMARY KEY, sent_at TEXT, day TEXT, channel TEXT, ok INTEGER, detail TEXT);
CREATE INDEX IF NOT EXISTS sales_day ON sales(created_at);
CREATE INDEX IF NOT EXISTS patients_day ON patients(created_at);
"""


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def db():
    c = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    return c


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def make_user(c, username, name, role, password):
    if role not in ROLES:
        raise ApiError(400, "Unknown role")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", username or ""):
        raise ApiError(400, "Username: 3-30 letters, numbers, . _ -")
    if len(password or "") < 8:
        raise ApiError(400, "Password must be at least 8 characters")
    salt = secrets.token_hex(16)
    try:
        c.execute("INSERT INTO users(username,name,role,salt,pw) VALUES(?,?,?,?,?)",
                  (username, name, role, salt, hash_pw(password, salt)))
    except sqlite3.IntegrityError:
        raise ApiError(400, "That username is taken")


def init_db():
    with closing(db()) as c:
        c.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v))
        if not c.execute("SELECT 1 FROM users").fetchone():
            pw = secrets.token_urlsafe(9)
            make_user(c, "admin", "Administrator", "admin", pw)
            path = os.path.join(BASE, "FIRST-LOGIN.txt")
            with open(path, "w") as f:
                f.write(f"Username: admin\nPassword: {pw}\n\n"
                        "Log in, change this password (top right), then delete this file.\n")
            print(f"\n  First run: admin login saved in {path}\n")


def get_settings(c):
    return {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM settings")}


def set_setting(c, key, value):
    c.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (key, str(value)))


# ---------- stock & expiry ----------

def eff_expiry(m):
    e = date.fromisoformat(m["expiry"])
    if m["type"] == "Tonic/Syrup" and m["opened"]:
        e = min(e, date.fromisoformat(m["opened"]) + timedelta(days=30))
    return e


def days_left(m):
    return (eff_expiry(m) - date.today()).days


def med_row(m):
    d = days_left(m)
    status = "EXPIRED" if d < 0 else "30 days" if d <= 30 else "90 days" if d <= 90 else "OK"
    return {**dict(m), "effective_expiry": eff_expiry(m).isoformat(), "days_left": d, "status": status}


def stock_summary(c):
    out = {}
    for m in c.execute("SELECT * FROM meds"):
        s = out.setdefault(m["name"], {"name": m["name"], "type": m["type"], "usable": 0, "price": 0})
        if days_left(m) >= 0:
            s["usable"] += m["qty"]
            if m["qty"] > 0:
                s["price"] = m["price"] or s["price"]
    return sorted(out.values(), key=lambda s: s["name"].lower())


def dispense(c, user, b):
    try:
        pid, qty = int(b.get("patient_id")), int(b.get("qty"))
    except (TypeError, ValueError):
        raise ApiError(400, "Pick a patient and enter a quantity")
    name = (b.get("med") or "").strip()
    if qty <= 0 or not name:
        raise ApiError(400, "Pick a medicine and a quantity above 0")
    c.execute("BEGIN IMMEDIATE")
    try:
        p = c.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        if not p:
            raise ApiError(404, "Patient not found")
        allergies = [a.strip().lower() for a in (p["allergies"] or "").split(",") if a.strip()]
        hit = [a for a in allergies if a in name.lower()]
        if hit and not b.get("override_allergy"):
            raise ApiError(409, f"{p['name']} is allergic to {', '.join(hit)}.")
        batches = [m for m in c.execute("SELECT * FROM meds WHERE name=? AND qty>0", (name,))
                   if days_left(m) >= 0]
        batches.sort(key=eff_expiry)  # first-expiry, first-out
        avail = sum(m["qty"] for m in batches)
        if avail < qty:
            raise ApiError(400, f"Only {avail} usable units of {name} in stock")
        price = float(b.get("price") or batches[0]["price"] or 0)
        left, used = qty, []
        for m in batches:
            if not left:
                break
            take = min(left, m["qty"])
            c.execute("UPDATE meds SET qty=qty-? WHERE id=?", (take, m["id"]))
            used.append(f"{m['batch'] or m['id']}x{take}")
            left -= take
        c.execute("INSERT INTO sales(created_at,patient_id,med,qty,price,total,dose,batches,user_id)"
                  " VALUES(?,?,?,?,?,?,?,?,?)",
                  (now_str(), pid, name, qty, price, round(qty * price, 2),
                   (b.get("dose") or "").strip(), " ".join(used), user["id"]))
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    return {"ok": True, "total": round(qty * price, 2), "batches": used, "patient": p["name"]}


# ---------- daily report ----------

def pcode(pid):
    return f"P{pid:04d}"


def day_sales(c, day):
    return c.execute("SELECT s.*, p.name patient, p.phone FROM sales s JOIN patients p ON p.id=s.patient_id"
                     " WHERE s.created_at LIKE ? ORDER BY s.created_at", (day + "%",)).fetchall()


def build_report(c, day):
    s = get_settings(c)
    pts = c.execute("SELECT * FROM patients WHERE created_at LIKE ? ORDER BY id", (day + "%",)).fetchall()
    sales = day_sales(c, day)
    by_med = {}
    for r in sales:
        by_med[r["med"]] = by_med.get(r["med"], 0) + r["qty"]
    revenue = sum(r["total"] or 0 for r in sales)
    buyers = len({r["patient_id"] for r in sales})
    low_level = int(s.get("low_stock_level") or 50)
    low = [x for x in stock_summary(c) if x["usable"] < low_level]
    expiring = [med_row(m) for m in c.execute("SELECT * FROM meds WHERE qty>0") if days_left(m) <= 30]

    L = [f"{s['clinic_name']} - DAILY REPORT {day}", "",
         f"New patients: {len(pts)}",
         f"Patients who bought medicine: {buyers}",
         f"Medicine sales: {len(sales)}  |  Total: Rs {revenue:.2f}", "", "NEW PATIENTS"]
    L += [f"- {pcode(p['id'])} {p['name']}, {p['age'] or '?'}{(p['gender'] or ' ')[0]}, {p['phone']}"
          f" - {p['dx'] or '-'}" + (f" (allergy: {p['allergies']})" if p["allergies"] else "")
          for p in pts] or ["- none"]
    L += ["", "MEDICINES GIVEN"]
    L += [f"- {r['created_at'][11:]} {r['patient']}: {r['med']} x {r['qty']}"
          + (f" ({r['dose']})" if r["dose"] else "") + f" Rs {r['total'] or 0:.2f}" for r in sales] or ["- none"]
    L += ["", "TOTAL PER MEDICINE"]
    L += [f"- {m}: {q}" for m, q in sorted(by_med.items())] or ["- none"]
    if low:
        L += ["", "LOW STOCK: " + ", ".join(f"{x['name']} ({x['usable']})" for x in low)]
    if expiring:
        L += ["", "EXPIRY WARNINGS: " + ", ".join(
            f"{m['name']} {m['batch']} ({'expired' if m['days_left'] < 0 else str(m['days_left']) + 'd'})"
            for m in expiring)]
    return {"text": "\n".join(L), "patients": len(pts), "buyers": buyers, "sales": len(sales),
            "revenue": round(revenue, 2), "low": low, "expiring": expiring}


def sales_csv(c, day):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date time", "Patient ID", "Patient", "Phone", "Medicine", "Qty", "Price", "Total", "Dosage", "Batches"])
    for r in day_sales(c, day):
        w.writerow([r["created_at"], pcode(r["patient_id"]), r["patient"], r["phone"], r["med"],
                    r["qty"], r["price"], r["total"], r["dose"], r["batches"]])
    return buf.getvalue()


def send_email(s, subject, body, attachment, filename):
    need = ["smtp_host", "smtp_user", "smtp_pass", "doctor_email"]
    if not all(s.get(k) for k in need):
        raise RuntimeError("Email is not set up (Settings: SMTP + doctor email)")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, s["smtp_from"] or s["smtp_user"], s["doctor_email"]
    msg.set_content(body)
    msg.add_attachment(attachment.encode("utf-8"), maintype="text", subtype="csv", filename=filename)
    port, ctx = int(s["smtp_port"] or 587), ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(s["smtp_host"], port, context=ctx, timeout=30)
    else:
        server = smtplib.SMTP(s["smtp_host"], port, timeout=30)
        server.starttls(context=ctx)
    with server:
        server.login(s["smtp_user"], s["smtp_pass"])
        server.send_message(msg)
    return "sent to " + s["doctor_email"]


def send_whatsapp(s, body):
    if not all(s.get(k) for k in ("twilio_sid", "twilio_token", "twilio_from", "doctor_whatsapp")):
        raise RuntimeError("WhatsApp is not set up (Settings: Twilio + doctor WhatsApp)")
    num = lambda n: "whatsapp:+" + re.sub(r"\D", "", n)
    if len(body) > 1500:  # WhatsApp message limit is 1600 characters
        body = body[:1450] + "\n...(full report sent by email)"
    req = Request(f"https://api.twilio.com/2010-04-01/Accounts/{s['twilio_sid']}/Messages.json",
                  data=urlencode({"From": num(s["twilio_from"]), "To": num(s["doctor_whatsapp"]),
                                  "Body": body}).encode())
    token = base64.b64encode(f"{s['twilio_sid']}:{s['twilio_token']}".encode()).decode()
    req.add_header("Authorization", "Basic " + token)
    try:
        with urlopen(req, timeout=30) as r:
            return "message id " + json.load(r).get("sid", "?")
    except HTTPError as e:
        raise RuntimeError("Twilio: " + json.loads(e.read() or b"{}").get("message", str(e)))


def send_report(day, channels=("email", "whatsapp"), auto=False):
    with closing(db()) as c:
        s = get_settings(c)
        rep = build_report(c, day)
        attach = sales_csv(c, day)
        results = []
        for ch in channels:
            try:
                if ch == "email":
                    detail = send_email(s, f"{s['clinic_name']} daily report {day}", rep["text"],
                                        attach, f"sales-{day}.csv")
                else:
                    detail = send_whatsapp(s, rep["text"])
                ok = 1
            except Exception as e:
                ok, detail = 0, str(e)
            detail = ("[auto] " if auto else "") + detail
            c.execute("INSERT INTO report_log(sent_at,day,channel,ok,detail) VALUES(?,?,?,?,?)",
                      (now_str(), day, ch, ok, detail))
            results.append({"channel": ch, "ok": bool(ok), "detail": detail})
        return results


def scheduler():
    """Sends today's report once a day at the configured time."""
    while True:
        try:
            with closing(db()) as c:
                s = get_settings(c)
                now, today = datetime.now(), date.today().isoformat()
                due = s.get("auto_send") == "1" and now.strftime("%H:%M") >= (s.get("report_time") or "20:00")
                if due and s.get("last_auto") != today:
                    set_setting(c, "last_auto", today)
                    chans = [ch for ch, k in (("email", "doctor_email"), ("whatsapp", "doctor_whatsapp")) if s.get(k)]
                    if chans:
                        for r in send_report(today, chans, auto=True):
                            print(f"[{now_str()}] auto report {r['channel']}: {'OK' if r['ok'] else 'FAILED'} {r['detail']}")
        except Exception as e:
            print("scheduler error:", e)
        time.sleep(30)


# ---------- HTTP ----------

ROUTES = []


def route(method, pattern, perm=None):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), perm, fn))
        return fn
    return deco


def clean(b, key, limit=200):
    return str(b.get(key) or "").strip()[:limit]


@route("POST", "/api/login")
def api_login(h, c, user, b, q):
    u = c.execute("SELECT * FROM users WHERE username=?", (clean(b, "username"),)).fetchone()
    if not u or not hmac.compare_digest(u["pw"], hash_pw(str(b.get("password") or ""), u["salt"])):
        time.sleep(1)
        raise ApiError(401, "Wrong username or password")
    c.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
    token = secrets.token_urlsafe(32)
    c.execute("INSERT INTO sessions VALUES(?,?,?)", (token, u["id"], time.time() + SESSION_HOURS * 3600))
    h.set_cookie = f"sid={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_HOURS * 3600}"
    return {"ok": True}


@route("POST", "/api/logout", "any")
def api_logout(h, c, user, b, q):
    c.execute("DELETE FROM sessions WHERE token=?", (h.token,))
    h.set_cookie = "sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
    return {"ok": True}


@route("GET", "/api/me", "any")
def api_me(h, c, user, b, q):
    return {"id": user["id"], "username": user["username"], "name": user["name"],
            "role": user["role"], "perms": sorted(ROLES[user["role"]])}


@route("POST", "/api/password", "any")
def api_password(h, c, user, b, q):
    if not hmac.compare_digest(user["pw"], hash_pw(str(b.get("old") or ""), user["salt"])):
        raise ApiError(400, "Current password is wrong")
    new = str(b.get("new") or "")
    if len(new) < 8:
        raise ApiError(400, "New password must be at least 8 characters")
    salt = secrets.token_hex(16)
    c.execute("UPDATE users SET salt=?, pw=? WHERE id=?", (salt, hash_pw(new, salt), user["id"]))
    c.execute("DELETE FROM sessions WHERE user_id=? AND token<>?", (user["id"], h.token))
    return {"ok": True}


@route("GET", "/api/dashboard", "patients_read")
def api_dashboard(h, c, user, b, q):
    today = date.today().isoformat()
    rep = build_report(c, today)
    log = [dict(r) for r in c.execute("SELECT * FROM report_log ORDER BY id DESC LIMIT 5")]
    return {**{k: rep[k] for k in ("patients", "buyers", "sales", "revenue", "low", "expiring")}, "log": log}


@route("GET", "/api/patients", "patients_read")
def api_patients(h, c, user, b, q):
    term = "%" + (q.get("q", [""])[0]).strip() + "%"
    rows = c.execute("SELECT p.*, (SELECT COUNT(*) FROM sales s WHERE s.patient_id=p.id) visits,"
                     " (SELECT COALESCE(SUM(total),0) FROM sales s WHERE s.patient_id=p.id) spent"
                     " FROM patients p WHERE p.name LIKE ? OR p.phone LIKE ? OR printf('P%04d',p.id) LIKE ?"
                     " ORDER BY p.id DESC LIMIT 200", (term, term, term))
    return [{**dict(r), "code": pcode(r["id"])} for r in rows]


@route("POST", "/api/patients", "patients_write")
def api_add_patient(h, c, user, b, q):
    name, phone = clean(b, "name", 100), clean(b, "phone", 20)
    if not name or not phone:
        raise ApiError(400, "Name and phone are required")
    age = clean(b, "age", 3)
    cur = c.execute("INSERT INTO patients(name,age,gender,phone,address,allergies,dx,doctor,created_at,created_by)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (name, int(age) if age.isdigit() else None, clean(b, "gender", 10), phone,
                     clean(b, "address"), clean(b, "allergies"), clean(b, "dx", 300), clean(b, "doctor", 100),
                     now_str(), user["id"]))
    return {"ok": True, "id": cur.lastrowid, "code": pcode(cur.lastrowid)}


@route("GET", r"/api/patients/(\d+)", "patients_read")
def api_patient(h, c, user, b, q, pid):
    p = c.execute("SELECT * FROM patients WHERE id=?", (int(pid),)).fetchone()
    if not p:
        raise ApiError(404, "Patient not found")
    hist = c.execute("SELECT created_at,med,qty,total,dose FROM sales WHERE patient_id=? ORDER BY id DESC",
                     (int(pid),))
    return {**dict(p), "code": pcode(p["id"]), "history": [dict(r) for r in hist]}


@route("GET", "/api/meds", "patients_read")
def api_meds(h, c, user, b, q):
    rows = [med_row(m) for m in c.execute("SELECT * FROM meds WHERE qty>0")]
    return {"batches": sorted(rows, key=lambda m: m["days_left"]), "summary": stock_summary(c)}


@route("POST", "/api/meds", "meds")
def api_add_med(h, c, user, b, q):
    name, exp = clean(b, "name", 100), clean(b, "expiry", 10)
    try:
        qty = int(b.get("qty"))
        date.fromisoformat(exp)
        opened = clean(b, "opened", 10)
        if opened:
            date.fromisoformat(opened)
        price = float(b.get("price") or 0)
    except (TypeError, ValueError):
        raise ApiError(400, "Check quantity, price and dates")
    if not name or qty <= 0:
        raise ApiError(400, "Medicine name and quantity are required")
    c.execute("INSERT INTO meds(name,type,batch,qty,expiry,opened,price) VALUES(?,?,?,?,?,?,?)",
              (name, clean(b, "type", 20), clean(b, "batch", 40), qty, exp, opened, price))
    return {"ok": True}


@route("POST", r"/api/meds/(\d+)/remove", "meds")
def api_remove_med(h, c, user, b, q, mid):
    """Write off a batch (expired, damaged or returned). Sales history is kept."""
    c.execute("UPDATE meds SET qty=0 WHERE id=?", (int(mid),))
    return {"ok": True}


@route("POST", "/api/dispense", "dispense")
def api_dispense(h, c, user, b, q):
    return dispense(c, user, b)


@route("GET", "/api/sales", "report")
def api_sales(h, c, user, b, q):
    day = q.get("date", [date.today().isoformat()])[0]
    return [{**dict(r), "code": pcode(r["patient_id"])} for r in day_sales(c, day)]


@route("GET", "/api/report", "report")
def api_report(h, c, user, b, q):
    day = q.get("date", [date.today().isoformat()])[0]
    log = [dict(r) for r in c.execute("SELECT * FROM report_log ORDER BY id DESC LIMIT 20")]
    return {**build_report(c, day), "log": log}


@route("POST", "/api/report/send", "report")
def api_send(h, c, user, b, q):
    day = clean(b, "date", 10) or date.today().isoformat()
    chans = [ch for ch in b.get("channels") or ["email", "whatsapp"] if ch in ("email", "whatsapp")]
    return send_report(day, chans)


@route("GET", "/api/settings", "admin")
def api_settings(h, c, user, b, q):
    s = get_settings(c)
    return {k: ("********" if k in SECRET_SETTINGS and v else v) for k, v in s.items() if k != "last_auto"}


@route("POST", "/api/settings", "admin")
def api_save_settings(h, c, user, b, q):
    for k in DEFAULT_SETTINGS:
        if k == "last_auto" or k not in b:
            continue
        v = str(b[k]).strip()
        if k in SECRET_SETTINGS and v == "********":
            continue  # unchanged
        if k == "report_time" and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ApiError(400, "Report time must be HH:MM")
        set_setting(c, k, v)
    return {"ok": True}


@route("GET", "/api/users", "admin")
def api_users(h, c, user, b, q):
    return [dict(r) for r in c.execute("SELECT id,username,name,role FROM users ORDER BY id")]


@route("POST", "/api/users", "admin")
def api_add_user(h, c, user, b, q):
    make_user(c, clean(b, "username", 30), clean(b, "name", 100), clean(b, "role", 20), str(b.get("password") or ""))
    return {"ok": True}


@route("POST", r"/api/users/(\d+)/reset", "admin")
def api_reset_user(h, c, user, b, q, uid):
    pw = str(b.get("password") or "")
    if len(pw) < 8:
        raise ApiError(400, "Password must be at least 8 characters")
    salt = secrets.token_hex(16)
    c.execute("UPDATE users SET salt=?, pw=? WHERE id=?", (salt, hash_pw(pw, salt), int(uid)))
    c.execute("DELETE FROM sessions WHERE user_id=?", (int(uid),))
    return {"ok": True}


@route("POST", r"/api/users/(\d+)/delete", "admin")
def api_del_user(h, c, user, b, q, uid):
    if int(uid) == user["id"]:
        raise ApiError(400, "You cannot delete your own account")
    c.execute("DELETE FROM users WHERE id=?", (int(uid),))
    return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    server_version = "MediAssist"

    def log_message(self, fmt, *args):
        pass

    def send(self, status, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else (
            json.dumps(body).encode() if ctype == "application/json" else body.encode())
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8" if not ctype.startswith("application/octet") else ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if getattr(self, "set_cookie", None):
            self.send_header("Set-Cookie", self.set_cookie)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def current_user(self, c):
        jar = SimpleCookie(self.headers.get("Cookie", ""))
        self.token = jar["sid"].value if "sid" in jar else ""
        if not self.token:
            return None
        return c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id"
                         " WHERE s.token=? AND s.expires>?", (self.token, time.time())).fetchone()

    def handle_any(self, method):
        url = urlparse(self.path)
        self.set_cookie = None
        if method == "GET" and url.path in ("/", "/index.html"):
            with open(os.path.join(BASE, "index.html"), "rb") as f:
                return self.send(200, f.read(), "text/html")
        try:
            with closing(db()) as c:
                user = self.current_user(c)
                if method == "GET" and url.path in ("/api/sales.csv", "/api/backup"):
                    return self.downloads(c, user, url)
                for m, rx, perm, fn in ROUTES:
                    match = rx.match(url.path)
                    if m != method or not match:
                        continue
                    if perm and not user:
                        raise ApiError(401, "Please log in")
                    if perm and perm != "any" and perm not in ROLES[user["role"]]:
                        raise ApiError(403, "Your role cannot do this")
                    body = {}
                    if method == "POST":
                        # JSON-only bodies + SameSite cookie protect against cross-site form posts
                        if "application/json" not in self.headers.get("Content-Type", ""):
                            raise ApiError(415, "JSON required")
                        n = int(self.headers.get("Content-Length") or 0)
                        if n > 100_000:
                            raise ApiError(413, "Request too large")
                        body = json.loads(self.rfile.read(n) or b"{}")
                    return self.send(200, fn(self, c, user, body, parse_qs(url.query), *match.groups()))
                raise ApiError(404, "Not found")
        except ApiError as e:
            self.send(e.status, {"error": str(e)})
        except Exception as e:
            print("error:", repr(e))
            self.send(500, {"error": "Server error: " + str(e)})

    def downloads(self, c, user, url):
        if not user:
            raise ApiError(401, "Please log in")
        perms = ROLES[user["role"]]
        if url.path == "/api/sales.csv":
            if "report" not in perms:
                raise ApiError(403, "Your role cannot do this")
            day = parse_qs(url.query).get("date", [date.today().isoformat()])[0]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                raise ApiError(400, "Bad date")
            return self.send(200, sales_csv(c, day), "text/csv",
                             {"Content-Disposition": f'attachment; filename="sales-{day}.csv"'})
        if "admin" not in perms:
            raise ApiError(403, "Admins only")
        mem = sqlite3.connect(":memory:")
        c.backup(mem)
        data = mem.serialize() if hasattr(mem, "serialize") else None
        mem.close()
        if data is None:
            with open(DB_PATH, "rb") as f:
                data = f.read()
        return self.send(200, bytes(data), "application/octet-stream",
                         {"Content-Disposition": f'attachment; filename="clinic-backup-{date.today()}.db"'})

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    init_db()
    threading.Thread(target=scheduler, daemon=True).start()
    print(f"MediAssist running:\n  this computer:   http://localhost:{PORT}\n"
          f"  other computers: http://{lan_ip()}:{PORT}  (same Wi-Fi/network)\nPress Ctrl+C to stop.")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
