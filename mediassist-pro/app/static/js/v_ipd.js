/* Inpatients: bed board, admission, notes and vitals, MAR, charges and running bill, discharge. */
"use strict";
RENDER.ipd = async (main, [mode, id]) => {
  if (mode === "a" && id) return admission(main, +id);
  const [beds, docs] = await Promise.all([api("/api/beds"), staff("doctor")]);
  let pre = "";
  if (mode === "admit" && id) { const p = await api("/api/patients/" + id); pre = `${p.code} · ${p.name} · ${p.phone}`; }
  const wards = {}; beds.forEach(b => (wards[b.ward] = wards[b.ward] || []).push(b));
  const free = beds.filter(b => b.status === "free");
  main.innerHTML = `<div class="kpis">${kpi("Occupied", `${beds.filter(b => b.status === "occupied").length} / ${beds.length}`, "beds")}${kpi("Free", free.length, "ready for admission")}${kpi("Cleaning", beds.filter(b => b.status === "cleaning").length, "mark free when ready", "warn")}${kpi("Blocked", beds.filter(b => b.status === "blocked").length, "")}</div>
  <div class="g-main"><div class="stack">${Object.entries(wards).map(([w, l]) => card(`${esc(w)} ward`, `${l.filter(b => b.status === "occupied").length} of ${l.length} occupied`, `<div class="beds">${l.map(b => b.status === "occupied"
      ? `<button class="bed occupied" data-act="go" data-v="ipd" data-p="a/${b.adm_id}"><span class="num-tag">${esc(b.number)} · ${b.kind}</span><b>${esc(b.pname)}</b><span class="small muted">${b.age ?? "?"}${(b.gender || " ")[0]} · ${esc(b.diagnosis || "")}</span><span class="small muted">${esc(b.dname || "")} · since ${b.admitted_at.slice(5, 10)}</span></button>`
      : `<div class="bed ${b.status}"><span class="num-tag">${esc(b.number)} · ${b.kind}</span><b>${b.status === "free" ? "Free" : b.status === "cleaning" ? "Cleaning" : "Blocked"}</b>${can("ipd_nursing") ? `<div class="row-actions">${b.status !== "free" ? `<button class="btn sm ghost" data-act="bedStatus" data-id="${b.id}" data-s="free">Mark free</button>` : `<button class="btn sm ghost" data-act="bedStatus" data-id="${b.id}" data-s="blocked">Block</button>`}</div>` : ""}</div>`).join("")}</div>`)).join("") || card("No beds yet", "", `<p class="empty">Add wards and beds below.</p>`)}</div>
  <div class="stack">${can("ipd") ? card("Admit a patient", "A deposit can be taken now", `<form data-submit="admit" class="stack"><div class="fields">${patInput("patient", pre)}
      <div class="span2"><label>Bed</label><select name="bed_id">${free.map(b => `<option value="${b.id}">${esc(b.ward)} ${esc(b.number)} (${b.kind})</option>`).join("") || "<option value=''>No free bed</option>"}</select></div>
      <div><label>Doctor</label>${docSelect(docs, "doctor_id", App.me.role === "doctor" ? App.me.id : "", "")}</div><div class="span2"><label>Reason</label><input name="reason"></div>
      <div class="span2"><label>Provisional diagnosis</label><input name="diagnosis"></div><div><label>ICD-10</label><input name="icd" list="icdOpts" data-input="icdSearch"></div>
      <div><label>Deposit ₹</label><input name="deposit" type="number" min="0"></div><div><label>Mode</label><select name="mode"><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option></select></div><div><label>Reference</label><input name="ref"></div></div>
      <div class="btns"><button class="btn">Admit</button></div></form>`) : ""}
    ${can("stock_admin") ? card("Add a bed", "", `<form data-submit="addBed" class="fields"><div><label>Ward</label><input name="ward" placeholder="General"></div><div><label>Bed no.</label><input name="number" placeholder="G7"></div><div><label>Type</label><select name="kind"><option value="general">General</option><option value="private">Private</option><option value="icu">ICU</option></select></div><div style="align-self:end"><button class="btn sm">Add</button></div></form>`) : ""}</div></div>`;
};
on("bedStatus", async el => { await api(`/api/beds/${el.dataset.id}/status`, { status: el.dataset.s }); go("ipd"); });
on("addBed", async f => { await api("/api/beds", vals(f)); toast("Bed added"); go("ipd"); });
on("admit", async f => {
  const v = vals(f), pid = pidOf(v.patient); if (!pid) return toast("Pick the patient from the list.");
  const r = await api("/api/admissions", { ...v, patient_id: pid }); toast(`Admitted as ${r.ip_no}`); go("ipd", ["a", r.id]);
});

async function admission(main, id) {
  const [a] = await Promise.all([api("/api/admissions/" + id + (App.cache.marDay ? "?mar_day=" + App.cache.marDay : "")), loadMeds(), loadServices()]); App.cache.adm = a;
  const tab = App.cache.admTab || "care", open = a.status === "admitted", isDoc = ["doctor", "owner"].includes(App.me.role);
  main.innerHTML = `<div class="card" style="margin-bottom:14px"><div class="phead"><div class="avatar">${initials(a.pname)}</div><div style="flex:1;min-width:0"><h2>${esc(a.pname)} <span class="mono small muted">${a.ip_no}</span></h2>
    <div class="small muted">${a.code} · ${a.age ?? "?"} yrs · ${esc(a.gender || "")}${a.weight ? ` · ${a.weight} kg` : ""} · ${esc(a.ward || "")} ${esc(a.bed || "")} · ${esc(a.dname || "")} · admitted ${a.admitted_at}</div></div>${open ? pill("Admitted", "p-info") : pill("Discharged " + (a.discharged_at || ""), "p-ok")}</div>
    ${a.allergies ? `<div class="banner" style="margin-top:10px">Allergic to ${esc(a.allergies)}</div>` : ""}
    <p class="small" style="margin:8px 0 0"><b>Diagnosis:</b> ${esc(a.diagnosis || "–")} ${a.icd ? `(${esc(a.icd)})` : ""} · <b>Running bill:</b> ${money(a.bill.total)} · deposits ${money(a.bill.deposits)} · <b>${a.bill.balance < 0 ? "advance left " + money(-a.bill.balance) : "balance " + money(a.bill.balance)}</b></p></div>
  ${subtabs([["care", "Notes and vitals"], ["mar", "Medicines"], ["bill", "Charges and bill"], ["dc", open ? "Discharge" : "Discharge summary"]], tab, "admTab")}<div id="admBody"></div>`;
  const body = $("#admBody");
  if (tab === "care") {
    body.innerHTML = `<div class="g-form">${open ? card("Add note", isDoc ? "Doctor's round (adds a visit charge)" : "Nursing note", `<form data-submit="admNote" class="stack"><textarea name="text" placeholder="${isDoc ? "Findings, plan" : "Condition, intake/output, care given"}"></textarea>
      <div class="fields"><div><label>Temp</label><input name="temp" type="number" step=".1"></div><div><label>Pulse</label><input name="pulse" type="number"></div><div><label>BP sys</label><input name="bp_sys" type="number"></div><div><label>BP dia</label><input name="bp_dia" type="number"></div><div><label>SpO₂</label><input name="spo2" type="number"></div><div><label>Sugar</label><input name="sugar" type="number"></div></div>
      ${isDoc ? `<label class="check"><input type="checkbox" name="charge_visit" value="1" checked> Charge a doctor visit for this round</label>` : ""}
      <div class="btns"><button class="btn">Save note</button></div></form>`) : "<div></div>"}
      <div class="stack">${card("Vitals", "", tbl(["When", "Temp", "Pulse", "BP", "SpO₂", "Sugar"], a.vitals.map(v => `<tr><td class="mono">${v.at.slice(5)}</td><td>${v.temp ?? "–"}</td><td>${v.pulse ?? "–"}</td><td>${v.bp_sys ?? "–"}/${v.bp_dia ?? "–"}</td><td>${v.spo2 ?? "–"}</td><td>${v.sugar ?? "–"}</td></tr>`).join("")))}
      ${card("Notes", "", `<div class="timeline">${a.notes.map(n => `<div class="tl"><div class="when">${n.at} · ${esc(n.uname || "")} · ${n.kind}</div>${esc(n.text)}</div>`).join("") || '<p class="empty">No notes yet.</p>'}</div>`)}
      ${card("Lab tests", "", tbl(["Order", "Tests", "Status"], a.labs.map(l => `<tr class="click" data-act="go" data-v="lab" data-p="o/${l.id}"><td class="mono">LAB${l.id}</td><td>${esc(l.tests)}</td><td>${l.status}</td></tr>`).join(""), "None ordered.") + (open ? `<div class="btns"><button class="btn sm ghost" data-act="admLab">Order tests</button></div>` : ""))}</div></div>`;
  } else if (tab === "mar") {
    body.innerHTML = card("Medicines today", "Each dose given is taken from this branch's pharmacy stock and charged to the bill",
      `<div class="tbl mar"><table><tr><th>Medicine</th><th>Dose</th><th>Route</th><th>Freq</th><th>${a.mar_day === localDay() ? "Today" : a.mar_day}</th><th></th></tr>${a.mar.map(m => `<tr><td><b>${esc(m.name)}</b><div class="small muted">by ${esc(m.oname || "")} · ${m.start_at.slice(5)}</div></td><td>${esc(m.dose)}</td><td>${esc(m.route)}</td><td class="mono">${esc(m.freq)}${m.times ? " " + esc(m.times) : ""}</td>
        <td>${m.active ? m.slots.map(s => `<span class="slot"><span class="mono">${s.due}</span>${s.record ? `<span class="${s.record.status === "given" ? "given" : "held"}">${s.record.status} ${s.record.at.slice(11)}</span>` : (can("ipd_nursing") && open ? `<span class="row-actions"><button class="btn sm" data-act="marGive" data-id="${m.id}" data-due="${s.due}">Give</button><button class="btn sm ghost" data-act="marHold" data-id="${m.id}" data-due="${s.due}">Hold</button></span>` : "due")}</span>`).join("") + m.extra.map(x => `<span class="slot">extra <span class="given">${x.status} ${x.at.slice(11)}</span></span>`).join("") : pill("Stopped", "p-plain")}</td>
        <td>${m.active && isDoc && open ? `<button class="btn sm ghost" data-act="marStop" data-id="${m.id}">Stop</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="6" class="empty">No medicines ordered.</td></tr>'}</table></div>
      ${isDoc && open ? `<h3 style="margin:14px 0 8px">Order a medicine</h3><form data-submit="marOrder" class="fields"><div class="span2"><input name="med" list="medOpts" placeholder="Medicine"></div><div><input name="dose" value="1" placeholder="Dose"></div><div><select name="route"><option>oral</option><option>IV</option><option>IM</option><option>SC</option><option>inhaled</option><option>topical</option></select></div><div><select name="freq"><option>OD</option><option>BD</option><option>TDS</option><option>QID</option><option>HS</option><option>SOS</option><option>STAT</option></select></div><div><input name="times" placeholder="Times, e.g. 08:00,20:00"></div><div><input name="days" type="number" min="1" max="90" placeholder="Days (blank = until stopped)"></div><div><button class="btn sm">Order</button></div></form>` : ""}`,
      `<input type="date" value="${a.mar_day}" max="${localDay()}" data-change="marDay" style="width:auto" title="Show another day's chart">`);
  } else if (tab === "bill") {
    body.innerHTML = `<div class="g-main">${card("Running bill", `${a.bill.days} bed day(s) so far`, tbl(["Item", "Qty", "Rate", "Amount"], a.bill.lines.map(l => `<tr><td>${esc(l.name)}<div class="small muted">${esc(l.cat || "")}${l.at ? " · " + l.at.slice(5) : ""}</div></td><td class="num">${l.qty}</td><td class="num">${money(P2R(l.rate_p))}</td><td class="num">${money(P2R(l.amount_p))}</td></tr>`).join("")) +
      `<div class="totals"><div><span>Hospital charges</span><b>${money(a.bill.total)}</b></div><div><span>Pharmacy credit bills</span><b>${money(a.bill.pharmacy_credit)}</b></div><div><span>Deposits received</span><b>− ${money(a.bill.deposits)}</b></div><div class="grand"><span>${a.bill.balance < 0 ? "Advance left (refund at discharge)" : "Balance due"}</span><b>${money(Math.abs(a.bill.balance))}</b></div></div>`)}
      <div class="stack">${open ? card("Add a charge", "Procedures, consumables, visits", `<form data-submit="admCharge" class="stack"><input name="svc" list="svcOpts" placeholder="Service"><input name="qty" type="number" min="1" value="1"><button class="btn sm">Add charge</button></form>`) : ""}
      ${open && can("hbilling") ? card("Take a deposit", "", `<form data-submit="admDeposit" class="stack"><input name="amount" type="number" min="1" placeholder="Amount ₹"><select name="mode"><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option></select><input name="ref" placeholder="Reference"><button class="btn sm">Record deposit</button></form>`) : ""}
      ${!open && a.invoice_id ? `<button class="btn" data-act="go" data-v="hbilling" data-p="inv/${a.invoice_id}">Open final invoice</button>` : ""}</div></div>`;
  } else {
    const s = a.summary || {};
    body.innerHTML = open ? card("Discharge", isDoc ? "Creates the final invoice and frees the bed" : "Only a doctor can discharge", `<form data-submit="discharge" class="stack"><div class="fields">
      <div class="span2"><label>Final diagnosis</label><input name="final_diagnosis" value="${esc(a.diagnosis || "")}" required></div><div><label>ICD-10</label><input name="icd" list="icdOpts" data-input="icdSearch" value="${esc(a.icd || "")}"></div>
      <div><label>Discharge type</label><select name="discharge_type"><option value="normal">Normal</option><option value="lama">Left against advice</option><option value="referred">Referred</option><option value="death">Death</option></select></div></div>
      ${[["history", "History and presenting complaint"], ["course", "Course in hospital"], ["procedures", "Procedures done"], ["investigations", "Key investigations"], ["condition", "Condition at discharge"], ["medications", "Medicines at discharge"], ["advice", "Advice"]].map(([k, l]) => `<div><label>${l}</label><textarea name="${k}"></textarea></div>`).join("")}
      <div class="fields"><div><label>Follow-up date</label><input name="followup" type="date"></div></div>
      ${a.labs.some(l => l.status === "ordered" || l.status === "collected") ? `<label class="check"><input type="checkbox" name="ignore_pending" value="1"> Discharge anyway: ${a.labs.filter(l => l.status === "ordered" || l.status === "collected").length} lab order(s) have no result yet</label>` : ""}
      <div class="btns"><button class="btn" ${isDoc ? "" : "disabled"}>Discharge and create invoice</button></div></form>`)
      : card("Discharge summary", `${a.discharge_type || ""} · ${a.discharged_at}`, `${[["Final diagnosis", s.final_diagnosis + (s.icd ? ` (${s.icd})` : "")], ["History", s.history], ["Course in hospital", s.course], ["Procedures", s.procedures], ["Investigations", s.investigations], ["Condition at discharge", s.condition], ["Medicines", s.medications], ["Advice", s.advice], ["Follow-up", s.followup]].filter(x => x[1]).map(([l, v]) => `<p><b>${l}:</b><br>${esc(v)}</p>`).join("")}<button class="btn ghost" data-act="printDc">Print summary</button>`);
  }
}
on("admTab", el => { App.cache.admTab = el.dataset.k; go("ipd", ["a", App.cache.adm.id]); });
const reAdm = () => go("ipd", ["a", App.cache.adm.id]);
on("marDay", el => { App.cache.marDay = el.value; reAdm(); });
on("admNote", async f => { const v = vals(f); if (f.charge_visit) v.charge_visit = f.charge_visit.checked; await api(`/api/admissions/${App.cache.adm.id}/notes`, v); toast("Saved"); reAdm(); });
on("marOrder", async f => {
  const v = vals(f), m = medByName(v.med); if (!m) return toast("Choose a medicine from the list.");
  const r = await withOverride((ov, reason) => api(`/api/admissions/${App.cache.adm.id}/mar`, { ...v, medicine_id: m.id, override: ov, override_reason: reason }));
  if (r) { toast("Ordered"); reAdm(); }
});
on("marGive", async el => { const r = await api(`/api/mar/${el.dataset.id}/give`, { due: el.dataset.due }); toast(r.warning || "Dose recorded and charged"); reAdm(); });
on("marHold", async el => { const v = await dialog("Hold or refuse this dose", `<label>Status</label><select name="status"><option value="held">Held</option><option value="refused">Refused by patient</option></select><label>Reason</label><input name="note" placeholder="e.g. BP low, NPO for surgery">`, { ok: "Record" }); if (v) { await api(`/api/mar/${el.dataset.id}/give`, { ...v, due: el.dataset.due }); reAdm(); } });
on("marStop", async el => { await api(`/api/mar/${el.dataset.id}/stop`, {}); reAdm(); });
on("admCharge", async f => { const v = vals(f), s = svcByName(v.svc); if (!s) return toast("Choose a service from the list."); await api(`/api/admissions/${App.cache.adm.id}/charges`, { service_id: s.id, qty: v.qty }); toast("Charge added"); reAdm(); });
on("admDeposit", async f => { await api(`/api/admissions/${App.cache.adm.id}/deposit`, vals(f)); toast("Deposit recorded"); reAdm(); });
on("admLab", async () => {
  const tests = await api("/api/lab/tests");
  const v = await dialog("Order lab tests", tests.map(t_ => `<label class="check"><input type="checkbox" name="t${t_.id}"> ${esc(t_.name)}</label>`).join("") + `<label>Priority</label><select name="priority"><option value="routine">Routine</option><option value="urgent">Urgent</option><option value="stat">STAT</option></select>`, { ok: "Order" });
  if (!v) return; const ids = Object.keys(v).filter(k => /^t\d+$/.test(k) && v[k]).map(k => +k.slice(1)); if (!ids.length) return;
  await api("/api/lab/orders", { patient_id: App.cache.adm.patient_id, admission_id: App.cache.adm.id, tests: ids, priority: v.priority }); toast("Sent to the lab"); reAdm();
});
on("discharge", async f => {
  if (!await dialog("Discharge now?", "<p>This closes the stay, creates the final invoice with all charges, applies the deposits and frees the bed.</p>", { ok: "Discharge" })) return;
  const v = vals(f); if (f.ignore_pending) v.ignore_pending = f.ignore_pending.checked;
  const r = await api(`/api/admissions/${App.cache.adm.id}/discharge`, v); toast(`Discharged. Invoice ${r.inv_no}`); App.cache.admTab = "dc"; reAdm();
});
on("printDc", () => {
  const a = App.cache.adm, s = a.summary || {};
  printHtml(`<div class="hdr"><div><h2>${esc(a.bname)}</h2><div>${esc(a.baddr || "")} · ${esc(a.bphone || "")}</div></div><div style="text-align:right"><b>DISCHARGE SUMMARY</b><div>${a.ip_no}</div></div></div>
    <p><b>${esc(a.pname)}</b> · ${a.code} · ${a.age ?? "?"} yrs · ${esc(a.gender || "")}<br>Admitted ${a.admitted_at} · Discharged ${a.discharged_at} (${esc(a.discharge_type || "")}) · ${esc(a.dname || "")} ${a.dreg ? "· Reg. " + esc(a.dreg) : ""}<br><b>Allergies:</b> ${esc(a.allergies || "none")}</p>
    ${[["Final diagnosis", (s.final_diagnosis || "") + (s.icd ? ` (ICD-10 ${s.icd})` : "")], ["History", s.history], ["Course in hospital", s.course], ["Procedures", s.procedures], ["Investigations", s.investigations], ["Condition at discharge", s.condition], ["Medicines at discharge", s.medications], ["Advice", s.advice], ["Follow-up", s.followup]].filter(x => x[1]).map(([l, v]) => `<p><b>${l}</b><br>${esc(v)}</p>`).join("")}
    <br><p style="text-align:right">Signature ____________________</p>`);
});
