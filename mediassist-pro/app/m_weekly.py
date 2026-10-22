"""Supplier dues (what the pharmacy owes, by invoice) and the weekly pharmacy summary sent to the owner and
branch: stock expiring within 6 months, non-moving stock, low stock and supplier dues."""
from datetime import date, datetime, timedelta

from .core import (P, R, add_days, audit, clean, get_settings, in_tx, need, need_branch, now_str, one, route, rows, rs,
                   today, valid_day)

CREDIT_DAYS = 30


def inr(v):
    """Rupees the Indian way: 1,00,393.30"""
    neg, v = v < 0, abs(v)
    whole, frac = f"{v:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    while len(head) > 2:
        tail, head = head[-2:] + "," + tail, head[:-2]
    return ("-" if neg else "") + "Rs " + (head + "," + tail if head else tail) + "." + frac


def due_of(p):
    return max(0, (p["total_p"] or 0) + (p["gst_p"] or 0) - (p["paid_p"] or 0))


def dues(c, bid):
    out = []
    for p in rows(c.execute("SELECT p.*, s.name supplier, s.phone sphone FROM purchases p LEFT JOIN suppliers s ON s.id=p.supplier_id "
                            "WHERE p.branch_id=? ORDER BY COALESCE(p.due_date, substr(p.created_at,1,10))", (bid,))):
        d = due_of(p)
        if d <= 0:
            continue
        dd = p["due_date"] or add_days(p["created_at"][:10], CREDIT_DAYS)
        out.append({"id": p["id"], "grn": f"GRN{p['id']}", "invoice_no": p["invoice_no"], "supplier": p["supplier"] or "Unknown supplier", "supplier_id": p["supplier_id"],
                    "date": p["created_at"][:10], "due_date": dd, "days": (date.fromisoformat(dd) - date.today()).days,
                    "amount": R(p["total_p"] + p["gst_p"]), "paid": R(p["paid_p"]), "due": R(d), "due_p": d})
    return out


@route("GET", "/api/supplier-dues", "stock")
def api_dues(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    lst = dues(c, br["id"])
    week = [x for x in lst if x["days"] <= 7]
    return {"rows": lst, "total": R(sum(x["due_p"] for x in lst)), "overdue": R(sum(x["due_p"] for x in lst if x["days"] < 0)),
            "this_week": R(sum(x["due_p"] for x in week)), "count": len(lst),
            "payments": rows(c.execute("SELECT sp.*, s.name supplier, u.name uname FROM supplier_payments sp LEFT JOIN suppliers s ON s.id=sp.supplier_id "
                                       "LEFT JOIN users u ON u.id=sp.user_id WHERE sp.branch_id=? ORDER BY sp.id DESC LIMIT 30", (br["id"],)))}


@route("POST", r"/api/purchases/(\d+)/pay", "stock_admin")
def api_pay_supplier(h, c, b, q, pid):
    br = need_branch(h, c, "pharmacy")
    amt, mode, ref = P(b.get("amount"), "amount"), clean(b, "mode", 10) or "bank", clean(b, "ref", 40)
    need(mode in ("cash", "upi", "bank", "cheque"), "Choose how it was paid")
    need(mode == "cash" or ref, "Enter the UTR, cheque or transaction number")

    def run():
        p = one(c, "SELECT * FROM purchases WHERE id=? AND branch_id=?", (int(pid), br["id"]))
        need(p, "Purchase not found", 404)
        need(0 < amt <= due_of(p), f"Payment must be between Rs 0.01 and the amount due, {rs(due_of(p))}")
        c.execute("UPDATE purchases SET paid_p=paid_p+? WHERE id=?", (amt, p["id"]))
        c.execute("INSERT INTO supplier_payments(branch_id,purchase_id,supplier_id,at,amount_p,mode,ref,user_id) VALUES(?,?,?,?,?,?,?,?)",
                  (br["id"], p["id"], p["supplier_id"], now_str(), amt, mode, ref, h.user["id"]))
        audit(c, h, "supplier.pay", f"GRN{p['id']} invoice {p['invoice_no'] or '-'} {rs(amt)} {mode} {ref}")
        return {"ok": True, "due": R(due_of(dict(p, paid_p=p["paid_p"] + amt)))}
    return in_tx(c, run)


@route("POST", r"/api/purchases/(\d+)/due", "stock_admin")
def api_set_due(h, c, b, q, pid):
    d = valid_day(clean(b, "due_date", 10), "due date")
    c.execute("UPDATE purchases SET due_date=? WHERE id=? AND branch_id=?", (d, int(pid), h.branch))
    audit(c, h, "supplier.due_date", f"GRN{pid} due {d}")
    return {"ok": True}


# ---------------------------------------------------------------- weekly pharmacy summary
def weekly_summary(c, bid):
    from .m_pharmacy import days_left, velocity
    br = one(c, "SELECT * FROM branches WHERE id=?", (bid,))
    meds = {m["id"]: m for m in rows(c.execute("SELECT * FROM medicines"))}
    batches = rows(c.execute("SELECT * FROM batches WHERE branch_id=? AND qty>0", (bid,)))
    usable = [b for b in batches if days_left(b) >= 0]
    exp6 = [b for b in usable if days_left(b) <= 182]
    exp_week = [b for b in usable if days_left(b) <= 7]
    expired = [b for b in batches if days_left(b) < 0]
    since = add_days(today(), -30)
    sold = {r[0] for r in c.execute("SELECT DISTINCT bi.medicine_id FROM bill_items bi JOIN bills b ON b.id=bi.bill_id WHERE b.branch_id=? AND b.created_at>=?", (bid, since))}
    per_med = {}
    for b in usable:
        per_med.setdefault(b["medicine_id"], []).append(b)
    non_moving = []
    for mid, bs in per_med.items():
        if mid in sold or all((b["received_at"] or "") >= since for b in bs):  # no date = old stock
            continue  # sold recently, or only just arrived
        non_moving.append({"medicine": meds[mid]["name"], "qty": sum(b["qty"] for b in bs), "value_p": sum(b["qty"] * b["cost_p"] for b in bs)})
    non_moving.sort(key=lambda x: -x["value_p"])
    stock = {mid: sum(b["qty"] for b in bs) for mid, bs in per_med.items()}
    vel = velocity(c, bid)
    low = [m for m in meds.values() if m["active"] and (stock.get(m["id"], 0) < m["reorder_level"]) and (vel.get(m["id"]) or stock.get(m["id"]))]
    d = dues(c, bid)
    val = lambda bs: sum(b["qty"] * b["cost_p"] for b in bs)
    out = {
        "branch": br["name"], "week_ending": today(),
        "expiring": {"batches": len(exp6), "this_week": len(exp_week), "value": R(val(exp6)),
                     "top": [{"medicine": meds[b["medicine_id"]]["name"], "batch": b["batch"], "expiry": b["expiry"], "qty": b["qty"], "value": R(b["qty"] * b["cost_p"])}
                             for b in sorted(exp6, key=lambda b: (days_left(b), -b["qty"] * b["cost_p"]))[:8]]},
        "expired_on_shelf": {"batches": len(expired), "value": R(val(expired))},
        "non_moving": {"items": len(non_moving), "value": R(sum(x["value_p"] for x in non_moving)),
                       "top": [dict(x, value=R(x.pop("value_p"))) for x in non_moving[:8]]},
        "low_stock": {"items": len(low), "names": [m["name"] for m in sorted(low, key=lambda m: m["name"])][:15]},
        "supplier_dues": {"this_week_bills": sum(1 for x in d if x["days"] <= 7), "this_week": R(sum(x["due_p"] for x in d if x["days"] <= 7)),
                          "overdue_bills": sum(1 for x in d if x["days"] < 0), "overdue": R(sum(x["due_p"] for x in d if x["days"] < 0)),
                          "pending_bills": len(d), "pending": R(sum(x["due_p"] for x in d))},
    }
    e, n, s = out["expiring"], out["non_moving"], out["supplier_dues"]
    lines = [f"{br['name']}: weekly pharmacy summary, week ending {today()}", "",
             f"Expiring within 6 months: {e['batches']} batches, {inr(e['value'])} at cost ({e['this_week']} expire this week)"]
    if out["expired_on_shelf"]["batches"]:
        lines.append(f"EXPIRED still on the shelf: {out['expired_on_shelf']['batches']} batches, {inr(out['expired_on_shelf']['value'])}. Remove them today.")
    lines += [f"Not sold in 30 days: {n['items']} medicines, {inr(n['value'])} at cost" + (f" (biggest: {', '.join(x['medicine'] for x in n['top'][:3])})" if n["top"] else ""),
              f"Below reorder level: {out['low_stock']['items']} medicines",
              f"Supplier bills due this week: {s['this_week_bills']}, {inr(s['this_week'])}" + (f"; overdue {s['overdue_bills']}, {inr(s['overdue'])}" if s["overdue_bills"] else ""),
              f"All pending supplier bills: {s['pending_bills']}, {inr(s['pending'])}"]
    out["text"] = "\n".join(lines)
    return out


@route("GET", "/api/stock/weekly", "stock")
def api_weekly(h, c, b, q):
    return weekly_summary(c, need_branch(h, c, "pharmacy")["id"])


@route("POST", "/api/stock/weekly/send", "stock_admin")
def api_weekly_send(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    res = send_weekly(c, [br])
    audit(c, h, "report.weekly_pharmacy", br["code"])
    return {"ok": True, "sent": res}


def send_weekly(c, branches=None):
    from .notify import deliver
    s, res = get_settings(c), []
    for br in branches or rows(c.execute("SELECT * FROM branches WHERE active=1 AND kind LIKE '%pharmacy%'")):
        text = weekly_summary(c, br["id"])["text"]
        to_email, to_wa = br["report_email"] or s.get("owner_email"), br["report_whatsapp"] or s.get("owner_whatsapp")
        if to_email or to_wa:
            res += deliver(c, "weekly_pharmacy", text, email=to_email, whatsapp=to_wa, subject=f"Weekly pharmacy summary: {br['name']}")
    return res


def weekly_due(s):
    """True once a week: on the chosen weekday, after the report time, if not sent yet this week."""
    if s.get("weekly_pharmacy", "1") != "1":
        return False
    now = datetime.now()
    day = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}.get((s.get("weekly_day") or "mon")[:3].lower(), 0)
    week_start = (now.date() - timedelta(days=(now.weekday() - day) % 7)).isoformat()
    return now.weekday() == day and now.strftime("%H:%M") >= (s.get("report_time") or "20:00") and (s.get("last_weekly") or "") < week_start
