"""AI assistant for doctors, pharmacists and managers: ask in text or by voice ("how many Dolo 650 do we have
and where?", "what did P00004 get last visit?", "is it safe to give Brufen to Fatima?", "today's collection?")
and get the answer as text or read aloud.

Claude answers by calling the read-only tools below. Every tool runs as the signed-in staff member, so it can
only see what their role and branch allow, and none of them can change anything. Conversations are kept per
user so follow-up questions work; the full assistant content (including thinking blocks) is stored and sent
back unchanged, as the API requires."""
import json
import re
import secrets

from .core import ApiError, all_access, audit, can, clean, get_settings, need, now_str, one, pcode, route, rows, today, valid_day

MODEL = "claude-opus-5-5"
MAX_ROUNDS = 8

SYSTEM = """You are the MediAssist assistant inside a hospital, clinic and pharmacy management system in India.
You help doctors, pharmacists, nurses and managers find information in the system quickly.

How to work:
- Use the tools to look things up. Never invent stock levels, patient details, results or amounts; if a tool
  does not return it, say you could not find it.
- The tools only show what this staff member's role and branch allow. If a tool says something is not allowed
  for their role, tell them plainly.
- You can read but not change anything. If they ask you to bill, dispense, edit or delete, tell them which
  screen to use.
- Clinical questions: give the facts from the record and the system's safety checks. The doctor makes the
  decision; say so briefly when you give clinical information. For emergencies, tell them to act first.
- Money is in Indian rupees (Rs). Dates are DD Mon YYYY.
- Reply in the language the user wrote or spoke in (English, Telugu or Hindi).
- Be brief: answer first, then only the details that matter. Use short lists, not tables."""

VOICE_NOTE = ("This reply will be read aloud. Answer in two to four short spoken sentences with no lists, symbols, "
              "markdown or codes the listener has to decode; say amounts as words a person would say, like '1,250 rupees'.")


# ---------------------------------------------------------------- tools (read-only, run as the signed-in user)
class Denied(Exception):
    pass


def _need(h, perm):
    if not can(h, perm):
        raise Denied(f"Your role ({h.user['role']}) can't see this.")


def _pid(c, ref):
    ref = str(ref or "").strip()
    m = re.fullmatch(r"[Pp]?0*(\d+)", ref)
    if m and one(c, "SELECT 1 FROM patients WHERE id=? AND erased_at IS NULL", (int(m.group(1)),)):
        return int(m.group(1))
    hits = rows(c.execute("SELECT id FROM patients WHERE erased_at IS NULL AND (lower(name)=lower(?) OR phone LIKE ?) LIMIT 2", (ref, f"%{ref[-10:]}" if ref.isdigit() else "~")))
    if len(hits) == 1:
        return hits[0]["id"]
    raise Denied(f"No single patient matches '{ref}'. Use find_patient first and pass the patient ID (like P00004).")


def t_find_medicine(c, h, a):
    _need(h, "patients_read")
    from .m_pharmacy import stock_info
    name = str(a.get("name") or "").strip()
    need(name, "Give a medicine name")
    meds = rows(c.execute("SELECT id, name FROM medicines WHERE active=1 AND (lower(name) LIKE lower(?) OR lower(generic) LIKE lower(?) OR barcode=?) ORDER BY name LIMIT 5",
                          (f"%{name}%", f"%{name}%", name)))
    if not meds:
        return {"found": False, "note": f"No medicine like '{name}' in the medicine list."}
    out = []
    for m in meds[:3]:
        s = stock_info(c, m["id"], h.branch)
        md = s["medicine"]
        out.append({"medicine": md["name"], "generic": md["generic"], "form": md["form"], "schedule": md["schedule"], "pack_size": md["pack_size"],
                    "usable_units_here": s.get("qty"), "status": s.get("status"), "reorder_level": md["reorder_level"],
                    "batches_here": [{"batch": b["batch"], "qty": b["qty"], "rack": b["rack"], "expires": b["effective_expiry"], "days_left": b["days_left"], "mrp_per_unit": b["mrp"]}
                                     for b in s.get("batches", [])[:6]],
                    "expired_on_shelf": len(s.get("expired", [])), "other_branches": s["others"],
                    "substitutes_in_stock": [{"medicine": x["name"], "units": x["stock"]} for x in s.get("alternatives", [])[:5]],
                    "note": "this login is not at a pharmacy branch" if s.get("no_pharmacy") else ""})
    return {"found": True, "results": out, "more_matches": [m["name"] for m in meds[3:]]}


def t_find_patient(c, h, a):
    _need(h, "patients_read")
    q = str(a.get("query") or "").strip()
    need(len(q) >= 2, "Give at least 2 letters of a name, a phone number or a patient ID")
    m = re.fullmatch(r"[Pp]0*(\d+)", q)
    found = rows(c.execute("SELECT * FROM patients WHERE id=? AND erased_at IS NULL", (int(m.group(1)),))) if m else \
        rows(c.execute("SELECT * FROM patients WHERE erased_at IS NULL AND (name LIKE ? OR phone LIKE ?) ORDER BY id DESC LIMIT 8", (f"%{q}%", f"%{q}%")))
    return [{"id": pcode(p["id"]), "name": p["name"], "age": p["age"], "gender": p["gender"], "phone_last4": (p["phone"] or "")[-4:],
             "allergies": p["allergies"] or "none recorded"} for p in found] or {"note": "No patient found."}


def t_patient_summary(c, h, a):
    _need(h, "patients_read")
    if get_settings(c).get("assistant_patients", "1") != "1":
        raise Denied("Patient records are switched off for the assistant in Settings.")
    from .m_clinical import current_meds
    pid = _pid(c, a.get("patient"))
    p = one(c, "SELECT * FROM patients WHERE id=?", (pid,))
    visits = rows(c.execute("SELECT v.*, u.name dname FROM visits v LEFT JOIN users u ON u.id=v.doctor_id WHERE v.patient_id=? AND v.status='done' ORDER BY v.completed_at DESC LIMIT 5", (pid,)))
    out_v = []
    for v in visits:
        rx = rows(c.execute("SELECT m.name, r.dose, r.freq, r.days FROM rx_items r JOIN medicines m ON m.id=r.medicine_id WHERE r.visit_id=?", (v["id"],)))
        out_v.append({"date": (v["completed_at"] or "")[:10], "doctor": v["dname"], "complaint": v["complaint"], "diagnosis": v["diagnosis"], "followup": v["followup"],
                      "vitals": {k: v[k] for k in ("bp_sys", "bp_dia", "pulse", "temp", "spo2", "sugar", "weight") if v[k] is not None}, "prescribed": rx})
    from .m_lab import order_detail
    labs = []
    for o in rows(c.execute("SELECT id FROM lab_orders WHERE patient_id=? AND status='verified' ORDER BY verified_at DESC LIMIT 3", (pid,))):
        d = order_detail(c, o["id"])
        labs.append({"lab_no": f"LAB{d['id']}", "date": (d["verified_at"] or "")[:10],
                     "results": [{"test": p_["name"], "value": p_["value"], "unit": p_["unit"], "flag": p_["flag"] or "", "range": p_["range"]}
                                 for t in d["tests"] for p_ in t["params"] if p_["value"] not in (None, "")]})
    adm = one(c, "SELECT ip_no, admitted_at, diagnosis, status FROM admissions WHERE patient_id=? ORDER BY id DESC LIMIT 1", (pid,))
    audit(c, h, "assistant.patient", pcode(pid))
    return {"id": pcode(pid), "name": p["name"], "age": p["age"], "gender": p["gender"], "blood_group": p["blood_group"], "allergies": p["allergies"] or "none recorded",
            "conditions": p["conditions"] or "", "weight_kg": p["weight"], "pregnant_lmp": p["lmp"], "current_medicines": [m.get("name") for m in current_meds(c, pid)],
            "recent_visits": out_v, "recent_lab_reports": labs, "last_admission": adm}


def t_check_safety(c, h, a):
    _need(h, "patients_read")
    from .m_clinical import current_meds, latest_creatinine
    from .safety import safety_check
    names = [str(x) for x in (a.get("medicines") or [])][:10]
    need(names, "List the medicines to check")
    items, missing = [], []
    for n in names:
        m = one(c, "SELECT * FROM medicines WHERE lower(name)=lower(?) OR lower(name) LIKE lower(?) ORDER BY length(name) LIMIT 1", (n, f"{n}%"))
        (items.append({"med": m, "dose": "", "freq": "", "days": None}) if m else missing.append(n))
    patient = one(c, "SELECT * FROM patients WHERE id=?", (_pid(c, a["patient"]),)) if a.get("patient") else None
    w = safety_check(patient, items, current_meds(c, patient["id"]) if patient else (), latest_creatinine(c, patient["id"]) if patient else None)
    return {"checked": [i["med"]["name"] for i in items], "not_in_medicine_list": missing, "patient": pcode(patient["id"]) if patient else "none (general check only)",
            "warnings": [{"severity": x["severity"], "text": x["text"]} for x in w] or "No warnings from the system's checks (allergies, interactions, conditions, kidney, pregnancy, doses)."}


def t_today(c, h, a):
    _need(h, "patients_read")
    br = one(c, "SELECT * FROM branches WHERE id=?", (h.branch,)) if h.branch else None
    if not br:
        raise Denied("Choose a branch first (top of the screen).")
    out = {"branch": br["name"], "date": today()}
    if "hospital" in br["kind"]:
        from datetime import datetime
        from .m_tracker import ipd_rows, opd_rows
        now = datetime.now()
        opd, ipd = opd_rows(c, br["id"], today(), now), ipd_rows(c, br["id"], today(), now)
        out["opd"] = {"total": len(opd), "finished": sum(1 for r in opd if r["done"]),
                      "waiting_for_doctor": [f"{r['name']} ({r['code']}){' CRITICAL' if r['triage'] == 'critical' else ''}" for r in opd
                                             if any(s["key"] == "doctor" and s["state"] in ("pending", "late") for s in r["steps"])]}
        out["inpatients"] = [f"{r['name']} {r['ip_no']}: {r['now']}" for r in ipd if not r["done"]]
        out["stuck"] = [f"{r['name']}: {'; '.join(r['stuck'])}" for r in opd + ipd if r["stuck"]]
        out["appointments_today"] = c.execute("SELECT COUNT(*) FROM appointments WHERE branch_id=? AND day=? AND status NOT IN ('cancelled','no_show')", (br["id"], today())).fetchone()[0]
    if h.user["role"] == "doctor":
        from .m_alerts import doctor_briefing
        out["your_day"] = doctor_briefing(c, h.user["id"])["text"]
    return out


def t_stock_alerts(c, h, a):
    if not (can(h, "stock") or can(h, "billing")):
        raise Denied(f"Your role ({h.user['role']}) can't see stock alerts.")
    br = one(c, "SELECT * FROM branches WHERE id=?", (h.branch,)) if h.branch else None
    if not br or "pharmacy" not in br["kind"]:
        raise Denied("This login is not at a pharmacy branch.")
    from .m_weekly import weekly_summary
    w = weekly_summary(c, br["id"])
    w.pop("text", None)
    if not can(h, "stock"):
        w.pop("supplier_dues", None)
    return w


def t_money(c, h, a):
    _need(h, "reports")
    day = valid_day(str(a.get("date") or today()))
    from .m_reports import bids_scope, daily_report
    bids = bids_scope(c, h)
    r = daily_report(c, bids, day, "report")
    keep = ("day", "seen", "new", "total", "hosp", "pharm", "collected", "dues", "modes", "collections", "doctors", "admitted_now", "admissions", "discharges", "labs", "prev_total")
    return {k: r[k] for k in keep if k in r}


def t_lab_report(c, h, a):
    _need(h, "patients_read")
    from .m_lab import order_detail
    m = re.fullmatch(r"(?i)(?:lab)?0*(\d+)", str(a.get("lab_no") or "").strip())
    need(m, "Give a lab number like LAB12")
    d = order_detail(c, int(m.group(1)))
    need(d["branch_id"] == h.branch or all_access(h.user), "That lab order is at another branch", 403)
    return {"lab_no": f"LAB{d['id']}", "patient": f"{d['pname']} ({d['code']})", "status": d["status"], "ordered": d["created_at"], "verified": d["verified_at"],
            "results": [{"test": t["name"], "param": p["name"], "value": p["value"], "unit": p["unit"], "flag": p["flag"] or "", "range": p["range"]}
                        for t in d["tests"] for p in t["params"]]}


TOOLS = {
    "find_medicine": (t_find_medicine, "Stock of a medicine at this branch: usable units, each batch with rack location, expiry and MRP, stock at other branches, and substitutes with the same salt when it's out. Search by brand, generic or barcode.",
                      {"name": {"type": "string", "description": "Brand or generic name, or barcode"}}, ["name"]),
    "find_patient": (t_find_patient, "Find patients by name, phone number or patient ID (P00004). Returns ID, age, gender, allergies.",
                     {"query": {"type": "string"}}, ["query"]),
    "patient_summary": (t_patient_summary, "One patient's record: allergies, conditions, current medicines, last 5 visits with diagnosis and prescription, last 3 lab reports with flags, last admission.",
                        {"patient": {"type": "string", "description": "Patient ID like P00004 (preferred), or exact name or phone"}}, ["patient"]),
    "check_safety": (t_check_safety, "Run the system's prescribing safety checks (allergy, interactions with current medicines, conditions, kidney, pregnancy, child doses) for medicines, optionally for a patient.",
                     {"medicines": {"type": "array", "items": {"type": "string"}}, "patient": {"type": "string", "description": "Patient ID, optional"}}, ["medicines"]),
    "today_at_branch": (t_today, "What's happening at this branch today: OPD patients and who is waiting for the doctor, inpatients and their status, stuck patients, appointments; for a doctor, their own day.",
                        {}, []),
    "stock_alerts": (t_stock_alerts, "Pharmacy alerts at this branch: stock expiring within 6 months, expired stock still on the shelf, medicines not sold in 30 days, below reorder level, supplier bills due.",
                     {}, []),
    "money_report": (t_money, "Revenue, collections by service with counts, payment modes, discounts/refunds, net collected, dues and doctor-wise numbers for one day (default today).",
                     {"date": {"type": "string", "description": "YYYY-MM-DD, optional"}}, []),
    "lab_report": (t_lab_report, "Results of one lab order by lab number (LAB12), with flags and normal ranges.",
                   {"lab_no": {"type": "string"}}, ["lab_no"]),
}


def tool_defs():
    return [{"name": n, "description": d, "input_schema": {"type": "object", "properties": p, "required": r, "additionalProperties": False}}
            for n, (_, d, p, r) in TOOLS.items()]


def run_tool(c, h, name, args):
    """Returns (json_text, is_error)."""
    if name not in TOOLS:
        return f"Unknown tool {name}", True
    try:
        res = TOOLS[name][0](c, h, args if isinstance(args, dict) else {})
        return json.dumps(res, default=str)[:30000], False
    except Denied as e:
        return str(e), True
    except ApiError as e:
        return str(e), True


# ---------------------------------------------------------------- conversation (installed server, Claude API)
def _client(c):
    key = get_settings(c).get("anthropic_api_key")
    need(key, "The assistant needs an Anthropic API key in Admin > Settings (AI).")
    try:
        import anthropic
    except ImportError:
        raise ApiError(400, "The assistant needs the Anthropic SDK on the server: run  pip install anthropic  and restart.")
    return anthropic, anthropic.Anthropic(api_key=key)


def _blocks(content):
    """Assistant content as plain dicts, unchanged, so it can be stored and sent back on the next turn."""
    return [b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else b for b in content]


def converse(c, h, chat, text, voice=False):
    anthropic, client = _client(c)
    msgs = json.loads(chat["messages"] or "[]")
    who = f"Signed in: {h.user['name']}, role {h.user['role']}" + (f", branch {one(c, 'SELECT name FROM branches WHERE id=?', (h.branch,))['name']}" if h.branch else ", all branches")
    msgs.append({"role": "user", "content": f"[{who}. Today {today()}.{' ' + VOICE_NOTE if voice else ''}]\n{text}"})
    used = []
    for _ in range(MAX_ROUNDS):
        try:
            resp = client.beta.messages.create(
                model=MODEL, max_tokens=16000, system=SYSTEM, tools=tool_defs(), messages=msgs,
                output_config={"effort": "low"}, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except anthropic.AuthenticationError:
            raise ApiError(400, "The Anthropic API key was rejected. Check it in Admin > Settings.")
        except anthropic.RateLimitError:
            raise ApiError(429, "The assistant is busy. Try again in a minute.")
        except anthropic.BadRequestError as e:
            raise ApiError(400, f"The assistant couldn't answer: {e.message}")
        except anthropic.APIStatusError as e:
            raise ApiError(502, f"AI service error ({e.status_code}). Try again later.")
        except anthropic.APIConnectionError:
            raise ApiError(502, "No connection to the AI service. Check the internet connection.")
        msgs.append({"role": "assistant", "content": _blocks(resp.content)})
        if resp.stop_reason == "refusal":
            answer = "I can't help with that one. Please check the record directly or ask a colleague."
            break
        calls = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason != "tool_use" or not calls:
            answer = "".join(b.text for b in resp.content if b.type == "text").strip() or "(no answer)"
            if resp.stop_reason == "max_tokens":
                answer += "\n(The answer was cut short. Ask for less at a time.)"
            break
        results = []
        for b in calls:
            out, err = run_tool(c, h, b.name, b.input)
            used.append(b.name)
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, **({"is_error": True} if err else {})})
        msgs.append({"role": "user", "content": results})
    else:
        answer = "That needed too many look-ups. Please ask a narrower question."
    c.execute("UPDATE assistant_chats SET messages=?, updated_at=?, turns=turns+1 WHERE id=?", (json.dumps(msgs), now_str(), chat["id"]))
    audit(c, h, "assistant.ask", f"{len(text)} chars, tools: {', '.join(used) or 'none'}{' (voice)' if voice else ''}")
    return {"answer": answer, "tools": used}


def _chat(c, h, cid=None):
    if cid:
        ch = one(c, "SELECT * FROM assistant_chats WHERE id=? AND user_id=?", (cid, h.user["id"]))
        need(ch, "Conversation not found", 404)
        return ch
    cid = secrets.token_hex(8)
    c.execute("INSERT INTO assistant_chats(id,user_id,created_at,updated_at,messages,turns) VALUES(?,?,?,?,?,0)", (cid, h.user["id"], now_str(), now_str(), "[]"))
    return one(c, "SELECT * FROM assistant_chats WHERE id=?", (cid,))


def _enabled(c, h):
    need(get_settings(c).get("assistant_on", "1") == "1", "The assistant is switched off in Admin > Settings.", 403)
    need(h.user["role"] in ("doctor", "pharmacist", "manager", "owner", "nurse", "lab_tech", "accountant") or all_access(h.user),
         "The assistant isn't available for your role.", 403)


@route("POST", "/api/assistant/ask", "any")
def api_ask(h, c, b, q):
    _enabled(c, h)
    text = clean(b, "text", 2000)
    need(text, "Type or say a question")
    chat = _chat(c, h, clean(b, "chat_id", 32) or None)
    r = converse(c, h, chat, text, bool(b.get("voice")))
    return dict(r, chat_id=chat["id"])


@route("POST", "/api/assistant/tool", "any")
def api_tool(h, c, b, q):
    """For an assistant that runs outside this server (the in-browser demo): run one read-only tool as this user."""
    _enabled(c, h)
    name = clean(b, "name", 40)
    out, err = run_tool(c, h, name, b.get("input") or {})
    audit(c, h, "assistant.tool", name)
    return {"ok": not err, "result": out}


@route("GET", "/api/assistant/info", "any")
def api_info(h, c, b, q):
    s = get_settings(c)
    on = s.get("assistant_on", "1") == "1"
    try:
        _enabled(c, h)
        allowed = True
    except ApiError:
        allowed = False
    return {"enabled": on and allowed, "server_ai": bool(s.get("anthropic_api_key")), "patients": s.get("assistant_patients", "1") == "1",
            "system": SYSTEM, "voice_note": VOICE_NOTE, "tools": tool_defs()}
