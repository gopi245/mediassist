"""Hospital billing: service rates, invoices (OPD, lab, IPD), payments and dues, refunds via
credit notes, insurance/TPA claims with status history, day-end cash closing."""
import sqlite3
from datetime import date

from .core import (ApiError, P, R, add_days, all_access, as_int, audit, can, clean, in_tx, need, need_branch, now_str, one, opt_num, pcode,
                   qget, route, rows, rs, today, valid_day)

MODES = ("cash", "upi", "card", "insurance")
CLAIM_FLOW = {"preauth": ("query", "approved", "rejected"), "query": ("preauth", "approved", "rejected"), "approved": ("settled", "rejected", "query"),
              "rejected": ("query",), "settled": ()}


def paid_p(c, inv_id):
    return c.execute("SELECT COALESCE(SUM(amount_p),0) FROM payments WHERE invoice_id=?", (inv_id,)).fetchone()[0]


def refunded_p(c, inv_id):
    return c.execute("SELECT COALESCE(SUM(amount_p),0) FROM credit_notes WHERE invoice_id=?", (inv_id,)).fetchone()[0]


def claim_open_p(c, inv_id):
    r = one(c, "SELECT * FROM claims WHERE invoice_id=? AND status IN ('preauth','query','approved') ORDER BY id DESC", (inv_id,))
    return (r["approved_p"] or r["requested_p"]) if r else 0


def inv_state(c, inv):
    # refunds are stored as negative payments and also reduce the invoice total
    paid, ref = paid_p(c, inv["id"]), refunded_p(c, inv["id"])
    due = max(0, inv["total_p"] - paid)
    ins = claim_open_p(c, inv["id"])
    if inv["cancelled_at"]:
        st = "cancelled"
    elif due == 0:
        st = "paid"
    elif ins:
        st = "insurance"
    else:
        st = "partial" if paid else "due"
    return {"paid_p": paid, "due_p": due, "excess_p": max(0, paid - inv["total_p"]), "patient_due_p": max(0, due - ins), "insurance_p": ins, "refunded_p": ref, "status": st}


def create_invoice(c, h, pid, items, doctor_id=None, visit_id=None, admission_id=None, kind="opd", discount_p=0, notes=""):
    br = need_branch(h, c, "hospital")
    need(items, "Add at least one service")
    lines, sub, gst = [], 0, 0
    for it in items:
        s = one(c, "SELECT * FROM services WHERE id=?", (it["service_id"],)) if it.get("service_id") else None
        name = it.get("name") or (s["name"] if s else None)
        need(name, "Unknown service")
        qty = float(it.get("qty") or 1)
        need(0 < qty <= 1000, f"Check the quantity for {name}")
        rate = int(it["rate_p"]) if it.get("rate_p") is not None else (s["rate_p"] if s else 0)
        disc = min(int(it.get("disc_p") or 0), round(qty * rate))
        gpct = s["gst_pct"] if s else 0
        net = round(qty * rate) - disc
        g = round(net * gpct / 100)
        lines.append((it.get("service_id"), name, it.get("cat") or (s["cat"] if s else "Other"), qty, rate, disc, gpct, net + g, it.get("ref")))
        sub += net + g
        gst += g
    discount_p = min(discount_p, sub)
    n = c.execute("SELECT COUNT(*) FROM invoices WHERE branch_id=?", (br["id"],)).fetchone()[0] + 1
    inv_no = f"{br['code']}/{'IP' if kind == 'ipd' else 'H'}/{n:05d}"
    while one(c, "SELECT 1 FROM invoices WHERE inv_no=?", (inv_no,)):
        n += 1
        inv_no = f"{br['code']}/{'IP' if kind == 'ipd' else 'H'}/{n:05d}"
    cur = c.execute("INSERT INTO invoices(branch_id,inv_no,patient_id,visit_id,admission_id,doctor_id,created_at,user_id,kind,sub_p,discount_p,gst_p,total_p,notes) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (br["id"], inv_no, pid, visit_id, admission_id, doctor_id, now_str(), h.user["id"], kind, sub, discount_p, gst, sub - discount_p, notes))
    for ln in lines:
        c.execute("INSERT INTO invoice_items(invoice_id,service_id,name,cat,qty,rate_p,disc_p,gst_pct,amount_p,ref) VALUES(?,?,?,?,?,?,?,?,?,?)", (cur.lastrowid, *ln))
        if ln[8] and str(ln[8]).startswith("LAB"):
            c.execute("UPDATE lab_orders SET invoice_id=? WHERE id=?", (cur.lastrowid, int(str(ln[8])[3:])))
    return one(c, "SELECT * FROM invoices WHERE id=?", (cur.lastrowid,))


# ---------------------------------------------------------------- services
@route("GET", "/api/services", "patients_read")
def api_services(h, c, b, q):
    return rows(c.execute("SELECT * FROM services WHERE active=1 OR ?='1' ORDER BY cat, name", (qget(q, "all"),)))


@route("POST", "/api/services", "stock_admin")
def api_service_save(h, c, b, q):
    name, cat = clean(b, "name", 100), clean(b, "cat", 30)
    need(name and cat, "Enter the service name and category")
    rate, gst = P(b.get("rate"), "rate"), opt_num(b.get("gst_pct")) or 0
    need(gst in (0, 5, 12, 18), "GST must be 0, 5, 12 or 18")
    try:
        if b.get("id"):
            old = one(c, "SELECT * FROM services WHERE id=?", (as_int(b["id"], "id"),))
            c.execute("UPDATE services SET name=?,cat=?,rate_p=?,gst_pct=?,active=? WHERE id=?", (name, cat, rate, gst, 0 if b.get("active") is False else 1, old["id"]))
            audit(c, h, "rate.change", f"{name} {rs(old['rate_p'])} -> {rs(rate)} GST {gst}%")
        else:
            c.execute("INSERT INTO services(name,cat,rate_p,gst_pct) VALUES(?,?,?,?)", (name, cat, rate, gst))
            audit(c, h, "rate.add", f"{name} {rs(rate)}")
    except sqlite3.IntegrityError:
        raise ApiError(400, "That service already exists")
    return {"ok": True}


# ---------------------------------------------------------------- unbilled work for a patient
@route("GET", r"/api/patients/(\d+)/unbilled", "hbilling")
def api_unbilled(h, c, b, q, pid):
    pid = int(pid)
    visits = rows(c.execute("SELECT v.id, v.completed_at, v.diagnosis, v.doctor_id, u.name dname FROM visits v LEFT JOIN users u ON u.id=v.doctor_id "
                            "WHERE v.patient_id=? AND v.branch_id=? AND v.status='done' AND v.completed_at>=? AND NOT EXISTS "
                            "(SELECT 1 FROM invoices i WHERE i.visit_id=v.id AND i.cancelled_at IS NULL) AND v.complaint<>'Discharge'",
                            (pid, h.branch, add_days(today(), -7))))
    labs = rows(c.execute("SELECT o.id, o.created_at, t.name, t.id test_id, s.id service_id, s.rate_p FROM lab_orders o JOIN lab_order_items i ON i.order_id=o.id "
                          "JOIN lab_tests t ON t.id=i.test_id LEFT JOIN services s ON s.id=t.service_id WHERE o.patient_id=? AND o.branch_id=? AND o.invoice_id IS NULL "
                          "AND o.admission_id IS NULL AND o.status<>'cancelled'", (pid, h.branch)))
    dues = []
    for inv in rows(c.execute("SELECT * FROM invoices WHERE patient_id=? AND cancelled_at IS NULL", (pid,))):
        st = inv_state(c, inv)
        if st["patient_due_p"]:
            dues.append({"id": inv["id"], "inv_no": inv["inv_no"], "due": R(st["patient_due_p"])})
    return {"visits": visits, "labs": labs, "dues": dues}


# ---------------------------------------------------------------- invoices
@route("POST", "/api/invoices", "hbilling")
def api_invoice(h, c, b, q):
    pid = as_int(b.get("patient_id"), "patient")
    need(one(c, "SELECT 1 FROM patients WHERE id=?", (pid,)), "Patient not found", 404)
    items = []
    for it in (b.get("items") or [])[:100]:
        rate = P(it.get("rate"), "rate") if it.get("rate") not in (None, "") else None
        if rate is not None and it.get("service_id") and not can(h, "stock_admin"):
            s = one(c, "SELECT rate_p FROM services WHERE id=?", (it["service_id"],))
            need(s and s["rate_p"] == rate, "Only managers can change a service rate on an invoice")
        items.append({"service_id": opt_num(it.get("service_id"), int), "name": clean(it, "name", 120) or None, "qty": opt_num(it.get("qty"), float) or 1,
                      "rate_p": rate, "disc_p": P(it.get("disc"), "discount"), "ref": clean(it, "ref", 20) or None})
    pay, mode, ref = P(b.get("pay_now"), "payment"), clean(b, "mode", 10) or "cash", clean(b, "ref", 40)
    need(mode in ("cash", "upi", "card"), "Invalid payment mode")
    need(not pay or mode == "cash" or ref, "Enter the UPI or card transaction reference")
    ins = b.get("insurance")

    def run():
        inv = create_invoice(c, h, pid, items, opt_num(b.get("doctor_id"), int), opt_num(b.get("visit_id"), int), None,
                             "lab" if all((i.get("ref") or "").startswith("LAB") for i in items) else "opd", P(b.get("discount"), "discount"), clean(b, "notes", 300))
        cap = inv["total_p"]
        if ins:
            cl = open_claim(c, h, inv, ins)
            cap -= cl["requested_p"]
        need(pay <= cap, f"Payment now can be at most {rs(cap)}" + (" (the rest is the insurance share)" if ins else ""))
        if pay:
            c.execute("INSERT INTO payments(branch_id,invoice_id,at,mode,amount_p,ref,user_id,kind) VALUES(?,?,?,?,?,?,?,?)",
                      (inv["branch_id"], inv["id"], now_str(), mode, pay, ref, h.user["id"], "payment"))
        audit(c, h, "invoice.create", f"{inv['inv_no']} {pcode(pid)} {rs(inv['total_p'])}" + (f" paid {rs(pay)} {mode}" if pay else "") + (f" claim {ins.get('tpa')}" if ins else ""))
        return inv
    inv = in_tx(c, run)
    from .m_portal import share
    share(c, pid, f"{one(c, 'SELECT name FROM branches WHERE id=?', (inv['branch_id'],))['name']}: your bill {inv['inv_no']} for Rs {R(inv['total_p']):.2f} is ready.", h.user["id"], pdf=("invoice", inv["id"]))
    return {"ok": True, "id": inv["id"], "inv_no": inv["inv_no"], **{k: R(v) if k.endswith("_p") else v for k, v in inv_state(c, inv).items()}}


@route("GET", "/api/invoices", "hbilling")
def api_invoices(h, c, b, q):
    br = need_branch(h, c, "hospital")
    flt, term = qget(q, "filter", "open"), qget(q, "q").strip()
    sql = "SELECT i.*, p.name pname, p.phone FROM invoices i JOIN patients p ON p.id=i.patient_id WHERE i.branch_id=?"
    args = [br["id"]]
    if term:
        sql += " AND (i.inv_no LIKE ? OR p.name LIKE ? OR p.phone LIKE ?)"
        args += [f"%{term}%"] * 3
    if qget(q, "date"):
        sql += " AND i.created_at LIKE ?"
        args.append(valid_day(qget(q, "date")) + "%")
    out = []
    for inv in rows(c.execute(sql + " ORDER BY i.id DESC LIMIT 400", args)):
        st = inv_state(c, inv)
        if flt == "open" and st["status"] not in ("due", "partial", "insurance"):
            continue
        if flt in ("due", "insurance", "paid", "cancelled") and st["status"] != flt and not (flt == "due" and st["status"] == "partial"):
            continue
        out.append(dict(inv, code=pcode(inv["patient_id"]), total=R(inv["total_p"]), **{k[:-2] if k.endswith("_p") else k: (R(v) if k.endswith("_p") else v) for k, v in st.items()}))
    return out


@route("GET", r"/api/invoices/(\d+)", "patients_read")
def api_invoice_get(h, c, b, q, iid):
    inv = one(c, "SELECT i.*, p.name pname, p.phone, p.age, p.gender, p.abha, u.name dname, u.reg_no dreg, br.name bname, br.address baddr, br.phone bphone, br.gstin, cu.name cashier "
                 "FROM invoices i JOIN patients p ON p.id=i.patient_id JOIN branches br ON br.id=i.branch_id LEFT JOIN users u ON u.id=i.doctor_id "
                 "LEFT JOIN users cu ON cu.id=i.user_id WHERE i.id=?", (int(iid),))
    need(inv and (inv["branch_id"] == h.branch or all_access(h.user)), "Invoice not found", 404)
    inv["code"] = pcode(inv["patient_id"])
    inv["items"] = rows(c.execute("SELECT * FROM invoice_items WHERE invoice_id=?", (inv["id"],)))
    inv["payments"] = rows(c.execute("SELECT p.*, u.name uname FROM payments p LEFT JOIN users u ON u.id=p.user_id WHERE invoice_id=? ORDER BY p.id", (inv["id"],)))
    inv["credit_notes"] = rows(c.execute("SELECT * FROM credit_notes WHERE invoice_id=?", (inv["id"],)))
    inv["claims"] = [dict(cl, events=rows(c.execute("SELECT e.*, u.name uname FROM claim_events e LEFT JOIN users u ON u.id=e.user_id WHERE claim_id=? ORDER BY e.id", (cl["id"],))))
                     for cl in rows(c.execute("SELECT * FROM claims WHERE invoice_id=? ORDER BY id", (inv["id"],)))]
    inv.update(inv_state(c, inv))
    return inv


@route("POST", r"/api/invoices/(\d+)/pay", "hbilling")
def api_pay(h, c, b, q, iid):
    inv = one(c, "SELECT * FROM invoices WHERE id=? AND branch_id=?", (int(iid), h.branch))
    need(inv and not inv["cancelled_at"], "Invoice not found", 404)
    amt, mode, ref = P(b.get("amount"), "amount"), clean(b, "mode", 10), clean(b, "ref", 40)
    need(mode in ("cash", "upi", "card"), "Invalid payment mode")
    need(amt > 0, "Enter an amount")
    need(mode == "cash" or ref, "Enter the transaction reference")
    def run():
        st = inv_state(c, inv)  # inside the write lock so two cashiers can't both take the last due amount
        need(amt <= st["patient_due_p"], f"The patient owes at most {rs(st['patient_due_p'])}")
        c.execute("INSERT INTO payments(branch_id,invoice_id,at,mode,amount_p,ref,user_id,kind) VALUES(?,?,?,?,?,?,?,?)", (h.branch, inv["id"], now_str(), mode, amt, ref, h.user["id"], "payment"))
        audit(c, h, "invoice.payment", f"{inv['inv_no']} {rs(amt)} {mode} {ref}")
    in_tx(c, run)
    return {"ok": True, **{k: R(v) if k.endswith("_p") else v for k, v in inv_state(c, inv).items()}}


@route("POST", r"/api/invoices/(\d+)/cancel", "hbilling")
def api_cancel(h, c, b, q, iid):
    inv = one(c, "SELECT * FROM invoices WHERE id=? AND branch_id=?", (int(iid), h.branch))
    need(inv and not inv["cancelled_at"], "Invoice not found", 404)
    need(not paid_p(c, inv["id"]), "This invoice has payments. Issue a refund (credit note) instead.")
    reason = clean(b, "reason", 200)
    need(reason, "Enter a reason")
    c.execute("UPDATE invoices SET cancelled_at=?, cancel_reason=? WHERE id=?", (now_str(), reason, inv["id"]))
    c.execute("UPDATE lab_orders SET invoice_id=NULL WHERE invoice_id=?", (inv["id"],))
    audit(c, h, "invoice.cancel", f"{inv['inv_no']} {reason}")
    return {"ok": True}


@route("POST", r"/api/invoices/(\d+)/refund", "hbilling")
def api_refund(h, c, b, q, iid):
    need(can(h, "stock_admin") or h.user["role"] == "owner", "Only a manager can issue refunds", 403)
    inv = one(c, "SELECT * FROM invoices WHERE id=? AND branch_id=?", (int(iid), h.branch))
    need(inv, "Invoice not found", 404)
    amt, reason, mode = P(b.get("amount"), "amount"), clean(b, "reason", 200), clean(b, "mode", 10) or "cash"
    need(amt > 0 and reason, "Enter the refund amount and reason")
    need(mode in ("cash", "upi", "card"), "Invalid refund mode")
    excess = bool(b.get("excess"))

    def run():
        net_paid = paid_p(c, inv["id"])  # checked under the write lock: two refunds can't both pass
        if excess:
            need(amt <= net_paid - inv["total_p"], f"Only {rs(max(0, net_paid - inv['total_p']))} was paid in excess")
        need(amt <= net_paid, f"Only {rs(net_paid)} has been paid on this invoice")
        n = c.execute("SELECT COUNT(*) FROM credit_notes WHERE branch_id=?", (h.branch,)).fetchone()[0] + 1
        code = one(c, "SELECT code FROM branches WHERE id=?", (h.branch,))["code"]
        cn = f"{code}/CN/{n:05d}"
        c.execute("INSERT INTO credit_notes(branch_id,cn_no,invoice_id,amount_p,reason,at,user_id,mode) VALUES(?,?,?,?,?,?,?,?)", (h.branch, cn, inv["id"], amt, reason, now_str(), h.user["id"], mode))
        c.execute("INSERT INTO payments(branch_id,invoice_id,at,mode,amount_p,ref,user_id,kind) VALUES(?,?,?,?,?,?,?,?)", (h.branch, inv["id"], now_str(), mode, -amt, cn, h.user["id"], "refund"))
        if not excess:  # a refund of an extra deposit doesn't change what the services cost
            c.execute("UPDATE invoices SET total_p=total_p-? WHERE id=?", (amt, inv["id"]))
        audit(c, h, "invoice.refund", f"{inv['inv_no']} {rs(amt)} {cn} {reason}")
        return cn
    return {"ok": True, "credit_note": in_tx(c, run)}


# ---------------------------------------------------------------- insurance claims
def open_claim(c, h, inv, ins):
    tpa = clean(ins, "tpa", 60)
    need(tpa and clean(ins, "policy", 40), "Enter the insurer and policy number")
    req = min(P(ins.get("requested"), "requested amount") or inv["total_p"], inv["total_p"])
    cur = c.execute("INSERT INTO claims(invoice_id,admission_id,patient_id,tpa,policy,claim_no,icd,requested_p,approved_p,status,created_at,updated_at,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (inv["id"], inv["admission_id"], inv["patient_id"], tpa, clean(ins, "policy", 40), clean(ins, "claim_no", 40), clean(ins, "icd", 10).upper() or None,
                     req, 0, "preauth", now_str(), now_str(), clean(ins, "notes", 300)))
    c.execute("INSERT INTO claim_events(claim_id,at,status,note,user_id) VALUES(?,?,?,?,?)", (cur.lastrowid, now_str(), "preauth", f"Requested {rs(req)}", h.user["id"]))
    return one(c, "SELECT * FROM claims WHERE id=?", (cur.lastrowid,))


@route("POST", r"/api/invoices/(\d+)/claim", "hbilling")
def api_claim_open(h, c, b, q, iid):
    inv = one(c, "SELECT * FROM invoices WHERE id=? AND branch_id=?", (int(iid), h.branch))
    need(inv and not inv["cancelled_at"], "Invoice not found", 404)
    need(not claim_open_p(c, inv["id"]), "This invoice already has an open claim")
    cl = in_tx(c, lambda: open_claim(c, h, inv, b))
    audit(c, h, "claim.open", f"{inv['inv_no']} {cl['tpa']} {rs(cl['requested_p'])}")
    return {"ok": True, "id": cl["id"]}


@route("GET", "/api/claims", "hbilling")
def api_claims(h, c, b, q):
    need_branch(h, c, "hospital")
    st = qget(q, "status", "open")
    sql = ("SELECT cl.*, i.inv_no, i.total_p, p.name pname FROM claims cl LEFT JOIN invoices i ON i.id=cl.invoice_id JOIN patients p ON p.id=cl.patient_id "
           "WHERE i.branch_id=?")
    args = [h.branch]
    if st == "open":
        sql += " AND cl.status IN ('preauth','query','approved')"
    elif st in CLAIM_FLOW:
        sql += " AND cl.status=?"
        args.append(st)
    out = rows(c.execute(sql + " ORDER BY cl.updated_at DESC LIMIT 200", args))
    for cl in out:
        cl["age_days"] = (date.today() - date.fromisoformat(cl["created_at"][:10])).days
    return out


@route("POST", r"/api/claims/(\d+)", "hbilling")
def api_claim_update(h, c, b, q, cid):
    cl = one(c, "SELECT cl.*, i.branch_id FROM claims cl JOIN invoices i ON i.id=cl.invoice_id WHERE cl.id=?", (int(cid),))
    need(cl and cl["branch_id"] == h.branch, "Claim not found", 404)
    st, note = clean(b, "status", 10), clean(b, "note", 500)
    need(st in CLAIM_FLOW.get(cl["status"], ()), f"A {cl['status']} claim can't move to {st}")

    def run():
        upd = {"status": st, "updated_at": now_str()}
        if b.get("claim_no"):
            upd["claim_no"] = clean(b, "claim_no", 40)
        if st == "approved":
            ap = P(b.get("approved"), "approved amount")
            need(0 < ap <= cl["requested_p"], f"Approved amount must be between Rs 1 and {rs(cl['requested_p'])}")
            upd["approved_p"] = ap
        if st == "settled":
            amt = P(b.get("settled"), "settled amount")
            need(0 <= amt <= (cl["approved_p"] or cl["requested_p"]), "Settled amount is more than approved")
            upd["settled_p"] = amt
            if amt:
                c.execute("INSERT INTO payments(branch_id,invoice_id,at,mode,amount_p,ref,user_id,kind) VALUES(?,?,?,?,?,?,?,?)",
                          (h.branch, cl["invoice_id"], now_str(), "insurance", amt, cl["claim_no"] or cl["tpa"], h.user["id"], "payment"))
        c.execute(f"UPDATE claims SET {','.join(k + '=?' for k in upd)} WHERE id=?", (*upd.values(), cl["id"]))
        c.execute("INSERT INTO claim_events(claim_id,at,status,note,user_id) VALUES(?,?,?,?,?)", (cl["id"], now_str(), st, note, h.user["id"]))
        audit(c, h, "claim.update", f"claim {cl['id']} {cl['tpa']} -> {st} {note}")
    in_tx(c, run)
    return {"ok": True}


# ---------------------------------------------------------------- cash closing
def day_receipts(c, bid, day):
    rec = []
    for p in rows(c.execute("SELECT p.*, i.inv_no, a.ip_no, pt.name pname, u.username FROM payments p LEFT JOIN invoices i ON i.id=p.invoice_id LEFT JOIN admissions a ON a.id=p.admission_id "
                            "LEFT JOIN patients pt ON pt.id=COALESCE(i.patient_id,a.patient_id) LEFT JOIN users u ON u.id=p.user_id WHERE p.branch_id=? AND p.at LIKE ?", (bid, day + "%"))):
        rec.append({"at": p["at"], "src": "Deposit" if p["kind"] == "deposit" else "Refund" if p["kind"] == "refund" else "Hospital", "ref": p["inv_no"] or p["ip_no"],
                    "who": p["pname"], "mode": p["mode"], "amount_p": p["amount_p"], "user": p["username"]})
    for bl in rows(c.execute("SELECT b.*, u.username FROM bills b LEFT JOIN users u ON u.id=b.user_id WHERE b.branch_id=? AND b.created_at LIKE ?", (bid, day + "%"))):
        if bl["pay_mode"] != "credit":
            rec.append({"at": bl["created_at"], "src": "Pharmacy", "ref": bl["bill_no"], "who": bl["customer"], "mode": bl["pay_mode"], "amount_p": bl["total_p"], "user": bl["username"]})
    for cn in rows(c.execute("SELECT cn.*, b.bill_no, b.customer, u.username FROM credit_notes cn JOIN bills b ON b.id=cn.bill_id LEFT JOIN users u ON u.id=cn.user_id "
                             "WHERE cn.branch_id=? AND cn.at LIKE ? AND cn.mode='cash'", (bid, day + "%"))):
        rec.append({"at": cn["at"], "src": "Pharmacy refund", "ref": cn["cn_no"], "who": cn["customer"], "mode": "cash", "amount_p": -cn["amount_p"], "user": cn["username"]})
    return sorted(rec, key=lambda r: r["at"])


@route("GET", "/api/closing", "hbilling")
def api_closing(h, c, b, q):
    br = need_branch(h, c)
    day = valid_day(qget(q, "date", today()))
    rec = day_receipts(c, br["id"], day)
    by_mode, by_user = {}, {}
    for r in rec:
        by_mode[r["mode"]] = by_mode.get(r["mode"], 0) + r["amount_p"]
        by_user[r["user"] or "-"] = by_user.get(r["user"] or "-", 0) + r["amount_p"]
    return {"receipts": [dict(r, amount=R(r["amount_p"])) for r in rec], "by_mode": {k: R(v) for k, v in by_mode.items()},
            "by_user": {k: R(v) for k, v in by_user.items()}, "expected_cash": R(by_mode.get("cash", 0)),
            "closing": one(c, "SELECT cl.*, u.name uname FROM closings cl LEFT JOIN users u ON u.id=cl.user_id WHERE cl.branch_id=? AND cl.day=?", (br["id"], day))}


@route("POST", "/api/closing", "hbilling")
def api_close(h, c, b, q):
    br = need_branch(h, c)
    day = valid_day(clean(b, "date", 10) or today())
    exp = sum(r["amount_p"] for r in day_receipts(c, br["id"], day) if r["mode"] == "cash")
    counted = P(b.get("counted"), "counted cash")
    c.execute("INSERT INTO closings(branch_id,day,expected_p,counted_p,diff_p,note,user_id,at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(branch_id,day) DO UPDATE SET "
              "expected_p=excluded.expected_p, counted_p=excluded.counted_p, diff_p=excluded.diff_p, note=excluded.note, user_id=excluded.user_id, at=excluded.at",
              (br["id"], day, exp, counted, counted - exp, clean(b, "note", 300), h.user["id"], now_str()))
    audit(c, h, "cash.close", f"{br['code']} {day} expected {rs(exp)} counted {rs(counted)}" + (f" {'excess' if counted > exp else 'short'} {rs(abs(counted - exp))}" if counted != exp else ""))
    return {"ok": True, "diff": R(counted - exp)}
