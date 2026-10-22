"""Accounts: expenses, doctor payouts, branch profit and loss, GST (GSTR-1 style) export,
Tally XML export."""
import csv
import io
import re
from datetime import date
from xml.sax.saxutils import escape

from .core import (P, R, add_days, all_access, as_int, audit, clean, in_tx, need, need_branch, now_str, one, opt_num, qget, route, rows, rs,
                   today, valid_day)
from .refdata import EXPENSE_CATEGORIES

PAYOUT_CATS = ("Consultation", "Procedure", "Inpatient")


def period_range(period):
    need(re.fullmatch(r"\d{4}-\d{2}", period or ""), "Period must be YYYY-MM")
    y, m = map(int, period.split("-"))
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start.isoformat(), add_days(end.isoformat(), -1)


def branches_in_scope(c, h):
    if h.branch:
        return [h.branch]
    need(all_access(h.user), "Choose a branch")
    return [r[0] for r in c.execute("SELECT id FROM branches WHERE active=1")]


# ---------------------------------------------------------------- expenses
@route("GET", "/api/expenses", "accounts")
def api_expenses(h, c, b, q):
    start, end = period_range(qget(q, "period", today()[:7]))
    bids = branches_in_scope(c, h)
    out = rows(c.execute(f"SELECT e.*, br.code, u.name uname FROM expenses e JOIN branches br ON br.id=e.branch_id LEFT JOIN users u ON u.id=e.user_id "
                         f"WHERE e.branch_id IN ({','.join('?' * len(bids))}) AND e.day BETWEEN ? AND ? ORDER BY e.day DESC, e.id DESC", (*bids, start, end)))
    return {"categories": EXPENSE_CATEGORIES, "rows": [dict(e, amount=R(e["amount_p"])) for e in out], "total": R(sum(e["amount_p"] for e in out))}


@route("POST", "/api/expenses", "accounts")
def api_add_expense(h, c, b, q):
    br = need_branch(h, c)
    cat = clean(b, "category", 40)
    need(cat in EXPENSE_CATEGORIES, "Choose a category")
    amt = P(b.get("amount"), "amount")
    need(amt > 0, "Enter the amount")
    day = valid_day(clean(b, "day", 10) or today())
    mode = clean(b, "mode", 10) or "cash"
    need(mode in ("cash", "upi", "card", "bank"), "Invalid payment mode")
    c.execute("INSERT INTO expenses(branch_id,day,category,amount_p,mode,vendor,note,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
              (br["id"], day, cat, amt, mode, clean(b, "vendor", 100), clean(b, "note", 300), h.user["id"], now_str()))
    audit(c, h, "expense.add", f"{br['code']} {day} {cat} {rs(amt)} {mode}")
    return {"ok": True}


# ---------------------------------------------------------------- doctor payouts
def doctor_earnings(c, period):
    start, end = period_range(period)
    out = []
    for d in rows(c.execute("SELECT * FROM users WHERE role IN ('doctor','owner') AND payout_pct>0 ORDER BY name")):
        billed = c.execute(f"SELECT COALESCE(SUM(ii.amount_p * (1.0 - i.discount_p * 1.0 / NULLIF(i.sub_p,0))),0) FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id "
                           f"WHERE i.doctor_id=? AND i.cancelled_at IS NULL AND substr(i.created_at,1,10) BETWEEN ? AND ? AND ii.cat IN ({','.join('?' * len(PAYOUT_CATS))})",
                           (d["id"], start, end, *PAYOUT_CATS)).fetchone()[0] or 0
        share = round(billed * d["payout_pct"] / 100)
        paid = one(c, "SELECT * FROM payouts WHERE doctor_id=? AND period=?", (d["id"], period))
        seen = c.execute("SELECT COUNT(*) FROM visits WHERE doctor_id=? AND status='done' AND substr(completed_at,1,10) BETWEEN ? AND ?", (d["id"], start, end)).fetchone()[0]
        out.append({"doctor_id": d["id"], "name": d["name"], "pct": d["payout_pct"], "patients": seen, "billed": R(round(billed)), "share": R(share), "share_p": share,
                    "paid": R(paid["amount_p"]) if paid else None, "paid_at": paid["paid_at"] if paid else None})
    return out


@route("GET", "/api/payouts", "accounts")
def api_payouts(h, c, b, q):
    return doctor_earnings(c, qget(q, "period", today()[:7]))


@route("POST", "/api/payouts", "accounts")
def api_pay_doctor(h, c, b, q):
    br = need_branch(h, c)
    period = clean(b, "period", 7)
    did = as_int(b.get("doctor_id"), "doctor")
    row = next((x for x in doctor_earnings(c, period) if x["doctor_id"] == did), None)
    need(row, "This doctor has no payout share set")
    need(row["paid"] is None, "This month's payout is already recorded")
    amt = P(b.get("amount"), "amount") if b.get("amount") not in (None, "") else row["share_p"]
    need(amt > 0, "Nothing to pay")
    mode = clean(b, "mode", 10) or "bank"

    def run():
        c.execute("INSERT INTO payouts(doctor_id,period,amount_p,paid_at,mode,note,user_id) VALUES(?,?,?,?,?,?,?)", (did, period, amt, now_str(), mode, clean(b, "note", 200), h.user["id"]))
        c.execute("INSERT INTO expenses(branch_id,day,category,amount_p,mode,vendor,note,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (br["id"], today(), "Doctor payout", amt, mode, row["name"], f"Payout {period} ({row['pct']:g}% of {rs(round(row['billed'] * 100))})", h.user["id"], now_str()))
        audit(c, h, "payout.pay", f"{row['name']} {period} {rs(amt)}")
    in_tx(c, run)
    return {"ok": True}


# ---------------------------------------------------------------- profit and loss
def pnl(c, bid, start, end):
    hosp = c.execute("SELECT COALESCE(SUM(total_p),0) FROM invoices WHERE branch_id=? AND cancelled_at IS NULL AND substr(created_at,1,10) BETWEEN ? AND ?", (bid, start, end)).fetchone()[0]
    pharm = c.execute("SELECT COALESCE(SUM(total_p-returned_p),0), COALESCE(SUM(gst_p),0) FROM bills WHERE branch_id=? AND substr(created_at,1,10) BETWEEN ? AND ?", (bid, start, end)).fetchone()
    cogs = c.execute("SELECT COALESCE(SUM((bi.qty-bi.returned)*bt.cost_p),0) FROM bill_items bi JOIN bills b ON b.id=bi.bill_id JOIN batches bt ON bt.id=bi.batch_id "
                     "WHERE b.branch_id=? AND substr(b.created_at,1,10) BETWEEN ? AND ?", (bid, start, end)).fetchone()[0]
    ward = c.execute("SELECT COALESCE(SUM(bt.cost_p * -m.change),0) FROM stock_moves m JOIN batches bt ON bt.id=m.batch_id WHERE m.branch_id=? AND m.reason='ward_issue' AND substr(m.at,1,10) BETWEEN ? AND ?",
                     (bid, start, end)).fetchone()[0]
    writeoff = c.execute("SELECT COALESCE(SUM(bt.cost_p * -m.change),0) FROM stock_moves m JOIN batches bt ON bt.id=m.batch_id WHERE m.branch_id=? AND m.reason LIKE 'writeoff:%' AND substr(m.at,1,10) BETWEEN ? AND ?",
                         (bid, start, end)).fetchone()[0]
    exp = {r[0]: r[1] for r in c.execute("SELECT category, SUM(amount_p) FROM expenses WHERE branch_id=? AND day BETWEEN ? AND ? GROUP BY category", (bid, start, end))}
    revenue = hosp + pharm[0] - pharm[1]
    costs = cogs + ward + writeoff + sum(exp.values())
    return {"hospital": R(hosp), "pharmacy_net_of_gst": R(pharm[0] - pharm[1]), "pharmacy_gst": R(pharm[1]), "revenue": R(revenue),
            "cogs": R(cogs + ward), "stock_writeoffs": R(writeoff), "expenses": {k: R(v) for k, v in sorted(exp.items())}, "expenses_total": R(sum(exp.values())),
            "profit": R(revenue - costs), "margin": round((revenue - costs) / revenue * 100, 1) if revenue else None}


@route("GET", "/api/pnl", "accounts")
def api_pnl(h, c, b, q):
    start, end = period_range(qget(q, "period", today()[:7]))
    out = []
    for bid in branches_in_scope(c, h):
        br = one(c, "SELECT code,name FROM branches WHERE id=?", (bid,))
        out.append(dict(pnl(c, bid, start, end), code=br["code"], branch=br["name"]))
    tot = {k: round(sum(x[k] for x in out), 2) for k in ("hospital", "pharmacy_net_of_gst", "pharmacy_gst", "revenue", "cogs", "stock_writeoffs", "expenses_total", "profit")}
    tot["margin"] = round(tot["profit"] / tot["revenue"] * 100, 1) if tot["revenue"] else None
    return {"start": start, "end": end, "branches": out, "total": tot}


# ---------------------------------------------------------------- GST
def gst_rows(c, bid, start, end):
    rate, hsn = {}, {}
    for r in rows(c.execute("SELECT bi.gst_pct, m.hsn, m.name, bi.qty-bi.returned q, bi.net_p * (bi.qty-bi.returned) * 1.0 / bi.qty net, bi.gst_p * (bi.qty-bi.returned) * 1.0 / bi.qty gst "
                            "FROM bill_items bi JOIN bills b ON b.id=bi.bill_id JOIN medicines m ON m.id=bi.medicine_id WHERE b.branch_id=? AND substr(b.created_at,1,10) BETWEEN ? AND ?",
                            (bid, start, end))):
        taxable = r["net"] - r["gst"]
        x = rate.setdefault(r["gst_pct"], {"rate": r["gst_pct"], "taxable": 0, "cgst": 0, "sgst": 0})
        x["taxable"] += taxable
        x["cgst"] += r["gst"] / 2
        x["sgst"] += r["gst"] / 2
        key = r["hsn"] or "3004"
        y = hsn.setdefault((key, r["gst_pct"]), {"hsn": key, "rate": r["gst_pct"], "qty": 0, "taxable": 0, "tax": 0})
        y["qty"] += r["q"]
        y["taxable"] += taxable
        y["tax"] += r["gst"]
    for r in rows(c.execute("SELECT ii.gst_pct, ii.amount_p FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id WHERE i.branch_id=? AND i.cancelled_at IS NULL "
                            "AND ii.gst_pct>0 AND substr(i.created_at,1,10) BETWEEN ? AND ?", (bid, start, end))):
        tax = r["amount_p"] - r["amount_p"] / (1 + r["gst_pct"] / 100)
        x = rate.setdefault(r["gst_pct"], {"rate": r["gst_pct"], "taxable": 0, "cgst": 0, "sgst": 0})
        x["taxable"] += r["amount_p"] - tax
        x["cgst"] += tax / 2
        x["sgst"] += tax / 2
    itc = c.execute("SELECT COALESCE(SUM(gst_p),0) FROM purchases WHERE branch_id=? AND substr(created_at,1,10) BETWEEN ? AND ?", (bid, start, end)).fetchone()[0]
    exempt = c.execute("SELECT COALESCE(SUM(ii.amount_p),0) FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id WHERE i.branch_id=? AND i.cancelled_at IS NULL "
                       "AND ii.gst_pct=0 AND substr(i.created_at,1,10) BETWEEN ? AND ?", (bid, start, end)).fetchone()[0]
    rnd = lambda d: {k: (round(v / 100, 2) if k in ("taxable", "cgst", "sgst", "tax") else v) for k, v in d.items()}
    return {"b2cs": [rnd(x) for x in sorted(rate.values(), key=lambda x: x["rate"])], "hsn": [rnd(x) for x in sorted(hsn.values(), key=lambda x: (x["hsn"], x["rate"]))],
            "exempt_services": R(exempt), "input_tax_purchases": R(itc)}


@route("GET", "/api/gst", "accounts")
def api_gst(h, c, b, q):
    br = need_branch(h, c)
    start, end = period_range(qget(q, "period", today()[:7]))
    out = dict(gst_rows(c, br["id"], start, end), branch=br["name"], gstin=br["gstin"], period=qget(q, "period", today()[:7]))
    if qget(q, "format") == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["GSTR-1 working file", br["name"], br["gstin"] or "GSTIN not set", out["period"]])
        w.writerow([])
        w.writerow(["B2CS (intra-state)", "Rate %", "Taxable value", "CGST", "SGST"])
        for x in out["b2cs"]:
            w.writerow(["", x["rate"], x["taxable"], x["cgst"], x["sgst"]])
        w.writerow([])
        w.writerow(["HSN summary", "HSN", "Rate %", "Quantity (units)", "Taxable value", "Total tax"])
        for x in out["hsn"]:
            w.writerow(["", x["hsn"], x["rate"], x["qty"], x["taxable"], x["tax"]])
        w.writerow([])
        w.writerow(["Exempt healthcare services", out["exempt_services"]])
        w.writerow(["Input tax on purchases (check against GSTR-2B)", out["input_tax_purchases"]])
        h.download = (f"GSTR1-{br['code']}-{out['period']}.csv", buf.getvalue(), "text/csv")
        return None
    return out


# ---------------------------------------------------------------- Tally
@route("GET", "/api/tally", "accounts")
def api_tally(h, c, b, q):
    """Day-wise sales and receipt vouchers in Tally XML. Ledger names follow common defaults;
    rename them here or create matching ledgers in Tally before import."""
    br = need_branch(h, c)
    start, end = period_range(qget(q, "period", today()[:7]))
    company = clean({"x": qget(q, "company")}, "x", 100) or br["name"]
    vouchers = []
    d = start
    while d <= end:
        hosp = c.execute("SELECT COALESCE(SUM(total_p),0) FROM invoices WHERE branch_id=? AND cancelled_at IS NULL AND created_at LIKE ?", (br["id"], d + "%")).fetchone()[0]
        ph = c.execute("SELECT COALESCE(SUM(total_p-returned_p),0), COALESCE(SUM(gst_p),0) FROM bills WHERE branch_id=? AND created_at LIKE ?", (br["id"], d + "%")).fetchone()
        if hosp or ph[0]:
            ds = d.replace("-", "")
            ent = []
            if hosp:
                ent.append(("Hospital Services Income", hosp))
            if ph[0]:
                ent.append(("Pharmacy Sales", ph[0] - ph[1]))
                if ph[1]:
                    ent.append(("Output CGST", ph[1] // 2))
                    ent.append(("Output SGST", ph[1] - ph[1] // 2))
            total = sum(a for _, a in ent)
            lines = "".join(f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(n)}</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>{R(a):.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>" for n, a in ent)
            vouchers.append(f"<TALLYMESSAGE xmlns:UDF=\"TallyUDF\"><VOUCHER VCHTYPE=\"Sales\" ACTION=\"Create\"><DATE>{ds}</DATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>"
                            f"<VOUCHERNUMBER>{br['code']}-{ds}</VOUCHERNUMBER><NARRATION>Day sales {escape(br['name'])} {d}</NARRATION>"
                            f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>Cash and Bank Collections</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-{R(total):.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>"
                            f"{lines}</VOUCHER></TALLYMESSAGE>")
        d = add_days(d, 1)
    for e in rows(c.execute("SELECT * FROM expenses WHERE branch_id=? AND day BETWEEN ? AND ?", (br["id"], start, end))):
        ds = e["day"].replace("-", "")
        vouchers.append(f"<TALLYMESSAGE xmlns:UDF=\"TallyUDF\"><VOUCHER VCHTYPE=\"Payment\" ACTION=\"Create\"><DATE>{ds}</DATE><VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>"
                        f"<NARRATION>{escape(e['category'])} {escape(e['vendor'] or '')} {escape(e['note'] or '')}</NARRATION>"
                        f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(e['category'])}</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-{R(e['amount_p']):.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>"
                        f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{'Cash' if e['mode'] == 'cash' else 'Bank'}</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>{R(e['amount_p']):.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>"
                        f"</VOUCHER></TALLYMESSAGE>")
    xml = (f"<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME>"
           f"<STATICVARIABLES><SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC><REQUESTDATA>{''.join(vouchers)}</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    audit(c, h, "tally.export", f"{br['code']} {start}..{end} {len(vouchers)} vouchers")
    h.download = (f"tally-{br['code']}-{start[:7]}.xml", xml, "application/xml")
    return None
