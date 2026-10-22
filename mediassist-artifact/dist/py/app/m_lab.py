"""Laboratory: test catalogue with reference ranges, orders from OPD/IPD, sample collection,
result entry with automatic H/L/critical flags, verification, delivery to doctor and patient."""
from .core import (ApiError, as_int, audit, can, clean, in_tx, need, need_branch, now_str, one, opt_num, pcode, qget, route, rows, today)

STATUSES = ("ordered", "collected", "resulted", "verified", "cancelled")


def create_order(c, h, patient_id, test_ids, visit_id=None, admission_id=None, doctor_id=None, priority="routine", note=""):
    br = need_branch(h, c, "hospital")
    need(test_ids, "Choose at least one test")
    need(priority in ("routine", "urgent", "stat"), "Priority must be routine, urgent or STAT")
    for t in test_ids:
        need(one(c, "SELECT 1 FROM lab_tests WHERE id=? AND active=1", (t,)), "Unknown lab test", 404)
    cur = c.execute("INSERT INTO lab_orders(branch_id,patient_id,visit_id,admission_id,doctor_id,created_at,priority,status,note) VALUES(?,?,?,?,?,?,?,?,?)",
                    (br["id"], patient_id, visit_id, admission_id, doctor_id, now_str(), priority, "ordered", note))
    for t in dict.fromkeys(test_ids):
        c.execute("INSERT INTO lab_order_items(order_id,test_id) VALUES(?,?)", (cur.lastrowid, t))
    audit(c, h, "lab.order", f"LAB{cur.lastrowid} {pcode(patient_id)} {len(test_ids)} tests {priority}")
    return cur.lastrowid


NORMAL_WORDS = {"negative", "neg", "-ve", "absent", "not seen", "nil", "none", "non-reactive", "nonreactive", "non reactive", "normal", "not detected",
                "nad", "within normal limits", "wnl", "clear"}


def norm_text(t):
    return " ".join((t or "").lower().replace("_", " ").split())


def flag_for(p, num, text):
    if num is None:
        if p["ref_text"] and text:
            ref, val = norm_text(p["ref_text"]), norm_text(text)
            if val == ref or (ref in NORMAL_WORDS and val in NORMAL_WORDS):
                return "N"
            return "A"  # abnormal text result, e.g. "Positive" where "Negative" is normal
        return "N" if text else None
    if p["crit_low"] is not None and num < p["crit_low"]:
        return "LL"
    if p["crit_high"] is not None and num > p["crit_high"]:
        return "HH"
    if p["low"] is not None and num < p["low"]:
        return "L"
    if p["high"] is not None and num > p["high"]:
        return "H"
    return "N"


def order_detail(c, oid):
    o = one(c, "SELECT o.*, p.name pname, p.age, p.gender, p.phone, p.whatsapp_ok, u.name dname, br.name bname, br.address baddr, br.phone bphone, "
               "cu.name collected_name, ru.name resulted_name, vu.name verified_name, vu.reg_no verified_reg FROM lab_orders o JOIN patients p ON p.id=o.patient_id "
               "JOIN branches br ON br.id=o.branch_id LEFT JOIN users u ON u.id=o.doctor_id LEFT JOIN users cu ON cu.id=o.collected_by "
               "LEFT JOIN users ru ON ru.id=o.resulted_by LEFT JOIN users vu ON vu.id=o.verified_by WHERE o.id=?", (oid,))
    need(o, "Lab order not found", 404)
    o["code"] = pcode(o["patient_id"])
    o["tests"] = []
    for it in rows(c.execute("SELECT i.id item_id, t.* FROM lab_order_items i JOIN lab_tests t ON t.id=i.test_id WHERE i.order_id=?", (oid,))):
        params = rows(c.execute("SELECT * FROM lab_params WHERE test_id=? ORDER BY sort, id", (it["id"],)))
        res = {r["param_id"]: r for r in rows(c.execute("SELECT * FROM lab_results WHERE order_item_id=?", (it["item_id"],)))}
        for p in params:
            r = res.get(p["id"])
            p.update(value=r["value"] if r else None, flag=r["flag"] if r else None,
                     range=p["ref_text"] or (f"{p['low']:g} - {p['high']:g}" if p["low"] is not None and p["high"] is not None else ""))
        o["tests"].append({"item_id": it["item_id"], "id": it["id"], "code": it["code"], "name": it["name"], "sample": it["sample"], "params": params})
    o["critical"] = any(p["flag"] in ("LL", "HH") for t in o["tests"] for p in t["params"])
    o["abnormal"] = sum(1 for t in o["tests"] for p in t["params"] if p["flag"] not in (None, "N"))
    return o


@route("GET", "/api/lab/tests", "patients_read")
def api_tests(h, c, b, q):
    out = rows(c.execute("SELECT t.*, s.rate_p FROM lab_tests t LEFT JOIN services s ON s.id=t.service_id WHERE t.active=1 ORDER BY t.name"))
    for t in out:
        t["params"] = rows(c.execute("SELECT * FROM lab_params WHERE test_id=? ORDER BY sort,id", (t["id"],)))
    return out


@route("POST", "/api/lab/orders", "visit_create")
def api_order(h, c, b, q):
    pid = as_int(b.get("patient_id"), "patient")
    need(one(c, "SELECT 1 FROM patients WHERE id=?", (pid,)), "Patient not found", 404)
    tests = [as_int(t, "test") for t in (b.get("tests") or [])[:30]]
    oid = in_tx(c, lambda: create_order(c, h, pid, tests, opt_num(b.get("visit_id"), int), opt_num(b.get("admission_id"), int),
                                        opt_num(b.get("doctor_id"), int) or (h.user["id"] if h.user["role"] == "doctor" else None),
                                        clean(b, "priority", 10) or "routine", clean(b, "note", 300)))
    return {"ok": True, "id": oid}


@route("GET", "/api/lab/orders", "patients_read")
def api_orders(h, c, b, q):
    need_branch(h, c, "hospital")
    status = qget(q, "status", "open")
    sql = ("SELECT o.*, p.name pname, p.age, p.gender, u.name dname, (SELECT group_concat(t.name, ', ') FROM lab_order_items i JOIN lab_tests t ON t.id=i.test_id "
           "WHERE i.order_id=o.id) tests FROM lab_orders o JOIN patients p ON p.id=o.patient_id LEFT JOIN users u ON u.id=o.doctor_id WHERE o.branch_id=?")
    args = [h.branch]
    if status == "open":
        sql += " AND o.status IN ('ordered','collected','resulted')"
    elif status in STATUSES:
        sql += " AND o.status=? AND o.created_at>=?"
        args += [status, qget(q, "since", today())]
    out = rows(c.execute(sql + " ORDER BY CASE o.priority WHEN 'stat' THEN 0 WHEN 'urgent' THEN 1 ELSE 2 END, o.id", args))
    for o in out:
        o["code"] = pcode(o["patient_id"])
    return out


@route("GET", r"/api/lab/orders/(\d+)", "patients_read")
def api_order_get(h, c, b, q, oid):
    return order_detail(c, int(oid))


@route("POST", r"/api/lab/orders/(\d+)/collect", "lab")
def api_collect(h, c, b, q, oid):
    o = one(c, "SELECT * FROM lab_orders WHERE id=? AND branch_id=?", (int(oid), h.branch))
    need(o and o["status"] == "ordered", "Only new orders can be collected")
    c.execute("UPDATE lab_orders SET status='collected', collected_at=?, collected_by=? WHERE id=?", (now_str(), h.user["id"], o["id"]))
    audit(c, h, "lab.collect", f"LAB{o['id']}")
    return {"ok": True}


@route("POST", r"/api/lab/orders/(\d+)/results", "lab")
def api_results(h, c, b, q, oid):
    o = one(c, "SELECT * FROM lab_orders WHERE id=? AND branch_id=?", (int(oid), h.branch))
    need(o and o["status"] in ("collected", "resulted"), "Collect the sample before entering results")
    vals = b.get("values") or {}

    def run():
        n = 0
        for it in rows(c.execute("SELECT * FROM lab_order_items WHERE order_id=?", (o["id"],))):
            for p in rows(c.execute("SELECT * FROM lab_params WHERE test_id=?", (it["test_id"],))):
                key = f"{it['id']}:{p['id']}"
                if key not in vals:
                    continue
                text = str(vals[key] or "").strip()[:60]
                if not text:
                    c.execute("DELETE FROM lab_results WHERE order_item_id=? AND param_id=?", (it["id"], p["id"]))
                    continue
                try:
                    num = float(text)
                except ValueError:
                    num = None
                    need(p["low"] is None and p["high"] is None, f"{p['name']} needs a number")
                c.execute("INSERT INTO lab_results(order_item_id,param_id,value,num,flag) VALUES(?,?,?,?,?) ON CONFLICT(order_item_id,param_id) "
                          "DO UPDATE SET value=excluded.value, num=excluded.num, flag=excluded.flag", (it["id"], p["id"], text, num, flag_for(p, num, text)))
                n += 1
        missing = c.execute("SELECT COUNT(*) FROM lab_order_items i JOIN lab_params p ON p.test_id=i.test_id LEFT JOIN lab_results r ON r.order_item_id=i.id AND r.param_id=p.id "
                            "WHERE i.order_id=? AND r.id IS NULL", (o["id"],)).fetchone()[0]
        if b.get("submit"):
            need(not missing, f"{missing} results are still empty")
            c.execute("UPDATE lab_orders SET status='resulted', resulted_at=?, resulted_by=? WHERE id=?", (now_str(), h.user["id"], o["id"]))
        audit(c, h, "lab.results", f"LAB{o['id']} {n} values{' submitted' if b.get('submit') else ''}")
        return {"ok": True, "missing": missing}
    out = in_tx(c, run)
    d = order_detail(c, o["id"])
    if d["critical"] and b.get("submit"):
        from .notify import notify_staff
        notify_staff(c, d["doctor_id"], f"CRITICAL lab result for {d['pname']} ({d['code']}), LAB{o['id']}: " +
                     ", ".join(f"{p['name']} {p['value']} {p['unit'] or ''}" for t in d["tests"] for p in t["params"] if p["flag"] in ("LL", "HH")))
    return dict(out, critical=d["critical"])


@route("POST", r"/api/lab/orders/(\d+)/verify", "lab_verify")
def api_verify(h, c, b, q, oid):
    o = one(c, "SELECT * FROM lab_orders WHERE id=? AND branch_id=?", (int(oid), h.branch))
    need(o and o["status"] == "resulted", "Only resulted orders can be verified")
    c.execute("UPDATE lab_orders SET status='verified', verified_at=?, verified_by=? WHERE id=?", (now_str(), h.user["id"], o["id"]))
    audit(c, h, "lab.verify", f"LAB{o['id']}")
    d = order_detail(c, o["id"])
    sent = None
    if b.get("send_patient", True) and d["whatsapp_ok"]:
        from .notify import send_patient
        lines = [f"{d['bname']}: lab report for {d['pname']} ({d['code']}), LAB{d['id']}"]
        for t in d["tests"]:
            lines.append(f"\n{t['name']}")
            for p in t["params"]:
                fl = {"H": " HIGH", "L": " LOW", "HH": " CRITICAL HIGH", "LL": " CRITICAL LOW", "A": " ABNORMAL"}.get(p["flag"], "")
                lines.append(f"  {p['name']}: {p['value']} {p['unit'] or ''}{fl} (normal {p['range'] or '-'})")
        lines.append("\nPlease show this report to your doctor. Results marked HIGH/LOW need review.")
        from .m_portal import link_for, link_line, pdf_url
        ll = link_line(c, d["patient_id"], h.user["id"])  # empty when the records link is switched off
        lines.append(ll)
        sent = send_patient(c, d["patient_id"], "lab_report", "\n".join(lines), media_url=pdf_url(c, link_for(c, d["patient_id"]), "lab", d["id"]) if ll else None)
    return {"ok": True, "sent": sent}


@route("POST", r"/api/lab/orders/(\d+)/cancel", "lab")
def api_cancel(h, c, b, q, oid):
    o = one(c, "SELECT * FROM lab_orders WHERE id=? AND branch_id=?", (int(oid), h.branch))
    need(o and o["status"] in ("ordered", "collected"), "Only orders without results can be cancelled")
    reason = clean(b, "reason", 200)
    need(reason, "Enter a reason")
    c.execute("UPDATE lab_orders SET status='cancelled', note=? WHERE id=?", (reason, o["id"]))
    audit(c, h, "lab.cancel", f"LAB{o['id']} {reason}")
    return {"ok": True}


@route("GET", r"/api/patients/(\d+)/lab-trend", "patients_read")
def api_trend(h, c, b, q, pid):
    return rows(c.execute("SELECT lp.name, lp.unit, lp.low, lp.high, r.num, r.value, r.flag, o.created_at FROM lab_results r JOIN lab_params lp ON lp.id=r.param_id "
                          "JOIN lab_order_items i ON i.id=r.order_item_id JOIN lab_orders o ON o.id=i.order_id WHERE o.patient_id=? AND o.status='verified' "
                          "ORDER BY lp.name, o.created_at", (int(pid),)))
