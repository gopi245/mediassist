"""Patient tracker: where every patient at the branch is right now. For each of today's OPD patients and every
inpatient, the steps of their visit (doctor, lab, pharmacy, bill; for inpatients advance, round, medicines,
discharge) are marked done, pending or not needed, and patients who are stuck come first with the reason."""
from datetime import datetime

from .core import R, need_branch, pcode, qget, route, rows, today, valid_day

# minutes after which a pending step counts as stuck
LIMITS = {"doctor": 45, "critical": 10, "collect": 60, "result": 180, "verify": 60, "dispense": 60}


def _mins(since, now):
    try:
        return int((now - datetime.strptime(since[:16], "%Y-%m-%d %H:%M")).total_seconds() // 60)
    except (TypeError, ValueError):
        return 0


def _ago(m):
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def step(key, label, state, at=None, note=""):
    at = at or ""
    shown = at[11:16] if at[:10] == today() or len(at) < 16 else f"{at[8:10]}/{at[5:7]} {at[11:16]}"
    return {"key": key, "label": label, "state": state, "at": shown, "note": note}


def opd_rows(c, bid, day, now):
    from .m_billing import inv_state
    out = []
    for v in rows(c.execute("SELECT v.*, p.name pname, p.age, p.gender, p.phone, u.name dname, a.token FROM visits v JOIN patients p ON p.id=v.patient_id "
                            "LEFT JOIN users u ON u.id=v.doctor_id LEFT JOIN appointments a ON a.visit_id=v.id "
                            "WHERE v.branch_id=? AND v.created_at LIKE ? AND v.status<>'cancelled' AND v.complaint IS NOT 'Discharge' ORDER BY v.id", (bid, day + "%"))):
        steps, stuck = [step("arrived", "Arrived", "done", v["created_at"], f"token {v['token']}" if v["token"] else "")], []
        # doctor
        if v["status"] in ("done", "admitted"):
            steps.append(step("doctor", "Seen by doctor", "done", v["completed_at"], v["dname"] or ""))
        elif v["status"] == "in_consult":
            steps.append(step("doctor", "With doctor", "now", None, v["dname"] or ""))
        else:
            m = _mins(v["created_at"], now)
            late = m > LIMITS["critical" if v["triage"] == "critical" else "doctor"]
            steps.append(step("doctor", "Waiting for doctor", "late" if late else "pending", None, f"waiting {_ago(m)}"))
            if late:
                stuck.append(f"waiting {_ago(m)} for the doctor" + (" (CRITICAL triage)" if v["triage"] == "critical" else ""))
        if v["status"] == "admitted":  # moved to the ward: lab, medicines and bill continue on the inpatient side
            steps.append(step("admit", "Admitted", "done", v["completed_at"], (v["notes"] or "").split("Admitted ")[-1]))
            out.append({"kind": "opd", "id": v["id"], "patient_id": v["patient_id"], "name": v["pname"], "code": pcode(v["patient_id"]), "age": v["age"], "gender": v["gender"],
                        "phone": v["phone"], "doctor": v["dname"], "token": v["token"], "since": v["created_at"][11:16], "triage": v["triage"], "complaint": v["complaint"],
                        "steps": steps, "stuck": [], "done": True, "now": "Admitted"})
            continue
        # lab
        orders = rows(c.execute("SELECT * FROM lab_orders WHERE visit_id=? AND status<>'cancelled'", (v["id"],)))
        if not orders:
            steps.append(step("lab", "Lab", "na"))
        for o in orders:
            if o["status"] == "verified":
                steps.append(step("lab", "Lab report", "done", o["verified_at"], f"LAB{o['id']} sent to patient"))
            elif o["status"] == "resulted":
                m = _mins(o["resulted_at"], now)
                steps.append(step("lab", "Lab: waiting for verification", "late" if m > LIMITS["verify"] else "pending", None, f"LAB{o['id']} · {_ago(m)}"))
                if m > LIMITS["verify"]:
                    stuck.append(f"lab report LAB{o['id']} waiting {_ago(m)} for verification")
            elif o["status"] == "collected":
                m = _mins(o["collected_at"], now)
                steps.append(step("lab", "Lab: sample being tested", "late" if m > LIMITS["result"] else "pending", None, f"LAB{o['id']} · {_ago(m)}"))
                if m > LIMITS["result"]:
                    stuck.append(f"lab sample LAB{o['id']} collected {_ago(m)} ago, no result yet")
            else:
                m = _mins(o["created_at"], now)
                steps.append(step("lab", "Lab: sample not collected", "late" if m > LIMITS["collect"] else "pending", None, f"LAB{o['id']} · {_ago(m)}"))
                if m > LIMITS["collect"]:
                    stuck.append(f"lab sample for LAB{o['id']} not collected for {_ago(m)}")
        # pharmacy
        rx = c.execute("SELECT COALESCE(SUM(qty),0), COALESCE(SUM(MIN(dispensed,qty)),0), COUNT(*) FROM rx_items WHERE visit_id=?", (v["id"],)).fetchone()
        if not rx[2]:
            steps.append(step("pharmacy", "Medicines", "na", None, "none prescribed" if v["status"] == "done" else ""))
        elif rx[1] >= rx[0]:
            b = c.execute("SELECT created_at FROM bills WHERE visit_id=? ORDER BY id DESC LIMIT 1", (v["id"],)).fetchone()
            steps.append(step("pharmacy", "Medicines given", "done", b[0] if b else None))
        else:
            m = _mins(v["completed_at"], now) if v["completed_at"] else 0
            late = v["status"] == "done" and m > LIMITS["dispense"]
            steps.append(step("pharmacy", "Medicines " + ("partly given" if rx[1] else "not given"), "late" if late else "pending", None,
                              f"{rx[2]} item{'s' if rx[2] > 1 else ''} · {_ago(m)} since prescription" if v["status"] == "done" else f"{rx[2]} items"))
            if late:
                stuck.append(f"prescription not {'fully ' if rx[1] else ''}dispensed {_ago(m)} after the consultation (bought outside?)")
        # bill
        invs = rows(c.execute("SELECT * FROM invoices WHERE visit_id=? AND cancelled_at IS NULL", (v["id"],)))
        if invs:
            st = [inv_state(c, i) for i in invs]
            due = sum(s["patient_due_p"] for s in st)
            if due:
                steps.append(step("bill", "Bill: payment due", "late" if v["status"] == "done" else "pending", None, f"Rs {R(due):,.0f} due"))
                if v["status"] == "done":
                    stuck.append(f"Rs {R(due):,.0f} not paid")
            else:
                steps.append(step("bill", "Bill paid", "done", invs[-1]["created_at"], ", ".join(i["inv_no"] for i in invs)))
        else:
            steps.append(step("bill", "Not billed", "late" if v["status"] == "done" else "pending", None, "consultation not billed yet" if v["status"] == "done" else ""))
            if v["status"] == "done":
                stuck.append("consultation not billed")
        live = [s for s in steps if s["state"] in ("pending", "late", "now")]
        out.append({"kind": "opd", "id": v["id"], "patient_id": v["patient_id"], "name": v["pname"], "code": pcode(v["patient_id"]), "age": v["age"], "gender": v["gender"],
                    "phone": v["phone"], "doctor": v["dname"], "token": v["token"], "since": v["created_at"][11:16], "triage": v["triage"], "complaint": v["complaint"],
                    "steps": steps, "stuck": stuck, "done": not live, "now": live[0]["label"] if live else "Done for today"})
    return out


def ipd_rows(c, bid, day, now):
    from .m_ipd import running_bill
    out = []
    for a in rows(c.execute("SELECT a.*, p.name pname, p.age, p.gender, p.phone, u.name dname, b.ward, b.number bed FROM admissions a JOIN patients p ON p.id=a.patient_id "
                            "LEFT JOIN users u ON u.id=a.doctor_id LEFT JOIN beds b ON b.id=a.bed_id "
                            "WHERE a.branch_id=? AND (a.status='admitted' OR a.discharged_at LIKE ?) ORDER BY a.admitted_at", (bid, day + "%"))):
        steps, stuck = [step("admitted", "Admitted", "done", a["admitted_at"], f"{a['ward'] or ''} {a['bed'] or ''}".strip())], []
        dep = c.execute("SELECT COALESCE(SUM(amount_p),0) FROM payments WHERE (admission_id=? OR invoice_id=?) AND kind IN ('deposit','payment')",
                        (a["id"], a["invoice_id"] or -1)).fetchone()[0]
        if a["status"] == "admitted":
            bill = running_bill(c, a)
            total = bill.get("total_p") or 0
            if not dep:
                steps.append(step("advance", "No advance taken", "late", None, f"bill so far Rs {R(total):,.0f}"))
                stuck.append("no advance deposit taken")
            elif total > dep:
                steps.append(step("advance", "Advance used up", "late" if total - dep > dep * 0.2 else "pending", None, f"Rs {R(dep):,.0f} paid · bill Rs {R(total):,.0f}"))
                if total - dep > dep * 0.2:
                    stuck.append(f"bill Rs {R(total):,.0f} is more than the Rs {R(dep):,.0f} advance; ask for more")
            else:
                steps.append(step("advance", "Advance paid", "done", None, f"Rs {R(dep):,.0f} · bill Rs {R(total):,.0f}"))
            rnd = c.execute("SELECT MAX(at) FROM ipd_notes WHERE admission_id=? AND kind='round' AND at LIKE ?", (a["id"], day + "%")).fetchone()[0]
            if rnd:
                steps.append(step("round", "Doctor's round", "done", rnd))
            else:
                late = now.hour >= 13
                steps.append(step("round", "Doctor's round not done", "late" if late else "pending"))
                if late:
                    stuck.append("no doctor's round recorded today")
            meds = c.execute("SELECT COUNT(*) FROM mar_orders WHERE admission_id=? AND active=1", (a["id"],)).fetchone()[0]
            if meds:
                given = c.execute("SELECT COUNT(*) FROM mar_admin m JOIN mar_orders o ON o.id=m.mar_id WHERE o.admission_id=? AND m.at LIKE ? AND m.status='given'",
                                  (a["id"], day + "%")).fetchone()[0]
                missed = c.execute("SELECT COUNT(*) FROM mar_admin m JOIN mar_orders o ON o.id=m.mar_id WHERE o.admission_id=? AND m.at LIKE ? AND m.status<>'given'",
                                   (a["id"], day + "%")).fetchone()[0]
                steps.append(step("meds", f"Medicines: {given} doses given" + (f", {missed} missed/held" if missed else ""), "done" if given and not missed else "pending" if not missed else "late",
                                  None, f"{meds} active order{'s' if meds > 1 else ''}"))
                if missed:
                    stuck.append(f"{missed} medicine dose{'s' if missed > 1 else ''} missed or held today")
            else:
                steps.append(step("meds", "Medicines", "na", None, "no active orders"))
            labs = rows(c.execute("SELECT * FROM lab_orders WHERE admission_id=? AND status NOT IN ('verified','cancelled')", (a["id"],)))
            if labs:
                oldest = min(labs, key=lambda o: o["created_at"])
                m = _mins(oldest["created_at"], now)
                steps.append(step("lab", f"Lab: {len(labs)} pending", "late" if m > LIMITS["result"] else "pending", None, f"oldest {_ago(m)}"))
                if m > LIMITS["result"]:
                    stuck.append(f"{len(labs)} lab order{'s' if len(labs) > 1 else ''} pending, oldest {_ago(m)}")
            else:
                steps.append(step("lab", "Lab", "na" if not c.execute("SELECT 1 FROM lab_orders WHERE admission_id=?", (a["id"],)).fetchone() else "done"))
            steps.append(step("discharge", "In hospital", "pending", None, f"day {(now.date() - datetime.strptime(a['admitted_at'][:10], '%Y-%m-%d').date()).days + 1}"))
        else:
            steps.append(step("discharge", "Discharged", "done", a["discharged_at"], a["discharge_type"] or ""))
        live = [s for s in steps if s["state"] in ("pending", "late", "now") and s["key"] != "discharge"]
        out.append({"kind": "ipd", "id": a["id"], "patient_id": a["patient_id"], "name": a["pname"], "code": pcode(a["patient_id"]), "age": a["age"], "gender": a["gender"],
                    "phone": a["phone"], "doctor": a["dname"], "ip_no": a["ip_no"], "since": a["admitted_at"][:16], "complaint": a["diagnosis"] or a["reason"],
                    "steps": steps, "stuck": stuck, "done": a["status"] != "admitted", "now": live[0]["label"] if live else ("Discharged" if a["status"] != "admitted" else "Stable")})
    return out


@route("GET", "/api/tracker", "patients_read")
def api_tracker(h, c, b, q):
    br = need_branch(h, c, "hospital")
    day = valid_day(qget(q, "date", today()))
    now = datetime.now() if day == today() else datetime.strptime(day + " 23:59", "%Y-%m-%d %H:%M")
    opd, ipd = opd_rows(c, br["id"], day, now), ipd_rows(c, br["id"], day, now)
    key = lambda r: (not r["stuck"], r["done"], r["since"])
    return {"day": day, "opd": sorted(opd, key=key), "ipd": sorted(ipd, key=key),
            "counts": {"opd": len(opd), "opd_done": sum(1 for r in opd if r["done"]), "ipd": sum(1 for r in ipd if not r["done"]),
                       "stuck": sum(1 for r in opd + ipd if r["stuck"]), "waiting_doctor": sum(1 for r in opd if any(s["key"] == "doctor" and s["state"] in ("pending", "late") for s in r["steps"]))}}
