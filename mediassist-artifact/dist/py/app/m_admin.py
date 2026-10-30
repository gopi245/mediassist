"""Sign-in, 2FA, branches, staff, settings, audit, CSV import, backups, DPDP data requests."""
import csv
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import time
from datetime import datetime

from .core import (ROLES, ApiError, BACKUP_DIR, DB_PATH, DEFAULT_SETTINGS, SECRET_SETTINGS, SESSION_HOURS, P, R, add_days,
                   all_access, as_int, audit, branch_row, clean, get_settings, hash_pw, in_tx, like, need, new_totp_secret, now_str,
                   one, opt_num, pcode, qget, route, rows, set_setting, today, totp_ok, valid_day)

BRANCH_KINDS = ("hospital", "pharmacy", "hospital+pharmacy")
LOCK_AFTER, LOCK_SECONDS = 5, 15 * 60


def make_user(c, b, existing=None):
    role = clean(b, "role", 20)
    need(role in ROLES, "Unknown role")
    branch_id = b.get("branch_id") or None
    if branch_id:
        branch_row(c, int(branch_id))
    if role == "owner":
        branch_id = None
    lang = clean(b, "lang", 5) or "en"
    need(lang in ("en", "hi", "te", "ta"), "Unknown language")
    fields = (clean(b, "name", 100), role, branch_id, clean(b, "reg_no", 40), clean(b, "email", 200), clean(b, "whatsapp", 20),
              0 if b.get("active") is False else 1, float(opt_num(b.get("payout_pct")) or 0), lang)
    need(0 <= fields[7] <= 100, "Payout share must be between 0 and 100%")
    if existing:
        c.execute("UPDATE users SET name=?,role=?,branch_id=?,reg_no=?,email=?,whatsapp=?,active=?,payout_pct=?,lang=? WHERE id=?", (*fields, existing))
        if not fields[6]:
            c.execute("DELETE FROM sessions WHERE user_id=?", (existing,))
        return existing
    username, pw = clean(b, "username", 30), str(b.get("password") or "")
    need(re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", username), "Username: 3-30 letters, numbers, . _ -")
    need(len(pw) >= 8, "Password must be at least 8 characters")
    salt = secrets.token_hex(16)
    try:
        cur = c.execute("INSERT INTO users(username,name,role,branch_id,reg_no,email,whatsapp,active,payout_pct,lang,salt,pw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (username, *fields, salt, hash_pw(pw, salt)))
    except sqlite3.IntegrityError:
        raise ApiError(400, "That username is taken")
    return cur.lastrowid


def default_branch(c, u):
    if u["branch_id"]:
        return u["branch_id"]
    if u["role"] == "owner":
        return 0
    r = c.execute("SELECT id FROM branches WHERE active=1 ORDER BY id").fetchone()
    return r[0] if r else 0


# ---------------------------------------------------------------- health and API reference
@route("GET", "/api/health")
def api_health(h, c, b, q):
    """Liveness for monitors: database reachable, schema version, server time. No patient data."""
    from .schema import MIGRATIONS
    v = c.execute("SELECT v FROM schema_version").fetchone()[0]
    return {"ok": v == len(MIGRATIONS), "schema": v, "expected": len(MIGRATIONS), "time": now_str()}


@route("GET", "/api/docs", "any")
def api_docs_list(h, c, b, q):
    """Every API route with its permission and a one-line description, generated from the code."""
    from .core import ROUTES
    out = []
    for method, rx, perm, fn in ROUTES:
        path = rx.pattern[1:-1].replace("(\\d+)", "{id}").replace("\\d+", "{id}").replace("\\", "")
        out.append({"method": method, "path": path, "permission": perm or "public", "module": fn.__module__.rsplit(".", 1)[-1],
                    "summary": (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""})
    out.sort(key=lambda r: (r["path"], r["method"]))
    return out


# ---------------------------------------------------------------- auth
@route("POST", "/api/login")
def api_login(h, c, b, q):
    from .m_appointments import rate_limit
    ip_key, ip_msg = f"login:{getattr(h, 'client_ip', '?')}", "Too many failed sign-ins from this address. Wait 15 minutes."
    rate_limit(ip_key, 30, 900, ip_msg, count=False)  # only failures count, below
    u = one(c, "SELECT * FROM users WHERE username=? AND active=1", (clean(b, "username"),))
    if u and u["locked_until"] > time.time():
        raise ApiError(429, f"Too many wrong passwords. Try again after {datetime.fromtimestamp(u['locked_until']).strftime('%H:%M')}.")
    if not u or hash_pw(str(b.get("password") or ""), u["salt"]) != u["pw"]:
        if u:
            n = u["failed_logins"] + 1
            c.execute("UPDATE users SET failed_logins=?, locked_until=? WHERE id=?", (n if n < LOCK_AFTER else 0, time.time() + LOCK_SECONDS if n >= LOCK_AFTER else 0, u["id"]))
        c.execute("INSERT INTO audit(at,user_id,branch_id,action,detail) VALUES(?,?,?,?,?)",
                  (now_str(), u["id"] if u else None, None, "login.failed", f"{str(b.get('username') or '')[:40]} from {getattr(h, 'client_ip', '')}"))
        try:
            rate_limit(ip_key, 30, 900, ip_msg)
        except ApiError:
            pass  # the 30th failure is recorded; the next attempt is refused
        time.sleep(0.8)
        raise ApiError(401, "Wrong username or password")
    c.execute("UPDATE users SET failed_logins=0, locked_until=0 WHERE id=?", (u["id"],))
    c.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
    token = secrets.token_urlsafe(32)
    mfa = 0 if u["totp_secret"] else 1
    c.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (token, u["id"], default_branch(c, u), time.time() + SESSION_HOURS * 3600, mfa))
    h.user, h.branch = u, 0
    audit(c, h, "login", "password ok, waiting for 2FA code" if not mfa else "")
    h.set_cookie = f"sid={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_HOURS * 3600}" + ("; Secure" if h.https else "")
    return {"ok": True, "mfa_required": not mfa}


OPEN_LOGIN = os.environ.get("MEDIASSIST_OPEN_LOGIN") == "1"   # demo only: sign in by picking a role, no password


@route("GET", "/api/open-login")
def api_open_roles(h, c, b, q):
    return {"roles": list(ROLES) if OPEN_LOGIN else []}


@route("POST", "/api/open-login")
def api_open_login(h, c, b, q):
    need(OPEN_LOGIN, "Role sign-in is turned off")
    role = clean(b, "role", 20)
    need(role in ROLES, "Unknown role")
    u = one(c, "SELECT * FROM users WHERE role=? AND active=1 ORDER BY id", (role,))
    if not u:
        uid = make_user(c, {"username": role.replace("_", "-"), "password": secrets.token_urlsafe(16), "role": role,
                            "name": role.replace("_", " ").title()})
        u = one(c, "SELECT * FROM users WHERE id=?", (uid,))
    token = secrets.token_urlsafe(32)
    c.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (token, u["id"], default_branch(c, u), time.time() + SESSION_HOURS * 3600, 1))
    h.user, h.branch = u, 0
    audit(c, h, "login", "role sign-in, no password")
    h.set_cookie = f"sid={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_HOURS * 3600}" + ("; Secure" if h.https else "")
    return {"ok": True}


@route("POST", "/api/2fa/verify", "mfa")
def api_2fa_verify(h, c, b, q):
    need(h.user["totp_secret"], "Two-step sign-in is not set up")
    step = totp_ok(h.user["totp_secret"], b.get("code"), h.user["last_totp"] or 0)
    if not step:
        time.sleep(0.8)
        raise ApiError(401, "That code is wrong, expired or already used. Use the next code from your authenticator app.")
    c.execute("UPDATE users SET last_totp=? WHERE id=?", (step, h.user["id"]))
    c.execute("UPDATE sessions SET mfa_ok=1 WHERE token=?", (h.token,))
    audit(c, h, "login.2fa")
    return {"ok": True}


@route("POST", "/api/2fa/setup", "any")
def api_2fa_setup(h, c, b, q):
    secret = new_totp_secret()
    issuer = get_settings(c)["org_name"].replace(" ", "%20")
    h.pending_totp = secret
    c.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (f"pending_totp_{h.user['id']}", secret))
    return {"secret": secret, "uri": f"otpauth://totp/{issuer}:{h.user['username']}?secret={secret}&issuer={issuer}"}


@route("POST", "/api/2fa/enable", "any")
def api_2fa_enable(h, c, b, q):
    s = get_settings(c).get(f"pending_totp_{h.user['id']}")
    need(s, "Start the setup again")
    need(totp_ok(s, b.get("code")), "That code doesn't match. Check the phone's time and try the current code.")
    c.execute("UPDATE users SET totp_secret=? WHERE id=?", (s, h.user["id"]))
    c.execute("DELETE FROM settings WHERE key=?", (f"pending_totp_{h.user['id']}",))
    audit(c, h, "2fa.enable")
    return {"ok": True}


@route("POST", "/api/2fa/disable", "any")
def api_2fa_disable(h, c, b, q):
    need(h.user["totp_secret"], "Two-step sign-in is not on")
    need(totp_ok(h.user["totp_secret"], b.get("code")), "Enter a current code to turn it off")
    c.execute("UPDATE users SET totp_secret=NULL WHERE id=?", (h.user["id"],))
    audit(c, h, "2fa.disable")
    return {"ok": True}


@route("POST", "/api/logout", "mfa")
def api_logout(h, c, b, q):
    c.execute("DELETE FROM sessions WHERE token=?", (h.token,))
    h.set_cookie = "sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
    return {"ok": True}


@route("GET", "/api/me", "mfa")
def api_me(h, c, b, q):
    u = h.user
    if all_access(u):
        brs = rows(c.execute("SELECT id,code,name,kind FROM branches WHERE active=1 ORDER BY id"))
    else:
        brs = rows(c.execute("SELECT id,code,name,kind FROM branches WHERE id=?", (u["branch_id"],)))
    s = get_settings(c)
    return {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"], "lang": u["lang"], "reg_no": u["reg_no"],
            "perms": sorted(ROLES[u["role"]]), "all_access": all_access(u), "branch": next((x for x in brs if x["id"] == h.branch), None),
            "branches": brs, "org_name": s["org_name"], "mfa_required": not h.mfa_ok, "has_2fa": bool(u["totp_secret"]),
            "suggest_2fa": u["role"] == "owner" and not u["totp_secret"] and not getattr(h, "open_access", False), "open_access": getattr(h, "open_access", False)}


@route("POST", "/api/branch", "any")
def api_switch(h, c, b, q):
    need(all_access(h.user), "You are assigned to one branch", 403)
    bid = as_int(b.get("branch_id") or 0, "branch")
    if bid:
        branch_row(c, bid)
    c.execute("UPDATE sessions SET branch_id=? WHERE token=?", (bid, h.token))
    return {"ok": True}


@route("POST", "/api/password", "any")
def api_password(h, c, b, q):
    need(hash_pw(str(b.get("old") or ""), h.user["salt"]) == h.user["pw"], "Current password is wrong")
    new = str(b.get("new") or "")
    need(len(new) >= 8, "New password must be at least 8 characters")
    salt = secrets.token_hex(16)
    c.execute("UPDATE users SET salt=?, pw=? WHERE id=?", (salt, hash_pw(new, salt), h.user["id"]))
    c.execute("DELETE FROM sessions WHERE user_id=? AND token<>?", (h.user["id"], h.token))
    audit(c, h, "password.change")
    return {"ok": True}


@route("POST", "/api/me/lang", "any")
def api_lang(h, c, b, q):
    lang = clean(b, "lang", 5)
    need(lang in ("en", "hi", "te", "ta"), "Unknown language")
    c.execute("UPDATE users SET lang=? WHERE id=?", (lang, h.user["id"]))
    return {"ok": True}


# ---------------------------------------------------------------- branches & staff
@route("GET", "/api/branches", "any")
def api_branches(h, c, b, q):
    return rows(c.execute("SELECT * FROM branches ORDER BY id"))


@route("POST", "/api/branches", "admin")
def api_save_branch(h, c, b, q):
    code, name, kind = clean(b, "code", 8).upper(), clean(b, "name", 100), clean(b, "kind", 20)
    need(re.fullmatch(r"[A-Z0-9]{2,8}", code) and name and kind in BRANCH_KINDS, "Code (2-8 letters/numbers), name and type are required")
    upi = clean(b, "upi_id", 60)
    need(not upi or re.fullmatch(r"[A-Za-z0-9._-]{2,}@[A-Za-z0-9.-]{2,}", upi), "UPI ID looks wrong (name@bank)")
    vals = (code, name, kind, clean(b, "address"), clean(b, "phone", 20), clean(b, "gstin", 20), clean(b, "dl_no", 60),
            clean(b, "report_email"), clean(b, "report_whatsapp", 20), 0 if b.get("active") is False else 1)
    hfr = clean(b, "hfr_id", 40) or None
    try:
        if b.get("id"):
            c.execute("UPDATE branches SET code=?,name=?,kind=?,address=?,phone=?,gstin=?,dl_no=?,report_email=?,report_whatsapp=?,active=?,upi_id=?,hfr_id=? WHERE id=?",
                      (*vals, upi or None, hfr, as_int(b["id"], "id")))
        else:
            c.execute("INSERT INTO branches(code,name,kind,address,phone,gstin,dl_no,report_email,report_whatsapp,active,upi_id,hfr_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (*vals, upi or None, hfr))
    except sqlite3.IntegrityError:
        raise ApiError(400, "Branch code already used")
    audit(c, h, "branch.save", f"{code} {name}")
    return {"ok": True}


@route("GET", "/api/users", "admin")
def api_users(h, c, b, q):
    return rows(c.execute("SELECT u.id,u.username,u.name,u.role,u.branch_id,u.reg_no,u.email,u.whatsapp,u.active,u.payout_pct,u.lang,"
                          "u.totp_secret IS NOT NULL has_2fa, b.name bname FROM users u LEFT JOIN branches b ON b.id=u.branch_id ORDER BY u.id"))


@route("GET", "/api/staff", "any")
def api_staff(h, c, b, q):
    role = qget(q, "role")
    sql = "SELECT id,name,role,reg_no,branch_id FROM users WHERE active=1"
    args = []
    if role:
        sql += " AND role=?"
        args.append(role)
    if h.branch:
        sql += " AND (branch_id IS NULL OR branch_id=?)"
        args.append(h.branch)
    return rows(c.execute(sql + " ORDER BY name", args))


@route("POST", "/api/users", "admin")
def api_save_user(h, c, b, q):
    uid = opt_num(b.get("id"), int)
    if uid == h.user["id"]:
        need(b.get("active") is not False and clean(b, "role", 20) == "owner", "You cannot demote or disable your own account")
    uid = make_user(c, b, uid)
    audit(c, h, "user.save", f"{uid} {clean(b, 'username')} role={clean(b, 'role')}")
    return {"ok": True}


@route(r"POST", r"/api/users/(\d+)/reset", "admin")
def api_reset_user(h, c, b, q, uid):
    pw = str(b.get("password") or "")
    need(len(pw) >= 8, "Password must be at least 8 characters")
    salt = secrets.token_hex(16)
    c.execute("UPDATE users SET salt=?, pw=?, failed_logins=0, locked_until=0 WHERE id=?", (salt, hash_pw(pw, salt), int(uid)))
    if b.get("clear_2fa"):
        c.execute("UPDATE users SET totp_secret=NULL WHERE id=?", (int(uid),))
    c.execute("DELETE FROM sessions WHERE user_id=?", (int(uid),))
    audit(c, h, "user.reset_password", f"{uid}{' and 2FA cleared' if b.get('clear_2fa') else ''}")
    return {"ok": True}


# ---------------------------------------------------------------- settings
@route("GET", "/api/settings", "admin")
def api_settings(h, c, b, q):
    s = get_settings(c)
    return {k: ("********" if k in SECRET_SETTINGS and s.get(k) else s.get(k, "")) for k in DEFAULT_SETTINGS if not k.startswith("last_")}


@route("POST", "/api/settings", "admin")
def api_save_settings(h, c, b, q):
    for k in DEFAULT_SETTINGS:
        if k.startswith("last_") or k not in b:
            continue
        v = str(b[k]).strip()
        if k in SECRET_SETTINGS and v == "********":
            continue
        if k in ("report_time", "reminder_time", "briefing_time"):
            need(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v), "Times must be HH:MM")
        if k in ("watch_amount", "watch_discount_pct"):
            need(re.fullmatch(r"\d{1,7}(\.\d+)?", v) and float(v) > 0, "Staff watch limits must be numbers above 0")
        if k == "max_discount_pct":
            need(re.fullmatch(r"\d{1,3}(\.\d+)?", v) and 0 <= float(v) <= 100, "Discount limit must be 0 to 100%")
        if k == "google_review_url":
            need(not v or v.startswith("https://"), "The Google review link must start with https://")
        if k == "weekly_day":
            need(v in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"), "Choose a weekday")
        if k == "portal_days":
            need(v.isdigit() and 7 <= int(v) <= 3650, "Patient links must last 7 to 3650 days")
        if k == "slot_minutes":
            need(v.isdigit() and 5 <= int(v) <= 60, "Slot length must be 5 to 60 minutes")
        set_setting(c, k, v)
    audit(c, h, "settings.save")
    return {"ok": True}


@route("GET", "/api/audit", "audit")
def api_audit(h, c, b, q):
    sql = "SELECT a.*, u.username, br.code FROM audit a LEFT JOIN users u ON u.id=a.user_id LEFT JOIN branches br ON br.id=a.branch_id WHERE 1=1"
    args = []
    if not all_access(h.user):
        sql += " AND a.branch_id=?"
        args.append(h.user["branch_id"])
    term = qget(q, "q").strip()
    if term:
        sql += " AND (a.action LIKE ? ESCAPE '\\' OR a.detail LIKE ? ESCAPE '\\' OR u.username LIKE ? ESCAPE '\\')"
        args += [like(term)] * 3
    limit, offset = min(as_int(qget(q, "limit", "200"), "limit", 1), 1000), as_int(qget(q, "offset", "0"), "offset", 0)
    return rows(c.execute(sql + " ORDER BY a.id DESC LIMIT ? OFFSET ?", (*args, limit, offset)))


@route("GET", "/api/errors", "admin")
def api_errors(h, c, b, q):
    return rows(c.execute("SELECT * FROM error_log ORDER BY id DESC LIMIT 100"))


# ---------------------------------------------------------------- CSV import (patients, stock)
def _csv_rows(text):
    text = text.lstrip("﻿")
    rd = csv.DictReader(io.StringIO(text))
    need(rd.fieldnames, "The file has no header row")
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rd]


@route("POST", "/api/import/patients", "admin")
def api_import_patients(h, c, b, q):
    data = _csv_rows(str(b.get("csv") or ""))
    need(len(data) <= 20000, "Import at most 20,000 rows at a time")

    def run():
        added, skipped, errors = 0, 0, []
        for i, r in enumerate(data, start=2):
            name, phone = r.get("name", ""), re.sub(r"[^\d+]", "", r.get("phone", ""))
            if not name or len(phone) < 10:
                errors.append(f"Row {i}: name and 10-digit phone needed")
                continue
            if one(c, "SELECT 1 FROM patients WHERE phone=? AND lower(name)=lower(?)", (phone, name)):
                skipped += 1
                continue
            age = r.get("age", "")
            c.execute("INSERT INTO patients(name,age,dob,gender,phone,address,allergies,conditions,blood_group,abha,branch_id,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (name[:100], int(age) if age.isdigit() else None, r.get("dob") or None, r.get("gender", "")[:10], phone, r.get("address", "")[:200],
                       r.get("allergies", "")[:200], r.get("conditions", "")[:200], r.get("blood_group", "")[:5], r.get("abha", "")[:20],
                       h.branch or None, now_str(), h.user["id"]))
            added += 1
        audit(c, h, "import.patients", f"added {added}, skipped {skipped} duplicates, {len(errors)} errors")
        return {"added": added, "skipped": skipped, "errors": errors[:50]}
    return in_tx(c, run)


@route("POST", "/api/import/stock", "admin")
def api_import_stock(h, c, b, q):
    need(h.branch, "Choose the branch to load stock into")
    data = _csv_rows(str(b.get("csv") or ""))

    def run():
        added, new_meds, errors = 0, 0, []
        for i, r in enumerate(data, start=2):
            name = r.get("medicine") or r.get("name") or ""
            try:
                qty = int(opt_num(r.get("qty") or r.get("quantity") or 0, float, "qty"))
                mrp, cost = P(r.get("mrp")), P(r.get("cost") or 0)
                exp = valid_day(r.get("expiry", ""), "expiry")
                gst, pack = opt_num(r.get("gst") or 5, float, "gst"), opt_num(r.get("pack_size") or 1, int, "pack_size")
            except ApiError as e:
                errors.append(f"Row {i}: {e}")
                continue
            if not name or qty <= 0 or not mrp:
                errors.append(f"Row {i}: medicine, qty and mrp are needed")
                continue
            m = one(c, "SELECT * FROM medicines WHERE lower(name)=lower(?)", (name,))
            if not m:
                c.execute("INSERT INTO medicines(name,generic,form,schedule,gst_pct,pack_size) VALUES(?,?,?,?,?,?)",
                          (name[:100], r.get("generic", "").lower()[:100], r.get("form", "Tablet")[:20], (r.get("schedule") or "OTC").upper()[:3],
                           gst, pack))
                m = one(c, "SELECT * FROM medicines WHERE lower(name)=lower(?)", (name,))
                new_meds += 1
            cur = c.execute("INSERT INTO batches(branch_id,medicine_id,batch,expiry,qty,mrp_p,cost_p,rack,received_at) VALUES(?,?,?,?,?,?,?,?,?)",
                            (h.branch, m["id"], r.get("batch", "")[:40], exp, qty, mrp, cost, r.get("rack", "").upper()[:12] or None, now_str()))
            c.execute("INSERT INTO stock_moves(at,branch_id,batch_id,change,reason,ref,user_id) VALUES(?,?,?,?,?,?,?)",
                      (now_str(), h.branch, cur.lastrowid, qty, "import", "opening stock", h.user["id"]))
            added += 1
        audit(c, h, "import.stock", f"{added} batches, {new_meds} new medicines, {len(errors)} errors")
        return {"added": added, "new_medicines": new_meds, "errors": errors[:50]}
    return in_tx(c, run)


# ---------------------------------------------------------------- backups
def make_backup(reason="manual"):
    from .core import db
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"mediassist-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{reason}.db")
    dst = sqlite3.connect(path)
    db().backup(dst)
    dst.close()
    return path


def prune_backups(keep_days):
    if not os.path.isdir(BACKUP_DIR):
        return
    cutoff = time.time() - keep_days * 86400
    for f in os.listdir(BACKUP_DIR):
        p = os.path.join(BACKUP_DIR, f)
        if f.endswith(".db") and os.path.getmtime(p) < cutoff:
            os.remove(p)


@route("GET", "/api/backups", "admin")
def api_backups(h, c, b, q):
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = [{"name": f, "size": os.path.getsize(os.path.join(BACKUP_DIR, f)),
            "at": datetime.fromtimestamp(os.path.getmtime(os.path.join(BACKUP_DIR, f))).strftime("%Y-%m-%d %H:%M")}
           for f in os.listdir(BACKUP_DIR) if f.endswith(".db")]
    return sorted(out, key=lambda x: x["at"], reverse=True)


@route("POST", "/api/backups", "admin")
def api_backup_now(h, c, b, q):
    p = make_backup("manual")
    audit(c, h, "backup.create", os.path.basename(p))
    return {"ok": True, "name": os.path.basename(p)}


# ---------------------------------------------------------------- DPDP: consent, export, erase
@route("POST", r"/api/patients/(\d+)/consent", "patients_write")
def api_consent(h, c, b, q, pid):
    need(one(c, "SELECT 1 FROM patients WHERE id=?", (int(pid),)), "Patient not found", 404)
    c.execute("UPDATE patients SET consent_at=?, consent_by=?, whatsapp_ok=? WHERE id=?",
              (now_str(), h.user["id"], 0 if b.get("whatsapp_ok") is False else 1, int(pid)))
    audit(c, h, "patient.consent", f"{pcode(int(pid))} whatsapp={'no' if b.get('whatsapp_ok') is False else 'yes'}")
    return {"ok": True}


@route("GET", r"/api/patients/(\d+)/export", "admin")
def api_patient_export(h, c, b, q, pid):
    pid = int(pid)
    p = one(c, "SELECT * FROM patients WHERE id=?", (pid,))
    need(p, "Patient not found", 404)
    out = {"patient": p}
    for t, col in (("visits", "patient_id"), ("problems", "patient_id"), ("vitals", "patient_id"), ("vaccinations", "patient_id"),
                   ("appointments", "patient_id"), ("lab_orders", "patient_id"), ("admissions", "patient_id"), ("invoices", "patient_id"),
                   ("bills", "patient_id"), ("documents", "patient_id"), ("claims", "patient_id")):
        out[t] = rows(c.execute(f"SELECT * FROM {t} WHERE {col}=?", (pid,)))
    c.execute("INSERT INTO data_requests(patient_id,kind,at,user_id,done_at) VALUES(?,?,?,?,?)", (pid, "export", now_str(), h.user["id"], now_str()))
    audit(c, h, "patient.export", pcode(pid))
    h.download = (f"{pcode(pid)}-records.json", json.dumps(out, indent=1, default=str), "application/json")
    return None


@route("POST", r"/api/patients/(\d+)/erase", "admin")
def api_patient_erase(h, c, b, q, pid):
    """DPDP erasure: removes identity and contact details. Clinical and billing records are kept,
    de-identified, because medical and tax law require retention."""
    pid = int(pid)
    p = one(c, "SELECT * FROM patients WHERE id=?", (pid,))
    need(p and not p["erased_at"], "Patient not found or already erased", 404)
    need(clean(b, "confirm") == pcode(pid), f"Type {pcode(pid)} to confirm")
    h1 = c.execute("SELECT 1 FROM bills bl JOIN bill_items bi ON bi.bill_id=bl.id JOIN medicines m ON m.id=bi.medicine_id "
                   "WHERE bl.patient_id=? AND m.schedule IN ('H1','X') AND bl.created_at>=?", (pid, add_days(today(), -3 * 365))).fetchone()
    need(not h1, "This patient bought Schedule H1/X medicines in the last 3 years. The law requires keeping their name in the "
                 "H1 register, so the record can't be erased yet. Note the request and erase after the retention period.")
    c.execute("UPDATE patients SET name=?, phone='0000000000', address=NULL, abha=NULL, dob=NULL, whatsapp_ok=0, erased_at=? WHERE id=?",
              (f"Erased {pcode(pid)}", now_str(), pid))
    c.execute("UPDATE bills SET customer=? WHERE patient_id=?", (f"Erased {pcode(pid)}", pid))
    tag = f"Erased {pcode(pid)}"
    c.execute("UPDATE messages SET to_addr='erased', body='[erased on patient request]' WHERE patient_id=?", (pid,))
    c.execute("UPDATE feedback SET comment=NULL WHERE patient_id=?", (pid,))
    c.execute("UPDATE appointments SET note=NULL WHERE patient_id=?", (pid,))
    c.execute("UPDATE portal_links SET revoked_at=? WHERE patient_id=? AND revoked_at IS NULL", (now_str(), pid))
    c.execute("UPDATE referrals SET to_doctor=NULL WHERE patient_id=?", (pid,))
    c.execute("UPDATE procedures SET consent_by=?, consent_witness=NULL WHERE patient_id=?", (tag, pid))
    c.execute("UPDATE documents SET filename=NULL, note=NULL WHERE patient_id=?", (pid,))
    c.execute("INSERT INTO data_requests(patient_id,kind,at,user_id,done_at,note) VALUES(?,?,?,?,?,?)",
              (pid, "erase", now_str(), h.user["id"], now_str(), clean(b, "reason", 200)))
    audit(c, h, "patient.erase", f"{pcode(pid)} {clean(b, 'reason', 200)}")
    return {"ok": True}
