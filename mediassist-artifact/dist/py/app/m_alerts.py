"""Keeping doctors in the loop without asking staff: a morning briefing on WhatsApp (today's appointments,
follow-ups, inpatients, reports to verify) and instant alerts as things happen (critical patient arrived, new
online booking, patient waiting too long, admission under them). Each alert type can be switched off in
Settings. Every alert also shows in the app's alert list, so it is seen even without WhatsApp."""
from datetime import datetime

from .core import R, add_days, all_access, audit, get_settings, need, now_str, one, pcode, route, rows, rs, set_setting, today

KINDS = {"critical": "Critical patient arrived", "booking": "New online booking", "wait": "Patient waiting too long", "admit": "Admission under you"}
WAIT_LIMIT = {"critical": 10, "other": 45}


def _on(c, kind):
    return get_settings(c).get("alert_" + kind, "1") == "1"


def branch_doctors(c, bid):
    return [r["id"] for r in rows(c.execute("SELECT id FROM users WHERE active=1 AND role='doctor' AND (branch_id=? OR branch_id IS NULL)", (bid,)))]


def alert(c, kind, uids, text, skip=None):
    """Send `text` to each doctor in `uids` (not to the person who caused it). Returns how many were alerted."""
    if not _on(c, kind):
        return 0
    from .notify import notify_staff
    n = 0
    for uid in dict.fromkeys(u for u in uids if u and u != skip):
        notify_staff(c, uid, text)
        n += 1
    return n


# ---------------------------------------------------------------- hooks (called after the record is saved)
def on_visit(c, h, vid):
    v = one(c, "SELECT v.*, p.name pname, p.age, p.gender, br.name bname FROM visits v JOIN patients p ON p.id=v.patient_id JOIN branches br ON br.id=v.branch_id WHERE v.id=?", (vid,))
    if not v or v["triage"] != "critical":
        return 0
    to = [v["doctor_id"]] if v["doctor_id"] else branch_doctors(c, v["branch_id"])
    return alert(c, "critical", to, f"CRITICAL patient at {v['bname']} OPD: {v['pname']} ({pcode(v['patient_id'])}, {v['age'] or '?'}{(v['gender'] or ' ')[0]}). "
                                    f"{v['complaint'] or ''}. Why: {v['triage_reasons'] or 'vital signs'}. Arrived {v['created_at'][11:16]}.", skip=h.user["id"] if h else None)


def on_booking(c, aid):
    a = one(c, "SELECT a.*, p.name pname, br.name bname FROM appointments a JOIN patients p ON p.id=a.patient_id JOIN branches br ON br.id=a.branch_id WHERE a.id=?", (aid,))
    if not a:
        return 0
    when = "today" if a["day"] == today() else "tomorrow" if a["day"] == add_days(today(), 1) else a["day"]
    return alert(c, "booking", [a["doctor_id"]], f"New online booking at {a['bname']}: {a['pname']}, {when} at {a['slot'] or 'walk-in time'}, token {a['token']}."
                                                 + (f" Note: {a['note']}" if a["note"] else ""))


def on_admit(c, h, aid):
    a = one(c, "SELECT a.*, p.name pname, b.ward, b.room, b.number bed, b.ac, u.name dname, br.name bname FROM admissions a JOIN patients p ON p.id=a.patient_id "
               "LEFT JOIN beds b ON b.id=a.bed_id LEFT JOIN users u ON u.id=a.doctor_id JOIN branches br ON br.id=a.branch_id WHERE a.id=?", (aid,))
    if not a:
        return 0
    n = 0
    s = get_settings(c)
    if s.get("alert_admit_owner", "1") == "1" and (s.get("owner_whatsapp") or s.get("owner_email")):
        from .notify import deliver
        deliver(c, "admit_alert", f"New admission at {a['bname']}: {a['pname']} ({pcode(a['patient_id'])}, {a['ip_no']}), "
                                  f"{a['ward'] or ''}{' room ' + a['room'] if a['room'] else ''} bed {a['bed'] or '-'}{' (AC)' if a['ac'] else ''}"
                                  f"{', Dr ' + a['dname'] if a['dname'] else ''}. {a['reason'] or a['diagnosis'] or ''}",
                email=s.get("owner_email"), whatsapp=s.get("owner_whatsapp"), subject="New admission")
        n += 1
    if a["doctor_id"]:
        n += alert(c, "admit", [a["doctor_id"]], f"Admitted under you: {a['pname']} ({a['ip_no']}), bed {a['ward'] or ''} {a['bed'] or ''}. {a['reason'] or a['diagnosis'] or ''}",
                   skip=h.user["id"] if h else None)
    return n


def check_waits(c, now=None):
    """Scheduler: tell the doctor once when a patient has waited too long (10 min for critical, 45 for others)."""
    if not _on(c, "wait"):
        return 0
    now, n = now or datetime.now(), 0
    for v in rows(c.execute("SELECT v.*, p.name pname, br.name bname FROM visits v JOIN patients p ON p.id=v.patient_id JOIN branches br ON br.id=v.branch_id "
                            "WHERE v.status='waiting' AND v.wait_alerted=0 AND v.created_at LIKE ?", (today() + "%",))):
        mins = int((now - datetime.strptime(v["created_at"][:16], "%Y-%m-%d %H:%M")).total_seconds() // 60)
        if mins < WAIT_LIMIT["critical" if v["triage"] == "critical" else "other"]:
            continue
        c.execute("UPDATE visits SET wait_alerted=1 WHERE id=?", (v["id"],))
        to = [v["doctor_id"]] if v["doctor_id"] else branch_doctors(c, v["branch_id"])
        n += alert(c, "wait", to, f"{v['pname']} ({pcode(v['patient_id'])}) has been waiting {mins} minutes at {v['bname']}"
                                  + (" and is CRITICAL" if v["triage"] == "critical" else "") + f". Complaint: {v['complaint'] or '-'}.")
    return n


# ---------------------------------------------------------------- morning briefing
def doctor_briefing(c, uid, day=None):
    day = day or today()
    u = one(c, "SELECT u.*, br.name bname FROM users u LEFT JOIN branches br ON br.id=u.branch_id WHERE u.id=?", (uid,))
    need(u, "User not found", 404)
    ap = rows(c.execute("SELECT * FROM appointments WHERE doctor_id=? AND day=? AND status NOT IN ('cancelled','no_show') ORDER BY slot", (uid, day)))
    fu = c.execute("SELECT COUNT(*) FROM visits WHERE doctor_id=? AND followup=? AND status='done'", (uid, day)).fetchone()[0]
    ipd = rows(c.execute("SELECT a.id FROM admissions a WHERE a.doctor_id=? AND a.status='admitted'", (uid,)))
    rounds = sum(1 for a in ipd if not c.execute("SELECT 1 FROM ipd_notes WHERE admission_id=? AND kind='round' AND at LIKE ?", (a["id"], day + "%")).fetchone())
    verify = c.execute("SELECT COUNT(*) FROM lab_orders WHERE doctor_id=? AND status='resulted'", (uid,)).fetchone()[0]
    y = add_days(day, -1)
    seen = c.execute("SELECT COUNT(*) FROM visits WHERE doctor_id=? AND status='done' AND completed_at LIKE ? AND complaint IS NOT 'Discharge'", (uid, y + "%")).fetchone()[0]
    billed = c.execute("SELECT COALESCE(SUM(total_p),0) FROM invoices WHERE doctor_id=? AND cancelled_at IS NULL AND created_at LIKE ?", (uid, y + "%")).fetchone()[0]
    first = next((a["slot"] for a in ap if a["slot"]), None)
    online = sum(1 for a in ap if a["source"] == "online")
    lines = [f"Good morning {u['name']}" + (f" ({u['bname']})" if u["bname"] else "") + f", {datetime.fromisoformat(day):%a %d %b}:",
             f"- {len(ap)} appointment{'s' if len(ap) != 1 else ''}" + (f", first at {first}" if first else "") + (f" ({online} booked online)" if online else "")
             if ap else "- No appointments booked yet",
             f"- {fu} follow-up{'s' if fu != 1 else ''} due today" if fu else None,
             f"- {len(ipd)} inpatient{'s' if len(ipd) != 1 else ''} under you" + (f", {rounds} round{'s' if rounds != 1 else ''} to do" if rounds else "") if ipd else None,
             f"- {verify} lab report{'s' if verify != 1 else ''} waiting for your verification" if verify else None,
             f"Yesterday: {seen} patient{'s' if seen != 1 else ''} seen" + (f", {rs(billed)} billed" if billed else "") + "."]
    return {"to": u["name"], "appointments": len(ap), "first": first, "online": online, "followups": fu, "inpatients": len(ipd), "rounds": rounds,
            "verify": verify, "seen_yesterday": seen, "billed_yesterday": R(billed), "text": "\n".join(x for x in lines if x)}


def owner_briefing(c, day=None):
    day = day or today()
    from .m_reports import collections, day_numbers
    s = get_settings(c)
    y = add_days(day, -1)
    bids = [r[0] for r in c.execute("SELECT id FROM branches WHERE active=1 ORDER BY id")]
    lines = [f"Good morning. {s.get('org_name') or 'Your group'}, {datetime.fromisoformat(day):%a %d %b}:"]
    for br in rows(c.execute("SELECT * FROM branches WHERE active=1 AND kind LIKE '%hospital%' ORDER BY id")):
        ap = c.execute("SELECT COUNT(*) FROM appointments WHERE branch_id=? AND day=? AND status NOT IN ('cancelled','no_show')", (br["id"], day)).fetchone()[0]
        inp = c.execute("SELECT COUNT(*) FROM admissions WHERE branch_id=? AND status='admitted'", (br["id"],)).fetchone()[0]
        free = c.execute("SELECT COUNT(*) FROM beds WHERE branch_id=? AND status='free'", (br["id"],)).fetchone()[0]
        pl = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
        lines.append(f"- {br['name']}: {pl(ap, 'appointment')}, {pl(inp, 'inpatient')}, {pl(free, 'bed')} free")
    n = day_numbers(c, bids, y)
    col = collections(c, bids, y, n)
    lines.append(f"Yesterday: {n['seen']} patients seen, revenue {rs(n['hosp_p'] + n['pharm_p'])}, net collected {rs(col['net_p'])}.")
    from .m_watch import watch
    w = watch(c, bids, y, y)
    if w["flagged"]:
        lines.append(f"Staff watch: {w['flagged']} flagged item{'s' if w['flagged'] != 1 else ''} yesterday ({w['high']} need a closer look). Open Reports > Staff watch.")
    return {"to": "Owner", "text": "\n".join(lines)}


def send_briefings(c, day=None):
    from .notify import deliver
    res = []
    for u in rows(c.execute("SELECT * FROM users WHERE active=1 AND role='doctor' AND (COALESCE(whatsapp,'')<>'' OR COALESCE(email,'')<>'')")):
        res += deliver(c, "briefing", doctor_briefing(c, u["id"], day)["text"], email=u["email"], whatsapp=u["whatsapp"], subject="Your day at a glance")
    s = get_settings(c)
    if s.get("owner_email") or s.get("owner_whatsapp"):
        res += deliver(c, "briefing", owner_briefing(c, day)["text"], email=s.get("owner_email"), whatsapp=s.get("owner_whatsapp"), subject="Good morning: today at a glance")
    return res


def briefing_due(s, now=None):
    now = now or datetime.now()
    return s.get("briefing_on", "1") == "1" and now.strftime("%H:%M") >= (s.get("briefing_time") or "08:00") and s.get("last_briefing") != now.strftime("%Y-%m-%d")


def scheduler_step(c):
    s = get_settings(c)
    out = {"waits": check_waits(c)}
    if briefing_due(s):
        set_setting(c, "last_briefing", today())
        out["briefings"] = send_briefings(c)
    return out


@route("GET", "/api/briefing", "any")
def api_briefing(h, c, b, q):
    """This morning's briefing for the signed-in doctor, or the group briefing for the owner."""
    if h.user["role"] == "doctor":
        return doctor_briefing(c, h.user["id"])
    need(all_access(h.user) or h.user["role"] == "manager", "Briefings are for doctors and owners", 403)
    return owner_briefing(c)


@route("POST", "/api/briefing/send", "admin")
def api_briefing_send(h, c, b, q):
    res = send_briefings(c)
    audit(c, h, "briefing.send", f"{len(res)} messages")
    return {"ok": True, "sent": res, "at": now_str()}
