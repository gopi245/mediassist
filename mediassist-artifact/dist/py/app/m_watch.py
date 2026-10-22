"""Staff watch: the actions that usually mean money or stock is leaking, pulled out of the records every day
and shown to the owner and managers: cancelled bills, refunds and pharmacy returns, counter discounts, stock
write-offs and manual stock reductions, and anything done late at night. Each item says who, when, how much
and why it was flagged. Nothing is blocked; the point is that every one of these is seen."""
from datetime import date

from .core import R, add_days, get_settings, need, qget, route, rows, rs, today

KINDS = {"cancel": "Bill cancelled", "refund": "Hospital refund", "return": "Pharmacy return", "discount": "Discount",
         "writeoff": "Stock written off", "stock_cut": "Stock reduced by hand"}


def _late(at):
    h = int((at or "00:00:00 12")[11:13] or 12)
    return h >= 22 or h < 7


def watch(c, bids, start, end):
    s = get_settings(c)
    big = int(float(s.get("watch_amount") or 2000) * 100)
    disc_pct = float(s.get("watch_discount_pct") or 10)
    ph = ",".join("?" * len(bids))
    lo, hi = start, end + " 99"
    users = {u["id"]: u["name"] for u in rows(c.execute("SELECT id, name FROM users"))}
    codes = {b["id"]: b["code"] for b in rows(c.execute("SELECT id, code FROM branches"))}
    items = []

    def add(kind, at, uid, bid, amount_p, ref, detail, reasons, link=None):
        reasons = [r for r in reasons if r]
        if _late(at):
            reasons.append("late at night")
        items.append({"kind": kind, "label": KINDS[kind], "at": at, "user_id": uid, "user": users.get(uid, "Unknown"), "branch": codes.get(bid, ""),
                      "amount": R(amount_p), "amount_p": amount_p, "ref": ref, "detail": detail, "reasons": reasons, "link": link,
                      "high": bool(reasons) and (amount_p >= big or len(reasons) > 1 or "late at night" in reasons or "same person billed and cancelled" in reasons)})

    # cancelled hospital bills
    for i in rows(c.execute(f"SELECT i.*, (SELECT a.user_id FROM audit a WHERE a.action='invoice.cancel' AND a.detail LIKE i.inv_no || ' %' ORDER BY a.id DESC LIMIT 1) by_uid, "
                            f"(SELECT COALESCE(SUM(amount_p),0) FROM payments p WHERE p.invoice_id=i.id AND p.kind<>'refund') paid FROM invoices i "
                            f"WHERE i.branch_id IN ({ph}) AND i.cancelled_at BETWEEN ? AND ?", (*bids, lo, hi))):
        add("cancel", i["cancelled_at"], i["by_uid"], i["branch_id"], i["total_p"], i["inv_no"], i["cancel_reason"] or "",
            ["money had been collected" if i["paid"] else "", "same person billed and cancelled" if i["by_uid"] and i["by_uid"] == i["user_id"] else "",
             "large amount" if i["total_p"] >= big else ""], {"view": "hbilling", "p": f"inv/{i['id']}"})
    # refunds and pharmacy returns (credit notes)
    for cn in rows(c.execute(f"SELECT cn.*, b.bill_no, b.user_id bill_uid, b.created_at bill_at, b.total_p bill_total, i.inv_no FROM credit_notes cn "
                             f"LEFT JOIN bills b ON b.id=cn.bill_id LEFT JOIN invoices i ON i.id=cn.invoice_id WHERE cn.branch_id IN ({ph}) AND cn.at BETWEEN ? AND ?", (*bids, lo, hi))):
        if cn["bill_id"]:
            days = (date.fromisoformat(cn["at"][:10]) - date.fromisoformat(cn["bill_at"][:10])).days
            add("return", cn["at"], cn["user_id"], cn["branch_id"], cn["amount_p"], cn["bill_no"], (cn["reason"] or "") + f" (credit note {cn['cn_no']})",
                ["cash paid back" if cn["mode"] == "cash" else "", "same person sold and took it back" if cn["user_id"] == cn["bill_uid"] else "",
                 f"returned {days} days after the sale" if days > 7 else "", "whole bill returned" if cn["amount_p"] >= cn["bill_total"] else "",
                 "large amount" if cn["amount_p"] >= big else ""])
        else:
            add("refund", cn["at"], cn["user_id"], cn["branch_id"], cn["amount_p"], cn["inv_no"] or cn["cn_no"], (cn["reason"] or "") + f" (credit note {cn['cn_no']})",
                ["large amount" if cn["amount_p"] >= big else ""], {"view": "hbilling", "p": f"inv/{cn['invoice_id']}"} if cn["invoice_id"] else None)
    # discounts at the counter and on hospital bills
    for b in rows(c.execute(f"SELECT * FROM bills WHERE branch_id IN ({ph}) AND discount_p>0 AND created_at BETWEEN ? AND ?", (*bids, lo, hi))):
        pct = 100 * b["discount_p"] / max(1, b["subtotal_p"])
        add("discount", b["created_at"], b["user_id"], b["branch_id"], b["discount_p"], b["bill_no"], f"{pct:.0f}% off {rs(b['subtotal_p'])} ({b['customer'] or ''})",
            [f"{pct:.0f}% discount" if pct >= disc_pct else "", "large amount" if b["discount_p"] >= big else ""])
    for i in rows(c.execute(f"SELECT i.*, (SELECT COALESCE(SUM(disc_p),0) FROM invoice_items WHERE invoice_id=i.id) item_disc FROM invoices i "
                            f"WHERE i.branch_id IN ({ph}) AND i.created_at BETWEEN ? AND ? AND (i.discount_p>0 OR EXISTS(SELECT 1 FROM invoice_items WHERE invoice_id=i.id AND disc_p>0))",
                            (*bids, lo, hi))):
        d = i["discount_p"] + i["item_disc"]
        pct = 100 * d / max(1, i["sub_p"])
        add("discount", i["created_at"], i["user_id"], i["branch_id"], d, i["inv_no"], f"{pct:.0f}% off {rs(i['sub_p'])}",
            [f"{pct:.0f}% discount" if pct >= disc_pct else "", "large amount" if d >= big else ""], {"view": "hbilling", "p": f"inv/{i['id']}"})
    # stock: write-offs and manual reductions (shelf edits and stock counts)
    for m in rows(c.execute(f"SELECT sm.*, bt.batch, bt.cost_p, md.name mname FROM stock_moves sm JOIN batches bt ON bt.id=sm.batch_id JOIN medicines md ON md.id=bt.medicine_id "
                            f"WHERE sm.branch_id IN ({ph}) AND sm.at BETWEEN ? AND ? AND sm.change<0 AND (sm.reason LIKE 'writeoff:%' OR sm.reason LIKE 'adjust:%' OR sm.reason='count_adjust')",
                            (*bids, lo, hi))):
        val = -m["change"] * m["cost_p"]
        why = m["reason"].split(":", 1)[-1]
        kind = "writeoff" if m["reason"].startswith("writeoff:") else "stock_cut"
        add(kind, m["at"], m["user_id"], m["branch_id"], val, f"{m['mname']} {m['batch'] or ''}".strip(),
            f"{-m['change']} units, {why.replace('_', ' ')}" + (f" ({m['ref']})" if m["ref"] else ""),
            ["not expired" if kind == "writeoff" and why != "expired" else "", "large amount" if val >= big else "",
             "no reason given" if kind == "stock_cut" and why in ("correction", "count_adjust") and not m["ref"] else ""])
    items.sort(key=lambda x: x["at"] or "", reverse=True)
    staff = {}
    for it in items:
        s_ = staff.setdefault(it["user_id"], {"user": it["user"], "count": 0, "flagged": 0, "amount": 0, "kinds": {}})
        s_["count"] += 1
        s_["flagged"] += 1 if it["reasons"] else 0
        s_["amount"] += it["amount_p"]
        s_["kinds"][it["label"]] = s_["kinds"].get(it["label"], 0) + 1
    totals = {}
    for it in items:
        t = totals.setdefault(it["kind"], {"label": it["label"], "count": 0, "amount": 0})
        t["count"] += 1
        t["amount"] += it["amount_p"]
    return {"start": start, "end": end, "items": items, "flagged": sum(1 for x in items if x["reasons"]), "high": sum(1 for x in items if x["high"]),
            "totals": [dict(t, amount=R(t["amount"])) for t in totals.values()],
            "staff": sorted([dict(v, amount=R(v["amount"])) for v in staff.values()], key=lambda v: (-v["flagged"], -v["amount"]))}


def watch_lines(c, bids, day):
    """Lines for the evening report (empty when nothing happened)."""
    w = watch(c, bids, day, day)
    if not w["items"]:
        return []
    out = ["", "*Staff watch:* " + ", ".join(f"{t['count']} {t['label'].lower()}{'s' if t['count'] > 1 and not t['label'].endswith('off') else ''} Rs {t['amount']:,.0f}" for t in w["totals"])]
    for it in [x for x in w["items"] if x["reasons"]][:6]:
        out.append(f"  {'!! ' if it['high'] else '- '}{it['user']}: {it['label'].lower()} {it['ref']} Rs {it['amount']:,.0f} ({', '.join(it['reasons'])})")
    if w["flagged"] > 6:
        out.append(f"  ...and {w['flagged'] - 6} more. Open Reports > Staff watch.")
    return out


@route("GET", "/api/watch", "audit")
def api_watch(h, c, b, q):
    days = int(qget(q, "days", "1") or 1)
    need(days in (1, 7, 30), "Choose today, 7 days or 30 days")
    end = today()
    from .m_reports import bids_scope
    return watch(c, bids_scope(c, h), add_days(end, -(days - 1)), end)
