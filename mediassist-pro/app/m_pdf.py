"""PDF documents patients keep on their phone: lab report, pharmacy bill, hospital bill and prescription,
on the branch letterhead. A small PDF writer in plain Python (standard Helvetica fonts, A4), so it needs no
extra packages and runs anywhere the server runs. Rupees are written as "Rs." because the standard PDF fonts
have no rupee sign."""
import re
import zlib
from datetime import datetime

from .core import R, all_access, get_settings, need, now_str, one, pcode, qget, route, rows

# Helvetica / Helvetica-Bold character widths (1/1000 em) for ASCII 32..126, from the standard font metrics
_W = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667,
      611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556,
      278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_WB = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + [333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667,
       611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556,
       333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]

TEAL, INK, MUTED, LINE, SOFT, RED, AMBER = (0.06, 0.37, 0.38), (0.07, 0.15, 0.17), (0.42, 0.49, 0.51), (0.82, 0.86, 0.85), (0.93, 0.96, 0.95), (0.72, 0.16, 0.12), (0.6, 0.36, 0.0)


def _clean(s):
    s = str("" if s is None else s).replace("₹", "Rs.").replace("–", "-").replace("—", "-").replace("·", "-").replace("’", "'").replace("“", '"').replace("”", '"')
    return s.encode("cp1252", "replace").decode("cp1252")


class Pdf:
    W, H, M = 595.28, 841.89, 40

    def __init__(self, title):
        self.title, self.pages = title, []
        self.new_page()

    def new_page(self):
        self.ops = []
        self.pages.append(self.ops)
        self.y = self.H - self.M

    # ---- primitives (y is the text baseline / top of the shape, measured from the bottom like PDF) ----
    def width(self, s, size=10, bold=False):
        t = _W if not bold else _WB
        return sum(t[ord(ch) - 32] if 32 <= ord(ch) <= 126 else 556 for ch in _clean(s)) * size / 1000

    def text(self, x, y, s, size=10, bold=False, color=INK, align="left"):
        s = _clean(s)
        if align == "right":
            x -= self.width(s, size, bold)
        elif align == "center":
            x -= self.width(s, size, bold) / 2
        esc = s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        self.ops.append(f"BT /{'F2' if bold else 'F1'} {size} Tf {color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg {x:.2f} {y:.2f} Td ({esc}) Tj ET")

    def rect(self, x, y, w, h, fill=None, stroke=None, lw=0.6):
        if fill:
            self.ops.append(f"{fill[0]:.3f} {fill[1]:.3f} {fill[2]:.3f} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")
        if stroke:
            self.ops.append(f"{lw} w {stroke[0]:.3f} {stroke[1]:.3f} {stroke[2]:.3f} RG {x:.2f} {y:.2f} {w:.2f} {h:.2f} re S")

    def line(self, x1, y1, x2, y2, color=LINE, lw=0.6):
        self.ops.append(f"{lw} w {color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def wrap(self, s, width, size=10, bold=False):
        out = []
        for para in _clean(s).split("\n"):
            cur = ""
            for word in para.split(" "):
                trial = (cur + " " + word).strip()
                if self.width(trial, size, bold) <= width or not cur:
                    cur = trial
                else:
                    out.append(cur)
                    cur = word
            out.append(cur)
        return out

    # ---- layout helpers ----
    def need_space(self, h):
        if self.y - h < self.M + 30:
            self.new_page()
            self.text(self.M, self.y - 4, self.title, 9, True, MUTED)
            self.y -= 22

    def para(self, s, size=10, bold=False, color=INK, gap=4, indent=0):
        for ln in self.wrap(s, self.W - 2 * self.M - indent, size, bold):
            self.need_space(size + 3)
            self.text(self.M + indent, self.y - size, ln, size, bold, color)
            self.y -= size + 3
        self.y -= gap

    def table(self, cols, data, size=9, head_fill=SOFT, row_style=None):
        """cols: [(title, width, align)]; data: list of rows (lists of strings). Wraps long cells; repeats the header on new pages."""
        x0, pad = self.M, 4

        def header():
            self.need_space(size + 10)
            self.rect(x0, self.y - size - 8, sum(c[1] for c in cols), size + 8, fill=head_fill)
            x = x0
            for title, w, al in cols:
                self.text(x + (w - pad if al == "right" else pad), self.y - size - 3, title.upper(), size - 1.5, True, MUTED, "right" if al == "right" else "left")
                x += w
            self.y -= size + 8
        header()
        for i, r in enumerate(data):
            st = (row_style or (lambda i, r: {}))(i, r)
            cells = [self.wrap(v, w - 2 * pad, size, st.get("bold", False)) for v, (_, w, _) in zip(r, cols)]
            h = max(len(cl) for cl in cells) * (size + 3) + 6
            if self.y - h < self.M + 30:
                self.new_page()
                self.text(self.M, self.y - 4, self.title, 9, True, MUTED)
                self.y -= 22
                header()
            x = x0
            for j, (cl, (_, w, al)) in enumerate(zip(cells, cols)):
                col = st.get("colors", {}).get(j, st.get("color", INK))
                for k, ln in enumerate(cl):
                    self.text(x + (w - pad if al == "right" else pad), self.y - 3 - size - k * (size + 3), ln, size, st.get("bold", False) or (j == 0 and st.get("bold0")), col,
                              "right" if al == "right" else "left")
                x += w
            self.y -= h
            self.line(x0, self.y, x0 + sum(c[1] for c in cols), self.y)

    def kv_box(self, pairs, cols=2):
        """Label/value grid (patient details)."""
        w = (self.W - 2 * self.M) / cols
        rows_ = [pairs[i:i + cols] for i in range(0, len(pairs), cols)]
        h = len(rows_) * 26 + 8
        self.need_space(h)
        self.rect(self.M, self.y - h, self.W - 2 * self.M, h, stroke=LINE)
        for ri, rw in enumerate(rows_):
            for ci, (k, v) in enumerate(rw):
                x, y = self.M + 8 + ci * w, self.y - 8 - ri * 26
                self.text(x, y - 7, k.upper(), 7, True, MUTED)
                self.text(x, y - 19, (str(v or "-"))[:60], 10, k in ("Patient", "Name"))
        self.y -= h + 12

    # ---- output ----
    def bytes(self, footer=""):
        n = len(self.pages)
        for i, ops in enumerate(self.pages):
            ops.append(f"0.6 w {LINE[0]} {LINE[1]} {LINE[2]} RG {self.M} 32 m {self.W - self.M} 32 l S")
            self.ops = ops
            self.text(self.M, 20, footer, 7.5, False, MUTED)
            self.text(self.W - self.M, 20, f"Page {i + 1} of {n}", 7.5, False, MUTED, "right")
        objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
                "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
                f"<< /Title ({_clean(self.title)}) /Producer (MediAssist) /CreationDate (D:{datetime.now():%Y%m%d%H%M%S}) >>"]
        kids = []
        for ops in self.pages:
            data = zlib.compress("\n".join(ops).encode("cp1252", "replace"))
            objs.append(f"<< /Length {len(data)} /Filter /FlateDecode >>\nstream\n".encode() + data + b"\nendstream")
            objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.W} {self.H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {len(objs)} 0 R >>")
            kids.append(f"{len(objs)} 0 R")
        objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {n} >>"
        out, offs = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
        for i, o in enumerate(objs, 1):
            offs.append(len(out))
            out += f"{i} 0 obj\n".encode() + (o if isinstance(o, bytes) else o.encode("cp1252", "replace")) + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)


def rs(v):
    neg, v = v < 0, abs(v or 0)
    whole, frac = f"{v:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    while len(head) > 2:
        tail, head = head[-2:] + "," + tail, head[:-2]
    return ("-" if neg else "") + "Rs. " + (head + "," + tail if head else tail) + "." + frac


def letterhead(pdf, c, br, title, right_lines=()):
    org = get_settings(c).get("org_name") or ""
    top = pdf.H - 30
    pdf.rect(0, pdf.H - 8, pdf.W, 8, fill=TEAL)
    pdf.text(pdf.M, top - 16, br["name"], 18, True, TEAL)
    sub = " - ".join(x for x in (br.get("address"), ("Ph " + br["phone"]) if br.get("phone") else None) if x)
    pdf.text(pdf.M, top - 30, sub, 8.5, False, MUTED)
    extra = " - ".join(x for x in ((("GSTIN " + br["gstin"]) if br.get("gstin") else None), (("DL " + br["dl_no"]) if br.get("dl_no") else None), org if org and org != br["name"] else None) if x)
    if extra:
        pdf.text(pdf.M, top - 41, extra, 8, False, MUTED)
    pdf.text(pdf.W - pdf.M, top - 16, title, 13, True, INK, "right")
    for i, ln in enumerate(x for x in right_lines if x):
        pdf.text(pdf.W - pdf.M, top - 30 - i * 11, ln, 8.5, False, MUTED, "right")
    pdf.y = top - 54 - max(0, len([x for x in right_lines if x]) - 2) * 11
    pdf.line(pdf.M, pdf.y, pdf.W - pdf.M, pdf.y, TEAL, 1.2)
    pdf.y -= 14


def _br(c, bid):
    return dict(one(c, "SELECT * FROM branches WHERE id=?", (bid,)))


def _pt(c, pid):
    return one(c, "SELECT * FROM patients WHERE id=?", (pid,)) if pid else None


def _age(p):
    return f"{p['age'] if p and p['age'] is not None else '?'} yrs / {(p['gender'] or '-') if p else '-'}"


def _dt(s):
    try:
        return datetime.strptime(s[:16], "%Y-%m-%d %H:%M").strftime("%d %b %Y, %H:%M")
    except (TypeError, ValueError):
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%d %b %Y")
        except (TypeError, ValueError):
            return s or "-"


# ---------------------------------------------------------------- documents
FLAG_TXT = {"H": "High", "L": "Low", "HH": "CRITICAL HIGH", "LL": "CRITICAL LOW", "A": "Abnormal"}


def lab_pdf(c, oid):
    from .m_lab import order_detail
    o = order_detail(c, oid)
    need(o["status"] == "verified", "The report isn't verified yet", 409)
    p, br = _pt(c, o["patient_id"]), _br(c, o["branch_id"])
    pdf = Pdf(f"Lab report LAB{o['id']} - {o['pname']}")
    letterhead(pdf, c, br, "AMENDED LABORATORY REPORT" if o["amended_at"] else "LABORATORY REPORT", [f"Lab no. LAB{o['id']}", f"Reported {_dt(o['verified_at'])}"]
               + ([f"Amended {_dt(o['amended_at'])}: {o['amend_reason']}"] if o["amended_at"] else []))
    pdf.kv_box([("Patient", o["pname"]), ("Patient ID", o["code"]), ("Age / Gender", _age(p)), ("Referred by", o["dname"] or "Self"),
                ("Sample collected", _dt(o["collected_at"])), ("Report verified", _dt(o["verified_at"]))])
    for t in o["tests"]:
        params = [x for x in t["params"] if x["value"] not in (None, "")]
        if not params:
            continue
        pdf.need_space(40)
        pdf.text(pdf.M, pdf.y - 12, t["name"], 11.5, True, TEAL)
        if t.get("sample"):
            pdf.text(pdf.W - pdf.M, pdf.y - 12, "Sample: " + t["sample"], 8, False, MUTED, "right")
        pdf.y -= 18
        data = [[x["name"], str(x["value"]), x["unit"] or "", x["range"] or "", FLAG_TXT.get(x["flag"], "")] for x in params]
        flags = [x["flag"] for x in params]

        def style(i, r, flags=flags):
            f = flags[i]
            if f in ("HH", "LL"):
                return {"bold": True, "colors": {1: RED, 4: RED}}
            if f in ("H", "L", "A"):
                return {"bold": True, "colors": {1: AMBER, 4: AMBER}}
            return {}
        pdf.table([("Test", 175, "left"), ("Result", 80, "left"), ("Unit", 70, "left"), ("Normal range", 110, "left"), ("Flag", 80, "left")], data, row_style=style)
        pdf.y -= 12
    if o.get("interp") and o.get("interp_patient") and o.get("interp_reviewed_at"):
        pdf.need_space(60)
        pdf.text(pdf.M, pdf.y - 12, "What this means", 11.5, True, TEAL)
        pdf.y -= 18
        for f in o["interp"]["findings"]:
            pdf.para("- " + f["text"], 9.5)
        pdf.para(o["interp"]["summary"], 9.5, True)
        pdf.para("Explanation reviewed by " + (o.get("verified_name") or "the doctor") + ". It is general information, not a diagnosis.", 8, color=MUTED)
        pdf.y -= 6
    pdf.need_space(80)
    pdf.y -= 6
    pdf.para("Results marked High or Low are outside the laboratory's reference range (adult ranges unless stated). Please show this report to your doctor; "
             "a single result is not a diagnosis.", 8.5, color=MUTED)
    pdf.y -= 18
    pdf.line(pdf.W - pdf.M - 180, pdf.y, pdf.W - pdf.M, pdf.y, INK)
    pdf.text(pdf.W - pdf.M, pdf.y - 12, o["verified_name"] or "", 10, True, INK, "right")
    pdf.text(pdf.W - pdf.M, pdf.y - 24, "Verified by" + (f" - Reg. {o['verified_reg']}" if o.get("verified_reg") else ""), 8, False, MUTED, "right")
    if o.get("resulted_name"):
        pdf.text(pdf.M, pdf.y - 12, "Tested by " + o["resulted_name"], 8.5, False, MUTED)
    return pdf.bytes(f"{br['name']} - LAB{o['id']} - verified electronically - printed {_dt(now_str())}"), f"Lab-report-LAB{o['id']}.pdf", o


def bill_pdf(c, bid):
    from .m_pharmacy import bill_detail
    b = bill_detail(c, bid)
    br = _br(c, b["branch_id"])
    p = _pt(c, b["patient_id"])
    pdf = Pdf(f"Pharmacy bill {b['bill_no']}")
    letterhead(pdf, c, br, "PHARMACY BILL", [f"Bill no. {b['bill_no']}", _dt(b["created_at"]), "Paid by " + (b["pay_mode"] or "").upper()])
    pdf.kv_box([("Patient", b["customer"]), ("Patient ID", b["patient_code"] or "-"), ("Age / Gender", _age(p) if p else "-"),
                ("Prescribed by", " - ".join(x for x in (b["doctor_name"], b["doctor_reg"]) if x) or "-")])
    data = [[str(i + 1), x["name"] + (f" (Sch. {x['schedule']})" if x["schedule"] in ("H", "H1") else ""), x["batch"] or "", (x["expiry"] or "")[:7],
             str(x["qty"] - (x["returned"] or 0)), rs(x["mrp"]), f"{x['gst_pct']:g}%", rs(x["net"])] for i, x in enumerate(b["items"])]
    pdf.table([("#", 22, "left"), ("Medicine", 170, "left"), ("Batch", 62, "left"), ("Exp", 46, "left"), ("Qty", 36, "right"), ("MRP", 60, "right"),
               ("GST", 40, "right"), ("Amount", 79, "right")], data)
    _totals(pdf, [("Subtotal (MRP)", rs(b["subtotal"])), ("Discount", "- " + rs(b["discount"])) if b["discount"] else None,
                  ("Returned", "- " + rs(b["returned"])) if b["returned"] else None, ("Total paid", rs(b["total"] - (b["returned"] or 0)), True),
                  ("GST included", rs(b["gst"]))])
    pdf.para("Prices include GST. Medicines once sold are taken back only with this bill, unopened and within 7 days. Keep medicines out of reach of children.", 8, color=MUTED)
    return pdf.bytes(f"{br['name']} - {b['bill_no']} - computer generated bill, no signature needed"), f"Bill-{b['bill_no']}.pdf", b


def invoice_pdf(c, iid):
    from .m_billing import inv_state
    inv = one(c, "SELECT i.*, p.name pname, u.name dname, u.reg_no dreg FROM invoices i JOIN patients p ON p.id=i.patient_id LEFT JOIN users u ON u.id=i.doctor_id WHERE i.id=?", (iid,))
    need(inv, "Bill not found", 404)
    br, p, st = _br(c, inv["branch_id"]), _pt(c, inv["patient_id"]), inv_state(c, inv)
    items = rows(c.execute("SELECT * FROM invoice_items WHERE invoice_id=?", (iid,)))
    pays = rows(c.execute("SELECT * FROM payments WHERE invoice_id=? ORDER BY id", (iid,)))
    title = {"ipd": "INPATIENT BILL", "lab": "LAB BILL"}.get(inv["kind"], "OPD BILL")
    pdf = Pdf(f"{title.title()} {inv['inv_no']}")
    letterhead(pdf, c, br, title + (" (CANCELLED)" if inv["cancelled_at"] else ""), [f"Bill no. {inv['inv_no']}", _dt(inv["created_at"])])
    pdf.kv_box([("Patient", inv["pname"]), ("Patient ID", pcode(inv["patient_id"])), ("Age / Gender", _age(p)), ("Doctor", inv["dname"] or "-")])
    data = [[it["name"], f"{it['qty']:g}", rs(R(it["rate_p"])), rs(R(it["disc_p"])) if it["disc_p"] else "", rs(R(it["amount_p"]))] for it in items]
    pdf.table([("Service", 245, "left"), ("Qty", 40, "right"), ("Rate", 80, "right"), ("Discount", 70, "right"), ("Amount", 80, "right")], data)
    _totals(pdf, [("Discount on bill", "- " + rs(R(inv["discount_p"]))) if inv["discount_p"] else None, ("GST", rs(R(inv["gst_p"]))) if inv["gst_p"] else None,
                  ("Total", rs(R(inv["total_p"])), True), ("Paid", rs(R(st["paid_p"]))),
                  ("Insurance (awaited)", rs(R(st["insurance_p"]))) if st["insurance_p"] else None,
                  ("Balance to pay", rs(R(st["patient_due_p"])), True) if st["patient_due_p"] else None])
    if pays:
        pdf.text(pdf.M, pdf.y - 10, "Payments", 10, True)
        pdf.y -= 16
        pdf.table([("Date", 140, "left"), ("Mode", 90, "left"), ("Reference", 165, "left"), ("Amount", 120, "right")],
                  [[_dt(x["at"]), x["mode"].upper(), x["ref"] or "", rs(R(x["amount_p"]))] for x in pays])
    return pdf.bytes(f"{br['name']} - {inv['inv_no']} - computer generated bill, no signature needed"), f"Bill-{inv['inv_no']}.pdf", inv


def rx_pdf(c, vid):
    v = one(c, "SELECT v.*, u.name dname, u.reg_no dreg FROM visits v LEFT JOIN users u ON u.id=v.doctor_id WHERE v.id=?", (vid,))
    need(v and v["status"] == "done", "Prescription not found", 404)
    br, p = _br(c, v["branch_id"]), _pt(c, v["patient_id"])
    items = rows(c.execute("SELECT r.*, m.name, m.generic, m.schedule FROM rx_items r JOIN medicines m ON m.id=r.medicine_id WHERE r.visit_id=?", (vid,)))
    pdf = Pdf(f"Prescription - {p['name']}")
    letterhead(pdf, c, br, "PRESCRIPTION", [v["dname"] or "", ("Reg. " + v["dreg"]) if v["dreg"] else "", _dt(v["completed_at"] or v["created_at"])])
    pdf.kv_box([("Patient", p["name"]), ("Patient ID", pcode(p["id"])), ("Age / Gender", _age(p)), ("Allergies", p["allergies"] or "None recorded")])
    vit = [f"BP {v['bp_sys']}/{v['bp_dia']}" if v["bp_sys"] else "", f"Pulse {v['pulse']}" if v["pulse"] else "", f"Temp {v['temp']:.1f} C" if v["temp"] else "",
           f"SpO2 {v['spo2']}%" if v["spo2"] else "", f"Weight {v['weight']} kg" if v["weight"] else "", f"Sugar {v['sugar']}" if v["sugar"] else ""]
    if any(vit):
        pdf.para("Vitals: " + ", ".join(x for x in vit if x), 9, color=MUTED)
    if v["complaint"]:
        pdf.para("Complaint: " + v["complaint"], 10)
    if v["history"]:
        pdf.para("History: " + v["history"], 9.5)
    if v["examination"]:
        pdf.para("Examination: " + v["examination"], 9.5)
    pdf.para("Diagnosis: " + (v["diagnosis"] or "-") + (f" ({v['icd']})" if v["icd"] else ""), 10.5, True)
    pdf.text(pdf.M, pdf.y - 18, "Rx", 18, True, TEAL)
    pdf.y -= 26
    if items:
        sched = lambda x: f" [Sch. {x['schedule']}]" if (x["schedule"] or "OTC") != "OTC" else ""
        pdf.table([("Medicine", 165, "left"), ("Dose", 50, "left"), ("When", 80, "left"), ("Days", 35, "right"), ("Qty", 35, "right"), ("Instructions", 150, "left")],
                  [[x["name"] + sched(x) + (f"\n{x['generic']}" if x["generic"] else ""), x["dose"] or "", x["freq"] or "", str(x["days"] or ""), str(x["qty"] or ""), x["instructions"] or ""] for x in items],
                  row_style=lambda i, r: {"bold0": True})
    else:
        pdf.para("No medicines prescribed.", 10, color=MUTED)
    pdf.y -= 8
    if v["notes"]:
        pdf.para("Advice: " + v["notes"], 10)
    if v["followup"]:
        pdf.para("Come back on " + _dt(v["followup"]) + ".", 10.5, True, TEAL)
    pdf.need_space(60)
    pdf.y -= 30
    pdf.line(pdf.W - pdf.M - 180, pdf.y, pdf.W - pdf.M, pdf.y, INK)
    pdf.text(pdf.W - pdf.M, pdf.y - 12, v["dname"] or "", 10, True, INK, "right")
    if v["dreg"]:
        pdf.text(pdf.W - pdf.M, pdf.y - 24, "Reg. " + v["dreg"], 8, False, MUTED, "right")
    return pdf.bytes(f"{br['name']} - prescription for {p['name']} - not valid for Schedule X medicines"), f"Prescription-{pcode(p['id'])}-{(v['completed_at'] or '')[:10]}.pdf", v


def _totals(pdf, lines):
    pdf.y -= 6
    for ln in [x for x in lines if x]:
        k, v, strong = ln[0], ln[1], len(ln) > 2
        pdf.need_space(16)
        pdf.text(pdf.W - pdf.M - 120, pdf.y - 11, k, 10 if strong else 9, strong, INK if strong else MUTED, "right")
        pdf.text(pdf.W - pdf.M, pdf.y - 11, v, 10 if strong else 9, strong, INK, "right")
        pdf.y -= 16
    pdf.y -= 10


def referral_pdf(c, rid):
    import json as _json
    r = one(c, "SELECT r.*, u.name by_name, u.reg_no by_reg FROM referrals r LEFT JOIN users u ON u.id=r.by_user WHERE r.id=?", (rid,))
    need(r, "Referral not found", 404)
    br, p = _br(c, r["branch_id"]), _pt(c, r["patient_id"])
    pdf = Pdf(f"Referral - {p['name']}")
    letterhead(pdf, c, br, "REFERRAL LETTER", [f"Ref. REF{r['id']}", _dt(r["at"]), r["urgency"].upper()])
    pdf.kv_box([("Patient", p["name"]), ("Patient ID", pcode(p["id"])), ("Age / Gender", _age(p)), ("Phone", p["phone"] or ""),
                ("Referred to", r["to_facility"] + (f", {r['to_doctor']}" if r["to_doctor"] else "")), ("Specialty", r["specialty"] or "-"),
                ("Allergies", p["allergies"] or "None recorded"), ("Known conditions", p["conditions"] or "-")])
    pdf.para("Reason for referral: " + r["reason"], 10.5, True)
    if r["summary"]:
        pdf.para("Clinical summary: " + r["summary"], 10)
    if r["treatment_given"]:
        pdf.para("Treatment given so far: " + r["treatment_given"], 10)
    if r["vitals"]:
        v = _json.loads(r["vitals"])
        bits = [f"BP {v['bp_sys']}/{v['bp_dia']}" if v.get("bp_sys") else "", f"Pulse {v['pulse']}" if v.get("pulse") else "", f"RR {v['resp_rate']}" if v.get("resp_rate") else "",
                f"SpO2 {v['spo2']}%" if v.get("spo2") else "", f"Temp {v['temp']} C" if v.get("temp") else "", f"GCS {v['gcs']}" if v.get("gcs") else "", f"Sugar {v['sugar']}" if v.get("sugar") else ""]
        if any(bits):
            pdf.para("Vitals at referral: " + ", ".join(x for x in bits if x), 9.5, color=MUTED)
    if r["transport"]:
        pdf.para("Transport: " + r["transport"], 9.5, color=MUTED)
    pdf.need_space(60)
    pdf.y -= 30
    pdf.line(pdf.W - pdf.M - 180, pdf.y, pdf.W - pdf.M, pdf.y, INK)
    pdf.text(pdf.W - pdf.M, pdf.y - 12, r["by_name"] or "", 10, True, INK, "right")
    if r["by_reg"]:
        pdf.text(pdf.W - pdf.M, pdf.y - 24, "Reg. " + r["by_reg"], 8, False, MUTED, "right")
    return pdf.bytes(f"{br['name']} - referral for {p['name']}"), f"Referral-{pcode(p['id'])}-{r['at'][:10]}.pdf", r


MAKERS = {"lab": lab_pdf, "bill": bill_pdf, "invoice": invoice_pdf, "rx": rx_pdf, "referral": referral_pdf}
TABLES = {"lab": "lab_orders", "bill": "bills", "invoice": "invoices", "rx": "visits", "referral": "referrals"}


def make(c, kind, rid):
    need(kind in MAKERS, "Unknown document", 404)
    data, name, _ = MAKERS[kind](c, rid)
    return data, re.sub(r"[^A-Za-z0-9._-]+", "-", name)


# ---------------------------------------------------------------- staff download
@route("GET", r"/api/pdf/(lab|bill|invoice|rx|referral)/(\d+)", "patients_read")
def api_pdf(h, c, b, q, kind, rid):
    row = one(c, f"SELECT branch_id FROM {TABLES[kind]} WHERE id=?", (int(rid),))
    need(row, "Not found", 404)
    need(row["branch_id"] == h.branch or all_access(h.user), "This belongs to another branch", 403)
    data, name = make(c, kind, int(rid))
    h.download = (name, data, "application/pdf")
    h.inline = qget(q, "inline") == "1"
    return None
