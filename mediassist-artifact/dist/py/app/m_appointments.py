"""Appointments and tokens: slots, staff and online booking, check-in to the OPD queue,
public token display data, reminders."""
import re
import threading
import time
from datetime import date, datetime, timedelta

from .core import (ApiError, add_days, as_int, audit, clean, get_settings, in_tx, need, need_branch, now_str, one, opt_num, pcode, qget,
                   route, rows, today, valid_day)


def opd_hours(s):
    out = []
    for part in (s.get("opd_hours") or "09:00-13:00,17:00-20:00").split(","):
        m = re.fullmatch(r"\s*(\d{2}):(\d{2})-(\d{2}):(\d{2})\s*", part)
        if m:
            out.append((int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])))
    return out


def free_slots(c, bid, doctor_id, day):
    s = get_settings(c)
    step = int(s.get("slot_minutes") or 10)
    taken = {r[0] for r in c.execute("SELECT slot FROM appointments WHERE branch_id=? AND doctor_id=? AND day=? AND status NOT IN ('cancelled','no_show')", (bid, doctor_id, day))}
    now = datetime.now()
    out = []
    for a, z in opd_hours(s):
        for t in range(a, z, step):
            hhmm = f"{t // 60:02d}:{t % 60:02d}"
            if hhmm in taken:
                continue
            if day == today() and (t < now.hour * 60 + now.minute):
                continue
            out.append(hhmm)
    return out


def book(c, h_user_id, bid, pid, doctor_id, day, slot, source, note=""):
    valid_day(day)
    need(day >= today(), "Choose today or a later date")
    need(day <= add_days(today(), 60), "Book at most 60 days ahead")
    doc = one(c, "SELECT * FROM users WHERE id=? AND role IN ('doctor','owner') AND active=1", (doctor_id,))
    need(doc, "Choose a doctor")
    if slot:
        need(re.fullmatch(r"\d{2}:\d{2}", slot), "Invalid time slot")
        need(slot in free_slots(c, bid, doctor_id, day), "That slot was just taken. Pick another time.")
    need(not one(c, "SELECT 1 FROM appointments WHERE patient_id=? AND doctor_id=? AND day=? AND status IN ('booked','checked_in')", (pid, doctor_id, day)),
         "This patient already has an appointment with this doctor on that day")
    token = c.execute("SELECT COALESCE(MAX(token),0)+1 FROM appointments WHERE branch_id=? AND doctor_id=? AND day=?", (bid, doctor_id, day)).fetchone()[0]
    cur = c.execute("INSERT INTO appointments(branch_id,patient_id,doctor_id,day,slot,token,status,source,created_at,created_by,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (bid, pid, doctor_id, day, slot or None, token, "booked", source, now_str(), h_user_id, note))
    return cur.lastrowid, token


@route("GET", "/api/appointments/slots", "appointments")
def api_slots(h, c, b, q):
    br = need_branch(h, c, "hospital")
    return free_slots(c, br["id"], as_int(qget(q, "doctor_id"), "doctor"), valid_day(qget(q, "day", today())))


@route("GET", "/api/appointments", "appointments")
def api_list(h, c, b, q):
    br = need_branch(h, c, "hospital")
    day = valid_day(qget(q, "day", today()))
    out = rows(c.execute("SELECT a.*, p.name pname, p.phone, p.age, p.gender, u.name dname FROM appointments a JOIN patients p ON p.id=a.patient_id "
                         "LEFT JOIN users u ON u.id=a.doctor_id WHERE a.branch_id=? AND a.day=? ORDER BY u.name, a.token", (br["id"], day)))
    for a in out:
        a["code"] = pcode(a["patient_id"])
    return out


@route("POST", "/api/appointments", "appointments")
def api_book(h, c, b, q):
    br = need_branch(h, c, "hospital")
    pid = as_int(b.get("patient_id"), "patient")
    need(one(c, "SELECT 1 FROM patients WHERE id=?", (pid,)), "Patient not found", 404)
    src = clean(b, "source", 10) or "phone"
    need(src in ("phone", "walkin", "followup"), "Unknown booking source")
    aid, token = in_tx(c, lambda: book(c, h.user["id"], br["id"], pid, as_int(b.get("doctor_id"), "doctor"), clean(b, "day", 10) or today(),
                                       clean(b, "slot", 5), src, clean(b, "note", 200)))
    audit(c, h, "appt.book", f"#{aid} {pcode(pid)} token {token}")
    return {"ok": True, "id": aid, "token": token}


@route("POST", r"/api/appointments/(\d+)/checkin", "visit_create")
def api_checkin(h, c, b, q, aid):
    a = one(c, "SELECT * FROM appointments WHERE id=? AND branch_id=?", (int(aid), h.branch))
    need(a and a["status"] == "booked", "Only booked appointments can be checked in")
    need(a["day"] == today(), "This appointment is not for today")
    from .m_clinical import create_visit

    def run():
        vid, level, why = create_visit(c, h, a["patient_id"], b, appointment_id=a["id"], doctor_id=a["doctor_id"])
        c.execute("UPDATE appointments SET status='checked_in', visit_id=? WHERE id=?", (vid, a["id"]))
        return vid, level, why
    vid, level, why = in_tx(c, run)
    audit(c, h, "appt.checkin", f"#{a['id']} token {a['token']} -> visit {vid}")
    from .m_alerts import on_visit
    on_visit(c, h, vid)
    return {"ok": True, "visit_id": vid, "triage": level, "reasons": why}


@route("POST", r"/api/appointments/(\d+)/status", "appointments")
def api_status(h, c, b, q, aid):
    st = clean(b, "status", 12)
    need(st in ("cancelled", "no_show", "booked"), "Status must be cancelled, no_show or booked")
    a = one(c, "SELECT * FROM appointments WHERE id=? AND branch_id=?", (int(aid), h.branch))
    need(a and a["status"] in ("booked", "no_show", "cancelled"), "This appointment can't be changed now")
    c.execute("UPDATE appointments SET status=? WHERE id=?", (st, a["id"]))
    audit(c, h, "appt.status", f"#{a['id']} {st}")
    return {"ok": True}


# ---------------------------------------------------------------- public: token screen and online booking
def public_branch(c, code):
    br = one(c, "SELECT * FROM branches WHERE code=? AND active=1 AND kind LIKE '%hospital%'", ((code or "").upper(),))
    need(br, "Unknown branch", 404)
    return br


@route("GET", "/api/public/tokens")
def api_tokens(h, c, b, q):
    """No patient names: token numbers and doctor names only."""
    br = public_branch(c, qget(q, "branch"))
    docs = {}
    for a in rows(c.execute("SELECT a.token, a.status, u.name dname, v.status vstatus FROM appointments a JOIN users u ON u.id=a.doctor_id "
                            "LEFT JOIN visits v ON v.id=a.visit_id WHERE a.branch_id=? AND a.day=? ORDER BY a.token", (br["id"], today()))):
        d = docs.setdefault(a["dname"], {"doctor": a["dname"], "now": None, "next": [], "done": 0})
        if a["status"] == "in_consult" or a["vstatus"] == "in_consult":
            d["now"] = a["token"]
        elif a["status"] == "checked_in":
            d["next"].append(a["token"])
        elif a["status"] == "done":
            d["done"] += 1
    return {"branch": br["name"], "time": datetime.now().strftime("%H:%M"), "doctors": [dict(d, next=d["next"][:5]) for d in docs.values()]}


@route("GET", "/api/public/booking")
def api_public_info(h, c, b, q):
    need(get_settings(c).get("online_booking") == "1", "Online booking is switched off", 403)
    br = public_branch(c, qget(q, "branch"))
    docs = rows(c.execute("SELECT id, name FROM users WHERE active=1 AND role='doctor' AND (branch_id IS NULL OR branch_id=?) ORDER BY name", (br["id"],)))
    day = qget(q, "day")
    out = {"branch": br["name"], "code": br["code"], "doctors": docs}
    if day and qget(q, "doctor_id"):
        out["slots"] = free_slots(c, br["id"], as_int(qget(q, "doctor_id"), "doctor"), valid_day(day))
    return out


_rate = {}
_rate_lock = threading.Lock()


def rate_limit(key, n=5, window=3600, msg="Too many bookings from this connection. Please call the hospital.", count=True):
    """Refuse once `key` has had n hits in `window` seconds. count=False only checks; the caller records the hit later."""
    now = time.time()
    with _rate_lock:
        if len(_rate) > 5000:  # forget quiet keys so the table can't grow without bound
            for k in [k for k, v in _rate.items() if not v or now - v[-1] > window]:
                del _rate[k]
        hits = [t for t in _rate.get(key, []) if now - t < window]
        need(len(hits) < n, msg, 429)
        if count:
            hits.append(now)
            _rate[key] = hits


@route("POST", "/api/public/book")
def api_public_book(h, c, b, q):
    need(get_settings(c).get("online_booking") == "1", "Online booking is switched off", 403)
    rate_limit(h.client_ip)
    br = public_branch(c, clean(b, "branch", 8))
    name, phone = clean(b, "name", 100), re.sub(r"\D", "", clean(b, "phone", 20))[-10:]
    need(name and len(phone) == 10, "Enter your name and 10-digit mobile number")
    need(b.get("consent"), "Please agree to the privacy notice to book")
    age = opt_num(b.get("age"), int, "age")

    def run():
        p = one(c, "SELECT * FROM patients WHERE phone=? AND lower(name)=lower(?) AND erased_at IS NULL", (phone, name))
        if not p:
            cur = c.execute("INSERT INTO patients(name,age,gender,phone,branch_id,created_at,consent_at,whatsapp_ok) VALUES(?,?,?,?,?,?,?,1)",
                            (name, age, clean(b, "gender", 10), phone, br["id"], now_str(), now_str()))
            pid = cur.lastrowid
        else:
            pid = p["id"]
        aid, token = book(c, None, br["id"], pid, as_int(b.get("doctor_id"), "doctor"), clean(b, "day", 10), clean(b, "slot", 5), "online", clean(b, "note", 200))
        c.execute("INSERT INTO audit(at,user_id,branch_id,action,detail) VALUES(?,?,?,?,?)", (now_str(), None, br["id"], "appt.online", f"#{aid} {pcode(pid)} token {token}"))
        return aid, token, pid
    aid, token, pid = in_tx(c, run)
    a = one(c, "SELECT a.*, u.name dname FROM appointments a JOIN users u ON u.id=a.doctor_id WHERE a.id=?", (aid,))
    from .notify import send_patient
    send_patient(c, pid, "booking", f"{br['name']}: your appointment with {a['dname']} is booked for {a['day']} at {a['slot'] or 'walk-in time'}. Token {token}. "
                                     "Please arrive 10 minutes early with any old reports.")
    from .m_alerts import on_booking
    on_booking(c, aid)
    return {"ok": True, "token": token, "day": a["day"], "slot": a["slot"], "doctor": a["dname"]}


def send_reminders(c):
    """Tomorrow's appointments and follow-ups. Called once a day by the scheduler."""
    from .notify import send_patient
    tmr, n = add_days(today(), 1), 0
    for a in rows(c.execute("SELECT a.*, u.name dname, br.name bname FROM appointments a JOIN users u ON u.id=a.doctor_id JOIN branches br ON br.id=a.branch_id "
                            "WHERE a.day=? AND a.status='booked' AND a.reminder_sent=0", (tmr,))):
        send_patient(c, a["patient_id"], "reminder", f"Reminder from {a['bname']}: appointment with {a['dname']} tomorrow ({a['day']}) at {a['slot'] or 'OPD hours'}. Token {a['token']}.")
        c.execute("UPDATE appointments SET reminder_sent=1 WHERE id=?", (a["id"],))
        n += 1
    s = get_settings(c)
    for v in rows(c.execute("SELECT v.*, u.name dname, br.name bname, br.code bcode FROM visits v JOIN users u ON u.id=v.doctor_id JOIN branches br ON br.id=v.branch_id "
                            "WHERE v.followup=? AND NOT EXISTS (SELECT 1 FROM appointments a WHERE a.patient_id=v.patient_id AND a.day=v.followup)", (tmr,))):
        link = f" Book a time: {s['public_url'].rstrip('/')}/book?branch={v['bcode']}" if s.get("public_url") else ""
        lang = (one(c, "SELECT lang FROM patients WHERE id=?", (v["patient_id"],)) or {"lang": None})["lang"] or "en"
        text = {"hi": f"{v['bname']}: {v['dname']} ने आपको कल ({v['followup']}) दोबारा बुलाया है ({v['diagnosis']}).",
                "te": f"{v['bname']}: {v['dname']} మిమ్మల్ని రేపు ({v['followup']}) మళ్ళీ రమ్మన్నారు ({v['diagnosis']}).",
                "ta": f"{v['bname']}: {v['dname']} உங்களை நாளை ({v['followup']}) மீண்டும் வரச் சொன்னார் ({v['diagnosis']})."}.get(
            lang, f"{v['bname']}: {v['dname']} asked to see you again tomorrow ({v['followup']}) for {v['diagnosis']}.")
        send_patient(c, v["patient_id"], "followup", text + link)
        n += 1
    return n
