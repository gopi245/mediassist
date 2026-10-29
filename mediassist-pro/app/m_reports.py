"""Dashboards, daily/branch/doctor/group reports, analytics, attendance, patient feedback,
downloads (sales, H1), and the background scheduler."""
import csv
import io
import secrets
import threading
import time
import traceback
from datetime import date, datetime, timedelta

from .core import (R, add_days, all_access, as_int, audit, branch_row, clean, db, get_settings, need, need_branch, now_str, one, pcode, qget,
                   reset_conn, route, rows, rs, set_setting, today, valid_day)


def bids_scope(c, h, bid=None):
    if bid:
        need(bid == h.branch or all_access(h.user), "Not your branch", 403)
        return [bid]
    if h.branch:
        return [h.branch]
    need(all_access(h.user), "Choose a branch")
    return [r[0] for r in c.execute("SELECT id FROM branches WHERE active=1 ORDER BY id")]


def rup(d):
    """Paise fields (x_p) -> rupees under the plain name (x)."""
    return {(k[:-2] if k.endswith("_p") else k): (R(v) if k.endswith("_p") else v) for k, v in d.items()}


def ph(n):
    return ",".join("?" * n)


def day_numbers(c, bids, day):
    p = ph(len(bids))
    seen = c.execute(f"SELECT COUNT(*) FROM visits WHERE branch_id IN ({p}) AND status='done' AND completed_at LIKE ? AND complaint IS NOT 'Discharge'", (*bids, day + "%")).fetchone()[0]
    new = c.execute(f"SELECT COUNT(*) FROM patients WHERE branch_id IN ({p}) AND created_at LIKE ?", (*bids, day + "%")).fetchone()[0]
    hosp = c.execute(f"SELECT COALESCE(SUM(total_p),0), COUNT(*) FROM invoices WHERE branch_id IN ({p}) AND cancelled_at IS NULL AND created_at LIKE ?", (*bids, day + "%")).fetchone()
    pharm = c.execute(f"SELECT COALESCE(SUM(total_p-returned_p),0), COUNT(*) FROM bills WHERE branch_id IN ({p}) AND created_at LIKE ?", (*bids, day + "%")).fetchone()
    coll = c.execute(f"SELECT COALESCE(SUM(amount_p),0) FROM payments WHERE branch_id IN ({p}) AND at LIKE ?", (*bids, day + "%")).fetchone()[0]
    pcoll = c.execute(f"SELECT COALESCE(SUM(total_p),0) FROM bills WHERE branch_id IN ({p}) AND created_at LIKE ? AND pay_mode<>'credit'", (*bids, day + "%")).fetchone()[0]
    return {"seen": seen, "new": new, "hosp_p": hosp[0], "invoices": hosp[1], "pharm_p": pharm[0], "bills": pharm[1], "collected_p": coll + pcoll}


def collections(c, bids, day, n):
    """What came in today, with counts: services by category, pharmacy bills, inpatient advances;
    then discounts, refunds and pharmacy returns; and the net cash actually kept."""
    p, d = ph(len(bids)), day + "%"
    lines = [dict(x) for x in rows(c.execute(
        f"SELECT COALESCE(NULLIF(ii.cat,''),'Other') cat, CAST(SUM(ii.qty) AS INTEGER) n, SUM(ii.amount_p) amount_p FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id "
        f"WHERE i.branch_id IN ({p}) AND i.cancelled_at IS NULL AND i.created_at LIKE ? GROUP BY 1 ORDER BY 3 DESC", (*bids, d)))]
    ph_ = c.execute(f"SELECT COUNT(*), COALESCE(SUM(total_p),0) FROM bills WHERE branch_id IN ({p}) AND created_at LIKE ?", (*bids, d)).fetchone()
    if ph_[0]:
        lines.append({"cat": "Pharmacy bills", "n": ph_[0], "amount_p": ph_[1]})
    dep = c.execute(f"SELECT COUNT(*), COALESCE(SUM(amount_p),0) FROM payments WHERE branch_id IN ({p}) AND kind='deposit' AND at LIKE ?", (*bids, d)).fetchone()
    if dep[0]:
        lines.append({"cat": "Inpatient advances", "n": dep[0], "amount_p": dep[1]})
    disc_b = c.execute(f"SELECT COUNT(*), COALESCE(SUM(discount_p),0) FROM bills WHERE branch_id IN ({p}) AND discount_p>0 AND created_at LIKE ?", (*bids, d)).fetchone()
    disc_i = c.execute(f"SELECT COUNT(*), COALESCE(SUM(i.discount_p + (SELECT COALESCE(SUM(disc_p),0) FROM invoice_items WHERE invoice_id=i.id)),0) FROM invoices i "
                       f"WHERE i.branch_id IN ({p}) AND i.cancelled_at IS NULL AND i.created_at LIKE ? AND (i.discount_p>0 OR EXISTS(SELECT 1 FROM invoice_items WHERE invoice_id=i.id AND disc_p>0))",
                       (*bids, d)).fetchone()
    ref = c.execute(f"SELECT COUNT(*), COALESCE(SUM(amount_p),0) FROM credit_notes WHERE branch_id IN ({p}) AND invoice_id IS NOT NULL AND at LIKE ?", (*bids, d)).fetchone()
    ret = c.execute(f"SELECT COUNT(*), COALESCE(SUM(amount_p),0), COALESCE(SUM(CASE WHEN mode='cash' THEN amount_p ELSE 0 END),0) FROM credit_notes "
                    f"WHERE branch_id IN ({p}) AND bill_id IS NOT NULL AND at LIKE ?", (*bids, d)).fetchone()
    less = [("discounts", disc_b[0] + disc_i[0], disc_b[1] + disc_i[1]), ("refunds", ref[0], ref[1]), ("pharmacy returns", ret[0], ret[1])]
    # refunds are already negative payments inside collected_p; pharmacy cash returns are not
    return {"lines": lines, "less": less, "net_p": n["collected_p"] - ret[2]}


def daily_report(c, bids, day, label):
    from .m_billing import inv_state
    n = day_numbers(c, bids, day)
    prev = day_numbers(c, bids, add_days(day, -1))
    week = [day_numbers(c, bids, add_days(day, -i)) for i in range(1, 8)]
    avg_rev = sum(w["hosp_p"] + w["pharm_p"] for w in week) / 7
    p = ph(len(bids))
    tri = {r[0]: r[1] for r in c.execute(f"SELECT triage, COUNT(*) FROM visits WHERE branch_id IN ({p}) AND created_at LIKE ? GROUP BY triage", (*bids, day + "%"))}
    adm = c.execute(f"SELECT COUNT(*) FROM admissions WHERE branch_id IN ({p}) AND admitted_at LIKE ?", (*bids, day + "%")).fetchone()[0]
    dis = c.execute(f"SELECT COUNT(*) FROM admissions WHERE branch_id IN ({p}) AND discharged_at LIKE ?", (*bids, day + "%")).fetchone()[0]
    inpat = c.execute(f"SELECT COUNT(*) FROM admissions WHERE branch_id IN ({p}) AND status='admitted'", bids).fetchone()[0]
    labs = c.execute(f"SELECT COUNT(*) FROM lab_orders WHERE branch_id IN ({p}) AND created_at LIKE ?", (*bids, day + "%")).fetchone()[0]
    dept = {r[0]: r[1] for r in c.execute(f"SELECT ii.cat, SUM(ii.amount_p) FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id WHERE i.branch_id IN ({p}) "
                                          f"AND i.cancelled_at IS NULL AND i.created_at LIKE ? GROUP BY ii.cat", (*bids, day + "%"))}
    if n["pharm_p"]:
        dept["Pharmacy"] = n["pharm_p"]
    modes = {}
    for r in c.execute(f"SELECT mode, SUM(amount_p) FROM payments WHERE branch_id IN ({p}) AND at LIKE ? GROUP BY mode", (*bids, day + "%")):
        modes[r[0]] = modes.get(r[0], 0) + r[1]
    for r in c.execute(f"SELECT pay_mode, SUM(total_p) FROM bills WHERE branch_id IN ({p}) AND created_at LIKE ? GROUP BY pay_mode", (*bids, day + "%")):
        modes[r[0]] = modes.get(r[0], 0) + r[1]
    docs = rows(c.execute(f"SELECT u.name, COUNT(DISTINCT v.id) seen, (SELECT COALESCE(SUM(total_p),0) FROM invoices i WHERE i.doctor_id=u.id AND i.cancelled_at IS NULL "
                          f"AND i.created_at LIKE ? AND i.branch_id IN ({p})) billed FROM users u LEFT JOIN visits v ON v.doctor_id=u.id AND v.status='done' AND v.completed_at LIKE ? "
                          f"AND v.branch_id IN ({p}) WHERE u.role IN ('doctor','owner') GROUP BY u.id HAVING seen>0 OR billed>0 ORDER BY seen DESC",
                          (day + "%", *bids, day + "%", *bids)))
    dues = 0
    for inv in rows(c.execute(f"SELECT * FROM invoices WHERE branch_id IN ({p}) AND cancelled_at IS NULL", bids)):
        dues += inv_state(c, inv)["due_p"]
    alerts = branch_alerts(c, bids, day)
    col = collections(c, bids, day, n)
    total = n["hosp_p"] + n["pharm_p"]
    pct = lambda a, b_: None if not b_ else round((a - b_) / b_ * 100)
    L = [f"*{label}: daily report*", datetime.fromisoformat(day).strftime("%a %d %b %Y"), "",
         f"*Patients:* {n['seen']} seen, {n['new']} new, {tri.get('critical', 0)} critical",
         f"*Inpatients:* {inpat} admitted now ({adm} in, {dis} out today) · Lab orders: {labs}",
         f"*Revenue:* {rs(total)}" + (f" ({'up' if pct(total, prev['hosp_p'] + prev['pharm_p']) >= 0 else 'down'} {abs(pct(total, prev['hosp_p'] + prev['pharm_p']))}% vs yesterday)"
                                      if pct(total, prev["hosp_p"] + prev["pharm_p"]) is not None else ""),
         f"  Hospital {rs(n['hosp_p'])} · Pharmacy {rs(n['pharm_p'])}",
         "", "*Collections:*"] + [f"  {x['cat']}: {x['n']} · {rs(x['amount_p'])}" for x in col["lines"]] + [
         "*Paid by:* " + " · ".join(f"{k.upper()} {rs(v)}" for k, v in sorted(modes.items()) if k != "credit" and v)
         + (f" (on credit, unpaid: {rs(modes['credit'])})" if modes.get("credit") else ""),
         "*Less:* " + " | ".join(f"{label} {cnt} · {rs(amt)}" for label, cnt, amt in col["less"] if cnt) if any(x[1] for x in col["less"]) else "*Less:* no discounts, refunds or returns",
         f"*Net collected:* {rs(col['net_p'])}",
         f"*Dues outstanding:* {rs(dues)}"]
    if docs:
        L += ["", "*Doctors:*"] + [f"  {d['name']}: {d['seen']} patients" + (f", {rs(d['billed'])} billed" if d["billed"] else "") for d in docs[:8]]
    if alerts:
        L += ["", "*Needs attention:*"] + [f"  - {a['text']}" for a in alerts[:10]]
    return {"day": day, "label": label, **rup(n), "total": R(total), "triage": tri, "admitted_now": inpat,
            "admissions": adm, "discharges": dis, "labs": labs, "dept": {k: R(v) for k, v in dept.items()}, "modes": {k: R(v) for k, v in modes.items()},
            "doctors": [dict(d, billed=R(d["billed"])) for d in docs], "dues": R(dues),
            "collections": {"lines": [dict(x, amount=R(x["amount_p"])) for x in col["lines"]], "less": [{"label": l_, "count": cnt, "amount": R(a_)} for l_, cnt, a_ in col["less"]],
                            "net": R(col["net_p"])}, "alerts": alerts, "prev_total": R(prev["hosp_p"] + prev["pharm_p"]),
            "prev_seen": prev["seen"], "avg7_total": R(avg_rev), "text": "\n".join(L)}


def branch_alerts(c, bids, day):
    from .m_pharmacy import days_left
    out = []
    for bid in bids:
        br = branch_row(c, bid)
        code = br["code"]
        if "pharmacy" in br["kind"]:
            exp = [b for b in rows(c.execute("SELECT * FROM batches WHERE branch_id=? AND qty>0", (bid,))) if days_left(b) < 0]
            if exp:
                out.append({"level": "high", "text": f"{code}: {len(exp)} expired batches on the shelf ({rs(sum(b['qty'] * b['cost_p'] for b in exp))} at cost)"})
            cold = one(c, "SELECT COUNT(*) n FROM temp_logs WHERE branch_id=? AND at LIKE ? AND ok=0", (bid, day + "%"))["n"]
            if cold:
                out.append({"level": "high", "text": f"{code}: fridge temperature out of 2-8°C {cold} times"})
            if not one(c, "SELECT 1 FROM temp_logs WHERE branch_id=? AND at LIKE ?", (bid, day + "%")) and one(c, "SELECT 1 FROM medicines WHERE cold_chain=1"):
                out.append({"level": "", "text": f"{code}: fridge temperature not logged today"})
        if "hospital" in br["kind"]:
            w = c.execute("SELECT COUNT(*) FROM visits WHERE branch_id=? AND status IN ('waiting','in_consult')", (bid,)).fetchone()[0]
            if w:
                out.append({"level": "info", "text": f"{code}: {w} patients waiting"})
            crit = c.execute("SELECT COUNT(*) FROM lab_orders o JOIN lab_order_items i ON i.order_id=o.id JOIN lab_results r ON r.order_item_id=i.id "
                             "WHERE o.branch_id=? AND o.status='resulted' AND r.flag IN ('LL','HH')", (bid,)).fetchone()[0]
            if crit:
                out.append({"level": "high", "text": f"{code}: {crit} critical lab values waiting for verification"})
            pend = c.execute("SELECT COUNT(*) FROM claims cl JOIN invoices i ON i.id=cl.invoice_id WHERE i.branch_id=? AND cl.status IN ('preauth','query') AND cl.created_at<?",
                             (bid, add_days(day, -7))).fetchone()[0]
            if pend:
                out.append({"level": "", "text": f"{code}: {pend} insurance claims pending over 7 days"})
        cl = one(c, "SELECT * FROM closings WHERE branch_id=? AND day=?", (bid, day))
        if cl and cl["diff_p"]:
            out.append({"level": "high", "text": f"{code}: cash drawer {'excess' if cl['diff_p'] > 0 else 'short'} {rs(abs(cl['diff_p']))}"})
    return out


@route("GET", "/api/dashboard", "any")
def api_dashboard(h, c, b, q):
    day = today()
    if not h.branch:
        need(all_access(h.user), "Choose a branch")
        bids = [r[0] for r in c.execute("SELECT id FROM branches WHERE active=1 ORDER BY id")]
        branches = []
        for bid in bids:
            br = branch_row(c, bid)
            n = day_numbers(c, [bid], day)
            branches.append({"id": bid, "code": br["code"], "name": br["name"], "kind": br["kind"], **rup(n),
                             "waiting": c.execute("SELECT COUNT(*) FROM visits WHERE branch_id=? AND status IN ('waiting','in_consult')", (bid,)).fetchone()[0],
                             "inpatients": c.execute("SELECT COUNT(*) FROM admissions WHERE branch_id=? AND status='admitted'", (bid,)).fetchone()[0],
                             "critical": c.execute("SELECT COUNT(*) FROM visits WHERE branch_id=? AND status='waiting' AND triage='critical'", (bid,)).fetchone()[0]})
        trend = []
        for i in range(13, -1, -1):
            d = add_days(day, -i)
            row = {"day": d}
            for bid in bids:
                n = day_numbers(c, [bid], d)
                row[str(bid)] = R(n["hosp_p"] + n["pharm_p"])
            trend.append(row)
        return {"mode": "org", "branches": branches, "trend": trend, "report": daily_report(c, bids, day, get_settings(c)["org_name"])}
    br = branch_row(c, h.branch)
    rep = daily_report(c, [h.branch], day, br["name"])
    crit = rows(c.execute("SELECT v.id, p.name, v.triage_reasons, v.created_at FROM visits v JOIN patients p ON p.id=v.patient_id WHERE v.branch_id=? AND v.status='waiting' AND v.triage='critical'", (h.branch,)))
    fups = rows(c.execute("SELECT p.name, p.phone, v.diagnosis FROM visits v JOIN patients p ON p.id=v.patient_id WHERE v.branch_id=? AND v.followup=?", (h.branch, day)))
    appts = c.execute("SELECT COUNT(*), SUM(status='booked'), SUM(status IN ('checked_in','in_consult','done')) FROM appointments WHERE branch_id=? AND day=?", (h.branch, day)).fetchone()
    beds = c.execute("SELECT COUNT(*), SUM(status='occupied') FROM beds WHERE branch_id=?", (h.branch,)).fetchone()
    lab = c.execute("SELECT SUM(status='ordered'), SUM(status='collected'), SUM(status='resulted') FROM lab_orders WHERE branch_id=?", (h.branch,)).fetchone()
    trend = [dict(day=add_days(day, -i), **rup(day_numbers(c, [h.branch], add_days(day, -i)))) for i in range(13, -1, -1)]
    return {"mode": "branch", "branch": br, "report": rep, "critical": crit, "followups": fups, "trend": trend,
            "appointments": {"total": appts[0], "booked": appts[1] or 0, "arrived": appts[2] or 0}, "beds": {"total": beds[0], "occupied": beds[1] or 0},
            "lab": {"ordered": lab[0] or 0, "collected": lab[1] or 0, "resulted": lab[2] or 0}}


# ---------------------------------------------------------------- reports
@route("GET", "/api/reports/daily", "reports")
def api_daily(h, c, b, q):
    bid = int(qget(q, "branch_id") or 0) or None
    bids = bids_scope(c, h, bid)
    label = branch_row(c, bids[0])["name"] if len(bids) == 1 else get_settings(c)["org_name"]
    return daily_report(c, bids, valid_day(qget(q, "date", today())), label)


def doctor_report(c, uid, day):
    d = one(c, "SELECT * FROM users WHERE id=?", (uid,))
    need(d, "Doctor not found", 404)
    vs = rows(c.execute("SELECT v.*, p.name pname, p.age, p.gender, p.phone, br.code bcode FROM visits v JOIN patients p ON p.id=v.patient_id JOIN branches br ON br.id=v.branch_id "
                        "WHERE v.doctor_id=? AND v.status='done' AND v.completed_at LIKE ? AND v.complaint IS NOT 'Discharge' ORDER BY v.completed_at", (uid, day + "%")))
    L = [f"{d['name']}: daily summary {day}", f"Patients seen: {len(vs)}", ""]
    for v in vs:
        rx = rows(c.execute("SELECT m.name, r.freq, r.days FROM rx_items r JOIN medicines m ON m.id=r.medicine_id WHERE visit_id=?", (v["id"],)))
        L.append(f"- {v['completed_at'][11:]} {v['bcode']} {pcode(v['patient_id'])} {v['pname']} {v['age'] or '?'}{(v['gender'] or ' ')[0]}"
                 f"{' [CRITICAL]' if v['triage'] == 'critical' else ''}: {v['diagnosis'] or '-'}{' (' + v['icd'] + ')' if v['icd'] else ''}")
        if rx:
            L.append("    Rx: " + "; ".join(f"{r['name']} {r['freq'] or ''} x{r['days'] or '?'}d" for r in rx))
    labs = rows(c.execute("SELECT o.id, p.name pname FROM lab_orders o JOIN patients p ON p.id=o.patient_id WHERE o.doctor_id=? AND o.status='resulted'", (uid,)))
    if labs:
        L += ["", f"Lab results waiting for your review: {len(labs)}"] + [f"- LAB{x['id']} {x['pname']}" for x in labs[:10]]
    inp = rows(c.execute("SELECT a.ip_no, p.name pname, a.diagnosis FROM admissions a JOIN patients p ON p.id=a.patient_id WHERE a.doctor_id=? AND a.status='admitted'", (uid,)))
    if inp:
        L += ["", f"Your inpatients ({len(inp)}):"] + [f"- {a['ip_no']} {a['pname']}: {a['diagnosis'] or '-'}" for a in inp]
    f = rows(c.execute("SELECT p.name, p.phone, v.diagnosis FROM visits v JOIN patients p ON p.id=v.patient_id WHERE v.doctor_id=? AND v.followup=?", (uid, add_days(day, 1))))
    L += ["", f"Follow-ups tomorrow ({len(f)}):"] + ([f"- {x['name']} {x['phone']} ({x['diagnosis'] or '-'})" for x in f] or ["- none"])
    return {"doctor": d["name"], "seen": len(vs), "text": "\n".join(L)}


@route("GET", "/api/reports/doctor", "reports")
def api_doc_report(h, c, b, q):
    uid = int(qget(q, "doctor_id") or 0) or h.user["id"]
    need(h.user["role"] != "doctor" or uid == h.user["id"], "Doctors can only see their own summary", 403)
    return doctor_report(c, uid, valid_day(qget(q, "date", today())))


@route("POST", "/api/reports/send", "reports")
def api_send(h, c, b, q):
    from .notify import deliver
    day = valid_day(clean(b, "date", 10) or today())
    kind = clean(b, "kind", 10)
    s = get_settings(c)
    if kind == "doctor":
        uid = int(b.get("doctor_id") or 0) or h.user["id"]
        need(h.user["role"] != "doctor" or uid == h.user["id"], "Doctors can only send their own summary", 403)
        u = one(c, "SELECT * FROM users WHERE id=?", (uid,))
        res = deliver(c, "doctor_report", doctor_report(c, uid, day)["text"], email=u["email"], whatsapp=u["whatsapp"])
    elif kind == "branch":
        br = need_branch(h, c)
        res = deliver(c, "daily_report", daily_report(c, [br["id"]], day, br["name"])["text"],
                      email=br["report_email"], whatsapp=br["report_whatsapp"], attachments=report_attachments(c, br, day))
    else:
        need(all_access(h.user) and h.user["role"] == "owner", "Owner only", 403)
        res = send_all(c, day)
    audit(c, h, "report.send", f"{kind} {day}")
    return res or [{"channel": "-", "ok": False, "detail": "No email or WhatsApp set for this recipient (Admin > Branches / Staff / Settings)"}]


def report_attachments(c, br, day):
    from .m_pharmacy import h1_csv, sales_csv
    if "pharmacy" not in br["kind"]:
        return ()
    att = [(f"sales-{br['code']}-{day}.csv", sales_csv(c, br["id"], day), "text/csv")]
    h1 = h1_csv(c, br["id"], day, day)
    if h1.count("\n") > 1:
        att.append((f"H1-{br['code']}-{day}.csv", h1, "text/csv"))
    return att


def send_all(c, day):
    from .m_watch import watch_lines
    from .notify import deliver
    res = []
    for br in rows(c.execute("SELECT * FROM branches WHERE active=1")):
        if br["report_email"] or br["report_whatsapp"]:
            res += deliver(c, "daily_report", daily_report(c, [br["id"]], day, br["name"])["text"] + "\n".join(watch_lines(c, [br["id"]], day)),
                           email=br["report_email"], whatsapp=br["report_whatsapp"],
                           attachments=report_attachments(c, br, day))
    for u in rows(c.execute("SELECT * FROM users WHERE active=1 AND role IN ('doctor','owner') AND (COALESCE(email,'')<>'' OR COALESCE(whatsapp,'')<>'')")):
        if one(c, "SELECT 1 FROM visits WHERE doctor_id=? AND completed_at LIKE ?", (u["id"], day + "%")):
            res += deliver(c, "doctor_report", doctor_report(c, u["id"], day)["text"], email=u["email"], whatsapp=u["whatsapp"])
    s = get_settings(c)
    if s.get("owner_email") or s.get("owner_whatsapp"):
        bids = [r[0] for r in c.execute("SELECT id FROM branches WHERE active=1")]
        res += deliver(c, "group_report", daily_report(c, bids, day, s["org_name"])["text"] + "\n".join(watch_lines(c, bids, day)),
                       email=s["owner_email"], whatsapp=s["owner_whatsapp"])
    return res


@route("GET", "/api/reports/followups", "patients_read")
def api_fu(h, c, b, q):
    from .m_clinical import api_followups
    return api_followups(h, c, b, q)


@route("GET", "/api/files/sales.csv", "reports")
def api_sales_csv(h, c, b, q):
    from .m_pharmacy import sales_csv
    br = need_branch(h, c, "pharmacy")
    day = valid_day(qget(q, "date", today()))
    h.download = (f"sales-{br['code']}-{day}.csv", sales_csv(c, br["id"], day), "text/csv")


@route("GET", "/api/files/h1.csv", "billing")
def api_h1_csv(h, c, b, q):
    from .m_pharmacy import h1_csv
    br = need_branch(h, c, "pharmacy")
    s, e = valid_day(qget(q, "from", today()[:8] + "01")), valid_day(qget(q, "to", today()))
    h.download = (f"H1-register-{br['code']}-{s}-to-{e}.csv", h1_csv(c, br["id"], s, e), "text/csv")


# ---------------------------------------------------------------- analytics
@route("GET", "/api/reports/revenue", "reports")
def api_revenue(h, c, b, q):
    """Revenue by service: ward and bed-wise, test-wise, department-wise, from hospital invoice lines plus pharmacy sales."""
    bids = bids_scope(c, h)
    days = as_int(qget(q, "days", "30"), "days", 1, 365)
    since = add_days(today(), -days)
    p = ph(len(bids))
    svc = rows(c.execute(f"SELECT COALESCE(ii.cat,'Other') cat, ii.name, COUNT(DISTINCT ii.invoice_id) bills, SUM(ii.qty) qty, SUM(ii.amount_p) rev_p "
                         f"FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id WHERE i.branch_id IN ({p}) AND i.created_at>=? AND i.cancelled_at IS NULL "
                         f"GROUP BY ii.cat, ii.name ORDER BY rev_p DESC", (*bids, since)))
    for x in svc:
        x["rev"] = R(x.pop("rev_p"))
    pharm = c.execute(f"SELECT COALESCE(SUM(total_p-returned_p),0), COUNT(*) FROM bills WHERE branch_id IN ({p}) AND created_at>=?", (*bids, since)).fetchone()
    return {"days": days, "since": since, "rows": svc, "pharmacy": {"rev": R(pharm[0]), "bills": pharm[1]},
            "total": R(sum(x["rev"] for x in svc) * 100 + pharm[0]) if svc or pharm[0] else 0}


@route("GET", "/api/analytics", "reports")
def api_analytics(h, c, b, q):
    bids = bids_scope(c, h)
    days = as_int(qget(q, "days", "30"), "days", 7, 365)
    since = add_days(today(), -days)
    p = ph(len(bids))
    heat = [[0] * 24 for _ in range(7)]
    for r in c.execute(f"SELECT created_at FROM visits WHERE branch_id IN ({p}) AND created_at>=?", (*bids, since)):
        dt = datetime.strptime(r[0], "%Y-%m-%d %H:%M")
        heat[dt.weekday()][dt.hour] += 1
    pts = c.execute(f"SELECT patient_id, COUNT(*) n FROM visits WHERE branch_id IN ({p}) AND created_at>=? AND status='done' GROUP BY patient_id", (*bids, since)).fetchall()
    repeat = sum(1 for r in pts if r[1] > 1)
    docs = rows(c.execute(f"SELECT u.name, COUNT(DISTINCT v.id) visits, COUNT(DISTINCT v.patient_id) patients FROM visits v JOIN users u ON u.id=v.doctor_id "
                          f"WHERE v.branch_id IN ({p}) AND v.status='done' AND v.completed_at>=? GROUP BY u.id ORDER BY visits DESC", (*bids, since)))
    for d in docs:
        d["revenue"] = R(c.execute(f"SELECT COALESCE(SUM(i.total_p),0) FROM invoices i JOIN users u ON u.id=i.doctor_id WHERE u.name=? AND i.branch_id IN ({p}) AND i.cancelled_at IS NULL AND i.created_at>=?",
                                   (d["name"], *bids, since)).fetchone()[0])
    dx = rows(c.execute(f"SELECT COALESCE(icd,'') icd, diagnosis, COUNT(*) n FROM visits WHERE branch_id IN ({p}) AND status='done' AND completed_at>=? AND diagnosis IS NOT NULL "
                        f"AND complaint IS NOT 'Discharge' GROUP BY lower(diagnosis) ORDER BY n DESC LIMIT 10", (*bids, since)))
    fb = c.execute(f"SELECT AVG(rating), COUNT(rating) FROM feedback WHERE branch_id IN ({p}) AND answered_at>=?", (*bids, since)).fetchone()
    noshow = c.execute(f"SELECT SUM(status='no_show'), COUNT(*) FROM appointments WHERE branch_id IN ({p}) AND day>=? AND day<?", (*bids, since, today())).fetchone()
    return {"days": days, "heat": heat, "patients": len(pts), "repeat": repeat, "repeat_pct": round(repeat / len(pts) * 100) if pts else 0,
            "doctors": docs, "diagnoses": dx, "feedback_avg": round(fb[0], 1) if fb[0] else None, "feedback_n": fb[1],
            "no_show_pct": round((noshow[0] or 0) / noshow[1] * 100) if noshow[1] else None}


# ---------------------------------------------------------------- attendance
@route("GET", "/api/attendance", "any")
def api_att(h, c, b, q):
    mine = one(c, "SELECT * FROM attendance WHERE user_id=? AND day=?", (h.user["id"], today()))
    out = {"me": mine}
    if h.user["role"] in ("owner", "manager", "accountant"):
        start, end = qget(q, "from", today()[:8] + "01"), qget(q, "to", today())
        sql = "SELECT a.*, u.name, u.role, br.code FROM attendance a JOIN users u ON u.id=a.user_id LEFT JOIN branches br ON br.id=a.branch_id WHERE a.day BETWEEN ? AND ?"
        args = [valid_day(start), valid_day(end)]
        if not all_access(h.user):
            sql += " AND a.branch_id=?"
            args.append(h.user["branch_id"])
        out["rows"] = rows(c.execute(sql + " ORDER BY a.day DESC, u.name", args))
    return out


@route("POST", "/api/attendance", "any")
def api_clock(h, c, b, q):
    mine = one(c, "SELECT * FROM attendance WHERE user_id=? AND day=?", (h.user["id"], today()))
    if not mine:
        c.execute("INSERT INTO attendance(user_id,branch_id,day,in_at) VALUES(?,?,?,?)", (h.user["id"], h.branch or h.user["branch_id"], today(), now_str()))
        return {"ok": True, "state": "in"}
    need(not mine["out_at"], "You have already clocked out today")
    c.execute("UPDATE attendance SET out_at=? WHERE id=?", (now_str(), mine["id"]))
    return {"ok": True, "state": "out"}


# ---------------------------------------------------------------- feedback
def queue_feedback(c, day):
    """Create a feedback link for each patient seen on `day` and send it once."""
    from .notify import send_patient
    s = get_settings(c)
    if not s.get("public_url"):
        return 0
    n = 0
    for v in rows(c.execute("SELECT v.*, br.name bname FROM visits v JOIN branches br ON br.id=v.branch_id WHERE v.status='done' AND v.completed_at LIKE ? "
                            "AND v.complaint IS NOT 'Discharge' AND NOT EXISTS (SELECT 1 FROM feedback f WHERE f.visit_id=v.id)", (day + "%",))):
        tok = secrets.token_urlsafe(12)
        c.execute("INSERT INTO feedback(token,branch_id,patient_id,visit_id,sent_at) VALUES(?,?,?,?,?)", (tok, v["branch_id"], v["patient_id"], v["id"], now_str()))
        send_patient(c, v["patient_id"], "feedback", f"Thank you for visiting {v['bname']}. How was your visit? Rate us in 10 seconds: {s['public_url'].rstrip('/')}/feedback?t={tok}")
        n += 1
    return n


@route("GET", "/api/public/feedback")
def api_fb_get(h, c, b, q):
    f = one(c, "SELECT f.*, br.name bname FROM feedback f JOIN branches br ON br.id=f.branch_id WHERE token=?", (qget(q, "t"),))
    need(f, "This feedback link is not valid", 404)
    return {"branch": f["bname"], "answered": bool(f["answered_at"])}


@route("POST", "/api/public/feedback")
def api_fb_post(h, c, b, q):
    f = one(c, "SELECT * FROM feedback WHERE token=?", (clean(b, "t", 40),))
    need(f, "This feedback link is not valid", 404)
    need(not f["answered_at"], "Thank you, we already have your feedback")
    rating = as_int(b.get("rating"), "rating", 1, 5)
    c.execute("UPDATE feedback SET rating=?, comment=?, answered_at=? WHERE id=?", (rating, clean(b, "comment", 1000), now_str(), f["id"]))
    if rating <= 2:
        from .notify import log_message
        log_message(c, "staff_alert", "Owner", "screen", f"Low rating ({rating}/5) from {pcode(f['patient_id'])}: {clean(b, 'comment', 300)}", True, "feedback")
    url = get_settings(c).get("google_review_url") or ""
    return {"ok": True, "review_url": url if rating >= 4 and url else None}   # happy patients are asked for a Google review


@route("GET", "/api/feedback", "reports")
def api_fb_list(h, c, b, q):
    bids = bids_scope(c, h)
    return rows(c.execute(f"SELECT f.*, p.name pname, br.code bcode FROM feedback f JOIN patients p ON p.id=f.patient_id JOIN branches br ON br.id=f.branch_id "
                          f"WHERE f.branch_id IN ({ph(len(bids))}) AND f.answered_at IS NOT NULL ORDER BY f.id DESC LIMIT 200", bids))


# ---------------------------------------------------------------- scheduler
def scheduler_tick():
    c = db()
    s = get_settings(c)
    now = datetime.now().strftime("%H:%M")
    if s.get("auto_send") == "1" and now >= (s.get("report_time") or "20:00") and s.get("last_auto") != today():
        set_setting(c, "last_auto", today())
        for r in send_all(c, today()):
            print(f"[{now_str()}] report -> {r['to']} {r['channel']}: {'OK' if r['ok'] else 'FAILED ' + r['detail']}")
        queue_feedback(c, today())
    if now >= (s.get("reminder_time") or "09:00") and s.get("last_reminders") != today():
        set_setting(c, "last_reminders", today())
        from .m_appointments import send_reminders
        n = send_reminders(c)
        if n:
            print(f"[{now_str()}] sent {n} appointment and follow-up reminders")
    from .m_alerts import scheduler_step
    for r in scheduler_step(c).get("briefings", []):
        print(f"[{now_str()}] morning briefing -> {r['to']} {r['channel']}: {'OK' if r['ok'] else 'FAILED ' + r['detail']}")
    from .m_weekly import send_weekly, weekly_due
    if s.get("auto_send") == "1" and weekly_due(s):
        set_setting(c, "last_weekly", today())
        for r in send_weekly(c):
            print(f"[{now_str()}] weekly pharmacy summary -> {r['to']} {r['channel']}: {'OK' if r['ok'] else 'FAILED ' + r['detail']}")
    if s.get("last_backup") != today():
        set_setting(c, "last_backup", today())
        from .m_admin import make_backup, prune_backups
        p = make_backup("daily")
        prune_backups(int(s.get("backup_keep_days") or 30))
        print(f"[{now_str()}] daily backup saved: {p}")


def scheduler_loop():
    while True:
        try:
            scheduler_tick()
        except Exception:
            traceback.print_exc()
        finally:
            reset_conn()
        time.sleep(30)
