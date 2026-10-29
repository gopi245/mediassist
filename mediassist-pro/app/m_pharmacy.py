"""Pharmacy: medicine master, stock and racks, lookup/barcode, purchases and purchase orders,
supplier returns, transfers, write-offs, fridge temperature log, stock counts, billing
(loose tablets or strips), returns, H1 register."""
import csv
import io
import math
import re
import sqlite3
from datetime import date, timedelta

from .core import (ApiError, P, R, add_days, all_access, as_int, audit, can, check_discount, clean, in_tx, need, need_branch, now_str, one, opt_num,
                   pcode, qget, route, rows, rs, today, valid_day)
from .m_clinical import current_meds, latest_creatinine
from .safety import safety_check

SCHEDULES = ("OTC", "H", "H1", "X")
PAY_MODES = ("cash", "upi", "card", "credit")
RACK_BY_FORM = {"Tablet": "A", "Capsule": "B", "Syrup": "C", "Sachet": "D", "Injection": "F", "Cream": "D", "Drops": "D"}


# ---------------------------------------------------------------- stock helpers
def eff_expiry(b):
    e = date.fromisoformat(b["expiry"])
    if b.get("opened"):
        e = min(e, date.fromisoformat(b["opened"]) + timedelta(days=30))
    return e


def days_left(b):
    return (eff_expiry(b) - date.today()).days


def usable_batches(c, bid, mid):
    out = [b for b in rows(c.execute("SELECT * FROM batches WHERE branch_id=? AND medicine_id=? AND qty>0", (bid, mid))) if days_left(b) >= 0]
    return sorted(out, key=eff_expiry)


def usable_stock(c, bid):
    out = {}
    for b in rows(c.execute("SELECT * FROM batches WHERE branch_id=? AND qty>0", (bid,))):
        if days_left(b) >= 0:
            out[b["medicine_id"]] = out.get(b["medicine_id"], 0) + b["qty"]
    return out


def pharmacies(c):
    return rows(c.execute("SELECT * FROM branches WHERE active=1 AND kind LIKE '%pharmacy%' ORDER BY id"))


def move(c, h, batch, change, reason, ref=""):
    c.execute("INSERT INTO stock_moves(at,branch_id,batch_id,change,reason,ref,user_id) VALUES(?,?,?,?,?,?,?)",
              (now_str(), batch["branch_id"], batch["id"], change, reason, ref, h.user["id"] if h.user else None))


def default_rack(c, mid):
    m = one(c, "SELECT * FROM medicines WHERE id=?", (mid,))
    if m["cold_chain"]:
        return "FRIDGE-1"
    letter = RACK_BY_FORM.get(m["form"], "D")
    same = [r[0] for r in c.execute("SELECT id FROM medicines WHERE form=? AND cold_chain=0 ORDER BY id", (m["form"],))]
    i = same.index(mid) if mid in same else 0
    return f"{letter}{i // 4 + 1}-{i % 4 + 1}"


def rack_for(c, bid, mid):
    r = c.execute("SELECT rack FROM batches WHERE branch_id=? AND medicine_id=? AND rack IS NOT NULL ORDER BY qty>0 DESC, id DESC LIMIT 1", (bid, mid)).fetchone()
    return r[0] if r else default_rack(c, mid)


def velocity(c, bid, days=30):
    since = add_days(today(), -days)
    return {r[0]: (r[1] or 0) / days for r in c.execute(
        "SELECT bi.medicine_id, SUM(bi.qty-bi.returned) FROM bill_items bi JOIN bills b ON b.id=bi.bill_id WHERE b.branch_id=? AND b.created_at>=? GROUP BY bi.medicine_id",
        (bid, since))}


def med_row(c, mid):
    m = one(c, "SELECT * FROM medicines WHERE id=?", (mid,))
    need(m, "Medicine not found", 404)
    return m


# ---------------------------------------------------------------- medicines
@route("GET", "/api/medicines", "patients_read")
def api_medicines(h, c, b, q):
    stock = usable_stock(c, h.branch) if h.branch else {}
    out = []
    for m in rows(c.execute("SELECT * FROM medicines WHERE active=1 OR ?='1' ORDER BY name", (qget(q, "all"),))):
        nxt = usable_batches(c, h.branch, m["id"])[:1] if h.branch else []
        out.append(dict(m, stock=stock.get(m["id"], 0), mrp=R(nxt[0]["mrp_p"]) if nxt else None, rack=nxt[0]["rack"] if nxt else None))
    return out


@route("POST", "/api/medicines", "stock")
def api_save_medicine(h, c, b, q):
    name, sched = clean(b, "name", 100), clean(b, "schedule", 3) or "OTC"
    need(name and sched in SCHEDULES, "Name and a valid schedule (OTC/H/H1/X) are required")
    gst = opt_num(b.get("gst_pct")) or 0
    need(gst in (0, 5, 12, 18, 28), "GST must be 0, 5, 12, 18 or 28")
    pack = as_int(b.get("pack_size") or 1, "pack size", 1, 1000)
    bc = re.sub(r"\s", "", clean(b, "barcode", 40)) or None
    vals = (name, clean(b, "generic", 100).lower(), clean(b, "form", 20), sched, gst, clean(b, "hsn", 10), as_int(b.get("reorder_level") or 0, "reorder level", 0),
            pack, bc, opt_num(b.get("strength_mg")), opt_num(b.get("max_daily_mg")), opt_num(b.get("ped_mg_per_kg_day")),
            1 if b.get("renal_caution") else 0, 1 if b.get("pregnancy_avoid") else 0, 1 if b.get("cold_chain") else 0, 0 if b.get("active") is False else 1)
    cols = "name,generic,form,schedule,gst_pct,hsn,reorder_level,pack_size,barcode,strength_mg,max_daily_mg,ped_mg_per_kg_day,renal_caution,pregnancy_avoid,cold_chain,active"
    try:
        if b.get("id"):
            c.execute(f"UPDATE medicines SET {','.join(x + '=?' for x in cols.split(','))} WHERE id=?", (*vals, as_int(b["id"], "id")))
        else:
            c.execute(f"INSERT INTO medicines({cols}) VALUES({','.join('?' * 16)})", vals)
    except sqlite3.IntegrityError:
        raise ApiError(400, "A medicine with this name already exists")
    audit(c, h, "medicine.save", name)
    return {"ok": True}


def stock_info(c, mid, bid):
    m = med_row(c, mid)
    phs = pharmacies(c)
    others = []
    for o in phs:
        u = usable_batches(c, o["id"], mid)
        if u and o["id"] != bid:
            others.append({"branch": o["name"], "code": o["code"], "qty": sum(x["qty"] for x in u), "rack": u[0]["rack"]})
    out = {"medicine": m, "others": others, "batches": [], "expired": [], "alternatives": []}
    if not bid or not any(o["id"] == bid for o in phs):
        out["no_pharmacy"] = True
        return out
    use = usable_batches(c, bid, mid)
    out["batches"] = [dict(x, days_left=days_left(x), effective_expiry=eff_expiry(x).isoformat(), mrp=R(x["mrp_p"])) for x in use]
    out["expired"] = [x for x in rows(c.execute("SELECT * FROM batches WHERE branch_id=? AND medicine_id=? AND qty>0", (bid, mid))) if days_left(x) < 0]
    out["qty"] = sum(x["qty"] for x in use)
    out["status"] = "out" if not out["qty"] else "low" if out["qty"] < m["reorder_level"] else "ok"
    g = (m["generic"] or "").split(" ")[:1]
    if g and not out["qty"]:
        st = usable_stock(c, bid)
        out["alternatives"] = [dict(x, stock=st[x["id"]]) for x in rows(c.execute("SELECT * FROM medicines WHERE id<>? AND active=1", (mid,)))
                               if (x["generic"] or "").split(" ")[:1] == g and st.get(x["id"])]
    return out


@route("GET", "/api/stock/lookup", "patients_read")
def api_lookup(h, c, b, q):
    code, name = qget(q, "barcode").strip(), qget(q, "name").strip()
    m = None
    if code:
        m = one(c, "SELECT * FROM medicines WHERE barcode=?", (code,))
        if not m:
            bt = one(c, "SELECT medicine_id FROM batches WHERE batch=? ORDER BY id DESC", (code,))
            m = med_row(c, bt["medicine_id"]) if bt else None
        need(m, f"No medicine with barcode {code}. Add the barcode in the medicine master.", 404)
    elif name:
        m = one(c, "SELECT * FROM medicines WHERE lower(name)=lower(?)", (name,))
        need(m, "Medicine not found", 404)
    else:
        m = med_row(c, as_int(qget(q, "id"), "medicine"))
    return stock_info(c, m["id"], h.branch)


@route("GET", "/api/stock", "patients_read")
def api_stock(h, c, b, q):
    if not h.branch:
        phs = pharmacies(c)
        stocks = {p["id"]: usable_stock(c, p["id"]) for p in phs}
        out = []
        for m in rows(c.execute("SELECT * FROM medicines WHERE active=1 ORDER BY name")):
            per = {p["code"]: stocks[p["id"]].get(m["id"], 0) for p in phs}
            out.append({"name": m["name"], "reorder_level": m["reorder_level"], "per_branch": per, "total": sum(per.values())})
        return {"mode": "org", "branches": [p["code"] for p in phs], "rows": out,
                "value": R(c.execute("SELECT COALESCE(SUM(qty*cost_p),0) FROM batches").fetchone()[0])}
    br = need_branch(h, c, "pharmacy")
    meds = {m["id"]: m for m in rows(c.execute("SELECT * FROM medicines"))}
    vel = velocity(c, br["id"])
    summary, blist = {}, []

    def row(mid):
        m = meds[mid]
        return summary.setdefault(mid, {"medicine_id": mid, "name": m["name"], "generic": m["generic"], "form": m["form"], "schedule": m["schedule"],
                                        "pack_size": m["pack_size"], "reorder_level": m["reorder_level"], "usable": 0, "expired": 0, "value_p": 0, "near_expiry": 0, "racks": []})
    for bt in rows(c.execute("SELECT * FROM batches WHERE branch_id=? AND qty>0", (br["id"],))):
        d, s = days_left(bt), row(bt["medicine_id"])
        if d < 0:
            s["expired"] += bt["qty"]
        else:
            s["usable"] += bt["qty"]
            s["value_p"] += bt["qty"] * bt["cost_p"]
            if d <= 90:
                s["near_expiry"] += bt["qty"]
            if bt["rack"] and bt["rack"] not in s["racks"]:
                s["racks"].append(bt["rack"])
        blist.append(dict(bt, medicine=meds[bt["medicine_id"]]["name"], form=meds[bt["medicine_id"]]["form"], days_left=d,
                          effective_expiry=eff_expiry(bt).isoformat(), mrp=R(bt["mrp_p"]), cost=R(bt["cost_p"]), value=R(bt["qty"] * bt["cost_p"])))
    for mid in vel:
        if mid in meds:
            row(mid)
    reorder = []
    for s in summary.values():
        avg = vel.get(s["medicine_id"], 0)
        s["per_day"], s["days_cover"] = round(avg, 1), (round(s["usable"] / avg) if avg else None)
        low = s["usable"] < s["reorder_level"] or (s["days_cover"] is not None and s["days_cover"] < 15)
        s["status"] = "out" if s["usable"] == 0 else "low" if low else "ok"
        s["value"] = R(s.pop("value_p"))
        if s["status"] != "ok":
            want = max(s["reorder_level"], math.ceil(avg * 30))
            pack = s["pack_size"] or 1
            qty = int(math.ceil((want - s["usable"]) / pack) * pack)
            if qty > 0:
                reorder.append({"medicine_id": s["medicine_id"], "medicine": s["name"], "have": s["usable"], "per_day": s["per_day"], "order": qty,
                                "why": f"{s['usable']} left, sells {s['per_day']}/day, reorder level {s['reorder_level']}"})
    others = [(o, velocity(c, o["id"]), usable_stock(c, o["id"])) for o in pharmacies(c) if o["id"] != br["id"]]
    transfers = []
    for bt in blist:
        d = bt["days_left"]
        if d < 0 or d > 120:
            continue
        excess = int(bt["qty"] - vel.get(bt["medicine_id"], 0) * d)
        if excess < 10:
            continue
        best = None
        for o, ov, os_ in others:
            room = int(ov.get(bt["medicine_id"], 0) * d - os_.get(bt["medicine_id"], 0))
            if room >= 10 and (not best or room > best[1]):
                best = (o, room, ov.get(bt["medicine_id"], 0))
        transfers.append({"batch_id": bt["id"], "medicine": bt["medicine"], "batch": bt["batch"], "days_left": d, "qty": min(excess, best[1]) if best else excess,
                          "to_branch": best[0]["id"] if best else None, "to_name": best[0]["name"] if best else "",
                          "why": (f"Only about {int(bt['qty'] - excess)} of {bt['qty']} will sell here before expiry. {best[0]['name']} sells {best[2]:.1f}/day."
                                  if best else f"About {excess} units will not sell before expiry. Return to the supplier or run an offer.")})
    order = {"out": 0, "low": 1, "ok": 2}
    return {"mode": "branch", "summary": sorted(summary.values(), key=lambda s: (order[s["status"]], s["name"])),
            "batches": sorted(blist, key=lambda x: x["days_left"]), "reorder": reorder, "transfers": transfers}


@route("POST", r"/api/batches/(\d+)", "stock")
def api_batch_update(h, c, b, q, bid):
    bt = one(c, "SELECT * FROM batches WHERE id=? AND branch_id=?", (int(bid), h.branch))
    need(bt, "Batch not found at this branch", 404)
    if "rack" in b:
        rack = clean(b, "rack", 12).upper()
        need(rack, "Enter a rack, e.g. A2-3")
        c.execute("UPDATE batches SET rack=? WHERE id=?", (rack, bt["id"]))
        audit(c, h, "stock.rack", f"batch {bt['batch']} {bt['rack'] or '-'} -> {rack}")
    if b.get("opened"):
        d = valid_day(clean(b, "opened", 10), "opened date")
        c.execute("UPDATE batches SET opened=? WHERE id=?", (d, bt["id"]))
        audit(c, h, "stock.opened", f"batch {bt['batch']} opened {d}")
    return {"ok": True}


ADJUST_REASONS = {"count": "Shelf count", "opening": "Opening stock", "found": "Found / not recorded", "damaged": "Damaged",
                  "correction": "Correction", "photo": "From a stock photo"}


@route("POST", "/api/stock/update", "stock")
def api_stock_update(h, c, b, q):
    """Edit stock directly: change quantity, batch, expiry, rack or MRP of a batch, or add a new batch.
    Every quantity change is logged as a stock move with a reason, so the audit trail stays complete."""
    br = need_branch(h, c, "pharmacy")
    lines = (b.get("lines") or [])[:300]
    need(lines, "Nothing to update")
    reason = clean(b, "reason", 20) or "correction"
    need(reason in ADJUST_REASONS, "Choose a reason for the change")
    doc = opt_num(b.get("doc_id"), int, "photo")
    ref = ((f"photo #{doc} " if doc else "") + clean(b, "note", 80)).strip()

    def run():
        changed, added = 0, 0
        for ln in lines:
            if ln.get("batch_id"):
                bt = one(c, "SELECT * FROM batches WHERE id=? AND branch_id=?", (as_int(ln["batch_id"], "batch"), br["id"]))
                need(bt, "Batch not found at this branch", 404)
                m = med_row(c, bt["medicine_id"])
                mult = m["pack_size"] if ln.get("unit") == "pack" else 1
                sets, what = {}, []
                if ln.get("qty") not in (None, ""):
                    new = as_int(ln["qty"], f"quantity of {m['name']}", 0) * mult
                    if new != bt["qty"]:
                        sets["qty"] = new
                        move(c, h, bt, new - bt["qty"], "adjust:" + reason, ref)
                        what.append(f"qty {bt['qty']}->{new}")
                if ln.get("batch") is not None and clean(ln, "batch", 40) != (bt["batch"] or ""):
                    sets["batch"] = clean(ln, "batch", 40)
                    what.append(f"batch {bt['batch']}->{sets['batch']}")
                if ln.get("expiry"):
                    e = valid_day(clean(ln, "expiry", 10), "expiry")
                    if e != bt["expiry"]:
                        sets["expiry"] = e
                        what.append(f"expiry {bt['expiry']}->{e}")
                if ln.get("rack"):
                    r = clean(ln, "rack", 12).upper()
                    if r != (bt["rack"] or ""):
                        sets["rack"] = r
                        what.append(f"rack {bt['rack'] or '-'}->{r}")
                if ln.get("mrp") not in (None, ""):
                    mrp = P(ln["mrp"], "MRP") // mult
                    need(mrp > 0, f"{m['name']}: MRP must be more than 0")
                    if mrp != bt["mrp_p"]:
                        sets["mrp_p"] = mrp
                        what.append(f"MRP {rs(bt['mrp_p'])}->{rs(mrp)}")
                if sets:
                    c.execute(f"UPDATE batches SET {','.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), bt["id"]))
                    audit(c, h, "stock.edit", f"{m['name']} batch {bt['batch']}: {', '.join(what)} ({ADJUST_REASONS[reason]})")
                    changed += 1
                continue
            m = med_row(c, as_int(ln.get("medicine_id"), "medicine"))
            mult = m["pack_size"] if ln.get("unit") == "pack" else 1
            qty = as_int(ln.get("qty"), f"quantity of {m['name']}", 1) * mult
            exp = valid_day(clean(ln, "expiry", 10), f"{m['name']} expiry")
            need(date.fromisoformat(exp) > date.today(), f"{m['name']}: this batch has already expired. Don't put it on the shelf.")
            mrp = P(ln.get("mrp"), "MRP") // mult
            need(mrp > 0, f"{m['name']}: MRP is required")
            if ln.get("cost") not in (None, ""):
                cost = P(ln["cost"], "cost") // mult
            else:
                last = c.execute("SELECT cost_p FROM batches WHERE medicine_id=? AND cost_p>0 ORDER BY branch_id=? DESC, id DESC LIMIT 1", (m["id"], br["id"])).fetchone()
                need(last, f"{m['name']}: enter the purchase cost (no earlier batch to copy it from)")
                cost = last[0]
            need(cost <= mrp, f"{m['name']}: cost is higher than MRP. Check the numbers.")
            rack = clean(ln, "rack", 12).upper() or rack_for(c, br["id"], m["id"])
            cur = c.execute("INSERT INTO batches(branch_id,medicine_id,batch,expiry,qty,mrp_p,cost_p,rack,received_at) VALUES(?,?,?,?,?,?,?,?,?)",
                            (br["id"], m["id"], clean(ln, "batch", 40), exp, qty, mrp, cost, rack, now_str()))
            move(c, h, {"id": cur.lastrowid, "branch_id": br["id"]}, qty, "adjust:" + reason, ref)
            audit(c, h, "stock.add", f"{m['name']} batch {clean(ln, 'batch', 40)} x{qty} rack {rack} ({ADJUST_REASONS[reason]})")
            added += 1
        return {"ok": True, "changed": changed, "added": added}
    return in_tx(c, run)


@route("GET", "/api/stock/edit", "stock")
def api_stock_edit_list(h, c, b, q):
    """Every medicine with its batches at this branch (including expired ones still on the shelf), for the edit screen."""
    br = need_branch(h, c, "pharmacy")
    meds = rows(c.execute("SELECT id,name,generic,form,pack_size,reorder_level FROM medicines WHERE active=1 ORDER BY name"))
    by = {}
    for bt in rows(c.execute("SELECT * FROM batches WHERE branch_id=? AND qty>0 ORDER BY expiry", (br["id"],))):
        by.setdefault(bt["medicine_id"], []).append(dict(bt, mrp=R(bt["mrp_p"]), days_left=days_left(bt)))
    for m in meds:
        m["batches"] = by.get(m["id"], [])
        m["qty"] = sum(x["qty"] for x in m["batches"] if x["days_left"] >= 0)
        last = c.execute("SELECT cost_p, mrp_p FROM batches WHERE medicine_id=? ORDER BY branch_id=? DESC, id DESC LIMIT 1", (m["id"], br["id"])).fetchone()
        m["last"] = {"cost": R(last[0]), "mrp": R(last[1])} if last else None
        m["rack"] = rack_for(c, br["id"], m["id"])
    return {"medicines": meds, "reasons": ADJUST_REASONS}


# ---------------------------------------------------------------- suppliers, POs, purchases
@route("GET", "/api/suppliers", "stock")
def api_suppliers(h, c, b, q):
    return rows(c.execute("SELECT * FROM suppliers ORDER BY name"))


@route("POST", "/api/suppliers", "stock")
def api_add_supplier(h, c, b, q):
    name = clean(b, "name", 100)
    need(name, "Supplier name required")
    cur = c.execute("INSERT INTO suppliers(name,phone,gstin,email) VALUES(?,?,?,?)", (name, clean(b, "phone", 20), clean(b, "gstin", 20), clean(b, "email", 100)))
    audit(c, h, "supplier.create", name)
    return {"ok": True, "id": cur.lastrowid}


@route("GET", "/api/purchase-orders", "stock")
def api_pos(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    out = rows(c.execute("SELECT po.*, s.name supplier FROM purchase_orders po LEFT JOIN suppliers s ON s.id=po.supplier_id WHERE po.branch_id=? ORDER BY po.id DESC LIMIT 60", (br["id"],)))
    for po in out:
        po["items"] = rows(c.execute("SELECT pi.*, m.name, m.pack_size FROM po_items pi JOIN medicines m ON m.id=pi.medicine_id WHERE po_id=?", (po["id"],)))
    return out


@route("POST", "/api/purchase-orders", "stock")
def api_create_po(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    items = [(as_int(i.get("medicine_id"), "medicine"), as_int(i.get("qty"), "quantity", 1)) for i in (b.get("items") or [])[:200]]
    need(items, "Add at least one medicine")

    def run():
        cur = c.execute("INSERT INTO purchase_orders(branch_id,supplier_id,created_at,status,user_id,note) VALUES(?,?,?,?,?,?)",
                        (br["id"], opt_num(b.get("supplier_id"), int), now_str(), "sent" if b.get("send") else "draft", h.user["id"], clean(b, "note", 300)))
        for mid, qty in items:
            med_row(c, mid)
            c.execute("INSERT INTO po_items(po_id,medicine_id,qty) VALUES(?,?,?)", (cur.lastrowid, mid, qty))
        audit(c, h, "po.create", f"PO-{cur.lastrowid} {len(items)} lines")
        return {"ok": True, "id": cur.lastrowid}
    return in_tx(c, run)


@route("POST", r"/api/purchase-orders/(\d+)/status", "stock")
def api_po_status(h, c, b, q, poid):
    st = clean(b, "status", 12)
    need(st in ("sent", "cancelled"), "Status must be sent or cancelled")
    c.execute("UPDATE purchase_orders SET status=? WHERE id=? AND branch_id=? AND status IN ('draft','sent')", (st, int(poid), h.branch))
    audit(c, h, "po.status", f"PO-{poid} {st}")
    return {"ok": True}


@route("POST", "/api/purchases", "stock")
def api_purchase(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    lines = (b.get("lines") or [])[:300]
    need(lines, "Add at least one line")
    po_id = opt_num(b.get("po_id"), int)

    def run():
        due = valid_day(clean(b, "due_date", 10), "payment due date") if b.get("due_date") else add_days(today(), 30)
        cur = c.execute("INSERT INTO purchases(branch_id,supplier_id,po_id,invoice_no,created_at,user_id,due_date) VALUES(?,?,?,?,?,?,?)",
                        (br["id"], opt_num(b.get("supplier_id"), int), po_id, clean(b, "invoice_no", 40), now_str(), h.user["id"], due))
        pid, total, gst = cur.lastrowid, 0, 0
        for ln in lines:
            m = med_row(c, as_int(ln.get("medicine_id"), "medicine"))
            unit = clean(ln, "unit", 6) or "unit"
            mult = m["pack_size"] if unit == "pack" else 1
            qty, free = as_int(ln.get("qty"), f"quantity of {m['name']}", 1) * mult, as_int(ln.get("free") or 0, "free quantity", 0) * mult
            cost, mrp = P(ln.get("cost"), "cost") // mult, P(ln.get("mrp"), "MRP") // mult
            exp = valid_day(clean(ln, "expiry", 10), "expiry")
            need(mrp, f"{m['name']}: MRP is required")
            need(cost <= mrp, f"{m['name']}: cost is higher than MRP. Check the invoice.")
            need(date.fromisoformat(exp) > date.today(), f"{m['name']}: this batch has already expired. Don't accept it.")
            rack = clean(ln, "rack", 12).upper() or rack_for(c, br["id"], m["id"])
            bc = c.execute("INSERT INTO batches(branch_id,medicine_id,batch,expiry,qty,mrp_p,cost_p,rack,purchase_id,received_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (br["id"], m["id"], clean(ln, "batch", 40), exp, qty + free, mrp, cost * qty // (qty + free), rack, pid, now_str()))
            move(c, h, {"id": bc.lastrowid, "branch_id": br["id"]}, qty + free, "purchase", f"GRN{pid}")
            total += cost * qty
            gst += round(cost * qty * m["gst_pct"] / 100)
            if po_id:
                c.execute("UPDATE po_items SET received=received+? WHERE po_id=? AND medicine_id=?", (qty, po_id, m["id"]))
        c.execute("UPDATE purchases SET total_p=?, gst_p=? WHERE id=?", (total, gst, pid))
        if po_id:
            left = c.execute("SELECT COUNT(*) FROM po_items WHERE po_id=? AND received<qty", (po_id,)).fetchone()[0]
            c.execute("UPDATE purchase_orders SET status=? WHERE id=?", ("partial" if left else "received", po_id))
        audit(c, h, "purchase.create", f"GRN{pid} invoice {clean(b, 'invoice_no', 40)} {rs(total)}")
        return {"ok": True, "id": pid, "total": R(total)}
    return in_tx(c, run)


# ---------------------------------------------------------------- supplier returns
@route("GET", "/api/supplier-returns", "stock")
def api_returns_list(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    out = rows(c.execute("SELECT r.*, s.name supplier FROM supplier_returns r LEFT JOIN suppliers s ON s.id=r.supplier_id WHERE r.branch_id=? ORDER BY r.id DESC LIMIT 50", (br["id"],)))
    for r in out:
        r["items"] = rows(c.execute("SELECT ri.*, bt.batch, m.name FROM supplier_return_items ri JOIN batches bt ON bt.id=ri.batch_id JOIN medicines m ON m.id=bt.medicine_id WHERE return_id=?", (r["id"],)))
    return out


@route("POST", "/api/supplier-returns", "stock")
def api_return_create(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    items = (b.get("items") or [])[:200]
    need(items, "Choose the batches to return")
    reason = clean(b, "reason", 30) or "expired"

    def run():
        cur = c.execute("INSERT INTO supplier_returns(branch_id,supplier_id,created_at,user_id,reason,status) VALUES(?,?,?,?,?,?)",
                        (br["id"], opt_num(b.get("supplier_id"), int), now_str(), h.user["id"], reason, "sent"))
        rid, total = cur.lastrowid, 0
        for it in items:
            bt = one(c, "SELECT * FROM batches WHERE id=? AND branch_id=?", (as_int(it.get("batch_id"), "batch"), br["id"]))
            need(bt, "Batch not found at this branch", 404)
            qty = as_int(it.get("qty"), "quantity", 1, bt["qty"])
            c.execute("UPDATE batches SET qty=qty-? WHERE id=?", (qty, bt["id"]))
            move(c, h, bt, -qty, "supplier_return", f"SR{rid}")
            c.execute("INSERT INTO supplier_return_items(return_id,batch_id,qty,cost_p) VALUES(?,?,?,?)", (rid, bt["id"], qty, bt["cost_p"]))
            total += qty * bt["cost_p"]
        c.execute("UPDATE supplier_returns SET total_p=? WHERE id=?", (total, rid))
        audit(c, h, "supplier_return.create", f"SR{rid} {reason} {rs(total)}")
        return {"ok": True, "id": rid, "total": R(total)}
    return in_tx(c, run)


@route("POST", r"/api/supplier-returns/(\d+)/credit", "stock")
def api_return_credit(h, c, b, q, rid):
    cn = clean(b, "credit_note_no", 40)
    need(cn, "Enter the supplier's credit note number")
    c.execute("UPDATE supplier_returns SET credit_note_no=?, status='credited' WHERE id=? AND branch_id=?", (cn, int(rid), h.branch))
    audit(c, h, "supplier_return.credit", f"SR{rid} credit note {cn}")
    return {"ok": True}


# ---------------------------------------------------------------- transfers, write-offs
@route("POST", "/api/transfers", "stock_admin")
def api_transfer(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    to = one(c, "SELECT * FROM branches WHERE id=?", (as_int(b.get("to_branch"), "destination"),))
    need(to and to["id"] != br["id"] and "pharmacy" in to["kind"] and to["active"], "Choose another active pharmacy branch")

    def run():
        bt = one(c, "SELECT * FROM batches WHERE id=? AND branch_id=?", (as_int(b.get("batch_id"), "batch"), br["id"]))
        need(bt, "Batch not found at this branch", 404)
        qty = as_int(b.get("qty"), "quantity", 1, bt["qty"])
        need(days_left(bt) >= 0, "Expired stock can't be transferred. Write it off.")
        c.execute("UPDATE batches SET qty=qty-? WHERE id=?", (qty, bt["id"]))
        ref = f"TR {br['code']}->{to['code']}"
        move(c, h, bt, -qty, "transfer_out", ref)
        nb = c.execute("INSERT INTO batches(branch_id,medicine_id,batch,expiry,opened,qty,mrp_p,cost_p,rack,received_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (to["id"], bt["medicine_id"], bt["batch"], bt["expiry"], bt["opened"], qty, bt["mrp_p"], bt["cost_p"], rack_for(c, to["id"], bt["medicine_id"]), now_str()))
        move(c, h, {"id": nb.lastrowid, "branch_id": to["id"]}, qty, "transfer_in", ref)
        audit(c, h, "stock.transfer", f"{ref} batch {bt['batch']} x{qty}")
        return {"ok": True}
    return in_tx(c, run)


@route("POST", "/api/writeoff", "stock")
def api_writeoff(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    reason = clean(b, "reason", 30)
    need(reason in ("expired", "damaged", "count_correction"), "Choose a reason")

    def run():
        bt = one(c, "SELECT * FROM batches WHERE id=? AND branch_id=?", (as_int(b.get("batch_id"), "batch"), br["id"]))
        need(bt, "Batch not found at this branch", 404)
        qty = as_int(b.get("qty"), "quantity", 1, bt["qty"])
        c.execute("UPDATE batches SET qty=qty-? WHERE id=?", (qty, bt["id"]))
        move(c, h, bt, -qty, "writeoff:" + reason, clean(b, "note", 100))
        audit(c, h, "stock.writeoff", f"batch {bt['batch']} x{qty} ({reason}) loss {rs(qty * bt['cost_p'])}")
        return {"ok": True}
    return in_tx(c, run)


# ---------------------------------------------------------------- cold chain
@route("GET", "/api/temp-logs", "stock")
def api_temps(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    logs = rows(c.execute("SELECT t.*, u.name uname FROM temp_logs t LEFT JOIN users u ON u.id=t.user_id WHERE t.branch_id=? ORDER BY t.id DESC LIMIT 120", (br["id"],)))
    today_logs = [x for x in logs if x["at"].startswith(today())]
    return {"logs": logs, "today_count": len(today_logs), "excursions": [x for x in logs if not x["ok"]][:20]}


@route("POST", "/api/temp-logs", "stock")
def api_temp_add(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    t = opt_num(b.get("temp_c"), float, "temperature")
    need(t is not None and -30 <= t <= 50, "Enter the fridge temperature in °C")
    fridge = clean(b, "fridge", 20) or "FRIDGE-1"
    ok = 1 if 2 <= t <= 8 else 0
    c.execute("INSERT INTO temp_logs(branch_id,at,fridge,temp_c,ok,user_id,note) VALUES(?,?,?,?,?,?,?)", (br["id"], now_str(), fridge, t, ok, h.user["id"], clean(b, "note", 200)))
    audit(c, h, "coldchain.log", f"{fridge} {t}°C{' OUT OF RANGE' if not ok else ''}")
    return {"ok": True, "in_range": bool(ok),
            "message": None if ok else f"{t}°C is outside 2–8°C. Move insulin and vaccines to another fridge and check the stock before selling."}


# ---------------------------------------------------------------- stock counts
@route("GET", "/api/stock-counts", "stock")
def api_counts(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    out = rows(c.execute("SELECT * FROM stock_counts WHERE branch_id=? ORDER BY id DESC LIMIT 20", (br["id"],)))
    for sc in out:
        sc["items"] = rows(c.execute("SELECT i.*, bt.batch, bt.rack, bt.expiry, m.name FROM stock_count_items i JOIN batches bt ON bt.id=i.batch_id "
                                     "JOIN medicines m ON m.id=bt.medicine_id WHERE count_id=? ORDER BY bt.rack, m.name", (sc["id"],)))
    return out


@route("POST", "/api/stock-counts", "stock")
def api_count_start(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    need(not one(c, "SELECT 1 FROM stock_counts WHERE branch_id=? AND status='open'", (br["id"],)), "A stock count is already open. Finish it first.")
    rack = clean(b, "rack", 12).upper()

    def run():
        cur = c.execute("INSERT INTO stock_counts(branch_id,created_at,user_id,status) VALUES(?,?,?,?)", (br["id"], now_str(), h.user["id"], "open"))
        sql = "SELECT * FROM batches WHERE branch_id=? AND qty>0" + (" AND rack LIKE ?" if rack else "")
        args = (br["id"], rack + "%") if rack else (br["id"],)
        n = 0
        for bt in rows(c.execute(sql, args)):
            c.execute("INSERT INTO stock_count_items(count_id,batch_id,system_qty) VALUES(?,?,?)", (cur.lastrowid, bt["id"], bt["qty"]))
            n += 1
        audit(c, h, "count.start", f"count {cur.lastrowid} {n} batches{' rack ' + rack if rack else ''}")
        return {"ok": True, "id": cur.lastrowid, "lines": n}
    return in_tx(c, run)


@route("POST", r"/api/stock-counts/(\d+)", "stock")
def api_count_update(h, c, b, q, cid):
    sc = one(c, "SELECT * FROM stock_counts WHERE id=? AND branch_id=?", (int(cid), h.branch))
    need(sc and sc["status"] == "open", "This count is closed", 400)
    for it in (b.get("items") or [])[:2000]:
        c.execute("UPDATE stock_count_items SET counted_qty=? WHERE id=? AND count_id=?", (as_int(it.get("counted"), "counted quantity", 0), as_int(it.get("id"), "line"), sc["id"]))
    if not b.get("close"):
        return {"ok": True}

    def run():
        diff_value, n = 0, 0
        for it in rows(c.execute("SELECT i.*, bt.qty cur_qty, bt.cost_p, bt.branch_id FROM stock_count_items i JOIN batches bt ON bt.id=i.batch_id WHERE count_id=?", (sc["id"],))):
            if it["counted_qty"] is None:
                continue
            # adjust against the system quantity at count start, keeping sales made since then
            delta = it["counted_qty"] - it["system_qty"]
            if delta:
                newq = max(0, it["cur_qty"] + delta)
                c.execute("UPDATE batches SET qty=? WHERE id=?", (newq, it["batch_id"]))
                move(c, h, {"id": it["batch_id"], "branch_id": it["branch_id"]}, newq - it["cur_qty"], "count_adjust", f"COUNT{sc['id']}")
                diff_value += delta * it["cost_p"]
                n += 1
        c.execute("UPDATE stock_counts SET status='closed', closed_at=? WHERE id=?", (now_str(), sc["id"]))
        audit(c, h, "count.close", f"count {sc['id']} {n} adjustments, value {'+' if diff_value >= 0 else '-'}{rs(abs(diff_value))}")
        return {"ok": True, "adjusted": n, "value": R(diff_value)}
    return in_tx(c, run)


# ---------------------------------------------------------------- billing
def offline_time(s):
    """A bill saved offline keeps the time it was made, if that is within the last 72 hours."""
    from datetime import datetime
    try:
        t = datetime.strptime(s, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return now_str()
    delta = (datetime.now() - t).total_seconds()
    return s if -300 <= delta <= 72 * 3600 else now_str()


def create_bill(c, h, b):
    br = need_branch(h, c, "pharmacy")
    key = clean(b, "offline_key", 64) or None
    if key:
        prev = one(c, "SELECT id,bill_no,total_p FROM bills WHERE offline_key=?", (key,))
        if prev:
            return {"ok": True, "id": prev["id"], "bill_no": prev["bill_no"], "total": R(prev["total_p"]), "duplicate": True}
    items = (b.get("items") or [])[:100]
    need(items, "Add at least one medicine")
    pay = clean(b, "pay_mode", 10) or "cash"
    need(pay in PAY_MODES, "Invalid payment mode")
    patient = one(c, "SELECT * FROM patients WHERE id=?", (as_int(b["patient_id"], "patient"),)) if b.get("patient_id") else None
    if b.get("patient_id"):
        need(patient, "Patient not found", 404)
    visit = None
    if b.get("visit_id"):
        visit = one(c, "SELECT v.*, u.name dname, u.reg_no dreg FROM visits v LEFT JOIN users u ON u.id=v.doctor_id WHERE v.id=?", (as_int(b["visit_id"], "prescription"),))
        need(visit and patient and visit["patient_id"] == patient["id"], "Prescription does not belong to this patient")
    need(pay != "credit" or patient, "Credit bills need a registered patient")
    doc_name = visit["dname"] if visit else clean(b, "doctor_name", 100)
    doc_reg = visit["dreg"] if visit else clean(b, "doctor_reg", 40)

    def run():
        lines = []
        for it in items:
            m = one(c, "SELECT * FROM medicines WHERE id=? AND active=1", (as_int(it.get("medicine_id"), "medicine"),))
            need(m, "Medicine not found", 404)
            unit = clean(it, "unit", 6) or "unit"
            qty = as_int(it.get("qty"), f"quantity of {m['name']}", 1) * (m["pack_size"] if unit == "strip" else 1)
            rx = None
            if it.get("rx_item_id"):
                rx = one(c, "SELECT * FROM rx_items WHERE id=?", (as_int(it["rx_item_id"], "rx item"),))
                need(rx and visit and rx["visit_id"] == visit["id"] and rx["medicine_id"] == m["id"], f"{m['name']} is not on this prescription")
                need(qty <= rx["qty"] - rx["dispensed"], f"{m['name']}: only {rx['qty'] - rx['dispensed']} left to dispense on this prescription")
            lines.append((m, qty, rx))
        for m, _, _ in lines:
            need(m["schedule"] != "X", f"{m['name']} is Schedule X. Sell it through the narcotics register, not here.")
            if m["schedule"] in ("H", "H1"):
                need(visit or (doc_name and doc_reg), f"{m['name']} is Schedule {m['schedule']}. Link the patient's prescription, or enter the prescribing doctor's name and registration number.")
            if m["schedule"] == "H1":
                need(patient, f"{m['name']} is Schedule H1. Register the patient for the H1 register.")
        warnings = []
        if patient:
            full = [{"med": m, "freq": rx["freq"] if rx else "", "dose": rx["dose"] if rx else "", "days": rx["days"] if rx else None} for m, _, rx in lines]
            warnings = safety_check(patient, full, current_meds(c, patient["id"]), latest_creatinine(c, patient["id"]))
        else:
            warnings = safety_check(None, [{"med": m} for m, _, _ in lines])
        if warnings and not b.get("override"):
            raise ApiError(409, "Safety warnings need the pharmacist's confirmation", warnings=warnings)
        alloc, sub = [], 0
        for m, qty, rx in lines:
            bs = usable_batches(c, br["id"], m["id"])
            avail = sum(x["qty"] for x in bs)
            if avail < qty:
                else_ = [f"{o['name']} ({usable_stock(c, o['id']).get(m['id'], 0)})" for o in pharmacies(c) if o["id"] != br["id"] and usable_stock(c, o["id"]).get(m["id"])]
                raise ApiError(400, f"Only {avail} {m['name']} in stock here." + (f" Available at {', '.join(else_)}." if else_ else ""))
            left = qty
            for bt in bs:
                if not left:
                    break
                take = min(left, bt["qty"])
                alloc.append((m, bt, take, rx))
                sub += take * bt["mrp_p"]
                left -= take
        disc = min(P(b.get("discount"), "discount"), sub)
        check_discount(c, h, disc, sub)
        n = c.execute("SELECT COUNT(*) FROM bills WHERE branch_id=?", (br["id"],)).fetchone()[0] + 1
        bill_no = f"{br['code']}-{n:06d}"
        cur = c.execute("INSERT INTO bills(branch_id,bill_no,created_at,patient_id,customer,visit_id,admission_id,doctor_name,doctor_reg,subtotal_p,discount_p,total_p,pay_mode,user_id,offline_key) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (br["id"], bill_no, offline_time(clean(b, "created_at", 16)), patient["id"] if patient else None,
                         patient["name"] if patient else (clean(b, "customer", 100) or "Walk-in"), visit["id"] if visit else None, opt_num(b.get("admission_id"), int),
                         doc_name, doc_reg, sub, disc, sub - disc, pay, h.user["id"], key))
        bill_id, gst_total, dleft = cur.lastrowid, 0, disc
        for i, (m, bt, take, rx) in enumerate(alloc):
            gross = take * bt["mrp_p"]
            share = dleft if i == len(alloc) - 1 else (disc * gross // sub if sub else 0)
            dleft -= share
            net = gross - share
            gst = net - round(net / (1 + m["gst_pct"] / 100))
            gst_total += gst
            c.execute("UPDATE batches SET qty=qty-? WHERE id=?", (take, bt["id"]))
            move(c, h, bt, -take, "sale", bill_no)
            c.execute("INSERT INTO bill_items(bill_id,medicine_id,batch_id,qty,mrp_p,gst_pct,net_p,gst_p,rx_item_id) VALUES(?,?,?,?,?,?,?,?,?)",
                      (bill_id, m["id"], bt["id"], take, bt["mrp_p"], m["gst_pct"], net, gst, rx["id"] if rx else None))
            if rx:
                c.execute("UPDATE rx_items SET dispensed=dispensed+? WHERE id=?", (take, rx["id"]))
        c.execute("UPDATE bills SET gst_p=? WHERE id=?", (gst_total, bill_id))
        audit(c, h, "bill.create", f"{bill_no} {rs(sub - disc)} {pay}" + (" (synced from offline)" if key else "")
              + (" OVERRIDE: " + " ".join(w["text"] for w in warnings) if warnings else ""))
        return {"ok": True, "id": bill_id, "bill_no": bill_no, "total": R(sub - disc)}
    return in_tx(c, run)


@route("POST", "/api/bills", "billing")
def api_bill(h, c, b, q):
    r = create_bill(c, h, b)
    if b.get("patient_id") and not r.get("duplicate"):
        from .m_portal import share
        br = one(c, "SELECT name FROM branches WHERE id=?", (h.branch,))
        r["shared"] = share(c, as_int(b["patient_id"], "patient"), f"{br['name']}: your pharmacy bill {r['bill_no']} for Rs {r['total']:.2f} is ready.", h.user["id"], pdf=("bill", r["id"]))
    return r


@route("GET", "/api/bills", "billing")
def api_bills(h, c, b, q):
    br = need_branch(h, c, "pharmacy")
    return [{"id": r["id"], "bill_no": r["bill_no"], "created_at": r["created_at"], "customer": r["customer"], "patient_code": pcode(r["patient_id"]) if r["patient_id"] else "",
             "total": R(r["total_p"]), "returned": R(r["returned_p"]), "pay_mode": r["pay_mode"]}
            for r in rows(c.execute("SELECT * FROM bills WHERE branch_id=? AND created_at LIKE ? ORDER BY id DESC", (br["id"], valid_day(qget(q, "date", today())) + "%")))]


def bill_detail(c, bid):
    bl = one(c, "SELECT b.*, br.name branch, br.address baddr, br.phone bphone, br.gstin, br.dl_no, u.name cashier FROM bills b JOIN branches br ON br.id=b.branch_id "
                "LEFT JOIN users u ON u.id=b.user_id WHERE b.id=?", (bid,))
    need(bl, "Bill not found", 404)
    items = rows(c.execute("SELECT bi.*, m.name, m.schedule, m.hsn, m.pack_size, bt.batch, bt.expiry, bt.rack FROM bill_items bi JOIN medicines m ON m.id=bi.medicine_id "
                           "JOIN batches bt ON bt.id=bi.batch_id WHERE bill_id=?", (bid,)))
    out = dict(bl, subtotal=R(bl["subtotal_p"]), discount=R(bl["discount_p"]), gst=R(bl["gst_p"]), total=R(bl["total_p"]), returned=R(bl["returned_p"]),
               patient_code=pcode(bl["patient_id"]) if bl["patient_id"] else "")
    out["items"] = [dict(i, mrp=R(i["mrp_p"]), net=R(i["net_p"]), gst=R(i["gst_p"])) for i in items]
    return out


@route("GET", r"/api/bills/(\d+)", "patients_read")
def api_bill_get(h, c, b, q, bid):
    d = bill_detail(c, int(bid))
    need(d["branch_id"] == h.branch or all_access(h.user), "Bill belongs to another branch", 403)
    return d


@route("POST", r"/api/bills/(\d+)/return", "billing")
def api_bill_return(h, c, b, q, bid):
    def run():
        bl = one(c, "SELECT * FROM bills WHERE id=? AND branch_id=?", (int(bid), h.branch))
        need(bl, "Bill not found at this branch", 404)
        refund = 0
        for it in (b.get("items") or []):
            qty = as_int(it.get("qty") or 0, "return quantity", 0)
            if not qty:
                continue
            bi = one(c, "SELECT * FROM bill_items WHERE id=? AND bill_id=?", (as_int(it.get("bill_item_id"), "item"), bl["id"]))
            need(bi and qty <= bi["qty"] - bi["returned"], "Return quantity is more than was sold")
            bt = one(c, "SELECT * FROM batches WHERE id=?", (bi["batch_id"],))
            if days_left(bt) >= 0:
                c.execute("UPDATE batches SET qty=qty+? WHERE id=?", (qty, bt["id"]))
                move(c, h, bt, qty, "return", bl["bill_no"])
            amt = bi["net_p"] * qty // bi["qty"]
            refund += amt
            c.execute("UPDATE bill_items SET returned=returned+? WHERE id=?", (qty, bi["id"]))
            if bi["rx_item_id"]:
                c.execute("UPDATE rx_items SET dispensed=MAX(0,dispensed-?) WHERE id=?", (qty, bi["rx_item_id"]))
        need(refund, "Nothing to return")
        c.execute("UPDATE bills SET returned_p=returned_p+? WHERE id=?", (refund, bl["id"]))
        n = c.execute("SELECT COUNT(*) FROM credit_notes WHERE branch_id=?", (h.branch,)).fetchone()[0] + 1
        br = one(c, "SELECT code FROM branches WHERE id=?", (h.branch,))
        cn = f"{br['code']}/CN/{n:05d}"
        c.execute("INSERT INTO credit_notes(branch_id,cn_no,bill_id,amount_p,reason,at,user_id,mode) VALUES(?,?,?,?,?,?,?,?)",
                  (h.branch, cn, bl["id"], refund, clean(b, "reason", 200), now_str(), h.user["id"], "cash" if bl["pay_mode"] != "credit" else "credit"))
        audit(c, h, "bill.return", f"{bl['bill_no']} refund {rs(refund)} credit note {cn}")
        return {"ok": True, "refund": R(refund), "credit_note": cn}
    return in_tx(c, run)


# ---------------------------------------------------------------- registers
def sales_csv(c, bid, day):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Bill no", "Date time", "Patient ID", "Customer", "Medicine", "Schedule", "HSN", "Batch", "Qty", "Returned", "MRP", "GST %", "Net", "GST", "Payment", "Doctor"])
    for r in c.execute("SELECT b.bill_no,b.created_at,b.patient_id,b.customer,m.name,m.schedule,m.hsn,bt.batch,bi.qty,bi.returned,bi.mrp_p,bi.gst_pct,bi.net_p,bi.gst_p,b.pay_mode,b.doctor_name "
                       "FROM bill_items bi JOIN bills b ON b.id=bi.bill_id JOIN medicines m ON m.id=bi.medicine_id JOIN batches bt ON bt.id=bi.batch_id "
                       "WHERE b.branch_id=? AND b.created_at LIKE ? ORDER BY b.id", (bid, day + "%")):
        w.writerow([r[0], r[1], pcode(r[2]) if r[2] else "", r[3], r[4], r[5], r[6] or "", r[7], r[8], r[9], R(r[10]), r[11], R(r[12]), R(r[13]), r[14], r[15] or ""])
    return buf.getvalue()


def h1_csv(c, bid, start, end):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Bill no", "Patient", "Address", "Phone", "Prescriber", "Prescriber reg. no", "Drug", "Batch", "Quantity"])
    for r in c.execute("SELECT b.created_at,b.bill_no,p.name,p.address,p.phone,b.doctor_name,b.doctor_reg,m.name,bt.batch,bi.qty-bi.returned FROM bill_items bi "
                       "JOIN bills b ON b.id=bi.bill_id JOIN medicines m ON m.id=bi.medicine_id JOIN batches bt ON bt.id=bi.batch_id LEFT JOIN patients p ON p.id=b.patient_id "
                       "WHERE m.schedule='H1' AND b.branch_id=? AND substr(b.created_at,1,10) BETWEEN ? AND ? ORDER BY b.id", (bid, start, end)):
        w.writerow(list(r))
    return buf.getvalue()
