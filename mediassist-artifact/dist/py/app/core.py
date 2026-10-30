"""Core plumbing shared by every module: database, errors, money/date helpers,
auth helpers, roles, audit, settings and the route registry."""
import base64
import hashlib
import hmac
import math
import json
import os
import re
import secrets
import sqlite3
import struct
import sys
import threading
import time
from datetime import date, datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("MEDIASSIST_DATA", os.path.join(BASE, "data"))
DB_PATH = os.environ.get("MEDIASSIST_DB", os.path.join(DATA_DIR, "mediassist.db"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
SESSION_HOURS = 12

# ------------------------------------------------------------------ roles
P_ALL = {"all_branches", "patients_read", "patients_write", "visit_create", "consult", "billing", "hbilling",
         "stock", "stock_admin", "reports", "org_reports", "admin", "audit", "lab", "lab_verify", "appointments",
         "ipd", "ipd_nursing", "admit", "certificates", "lab_admin", "accounts", "documents"}
ROLES = {
    "owner": set(P_ALL),
    "manager": {"patients_read", "patients_write", "visit_create", "billing", "hbilling", "stock", "stock_admin",
                "reports", "audit", "lab", "lab_admin", "appointments", "ipd", "admit", "certificates", "accounts", "documents"},
    "doctor": {"patients_read", "patients_write", "visit_create", "consult", "reports", "lab_verify", "appointments",
               "ipd", "admit", "certificates", "documents"},
    "nurse": {"patients_read", "visit_create", "ipd", "ipd_nursing", "admit", "appointments", "documents"},
    "reception": {"patients_read", "patients_write", "visit_create", "hbilling", "admit", "appointments", "documents"},
    "pharmacist": {"patients_read", "billing", "stock", "documents"},
    "lab_tech": {"patients_read", "lab", "documents"},
    "lab_incharge": {"patients_read", "lab", "lab_verify", "lab_admin", "reports", "documents"},
    "accountant": {"patients_read", "reports", "accounts", "hbilling"},
}


class ApiError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


# ------------------------------------------------------------------ db
_local = threading.local()


def db():
    """One connection per thread, reused; autocommit unless in_tx is used."""
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        if sys.platform == "emscripten":  # in-browser demo: single user on an in-memory filesystem; WAL/shm only slow it down
            c.execute("PRAGMA journal_mode=MEMORY")
            c.execute("PRAGMA synchronous=OFF")
            c.execute("PRAGMA temp_store=MEMORY")
        else:
            c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=15000")
        _local.conn = c
    return c


def reset_conn():
    c = getattr(_local, "conn", None)
    if c is not None:
        c.close()
        _local.conn = None


def in_tx(c, fn):
    c.execute("BEGIN IMMEDIATE")
    try:
        out = fn()
        c.execute("COMMIT")
        return out
    except BaseException:
        c.execute("ROLLBACK")
        raise


def rows(cur):
    return [dict(r) for r in cur]


def one(c, sql, args=()):
    r = c.execute(sql, args).fetchone()
    return dict(r) if r else None


# ------------------------------------------------------------------ helpers
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today():
    return date.today().isoformat()


def add_days(day, n):
    return (date.fromisoformat(day[:10]) + timedelta(days=n)).isoformat()


def valid_day(s, field="date"):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s or "")):
        raise ApiError(400, f"Invalid {field}")
    try:
        date.fromisoformat(s)
    except ValueError:
        raise ApiError(400, f"Invalid {field}")
    return s


def P(x, field="amount"):
    """Rupees -> integer paise."""
    try:
        f = float(x or 0)
        if not math.isfinite(f) or abs(f) > 1e9:
            raise ValueError
        v = int(round(f * 100))
    except (TypeError, ValueError, OverflowError):
        raise ApiError(400, f"Invalid {field}")
    if v < 0:
        raise ApiError(400, f"{field} cannot be negative")
    return v


def R(p):
    return round((p or 0) / 100, 2)


def rs(p):
    return f"Rs {R(p):,.2f}"


def as_int(v, field, lo=None, hi=None):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ApiError(400, f"Invalid {field}")
    if lo is not None and n < lo:
        raise ApiError(400, f"{field} must be at least {lo}")
    if hi is not None and n > hi:
        raise ApiError(400, f"{field} must be at most {hi}")
    return n


def opt_num(v, cast=float, field="number"):
    if v in (None, ""):
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        raise ApiError(400, f"Invalid {field}")


def clean(b, key, limit=200):
    return str(b.get(key) or "").strip()[:limit]


def qget(q, key, default=""):
    return q.get(key, [default])[0]


def pcode(pid):
    return f"P{pid:05d}"


def need(cond, msg, status=400):
    if not cond:
        raise ApiError(status, msg)


# ------------------------------------------------------------------ passwords and TOTP (2FA)
def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def new_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret, at=None, step=30, digits=6):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int((at or time.time()) // step)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 15
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


def totp_ok(secret, code, after_step=0):
    """True when the code matches the current step or its neighbours. Returns the matched step (truthy) so the
    caller can store it: a step at or before `after_step` was already used and is refused (replay guard)."""
    code = re.sub(r"\D", "", str(code or ""))
    for d in (-1, 0, 1):
        step = int(time.time()) // 30 + d
        if step > after_step and hmac.compare_digest(totp(secret, step * 30), code):
            return step
    return 0


def like(term):
    """Escape a search term for LIKE ... ESCAPE '\\' and wrap it in wildcards."""
    return "%" + re.sub(r"([\\%_])", r"\\\1", term) + "%"


# ------------------------------------------------------------------ settings & audit
DEFAULT_SETTINGS = {
    "org_name": "My Healthcare Group", "owner_email": "", "owner_whatsapp": "",
    "report_time": "20:00", "auto_send": "1", "reminder_time": "09:00",
    "smtp_host": "smtp.gmail.com", "smtp_port": "587", "smtp_user": "", "smtp_pass": "", "smtp_from": "",
    "twilio_sid": "", "twilio_token": "", "twilio_from": "", "anthropic_api_key": "",
    "whatsapp_provider": "auto", "meta_phone_id": "", "meta_token": "", "abdm_env": "sandbox", "abdm_client_id": "", "abdm_client_secret": "", "abdm_hip_id": "", "razorpay_key_id": "", "razorpay_key_secret": "", "razorpay_webhook_secret": "",
    "public_url": "", "online_booking": "1", "slot_minutes": "10", "opd_hours": "09:00-13:00,17:00-20:00", "backup_keep_days": "30",
    "portal_auto": "1", "portal_days": "180", "welcome_msg": "1",
    "weekly_pharmacy": "1", "weekly_day": "mon", "last_weekly": "",
    "watch_amount": "2000", "watch_discount_pct": "10",
    "briefing_on": "1", "briefing_time": "08:00", "last_briefing": "",
    "assistant_on": "1", "assistant_patients": "1", "lab_ai": "1",
    "alert_critical": "1", "alert_booking": "1", "alert_wait": "1", "alert_admit": "1", "alert_admit_owner": "1",
    "max_discount_pct": "10", "google_review_url": "",
    "last_auto": "", "last_reminders": "", "last_backup": "",
}
SECRET_SETTINGS = {"smtp_pass", "twilio_token", "anthropic_api_key", "meta_token", "razorpay_key_secret", "razorpay_webhook_secret", "abdm_client_secret"}


def get_settings(c):
    return {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM settings")}


def set_setting(c, k, v):
    c.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))


def check_discount(c, h, disc_p, gross_p):
    """Staff other than the owner and managers can give at most the discount limit in Admin > Settings."""
    if not disc_p or h.user["role"] in ("owner", "manager"):
        return
    pct = float(get_settings(c).get("max_discount_pct") or 0)
    need(disc_p <= gross_p * pct / 100 + 0.5, f"Discount is above your limit of {pct:g}%. Ask a manager to give a larger discount.", 403)


def audit(c, h, action, detail=""):
    c.execute("INSERT INTO audit(at,user_id,branch_id,action,detail) VALUES(?,?,?,?,?)",
              (now_str(), h.user["id"] if getattr(h, "user", None) else None, getattr(h, "branch", 0) or None,
               action, str(detail)[:600]))


# ------------------------------------------------------------------ branch helpers
def branch_row(c, bid):
    b = one(c, "SELECT * FROM branches WHERE id=?", (bid,))
    if not b:
        raise ApiError(404, "Branch not found")
    return b


def need_branch(h, c, kind=None):
    if not h.branch:
        raise ApiError(400, "Choose a branch first (top of the screen)")
    b = branch_row(c, h.branch)
    if kind and kind not in b["kind"]:
        raise ApiError(400, f"{b['name']} is not set up as a {kind}")
    return b


def all_access(user):
    return user["role"] == "owner" or user["branch_id"] is None


def can(h, perm):
    return perm in ROLES.get(h.user["role"], set())


# ------------------------------------------------------------------ routes
ROUTES = []
PUBLIC_GET = {}


def route(method, pattern, perm=None):
    """perm: None = public, "any" = any signed-in user, else a permission name."""
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), perm, fn))
        return fn
    return deco


def to_json(o):
    return json.dumps(o, default=str)
