"""Supplier purchase records: one organised record per supplier (purchases, payments, pending), full purchase history
with invoice, batches and prices, price comparison across suppliers for a medicine, and tracing any batch on the
shelf back to the supplier, invoice, date and price it came from."""
from .core import R, add_days, as_int, audit, clean, need, need_branch, one, opt_num, pcode, qget, route, rows, today


def pstatus(total_p, paid_p):
    if total_p <= 0:
        return "none"
    if paid_p >= total_p:
        return "paid"
    return "partial" if paid_p > 0 else "pending"


@route("GET", "/api/suppliers/overview", "stock")
def api_supplier_overview(h, c, b, q):
    """Every supplier with what was bought from them in the period, what is paid and what is pending."""
    br = need_branch(h, c, "pharmacy")
    days = opt_num(qget(q, "days"), int, "days") or 365
    since = add_days(today(), -days)
    out = []
    for s in rows(c.execute("SELECT * FROM suppliers ORDER BY name")):
        p = c.execute("SELECT COUNT(*), COALESCE(SUM(total_p),0), COALESCE(SUM(paid_p),0), MAX(created_at), "
                      "(SELECT COUNT(DISTINCT medicine_id) FROM batches bt JOIN purchases pp ON pp.id=bt.purchase_id WHERE pp.supplier_id=? AND pp.branch_id=? AND pp.created_at>=?) "
                      "FROM purchases WHERE supplier_id=? AND branch_id=? AND created_at>=?", (s["id"], br["id"], since, s["id"], br["id"], since)).fetchone()
        pend_all = c.execute("SELECT COALESCE(SUM(total_p-paid_p),0), SUM(due_date<?) FROM purchases WHERE supplier_id=? AND branch_id=? AND total_p>paid_p", (today(), s["id"], br["id"])).fetchone()
        ret = c.execute("SELECT COALESCE(SUM(total_p),0), SUM(status='sent') FROM supplier_returns WHERE supplier_id=? AND branch_id=?", (s["id"], br["id"])).fetchone()
        out.append({**s, "purchases": p[0], "total": R(p[1]), "paid": R(p[2]), "last_purchase": (p[3] or "")[:10], "items": p[4] or 0,
                    "pending": R(pend_all[0]), "overdue_bills": pend_all[1] or 0, "status": "overdue" if pend_all[1] else pstatus(p[1] if p[0] else 0, p[2]) if p[0] else ("pending" if pend_all[0] else "none"),
                    "returns": R(ret[0]), "returns_open": ret[1] or 0})
    out.sort(key=lambda x: (x["last_purchase"] or ""), reverse=True)
    tot = c.execute("SELECT COALESCE(SUM(total_p-paid_p),0), COALESCE(SUM(CASE WHEN due_date<? THEN total_p-paid_p ELSE 0 END),0) FROM purchases WHERE branch_id=? AND total_p>paid_p", (today(), br["id"])).fetchone()
    return {"days": days, "suppliers": out, "pending": R(tot[0]), "overdue": R(tot[1]), "active": sum(1 for x in out if x["purchases"])}


@route("GET", r"/api/suppliers/(\d+)/history", "stock")
def api_supplier_history(h, c, b, q, sid):
    """Full purchase history for one supplier: each goods receipt with its invoice, due date, payment status and every batch."""
    br = need_branch(h, c, "pharmacy")
    s = one(c, "SELECT * FROM suppliers WHERE id=?", (int(sid),))
    need(s, "Supplier not found", 404)
    purchases = []
    for p in rows(c.execute("SELECT p.*, u.name uname FROM purchases p LEFT JOIN users u ON u.id=p.user_id WHERE p.supplier_id=? AND p.branch_id=? ORDER BY p.id DESC LIMIT 200", (s["id"], br["id"]))):
        lines = rows(c.execute("SELECT bt.id batch_id, bt.batch, bt.expiry, bt.qty qty_left, bt.cost_p, bt.mrp_p, bt.rack, m.name medicine, m.id medicine_id, m.pack_size, "
                               "(SELECT COALESCE(SUM(change),0) FROM stock_moves sm WHERE sm.batch_id=bt.id AND sm.reason='purchase') qty_in "
                               "FROM batches bt JOIN medicines m ON m.id=bt.medicine_id WHERE bt.purchase_id=? ORDER BY m.name", (p["id"],)))
        purchases.append({"id": p["id"], "grn": f"GRN{p['id']}", "invoice_no": p["invoice_no"], "date": (p["created_at"] or "")[:10], "due_date": p["due_date"], "by": p["uname"],
                          "total": R(p["total_p"]), "gst": R(p["gst_p"]), "paid": R(p["paid_p"]), "due": R(max(0, p["total_p"] - p["paid_p"])),
                          "status": "overdue" if p["total_p"] > p["paid_p"] and (p["due_date"] or "9") < today() else pstatus(p["total_p"], p["paid_p"]),
                          "lines": [dict(l, cost=R(l["cost_p"]), mrp=R(l["mrp_p"]), amount=R(l["cost_p"] * (l["qty_in"] or 0))) for l in lines]})
    payments = rows(c.execute("SELECT sp.*, u.name uname FROM supplier_payments sp LEFT JOIN users u ON u.id=sp.user_id WHERE sp.supplier_id=? AND sp.branch_id=? ORDER BY sp.id DESC LIMIT 100", (s["id"], br["id"])))
    returns = rows(c.execute("SELECT * FROM supplier_returns WHERE supplier_id=? AND branch_id=? ORDER BY id DESC LIMIT 50", (s["id"], br["id"])))
    tot = sum(p["total"] for p in purchases)
    return {"supplier": s, "purchases": purchases, "payments": [dict(x, amount=R(x["amount_p"])) for x in payments], "returns": [dict(x, total=R(x["total_p"])) for x in returns],
            "total": round(tot, 2), "paid": round(sum(p["paid"] for p in purchases), 2), "pending": round(sum(p["due"] for p in purchases), 2)}


@route("POST", r"/api/suppliers/(\d+)", "stock")
def api_supplier_edit(h, c, b, q, sid):
    s = one(c, "SELECT * FROM suppliers WHERE id=?", (int(sid),))
    need(s, "Supplier not found", 404)
    name = clean(b, "name", 100) or s["name"]
    c.execute("UPDATE suppliers SET name=?, phone=?, gstin=?, email=? WHERE id=?",
              (name, clean(b, "phone", 20) or s["phone"], clean(b, "gstin", 20) or s["gstin"], clean(b, "email", 100) or s["email"], s["id"]))
    audit(c, h, "supplier.update", name)
    return {"ok": True}


@route("GET", "/api/stock/compare", "stock")
def api_compare(h, c, b, q):
    """What each supplier last charged for a medicine, side by side, with how often and how much was bought."""
    br = need_branch(h, c, "pharmacy")
    mid = as_int(qget(q, "medicine_id"), "medicine")
    m = one(c, "SELECT * FROM medicines WHERE id=?", (mid,))
    need(m, "Medicine not found", 404)
    out = []
    for r in rows(c.execute(
            "SELECT s.id supplier_id, s.name supplier, COUNT(*) times, SUM(bt.cost_p * (SELECT COALESCE(SUM(change),0) FROM stock_moves sm WHERE sm.batch_id=bt.id AND sm.reason='purchase')) spent_p, "
            "SUM((SELECT COALESCE(SUM(change),0) FROM stock_moves sm WHERE sm.batch_id=bt.id AND sm.reason='purchase')) qty, MIN(bt.cost_p) min_p, MAX(bt.cost_p) max_p, MAX(p.created_at) last_at "
            "FROM batches bt JOIN purchases p ON p.id=bt.purchase_id JOIN suppliers s ON s.id=p.supplier_id WHERE bt.medicine_id=? AND p.branch_id=? GROUP BY s.id ORDER BY last_at DESC", (mid, br["id"]))):
        last = one(c, "SELECT bt.cost_p, bt.mrp_p, p.invoice_no, p.id pid, p.created_at FROM batches bt JOIN purchases p ON p.id=bt.purchase_id WHERE bt.medicine_id=? AND p.supplier_id=? AND p.branch_id=? ORDER BY p.id DESC LIMIT 1",
                   (mid, r["supplier_id"], br["id"]))
        out.append({"supplier_id": r["supplier_id"], "supplier": r["supplier"], "times": r["times"], "qty": r["qty"] or 0, "spent": R(r["spent_p"] or 0),
                    "last_cost": R(last["cost_p"]), "last_cost_pack": R(last["cost_p"] * m["pack_size"]), "last_mrp": R(last["mrp_p"]), "last_date": (last["created_at"] or "")[:10],
                    "last_invoice": last["invoice_no"], "last_grn": f"GRN{last['pid']}", "min_cost": R(r["min_p"]), "max_cost": R(r["max_p"])})
    out.sort(key=lambda x: x["last_cost"])
    best = out[0] if out else None
    return {"medicine": {"id": m["id"], "name": m["name"], "pack_size": m["pack_size"], "generic": m["generic"]}, "suppliers": out,
            "cheapest": best and best["supplier"], "saving": round(out[-1]["last_cost_pack"] - best["last_cost_pack"], 2) if len(out) > 1 else 0}


@route("GET", r"/api/batches/(\d+)/trace", "stock")
def api_trace(h, c, b, q, bid):
    """A batch on the shelf traced back to its supplier, invoice, receipt date and price, with what happened to it since."""
    bt = one(c, "SELECT bt.*, m.name medicine, m.generic, m.pack_size, br.code bcode FROM batches bt JOIN medicines m ON m.id=bt.medicine_id JOIN branches br ON br.id=bt.branch_id WHERE bt.id=?", (int(bid),))
    need(bt and (bt["branch_id"] == h.branch or h.user["role"] == "owner"), "Batch not found", 404)
    p = one(c, "SELECT p.*, s.name supplier, s.phone sphone, s.gstin sgstin, u.name uname FROM purchases p LEFT JOIN suppliers s ON s.id=p.supplier_id LEFT JOIN users u ON u.id=p.user_id WHERE p.id=?", (bt["purchase_id"],)) if bt["purchase_id"] else None
    moves = rows(c.execute("SELECT sm.at, sm.reason kind, sm.change, sm.ref, u.name uname FROM stock_moves sm LEFT JOIN users u ON u.id=sm.user_id WHERE sm.batch_id=? ORDER BY sm.id", (bt["id"],)))
    sold = -sum(x["change"] for x in moves if x["kind"] == "sale")
    received = sum(x["change"] for x in moves if x["kind"] == "purchase")
    same_batch_elsewhere = rows(c.execute("SELECT br.code bcode, bt2.qty, bt2.rack FROM batches bt2 JOIN branches br ON br.id=bt2.branch_id WHERE bt2.medicine_id=? AND bt2.batch=? AND bt2.id<>?", (bt["medicine_id"], bt["batch"], bt["id"])))
    return {"batch": {**bt, "cost": R(bt["cost_p"]), "mrp": R(bt["mrp_p"])},
            "purchase": p and {"grn": f"GRN{p['id']}", "id": p["id"], "invoice_no": p["invoice_no"], "date": (p["created_at"] or "")[:10], "supplier": p["supplier"], "supplier_id": p["supplier_id"],
                               "phone": p["sphone"], "gstin": p["sgstin"], "received_by": p["uname"], "total": R(p["total_p"]), "paid": R(p["paid_p"]), "status": pstatus(p["total_p"], p["paid_p"]),
                               "due_date": p["due_date"]},
            "received": received, "sold": sold, "left": bt["qty"], "moves": moves, "same_batch_elsewhere": same_batch_elsewhere,
            "note": None if p else "This batch was entered without a goods receipt (opening stock or import), so there is no supplier invoice to trace."}
