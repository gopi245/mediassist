"""Laboratory: test catalogue with reference ranges, orders from OPD/IPD, sample collection,
result entry with automatic H/L/critical flags, verification, delivery to doctor and patient."""
from .core import (ApiError, P, R, as_int, audit, can, clean, get_settings, in_tx, need, need_branch, now_str, one, opt_num, pcode, qget, route, rows, rs, today)
from .lab_explain import interpret

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


def param_ranges(c, param_ids):
    out = {}
    if param_ids:
        for r in rows(c.execute(f"SELECT * FROM lab_ranges WHERE param_id IN ({','.join('?' * len(param_ids))})", list(param_ids))):
            out.setdefault(r["param_id"], []).append(r)
    return out


def pick_range(p, ranges, age, gender):
    """The normal range for this patient: the most specific sex/age range that fits, else the test's default."""
    fits = [r for r in ranges or [] if r["gender"] in ("", gender) and (age is None and r["age_from"] <= 18 < r["age_to"] or age is not None and r["age_from"] <= age < r["age_to"])]
    if fits:
        r = min(fits, key=lambda r: (r["gender"] == "", r["age_to"] - r["age_from"]))
        return r["low"], r["high"]
    return p["low"], p["high"]


def range_text(p, lo, hi):
    if p["ref_text"] and lo is None and hi is None:
        return p["ref_text"]
    return f"{lo:g} - {hi:g}" if lo is not None and hi is not None else (f"< {hi:g}" if hi is not None else f"> {lo:g}" if lo is not None else p["ref_text"] or "")


NORMAL_WORDS = {"negative", "neg", "-ve", "absent", "not seen", "nil", "none", "non-reactive", "nonreactive", "non reactive", "normal", "not detected",
                "nad", "within normal limits", "wnl", "clear"}


def norm_text(t):
    return " ".join((t or "").lower().replace("_", " ").split())


def flag_for(p, num, text, rng=None):
    lo, hi = rng if rng else (p["low"], p["high"])
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
    if lo is not None and num < lo:
        return "L"
    if hi is not None and num > hi:
        return "H"
    return "N"


def calc(formula, values):
    """Evaluate a lab formula like "{Total cholesterol} - {HDL} - {Triglycerides} / 5" safely (numbers, + - * / and brackets only).
    Returns None when a value it needs is missing or it divides by zero."""
    import ast
    import operator as op
    import re as _re
    names = _re.findall(r"\{([^}]+)\}", formula)
    if any(values.get(n) is None for n in names):
        return None
    expr = _re.sub(r"\{([^}]+)\}", lambda m: f"v{names.index(m.group(1))}", formula)
    ops = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.USub: op.neg, ast.UAdd: op.pos}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name) and _re.fullmatch(r"v\d+", n.id):
            return values[names[int(n.id[1:])]]
        if isinstance(n, ast.BinOp) and type(n.op) in ops:
            return ops[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in ops:
            return ops[type(n.op)](ev(n.operand))
        raise ValueError("Only numbers, + - * / and brackets are allowed in a formula")
    try:
        return round(ev(ast.parse(expr, mode="eval")), 2)
    except ZeroDivisionError:
        return None


def check_formula(formula, param_names):
    if not formula:
        return
    import re as _re
    for n in _re.findall(r"\{([^}]+)\}", formula):
        need(n in param_names, f"The formula uses {{{n}}}, which isn't a value in this test")
    try:
        calc(formula, {n: 1.0 for n in param_names})
    except (ValueError, SyntaxError) as e:
        raise ApiError(400, f"Formula: {e}")


def order_amount_p(c, oid):
    """What the ordered tests cost at today's rates (paise), and any test without a rate."""
    rs_ = rows(c.execute("SELECT t.name, s.id sid, s.rate_p FROM lab_order_items i JOIN lab_tests t ON t.id=i.test_id LEFT JOIN services s ON s.id=t.service_id "
                         "WHERE i.order_id=?", (oid,)))
    return sum(r["rate_p"] or 0 for r in rs_), [r["name"] for r in rs_ if not r["sid"]]


def pay_state(c, o):
    """Payment status of one lab order for every screen: paid, partial, due, unbilled, inpatient (on the IP bill), insurance."""
    if o["admission_id"]:
        return {"pay": "inpatient", "label": "On inpatient bill", "due": 0}
    inv = one(c, "SELECT * FROM invoices WHERE id=? AND cancelled_at IS NULL", (o["invoice_id"],)) if o["invoice_id"] else None
    if inv:
        from .m_billing import inv_state
        st = inv_state(c, inv)
        lab = {"paid": "Paid", "partial": "Part paid", "due": "Not paid", "insurance": "Insurance"}.get(st["status"], st["status"].title())
        return {"pay": st["status"], "label": lab, "due": R(st["due_p"]), "inv_no": inv["inv_no"], "invoice_id": inv["id"]}
    if o["status"] == "cancelled":
        return {"pay": "cancelled", "label": "Cancelled", "due": 0}
    amt, _ = order_amount_p(c, o["id"])
    return {"pay": "unbilled", "label": "Not paid", "due": R(amt)}


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
        rngs = param_ranges(c, [p["id"] for p in params])
        for p in params:
            r = res.get(p["id"])
            lo, hi = pick_range(p, rngs.get(p["id"]), o["age"], o["gender"])
            p.update(value=r["value"] if r else None, flag=r["flag"] if r else None, eff_low=lo, eff_high=hi,
                     range=(r and r["range_text"]) or range_text(p, lo, hi))
        o["tests"].append({"item_id": it["item_id"], "id": it["id"], "code": it["code"], "name": it["name"], "sample": it["sample"], "params": params})
    import json as _json
    o["interp"] = _json.loads(o["interpretation"]) if o["interpretation"] else None
    o["critical"] = any(p["flag"] in ("LL", "HH") for t in o["tests"] for p in t["params"])
    o["abnormal"] = sum(1 for t in o["tests"] for p in t["params"] if p["flag"] not in (None, "N"))
    inv = one(c, "SELECT * FROM invoices WHERE id=?", (o["invoice_id"],)) if o["invoice_id"] else None
    if inv and not inv["cancelled_at"]:
        from .m_billing import inv_state
        st = inv_state(c, inv)
        o["billing"] = {"inv_no": inv["inv_no"], "invoice_id": inv["id"], "at": inv["created_at"], "status": st["status"], "due": R(st["due_p"]), "total": R(inv["total_p"]), "kind": inv["kind"]}
    else:
        o["billing"] = None
    o["payment"] = pay_state(c, o)
    sent = one(c, "SELECT at, ok, channel FROM messages WHERE kind='lab_report' AND body LIKE ? ORDER BY id DESC LIMIT 1", (f"%LAB{o['id']}%",))
    o["sent"] = dict(sent) if sent else None
    o["ack"] = one(c, "SELECT u.name, o2.crit_ack_at FROM lab_orders o2 LEFT JOIN users u ON u.id=o2.crit_ack_by WHERE o2.id=? AND o2.crit_ack_at IS NOT NULL", (o["id"],))
    return o


@route("GET", "/api/lab/tests", "patients_read")
def api_tests(h, c, b, q):
    out = rows(c.execute("SELECT t.*, s.rate_p FROM lab_tests t LEFT JOIN services s ON s.id=t.service_id WHERE t.active=1 ORDER BY t.name"))
    for t in out:
        t["params"] = rows(c.execute("SELECT * FROM lab_params WHERE test_id=? ORDER BY sort,id", (t["id"],)))
    return out


@route("GET", "/api/lab/catalog", "lab_admin")
def api_catalog(h, c, b, q):
    out = rows(c.execute("SELECT t.*, s.rate_p FROM lab_tests t LEFT JOIN services s ON s.id=t.service_id ORDER BY t.active DESC, t.name"))
    params = rows(c.execute("SELECT * FROM lab_params ORDER BY test_id, sort, id"))
    rngs = param_ranges(c, [p["id"] for p in params])
    by_test = {}
    for p in params:
        p["ranges"] = rngs.get(p["id"], [])
        by_test.setdefault(p["test_id"], []).append(p)
    for t in out:
        t["rate"] = (t["rate_p"] or 0) / 100
        t["params"] = by_test.get(t["id"], [])
    return out


@route("POST", "/api/lab/catalog", "lab_admin")
def api_catalog_save(h, c, b, q):
    """Create or update one test with all its values and ranges, replacing what was there."""
    from .core import P
    code, name = clean(b, "code", 12).upper(), clean(b, "name", 120)
    need(code and name, "Enter the test code and name")
    rate = P(b.get("rate"), "rate")
    tid = int(b.get("id") or 0)
    params = b.get("params") or []
    need(params, "Add at least one value to report")
    names = [clean(p, "name", 60) for p in params]
    need(all(names) and len(set(names)) == len(names), "Each value needs a different name")

    def num(v, label):
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ApiError(400, f"{label} must be a number")

    def run():
        nonlocal tid
        dup = one(c, "SELECT id FROM lab_tests WHERE code=?", (code,))
        need(not dup or dup["id"] == tid, "That test code is already used")
        if tid:
            t = one(c, "SELECT * FROM lab_tests WHERE id=?", (tid,))
            need(t, "Test not found", 404)
            c.execute("UPDATE lab_tests SET code=?, name=?, sample=?, tat_hours=?, active=? WHERE id=?",
                      (code, name, clean(b, "sample", 60), opt_num(b.get("tat_hours"), int), 0 if b.get("active") is False else 1, tid))
            if t["service_id"]:
                c.execute("UPDATE services SET name=?, rate_p=? WHERE id=?", (f"Lab: {name}", rate, t["service_id"]))
        else:
            s = one(c, "SELECT id FROM services WHERE name=?", (f"Lab: {name}",))
            sid = s["id"] if s else c.execute("INSERT INTO services(name,cat,rate_p,gst_pct) VALUES(?,?,?,0)", (f"Lab: {name}", "Laboratory", rate)).lastrowid
            tid = c.execute("INSERT INTO lab_tests(code,name,sample,service_id,tat_hours) VALUES(?,?,?,?,?)",
                            (code, name, clean(b, "sample", 60), sid, opt_num(b.get("tat_hours"), int))).lastrowid
        keep = []
        for i, p in enumerate(params):
            nm = names[i]
            fields = (nm, clean(p, "unit", 20), num(p.get("low"), f"{nm} low"), num(p.get("high"), f"{nm} high"), num(p.get("crit_low"), f"{nm} critical low"),
                      num(p.get("crit_high"), f"{nm} critical high"), clean(p, "ref_text", 120) or None, i, clean(p, "formula", 200) or None)
            check_formula(fields[8], [n for n in names if n != nm])
            pid = int(p.get("id") or 0)
            if pid and one(c, "SELECT 1 FROM lab_params WHERE id=? AND test_id=?", (pid, tid)):
                c.execute("UPDATE lab_params SET name=?,unit=?,low=?,high=?,crit_low=?,crit_high=?,ref_text=?,sort=?,formula=? WHERE id=?", (*fields, pid))
            else:
                pid = c.execute("INSERT INTO lab_params(name,unit,low,high,crit_low,crit_high,ref_text,sort,formula,test_id) VALUES(?,?,?,?,?,?,?,?,?,?)", (*fields, tid)).lastrowid
            keep.append(pid)
            c.execute("DELETE FROM lab_ranges WHERE param_id=?", (pid,))
            for r in (p.get("ranges") or [])[:12]:
                g = clean(r, "gender", 10)
                need(g in ("", "Male", "Female"), "Range sex must be Any, Male or Female")
                af, at = num(r.get("age_from"), "Age from") or 0, num(r.get("age_to"), "Age to") or 200
                need(0 <= af < at, f"{nm}: 'age from' must be below 'age to'")
                c.execute("INSERT INTO lab_ranges(param_id,gender,age_from,age_to,low,high) VALUES(?,?,?,?,?,?)",
                          (pid, g, af, at, num(r.get("low"), f"{nm} range low"), num(r.get("high"), f"{nm} range high")))
        for old in rows(c.execute(f"SELECT id, name FROM lab_params WHERE test_id=? AND id NOT IN ({','.join('?' * len(keep))})", (tid, *keep))):
            need(not one(c, "SELECT 1 FROM lab_results WHERE param_id=?", (old["id"],)), f"{old['name']} has results on old reports, so it can't be removed. Rename it instead.")
            c.execute("DELETE FROM lab_ranges WHERE param_id=?", (old["id"],))
            c.execute("DELETE FROM lab_params WHERE id=?", (old["id"],))
        audit(c, h, "lab.catalog", f"{code} {name} {len(params)} values")
        return tid
    return {"ok": True, "id": in_tx(c, run)}


@route("POST", "/api/lab/orders", "any")
def api_order(h, c, b, q):
    need(can(h, "visit_create") or can(h, "lab"), "Not allowed", 403)   # walk-in orders by the lab bench too
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
           "WHERE i.order_id=o.id) tests, (SELECT inv_no FROM invoices i2 WHERE i2.id=o.invoice_id AND i2.cancelled_at IS NULL) inv_no "
           "FROM lab_orders o JOIN patients p ON p.id=o.patient_id LEFT JOIN users u ON u.id=o.doctor_id WHERE o.branch_id=?")
    args = [h.branch]
    if status == "open":
        sql += " AND o.status IN ('ordered','collected','resulted')"
    elif status in STATUSES:
        sql += " AND o.status=? AND o.created_at>=?"
        args += [status, qget(q, "since", today())]
    out = rows(c.execute(sql + " ORDER BY CASE o.priority WHEN 'stat' THEN 0 WHEN 'urgent' THEN 1 ELSE 2 END, o.id", args))
    for o in out:
        o["code"] = pcode(o["patient_id"])
        o["payment"] = pay_state(c, o)
    return out


@route("POST", r"/api/lab/orders/(\d+)/pay", "any")
def api_order_pay(h, c, b, q, oid):
    """Collect the money for a lab order and mark it paid. Bills exactly the ordered tests on a hospital invoice (so it is in
    receipts, GST and the day's cash closing), or takes the balance on the invoice already raised."""
    need(can(h, "lab_admin") or can(h, "hbilling"), "Only the lab in-charge or the billing desk can collect payment", 403)
    mode, ref = clean(b, "mode", 10) or "cash", clean(b, "ref", 40)
    need(mode in ("cash", "upi", "card"), "Invalid payment mode")
    need(mode == "cash" or ref, "Enter the UPI or card transaction reference")

    def run():
        o = one(c, "SELECT * FROM lab_orders WHERE id=? AND branch_id=?", (int(oid), h.branch))
        need(o, "Lab order not found at this branch", 404)
        need(o["status"] != "cancelled", "This order was cancelled")
        need(not o["admission_id"], "This patient is admitted: the tests go on the inpatient bill and are paid at discharge")
        inv = one(c, "SELECT * FROM invoices WHERE id=? AND cancelled_at IS NULL", (o["invoice_id"],)) if o["invoice_id"] else None
        if not inv:
            amt, no_rate = order_amount_p(c, o["id"])
            need(not no_rate, f"No price set for {', '.join(no_rate)}. Set it in Laboratory > Tests & ranges.")
            from .m_billing import create_invoice
            items = [{"service_id": r[0], "ref": f"LAB{o['id']}"} for r in c.execute(
                "SELECT t.service_id FROM lab_order_items i JOIN lab_tests t ON t.id=i.test_id WHERE i.order_id=?", (o["id"],))]
            inv = create_invoice(c, h, o["patient_id"], items, o["doctor_id"], o["visit_id"], None, "lab")
        from .m_billing import inv_state
        due = inv_state(c, inv)["due_p"]
        need(due > 0, f"Already paid ({inv['inv_no']})")
        amount = P(b.get("amount"), "amount") if b.get("amount") not in (None, "") else due
        need(0 < amount <= due, f"Amount must be between Rs 1 and {rs(due)}")
        c.execute("INSERT INTO payments(branch_id,invoice_id,at,mode,amount_p,ref,user_id,kind) VALUES(?,?,?,?,?,?,?,?)",
                  (inv["branch_id"], inv["id"], now_str(), mode, amount, ref, h.user["id"], "payment"))
        audit(c, h, "lab.pay", f"LAB{o['id']} {inv['inv_no']} {rs(amount)} {mode} {ref}")
        return dict(pay_state(c, dict(o, invoice_id=inv["id"])), collected=R(amount))
    return in_tx(c, run)


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
    pt = one(c, "SELECT age, gender FROM patients WHERE id=?", (o["patient_id"],))

    def save(it_id, p, text, num, rng):
        c.execute("INSERT INTO lab_results(order_item_id,param_id,value,num,flag,range_text) VALUES(?,?,?,?,?,?) ON CONFLICT(order_item_id,param_id) "
                  "DO UPDATE SET value=excluded.value, num=excluded.num, flag=excluded.flag, range_text=excluded.range_text",
                  (it_id, p["id"], text, num, flag_for(p, num, text, rng), range_text(p, *rng)))

    def run():
        n = 0
        for it in rows(c.execute("SELECT * FROM lab_order_items WHERE order_id=?", (o["id"],))):
            params = rows(c.execute("SELECT * FROM lab_params WHERE test_id=? ORDER BY sort, id", (it["test_id"],)))
            rngs = param_ranges(c, [p["id"] for p in params])
            rng = {p["id"]: pick_range(p, rngs.get(p["id"]), pt["age"], pt["gender"]) for p in params}
            for p in params:
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
                    need(p["low"] is None and p["high"] is None and not p["formula"], f"{p['name']} needs a number")
                save(it["id"], p, text, num, rng[p["id"]])
                n += 1
            # calculated values (LDL, globulin, MCV...) unless the technician typed one in
            nums = {r["name"]: r["num"] for r in rows(c.execute("SELECT lp.name, r.num FROM lab_results r JOIN lab_params lp ON lp.id=r.param_id WHERE r.order_item_id=?", (it["id"],)))}
            for p in params:
                if not p["formula"] or str(vals.get(f"{it['id']}:{p['id']}") or "").strip():
                    continue
                v = calc(p["formula"], nums)
                if v is None:
                    c.execute("DELETE FROM lab_results WHERE order_item_id=? AND param_id=?", (it["id"], p["id"]))
                else:
                    save(it["id"], p, f"{v:g}", v, rng[p["id"]])
                    nums[p["name"]] = v
        missing = c.execute("SELECT COUNT(*) FROM lab_order_items i JOIN lab_params p ON p.test_id=i.test_id LEFT JOIN lab_results r ON r.order_item_id=i.id AND r.param_id=p.id "
                            "WHERE i.order_id=? AND r.id IS NULL", (o["id"],)).fetchone()[0]
        if b.get("submit"):
            need(not missing, f"{missing} results are still empty")
            c.execute("UPDATE lab_orders SET status='resulted', resulted_at=?, resulted_by=? WHERE id=?", (now_str(), h.user["id"], o["id"]))
        audit(c, h, "lab.results", f"LAB{o['id']} {n} values{' submitted' if b.get('submit') else ''}")
        return {"ok": True, "missing": missing}
    out = in_tx(c, run)
    if b.get("submit"):
        draft_interpretation(c, o["id"])   # a draft for the verifier to review; never blocks results
    d = order_detail(c, o["id"])
    if b.get("submit"):
        save_interp(c, o["id"], interpret(d), reviewed=False)
        d = order_detail(c, o["id"])
    if d["critical"] and b.get("submit"):
        from .notify import notify_staff
        from .m_alerts import branch_doctors
        text = (f"CRITICAL lab result for {d['pname']} ({d['code']}), LAB{o['id']}: " +
                ", ".join(f"{p['name']} {p['value']} {p['unit'] or ''}" for t in d["tests"] for p in t["params"] if p["flag"] in ("LL", "HH")) +
                ". Acknowledge it in the app (Dashboard > Critical results).")
        for uid in ([d["doctor_id"]] if d["doctor_id"] else branch_doctors(c, o["branch_id"])):  # a walk-in order has no doctor: every doctor here is told
            notify_staff(c, uid, text)
        c.execute("UPDATE lab_orders SET crit_ack_at=NULL, crit_ack_by=NULL WHERE id=?", (o["id"],))
    return dict(out, critical=d["critical"])


def draft_interpretation(c, oid):
    """Best effort: a short AI interpretation for the verifier to review. Returns None when AI is off or fails."""
    s = get_settings(c)
    if s.get("lab_ai", "1") != "1" or not s.get("anthropic_api_key"):
        return None
    d = order_detail(c, oid)
    lines = [f"Patient: {d['age'] if d['age'] is not None else '?'} year old {d['gender'] or 'person'}."]
    for t in d["tests"]:
        for p in t["params"]:
            if p["value"] is not None:
                lines.append(f"{t['name']} - {p['name']}: {p['value']} {p['unit'] or ''} (normal {p['range'] or '-'}, flag {p['flag'] or 'N'})")
    try:
        from .m_assistant import ai_text
        txt = ai_text(c, "You are a pathologist writing the interpretation paragraph of a lab report in India. In two to four short sentences, say in plain "
                         "clinical language what the results show, connect related values, and say what deserves follow-up. Mention only what these values support: "
                         "no treatment advice and no speculation. No preamble.", "\n".join(lines), 1000)[:2000]
    except Exception:
        return None
    c.execute("UPDATE lab_orders SET clin_interpretation=? WHERE id=?", (txt, oid))
    return txt


@route("POST", r"/api/lab/orders/(\d+)/verify", "lab_verify")
def api_verify(h, c, b, q, oid):
    o = one(c, "SELECT * FROM lab_orders WHERE id=? AND branch_id=?", (int(oid), h.branch))
    need(o and o["status"] == "resulted", "Only resulted orders can be verified")
    if "clin_interpretation" in b:   # the verifier's edited (or cleared) interpretation is what goes on the report
        c.execute("UPDATE lab_orders SET clin_interpretation=? WHERE id=?", (clean(b, "clin_interpretation", 2000) or None, o["id"]))
    c.execute("UPDATE lab_orders SET status='verified', verified_at=?, verified_by=? WHERE id=?", (now_str(), h.user["id"], o["id"]))
    if not o["interpretation"]:
        save_interp(c, o["id"], interpret(order_detail(c, o["id"])), reviewed=False)
    c.execute("UPDATE lab_orders SET interp_reviewed_by=?, interp_reviewed_at=? WHERE id=?", (h.user["id"], now_str(), o["id"]))
    audit(c, h, "lab.verify", f"LAB{o['id']}" + (" with explanation for the patient" if one(c, "SELECT 1 FROM lab_orders WHERE id=? AND interp_patient=1", (o["id"],)) else ""))
    d = order_detail(c, o["id"])
    sent = None
    if b.get("send_patient", True) and d["whatsapp_ok"]:
        from .notify import send_patient
        lines = [f"{d['bname']}: {'AMENDED ' if d['amended_at'] else ''}lab report for {d['pname']} ({d['code']}), LAB{d['id']}"]
        for t in d["tests"]:
            lines.append(f"\n{t['name']}")
            for p in t["params"]:
                fl = {"H": " HIGH", "L": " LOW", "HH": " CRITICAL HIGH", "LL": " CRITICAL LOW", "A": " ABNORMAL"}.get(p["flag"], "")
                lines.append(f"  {p['name']}: {p['value']} {p['unit'] or ''}{fl} (normal {p['range'] or '-'})")
        if d["interp"] and d["interp_patient"]:
            lines.append("\nWhat this means (reviewed by your doctor):")
            for f in d["interp"]["findings"]:
                lines.append(f"- {f['text']}")
            lines.append(d["interp"]["summary"])
        lines.append("\nPlease show this report to your doctor. Results marked HIGH/LOW need review.")
        from .m_portal import link_for, link_line, pdf_url
        ll = link_line(c, d["patient_id"], h.user["id"])  # empty when the records link is switched off
        lines.append(ll)
        sent = send_patient(c, d["patient_id"], "lab_report", "\n".join(lines), media_url=pdf_url(c, link_for(c, d["patient_id"]), "lab", d["id"]) if ll else None)
    return {"ok": True, "sent": sent}


def save_interp(c, oid, interp, reviewed):
    import json as _json
    c.execute("UPDATE lab_orders SET interpretation=?, interp_source=?, interp_at=? WHERE id=?", (_json.dumps(interp), interp.get("source", "rules"), now_str(), oid))
    if not reviewed:
        c.execute("UPDATE lab_orders SET interp_reviewed_by=NULL, interp_reviewed_at=NULL WHERE id=?", (oid,))


@route("POST", r"/api/lab/orders/(\d+)/interpret", "any")
def api_interpret(h, c, b, q, oid):
    """Plain-language explanation of the results. {} regenerates the rule-based text; {ai: true} rewrites it with the
    model (needs an API key); {findings, summary} saves the doctor's edited wording; {patient: false} keeps it off
    the patient's report. Editing and the patient switch need lab_verify."""
    need(can(h, "lab") or can(h, "lab_verify"), "Not allowed", 403)
    o = one(c, "SELECT * FROM lab_orders WHERE id=? AND branch_id=?", (int(oid), h.branch))
    need(o and o["status"] in ("resulted", "verified"), "Enter and submit the results first")
    d = order_detail(c, o["id"])
    if "findings" in b or "summary" in b or "patient" in b:
        need(can(h, "lab_verify"), "Only the verifying doctor can edit the explanation", 403)
        cur = d["interp"] or interpret(d)
        if "findings" in b:
            by = {str(f.get("param", "")).lower(): clean(f, "text", 600) for f in (b.get("findings") or []) if isinstance(f, dict)}
            for f in cur["findings"]:
                if by.get(f["param"].lower()):
                    f["text"] = by[f["param"].lower()]
        if "summary" in b:
            cur["summary"] = clean(b, "summary", 1200) or cur["summary"]
        if "findings" in b or "summary" in b:
            cur["source"] = "doctor"
        save_interp(c, o["id"], cur, reviewed=o["status"] == "verified")
        if "patient" in b:
            c.execute("UPDATE lab_orders SET interp_patient=? WHERE id=?", (1 if b.get("patient") else 0, o["id"]))
        audit(c, h, "lab.interpret", f"LAB{o['id']} edited" + ("" if b.get("patient", True) else ", kept off the patient's report"))
        return order_detail(c, o["id"])["interp"]
    p = one(c, "SELECT age, gender, conditions FROM patients WHERE id=?", (o["patient_id"],))
    if b.get("ai"):
        from .lab_explain import ai_interpret
        interp = ai_interpret(c, d, dict(p))
    elif b.get("ai_text"):  # wording produced on the client (in-browser demo): same merge, same limits
        from .lab_explain import merge_ai
        interp = merge_ai(d, b["ai_text"] if isinstance(b["ai_text"], dict) else {})
    else:
        interp = interpret(d)
    save_interp(c, o["id"], interp, reviewed=False)
    if o["status"] == "verified":  # verified report: the verifying doctor's new wording counts as reviewed
        c.execute("UPDATE lab_orders SET interp_reviewed_by=?, interp_reviewed_at=? WHERE id=?", (h.user["id"], now_str(), o["id"]))
    audit(c, h, "lab.interpret", f"LAB{o['id']} {interp['source']}")
    return interp


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
