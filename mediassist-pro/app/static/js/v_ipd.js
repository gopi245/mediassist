/* Inpatients: bed board, admission, notes and vitals, MAR, charges and running bill, discharge. */
"use strict";
RENDER.ipd = async (main, [mode, id, tab]) => {
  if (mode === "a" && id) { if (tab) App.cache.admTab = tab; return admission(main, +id); }   // a/<id>/<tab>: open on that tab
  const [beds, docs] = await Promise.all([api("/api/beds"), staff("doctor")]);
  let pre = "";
  App.cache.assign = null; App.cache.ipdDocs = docs;
  if (mode === "admit" && id) { const p = await api("/api/patients/" + id); pre = `${p.code} · ${p.name} · ${p.phone}`; App.cache.assign = { id: p.id, name: p.name, code: p.code }; }
  const wards = {}; beds.forEach(b => (wards[b.ward] = wards[b.ward] || []).push(b));
  const free = beds.filter(b => b.status === "free");
  if (mode === "admit" && !App.cache.admitBed) { try { App.cache.admitBed = +sessionStorage.getItem("ma-admit-bed") || null; } catch (e) {} }
  try { sessionStorage.removeItem("ma-admit-bed"); } catch (e) {}
  const tile = b => b.status === "occupied"
    ? `<button class="mtile occupied" data-act="go" data-v="ipd" data-p="a/${b.adm_id}" title="${esc(b.number)} · ${esc(b.pname)} · ${esc(b.dname || "")}"><b>${esc(b.number)}</b><span>${esc((b.pname || "").split(" ")[0])}</span></button>`
    : `<button class="mtile ${b.status}" ${b.status === "free" && can("admit") ? `data-act="mapAdmit" data-id="${b.id}"` : "disabled"} title="${esc(b.number)} · ${b.status}"><b>${esc(b.number)}</b><span>${b.kind === "icu" ? "ICU" : b.kind === "private" ? "Pvt" : "Gen"}${b.ac ? " · AC" : ""}</span></button>`;
  const rooms = l => { const g = []; l.forEach(b => { const k = b.room || ""; let x = g.find(y => y.k === k); if (!x) g.push(x = { k, l: [] }); x.l.push(b); }); return g; };
  const roomBox = r => r.k ? `<div class="mroom"><div class="mroom-h">Room ${esc(r.k)} · ${r.l[0].ac ? "AC" : "Non-AC"} · ${r.l.length} bed${r.l.length > 1 ? "s" : ""}</div><div class="mroom-g">${r.l.map(tile).join("")}</div></div>` : r.l.map(tile).join("");
  const map = beds.length ? card("Bed map", `Tap a green bed to admit, a red bed to open the patient`,
    `<div class="mlegend"><span class="mtile free"></span>Free <span class="mtile occupied"></span>Occupied <span class="mtile cleaning"></span>Cleaning <span class="mtile blocked"></span>Blocked</div>` +
    Object.entries(wards).map(([w, l]) => `<div class="mward"><div class="mward-h"><b>${esc(w)}</b> <span class="small muted">${l.filter(b => b.status === "free").length} free of ${l.length}</span></div><div class="mgrid">${rooms(l).map(roomBox).join("")}</div></div>`).join("")) : "";
  const as = App.cache.assign;
  const banner = as ? `<div class="bedinfo" style="margin:0 0 14px"><span class="bedinfo-ic" aria-hidden="true">🛏</span><div style="flex:1;min-width:0"><b>Choosing a bed for ${esc(as.name)}</b> <span class="mono small">${esc(as.code)}</span><div class="small">Tap any green (free) bed to assign it.</div></div><button class="btn sm ghost" data-act="go" data-v="patients" data-p="${as.id}">Cancel</button></div>` : "";
  main.innerHTML = banner + map + `<div class="row-actions" style="margin-bottom:10px"><button class="btn sm ghost" data-act="go" data-v="beds">Open the bed board</button></div><div class="kpis">${kpi("Occupied", `${beds.filter(b => b.status === "occupied").length} / ${beds.length}`, "beds")}${kpi("Free", free.length, "ready for admission")}${kpi("Cleaning", beds.filter(b => b.status === "cleaning").length, "mark free when ready", "warn")}${kpi("Blocked", beds.filter(b => b.status === "blocked").length, "")}</div>
  <div class="g-main"><div class="stack"><details class="opt"><summary>Every bed, with Mark free / Block</summary>${Object.entries(wards).map(([w, l]) => card(`${esc(w)} ward`, `${l.filter(b => b.status === "occupied").length} of ${l.length} occupied`, `<div class="beds">${l.map(b => b.status === "occupied"
      ? `<button class="bed occupied" data-act="go" data-v="ipd" data-p="a/${b.adm_id}"><span class="num-tag">${esc(b.number)} · ${b.kind}</span><b>${esc(b.pname)}</b><span class="small muted">${b.age ?? "?"}${(b.gender || " ")[0]} · ${esc(b.diagnosis || "")}</span><span class="small muted">${esc(b.dname || "")} · since ${b.admitted_at.slice(5, 10)}</span></button>`
      : `<div class="bed ${b.status}"><span class="num-tag">${esc(b.number)} · ${b.kind}</span><b>${b.status === "free" ? "Free" : b.status === "cleaning" ? "Cleaning" : "Blocked"}</b>${b.status === "free" && as && can("admit") ? `<div class="row-actions"><button class="btn sm" data-act="mapAdmit" data-id="${b.id}">Assign</button></div>` : ""}${can("ipd_nursing") || can("admit") ? `<div class="row-actions">${b.status !== "free" ? `<button class="btn sm ghost" data-act="bedStatus" data-id="${b.id}" data-s="free">Mark free</button>` : `<button class="btn sm ghost" data-act="bedStatus" data-id="${b.id}" data-s="blocked">Block</button>`}</div>` : ""}</div>`).join("")}</div>`)).join("") || card("No beds yet", "", `<p class="empty">Add wards and beds below.</p>`)}</details></div>
  <div class="stack">${can("admit") ? card("Admit a patient", "A deposit can be taken now", `<form data-submit="admit" class="stack"><div class="fields">${patInput("patient", pre)}</div>${newPatBlock()}<div class="fields">
      <div class="span2"><label>Bed</label><select name="bed_id">${free.map(b => `<option value="${b.id}" ${App.cache.admitBed === b.id ? "selected" : ""}>${esc(b.ward)} · ${b.room ? `Room ${esc(b.room)} · ` : ""}${esc(b.number)} (${b.kind}${b.ac ? ", AC" : ""})</option>`).join("") || "<option value=''>No free bed</option>"}</select></div>
      <div><label>Doctor</label>${docSelect(docs, "doctor_id", App.me.role === "doctor" ? App.me.id : "", "")}</div><div class="span2"><label>Reason</label><input name="reason"></div>
      <div class="span2"><label>Provisional diagnosis</label><input name="diagnosis" value="${esc(App.cache.admitDx || "")}"></div><div><label>ICD-10</label><input name="icd" list="icdOpts" data-input="icdSearch"></div>
      <div><label>Deposit ₹</label><input name="deposit" type="number" min="0"></div><div><label>Mode</label><select name="mode"><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option></select></div><div><label>Reference</label><input name="ref"></div></div>
      <div class="btns"><button class="btn">Admit</button></div></form>`) : ""}
    ${can("stock_admin") ? card("Add a room", "Room 101 with 3 beds makes 101-A, 101-B, 101-C. With 1 bed it's just 101. Add each room once.", `<form data-submit="addBed" class="fields"><div><label>Ward / floor</label><input name="ward" placeholder="First floor"></div><div><label>Room no.</label><input name="room" placeholder="101" maxlength="8" required></div><div><label>Beds in room</label><input name="count" type="number" min="1" max="26" value="1"></div><div><label>AC</label><select name="ac"><option value="0">Non-AC</option><option value="1">AC</option></select></div><div><label>Type</label><select name="kind"><option value="general">General</option><option value="private">Private</option><option value="icu">ICU</option></select></div><div style="align-self:end"><button class="btn sm">Add</button></div></form>`) : ""}</div></div>`;
};
on("moveBed", async f => { const v = vals(f); if (!v.bed_id) return; await api(`/api/admissions/${App.cache.adm.id}/transfer`, v); toast("Bed changed. The old bed is marked for cleaning."); go("ipd", ["a", App.cache.adm.id]); });
on("bedStatus", async el => { await api(`/api/beds/${el.dataset.id}/status`, { status: el.dataset.s }); go("ipd"); });
on("addBed", async f => { const r = await api("/api/beds", vals(f)); toast(r.added === 1 ? "Bed added" : `${r.added} beds added`); go("ipd"); });
on("mapAdmit", async el => {
  const as = App.cache.assign;
  if (as) {
    const label = el.querySelector("b") ? el.querySelector("b").textContent : (el.closest(".bed")?.querySelector(".num-tag")?.textContent || "").split(" · ")[0];
    const v = await dialog(`Assign bed ${label} to ${as.name}?`, `<label>Doctor (optional)</label>${docSelect(App.cache.ipdDocs, "doctor_id", App.me.role === "doctor" ? App.me.id : "", "No doctor yet")}<label>Reason (optional)</label><input name="reason">`, { ok: "Assign bed" });
    if (!v) return;
    await api("/api/admissions", { ...v, patient_id: as.id, bed_id: +el.dataset.id });
    toast(`Bed ${label} assigned to ${as.name}`); App.cache.assign = null; go("patients", [as.id]); return;
  }
  const s = $("form[data-submit=admit] select[name=bed_id]"); if (!s) return; s.value = el.dataset.id; s.closest("form").scrollIntoView({ behavior: "smooth" }); s.closest("form").querySelector("input").focus(); });
on("admit", async f => {
  const v = vals(f), pid = await opdPatient(f); if (!pid) return;
  const r = await api("/api/admissions", { ...v, patient_id: pid }); App.cache.admitBed = null; App.cache.admitDx = null; toast(`Admitted as ${r.ip_no}`); go("ipd", ["a", r.id]);
});

async function admission(main, id) {
  const [a, beds] = await Promise.all([api("/api/admissions/" + id + (App.cache.marDay ? "?mar_day=" + App.cache.marDay : "")), api("/api/beds"), loadMeds(), loadServices()]); App.cache.adm = a;
  if (!App.cache.ipdDocs) App.cache.ipdDocs = await staff("doctor").catch(() => []);
  const tab = can("ipd") ? App.cache.admTab || "care" : "bill", open = a.status === "admitted", isDoc = ["doctor", "owner"].includes(App.me.role);
  const w = a.watch || {}, n2 = w.news2;
  const newsPill = n2 ? pill(`NEWS2 ${n2.score} · ${n2.band}`, n2.band === "high" ? "p-crit" : n2.band === "medium" ? "p-warn" : "p-ok") : pill("No vitals yet", "p-plain");
  const freeBeds = beds.filter(b => b.status === "free");
  const move = open && can("admit") ? `<form data-submit="moveBed" class="fields" style="margin-top:10px"><div class="span2"><label>Change bed</label><select name="bed_id">${freeBeds.map(b => `<option value="${b.id}">${esc(b.ward)} · ${b.room ? `Room ${esc(b.room)} · ` : ""}${esc(b.number)} (${b.kind}${b.ac ? ", AC" : ""})</option>`).join("") || "<option value=''>No free bed</option>"}</select></div><div style="align-self:end"><button class="btn sm" ${freeBeds.length ? "" : "disabled"}>Move</button></div></form>` : "";
  main.innerHTML = `<div class="card" style="margin-bottom:14px"><div class="phead"><div class="avatar">${initials(a.pname)}</div><div style="flex:1;min-width:0"><h2>${esc(a.pname)} <span class="mono small muted">${a.ip_no}</span></h2>
    <div class="small muted">${a.code} · ${a.age ?? "?"} yrs · ${esc(a.gender || "")}${a.weight ? ` · ${a.weight} kg` : ""} · ${esc(a.ward || "")} ${esc(a.bed || "")} · ${esc(a.dname || "")} · admitted ${a.admitted_at}</div></div>${open ? pill("Admitted", "p-info") : pill("Discharged " + (a.discharged_at || ""), "p-ok")}</div>
    ${a.allergies ? `<div class="banner" style="margin-top:10px">Allergic to ${esc(a.allergies)}</div>` : ""}
    ${open ? `<p class="small" style="margin:8px 0 0">${newsPill} ${n2 ? `<span class="muted">${esc(n2.parts.join(", ") || "all normal")}${n2.missing.length ? " · not recorded: " + n2.missing.join(", ") : ""} · ${esc(n2.action)}</span>` : ""}${w.every_h ? ` · vitals every ${w.every_h} h, next ${w.overdue ? `<b class="allergy">overdue since ${w.due_at.slice(11)}</b>` : "at " + w.due_at.slice(11)}` : ""}</p>` : ""}
    <p class="small" style="margin:8px 0 0">${open ? `<b>Expected discharge:</b> ${a.planned_discharge ? esc(a.planned_discharge) : "not set"} ${isDoc ? `<button class="linkbtn" data-act="planDischarge" data-id="${a.id}" data-d="${esc(a.planned_discharge || "")}">change</button>` : ""} · ` : ""}<b>Diagnosis:</b> ${esc(a.diagnosis || "–")} ${a.icd ? `(${esc(a.icd)})` : ""} · <b>Running bill:</b> ${money(a.bill.total)} · deposits ${money(a.bill.deposits)} · <b>${a.bill.balance < 0 ? "advance left " + money(-a.bill.balance) : "balance " + money(a.bill.balance)}</b></p>${move}</div>
  ${can("ipd") ? subtabs([["care", "Notes and vitals"], ["mar", "Medicines"], ["proc", `Procedures & imaging (${a.procedures.length + a.imaging.length})`], ["bill", "Charges and bill"], ["dc", open ? "Discharge" : "Discharge summary"]], tab, "admTab") : ""}<div id="admBody"></div>`;
  const body = $("#admBody");
  if (tab === "care") {
    body.innerHTML = `<div class="g-form">${open ? card("Add note", isDoc ? "Doctor's round (adds a visit charge)" : "Nursing note", `<form data-submit="admNote" class="stack"><label style="margin:0">Note ${micBtn("text")}</label><textarea name="text" placeholder="${isDoc ? "Findings, plan" : "Condition, intake/output, care given"}"></textarea>
      <div class="fields"><div><label>Temp</label><input name="temp" type="number" step=".1"></div><div><label>Pulse</label><input name="pulse" type="number"></div><div><label>BP sys</label><input name="bp_sys" type="number"></div><div><label>BP dia</label><input name="bp_dia" type="number"></div><div><label>SpO₂</label><input name="spo2" type="number"></div><div><label>Sugar</label><input name="sugar" type="number"></div></div>

      ${isDoc ? `<label class="check"><input type="checkbox" name="charge_visit" value="1" checked> Charge a doctor visit for this round</label>` : ""}      <div class="btns"><button class="btn">Save note</button></div></form>`) : "<div></div>"}
      ${open ? card("Vitals schedule", "How often nursing records vitals; overdue sets show on the ward watch", `<form data-submit="vitalsPlan" class="fields"><div><label>Every (hours)</label><select name="every_h"><option value="">No schedule</option>${[1, 2, 4, 6, 8, 12].map(x => `<option value="${x}" ${w.every_h === x ? "selected" : ""}>${x} h</option>`).join("")}</select></div><div style="align-self:end"><button class="btn sm ghost">Save</button></div></form>`) : ""}
      ${card("Fluids in / out", `Last 24 h: in ${a.io.in_24h} ml · out ${a.io.out_24h} ml · balance <b style="color:${Math.abs(a.io.balance_24h) > 1500 ? "var(--crit)" : "inherit"}">${a.io.balance_24h > 0 ? "+" : ""}${a.io.balance_24h} ml</b>`,
        (open ? `<form data-submit="ioAdd" class="fields"><div><label>Kind</label><select name="kind" data-change="ioKind"><option value="in">Intake</option><option value="out">Output</option></select></div><div><label>Route</label><select name="what" id="ioWhat"><option>oral</option><option>iv</option><option>ng</option><option>blood</option><option>other</option></select></div><div><label>ml</label><input name="ml" type="number" min="1" max="10000"></div><div><label>Note</label><input name="note"></div><div style="align-self:end"><button class="btn sm">Record</button></div></form>` : "") +
        tbl(["When", "", "Route", "ml", "By"], a.io.rows.slice(0, 20).map(x => `<tr><td class="mono small">${x.at.slice(5, 16)}</td><td>${x.kind === "in" ? pill("In", "p-info") : pill("Out", "p-warn")}</td><td>${esc(x.what)}${x.note ? ` <span class="small muted">${esc(x.note)}</span>` : ""}</td><td class="num">${x.ml}</td><td class="small">${esc(x.uname || "")}</td></tr>`).join(""), "Nothing charted yet."))}
      ${open ? card("Shift handover", "The next shift reads this first", `<form data-submit="handover" class="stack"><input name="situation" placeholder="Situation: why they are here, how they are now"><input name="background" placeholder="Background: diagnosis, key history, allergies"><input name="assessment" placeholder="Assessment: vitals trend, NEWS2, concerns"><input name="recommendation" placeholder="Recommendation: what the next shift must do or watch"><div class="btns"><button class="btn sm">Hand over</button></div></form>`) : ""}
      <div class="stack">${card("Vitals", "", tbl(["When", "Temp", "Pulse", "BP", "RR", "SpO₂", "GCS", "Sugar"], a.vitals.map(v => `<tr><td class="mono">${v.at.slice(5)}</td><td>${v.temp ?? "–"}</td><td>${v.pulse ?? "–"}</td><td>${v.bp_sys ?? "–"}/${v.bp_dia ?? "–"}</td><td>${v.resp_rate ?? "–"}</td><td>${v.spo2 ?? "–"}</td><td>${v.gcs ?? "–"}</td><td>${v.sugar ?? "–"}</td></tr>`).join("")))}
      ${card("Notes", "", `<div class="timeline">${a.notes.map(n => `<div class="tl${n.kind === "handover" ? " done" : ""}"><div class="when">${n.at} · ${esc(n.uname || "")} · ${n.kind === "handover" ? "shift handover" : n.kind}</div>${n.kind === "handover" ? n.text.split("\n").map(l => `<div><b>${esc(l.split(":")[0])}:</b>${esc(l.slice(l.indexOf(":") + 1))}</div>`).join("") : esc(n.text)}</div>`).join("") || '<p class="empty">No notes yet.</p>'}</div>`)}
      ${card("Lab tests", "", tbl(["Order", "Tests", "Status"], a.labs.map(l => `<tr class="click" data-act="go" data-v="lab" data-p="o/${l.id}"><td class="mono">LAB${l.id}</td><td>${esc(l.tests)}</td><td>${l.status}</td></tr>`).join(""), "None ordered.") + (open ? `<div class="btns"><button class="btn sm ghost" data-act="admLab">Order tests</button></div>` : ""))}</div></div>`;
  } else if (tab === "mar") {
    body.innerHTML = card("Medicines today", "Each dose given is taken from this branch's pharmacy stock and charged to the bill",
      `<div class="tbl mar"><table><tr><th>Medicine</th><th>Dose</th><th>Route</th><th>Freq</th><th>${a.mar_day === localDay() ? "Today" : a.mar_day}</th><th></th></tr>${a.mar.map(m => `<tr><td><b>${esc(m.name)}</b><div class="small muted">by ${esc(m.oname || "")} · ${m.start_at.slice(5)}${m.verbal ? ` · verbal order, entered by ${esc(m.ename || "nurse")}` : ""}</div>${m.verbal && !m.confirmed_at ? ` ${pill("Needs doctor's confirmation", "p-warn")}${isDoc && open ? ` <button class="btn sm" data-act="marConfirm" data-id="${m.id}">Confirm</button>` : ""}` : ""}</td><td>${esc(m.dose)}</td><td>${esc(m.route)}</td><td class="mono">${esc(m.freq)}${m.times ? " " + esc(m.times) : ""}</td>
        <td>${m.active ? m.slots.map(s => `<span class="slot"><span class="mono">${s.due}</span>${s.record ? `<span class="${s.record.status === "given" ? "given" : "held"}">${s.record.status} ${s.record.at.slice(11)}</span>` : (can("ipd_nursing") && open ? `<span class="row-actions"><button class="btn sm" data-act="marGive" data-id="${m.id}" data-due="${s.due}">Give</button><button class="btn sm ghost" data-act="marHold" data-id="${m.id}" data-due="${s.due}">Hold</button></span>` : "due")}</span>`).join("") + m.extra.map(x => `<span class="slot">extra <span class="given">${x.status} ${x.at.slice(11)}</span></span>`).join("") : pill("Stopped", "p-plain")}</td>
        <td>${m.active && isDoc && open ? `<button class="btn sm ghost" data-act="marStop" data-id="${m.id}">Stop</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="6" class="empty">No medicines ordered.</td></tr>'}</table></div>
      ${(isDoc || can("ipd_nursing")) && open ? `<h3 style="margin:14px 0 8px">${isDoc ? "Order a medicine" : "Add a medicine (doctor's verbal or phone order)"}</h3><form data-submit="marOrder" class="fields">${isDoc ? "" : `<div class="span2"><label>Ordered by</label>${docSelect(App.cache.ipdDocs || [], "ordered_by", a.doctor_id || "", "")}</div>`}<div class="span2"><input name="med" list="medOpts" placeholder="Medicine"></div><div><input name="dose" value="1" placeholder="Dose"></div><div><select name="route"><option>oral</option><option>IV</option><option>IM</option><option>SC</option><option>inhaled</option><option>topical</option></select></div><div><select name="freq"><option>OD</option><option>BD</option><option>TDS</option><option>QID</option><option>HS</option><option>SOS</option><option>STAT</option></select></div><div><input name="times" placeholder="Times, e.g. 08:00,20:00"></div><div><input name="days" type="number" min="1" max="90" placeholder="Days (blank = until stopped)"></div><div><button class="btn sm">Order</button></div></form>` : ""}`,
      `<input type="date" value="${a.mar_day}" max="${localDay()}" data-change="marDay" style="width:auto" title="Show another day's chart">`);
  } else if (tab === "proc") {
    body.innerHTML = careAdmissionTab(a, open, isDoc);
  } else if (tab === "bill") {
    body.innerHTML = `<div class="g-main">${card("Running bill", `${a.bill.days} bed day(s) so far`, tbl(["Item", "Qty", "Rate", "Amount"], a.bill.lines.map(l => `<tr><td>${esc(l.name)}<div class="small muted">${esc(l.cat || "")}${l.at ? " · " + l.at.slice(5) : ""}</div></td><td class="num">${l.qty}</td><td class="num">${money(P2R(l.rate_p))}</td><td class="num">${money(P2R(l.amount_p))}</td></tr>`).join("")) +
      `<div class="totals"><div><span>Hospital charges</span><b>${money(a.bill.total)}</b></div><div><span>Pharmacy credit bills</span><b>${money(a.bill.pharmacy_credit)}</b></div><div><span>Deposits received</span><b>− ${money(a.bill.deposits)}</b></div><div class="grand"><span>${a.bill.balance < 0 ? "Advance left (refund at discharge)" : "Balance due"}</span><b>${money(Math.abs(a.bill.balance))}</b></div></div>`)}
      <div class="stack">${open ? card("Add a charge", "Procedures, consumables, visits", `<form data-submit="admCharge" class="stack"><input name="svc" list="svcOpts" placeholder="Service"><input name="qty" type="number" min="1" value="1"><button class="btn sm">Add charge</button></form>`) : ""}
      ${open ? card("Daily add-ons", "Monitor, oxygen, ventilator… billed automatically every day until stopped", `${(a.daily || []).map(d => `<div class="row-actions" style="justify-content:space-between;margin-bottom:6px"><span>${esc(d.name)} <span class="small muted">${money(P2R(d.rate_p))}/day · since ${d.from_at.slice(5, 16)}${d.to_at ? " · stopped " + d.to_at.slice(5, 16) : ""}</span></span>${!d.to_at ? `<button class="btn sm ghost" data-act="dailyStop" data-id="${d.id}">Stop</button>` : ""}</div>`).join("")}
        <form data-submit="dailyStart" class="stack"><input name="svc" list="svcOpts" placeholder="Service, e.g. Monitor charges, per day"><button class="btn sm ghost">Start daily charge</button></form>`) : ""}
      ${open && can("hbilling") ? card("Take a deposit", "", `<form data-submit="admDeposit" class="stack"><input name="amount" type="number" min="1" placeholder="Amount ₹"><select name="mode"><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option></select><input name="ref" placeholder="Reference"><button class="btn sm">Record deposit</button></form>`) : ""}
      ${!open && a.invoice_id ? `<button class="btn" data-act="go" data-v="hbilling" data-p="inv/${a.invoice_id}">Open final invoice</button>` : ""}</div></div>`;
  } else {
    const s = a.summary || {};
    body.innerHTML = open ? card("Discharge", isDoc ? "Creates the final invoice and frees the bed" : "Only a doctor can discharge",
      `<form data-submit="discharge" class="stack"><div class="fields">
      <div class="span2"><label>Final diagnosis</label><input name="final_diagnosis" value="${esc(a.diagnosis || "")}" required></div><div><label>ICD-10</label><input name="icd" list="icdOpts" data-input="icdSearch" value="${esc(a.icd || "")}"></div>
      <div><label>Discharge type</label><select name="discharge_type" data-change="dcType"><option value="normal">Normal</option><option value="lama">Left against advice</option><option value="referred">Referred</option><option value="death">Death</option></select></div></div>
      ${[["history", "History and presenting complaint"], ["course", "Course in hospital"], ["procedures", "Procedures done"], ["investigations", "Key investigations"], ["condition", "Condition at discharge"]].map(([k, l]) => `<div><label>${l} ${micBtn(k)}</label><textarea name="${k}">${k === "procedures" ? esc(a.procedures.map(x => `${x.name} (${x.started_at || ""})`).join("; ")) : ""}</textarea></div>`).join("")}
      <h3>Medicines at discharge</h3><p class="small muted">Added here they are safety-checked, printed on the summary and can be dispensed at any pharmacy in the group.</p>
      <div class="fields"><div class="span2"><input id="dcMed" list="medOpts" placeholder="Medicine"></div><div><input id="dcDose" value="1" placeholder="Dose"></div><div><input id="dcFreq" value="1-0-1" placeholder="1-0-1 / OD"></div><div><input id="dcDays" type="number" min="1" value="5" placeholder="Days"></div><div class="span2"><input id="dcIns" placeholder="Instructions"></div><div><button type="button" class="btn ghost" data-act="dcAdd">Add</button></div></div>
      <div id="dcRx"></div>
      <div><label>Other medicines / notes</label><textarea name="medications" placeholder="Free text for anything not in the list"></textarea></div>
      ${[["advice", "Advice"]].map(([k, l]) => `<div><label>${l} ${micBtn(k)}</label><textarea name="${k}"></textarea></div>`).join("")}
      <div id="dcReferral" hidden><h3>Referral</h3><div class="fields"><div class="span2"><label>Referred to (facility)</label><input name="to_facility"></div><div><label>Doctor there</label><input name="to_doctor"></div><div><label>Urgency</label><select name="referral_urgency"><option value="urgent">Urgent</option><option value="emergency">Emergency</option><option value="routine">Routine</option></select></div><div class="span2"><label>Reason for referral</label><input name="referral_reason"></div><div><label>Transport</label><input name="transport" placeholder="ambulance with oxygen"></div></div></div>
      <div class="fields"><div><label>Follow-up date</label><input name="followup" type="date"></div></div>
      ${a.labs.some(l => l.status === "ordered" || l.status === "collected") ? `<label class="check"><input type="checkbox" name="ignore_pending" value="1"> Discharge anyway: ${a.labs.filter(l => l.status === "ordered" || l.status === "collected").length} lab order(s) have no result yet</label>` : ""}
      <div class="btns"><button class="btn" ${isDoc ? "" : "disabled"}>Discharge and create invoice</button>${isDoc ? `<button type="button" class="btn ghost" data-act="dcDraft">Draft with AI</button>` : ""}</div></form>`)
      : card("Discharge summary", `${a.discharge_type || ""} · ${a.discharged_at}`, `${[["Final diagnosis", s.final_diagnosis + (s.icd ? ` (${s.icd})` : "")], ["History", s.history], ["Course in hospital", s.course], ["Procedures", s.procedures], ["Investigations", s.investigations], ["Condition at discharge", s.condition], ["Medicines", s.medications], ["Advice", s.advice], ["Follow-up", s.followup]].filter(x => x[1]).map(([l, v]) => `<p><b>${l}:</b><br>${esc(v)}</p>`).join("")}${a.rx.length ? tbl(["Medicine", "Dose", "Freq", "Days", "Qty"], a.rx.map(r => `<tr><td>${esc(r.name)}${r.instructions ? `<div class="small muted">${esc(r.instructions)}</div>` : ""}</td><td>${esc(r.dose || "")}</td><td class="mono">${esc(r.freq || "")}</td><td>${r.days}</td><td>${r.qty}</td></tr>`).join("")) : ""}<button class="btn ghost" data-act="printDc">Print summary</button> <button class="btn ghost" data-act="pdfDl" data-p="discharge/${a.id}">PDF</button>`);
  }
}
on("admTab", el => { App.cache.admTab = el.dataset.k; go("ipd", ["a", App.cache.adm.id]); });
const reAdm = () => go("ipd", ["a", App.cache.adm.id]);
on("marDay", el => { App.cache.marDay = el.value; reAdm(); });
on("vitalsPlan", async f => { await api(`/api/admissions/${App.cache.adm.id}/vitals-plan`, vals(f)); toast("Schedule saved"); reAdm(); });
on("ioKind", el => { const w = $("#ioWhat"); w.innerHTML = (el.value === "in" ? ["oral", "iv", "ng", "blood", "other"] : ["urine", "vomit", "drain", "stool", "other"]).map(x => `<option>${x}</option>`).join(""); });
on("ioAdd", async f => { await api(`/api/admissions/${App.cache.adm.id}/io`, vals(f)); toast("Charted"); reAdm(); });
on("handover", async f => { await api(`/api/admissions/${App.cache.adm.id}/handover`, vals(f)); toast("Handed over"); reAdm(); });
on("admNote", async f => { const v = vals(f); if (f.charge_visit) v.charge_visit = f.charge_visit.checked; await api(`/api/admissions/${App.cache.adm.id}/notes`, v); toast("Saved"); reAdm(); });
on("marConfirm", async el => { await api(`/api/mar/${el.dataset.id}/confirm`, {}); toast("Confirmed"); reAdm(); });
on("marOrder", async f => {
  const v = vals(f), m = medByName(v.med); if (!m) return toast("Choose a medicine from the list.");
  const r = await withOverride((ov, reason) => api(`/api/admissions/${App.cache.adm.id}/mar`, { ...v, medicine_id: m.id, override: ov, override_reason: reason }));
  if (r) { toast(v.ordered_by ? "Added as a verbal order: the doctor will confirm it" : "Ordered"); reAdm(); }
});
on("marGive", async el => { const r = await api(`/api/mar/${el.dataset.id}/give`, { due: el.dataset.due }); toast(r.warning || "Dose recorded and charged"); reAdm(); });
on("marHold", async el => { const v = await dialog("Hold or refuse this dose", `<label>Status</label><select name="status"><option value="held">Held</option><option value="refused">Refused by patient</option></select><label>Reason</label><input name="note" placeholder="e.g. BP low, NPO for surgery">`, { ok: "Record" }); if (v) { await api(`/api/mar/${el.dataset.id}/give`, { ...v, due: el.dataset.due }); reAdm(); } });
on("marStop", async el => { await api(`/api/mar/${el.dataset.id}/stop`, {}); reAdm(); });
on("dailyStart", async f => { const s = svcByName(vals(f).svc); if (!s) return toast("Choose a service from the list."); await api(`/api/admissions/${App.cache.adm.id}/daily`, { service_id: s.id }); toast("Started. It will be billed each day."); reAdm(); });
on("dailyStop", async el => { await api(`/api/admissions/${App.cache.adm.id}/daily/${el.dataset.id}/stop`, {}); toast("Stopped"); reAdm(); });
on("admCharge", async f => { const v = vals(f), s = svcByName(v.svc); if (!s) return toast("Choose a service from the list."); await api(`/api/admissions/${App.cache.adm.id}/charges`, { service_id: s.id, qty: v.qty }); toast("Charge added"); reAdm(); });
on("admDeposit", async f => { const r = await api(`/api/admissions/${App.cache.adm.id}/deposit`, vals(f)); toast("Deposit recorded" + waSent(r)); reAdm(); });
on("admLab", async () => {
  const tests = await api("/api/lab/tests");
  const v = await dialog("Order lab tests", tests.map(t_ => `<label class="check"><input type="checkbox" name="t${t_.id}"> ${esc(t_.name)}</label>`).join("") + `<label>Priority</label><select name="priority"><option value="routine">Routine</option><option value="urgent">Urgent</option><option value="stat">STAT</option></select>`, { ok: "Order" });
  if (!v) return; const ids = Object.keys(v).filter(k => /^t\d+$/.test(k) && v[k]).map(k => +k.slice(1)); if (!ids.length) return;
  await api("/api/lab/orders", { patient_id: App.cache.adm.patient_id, admission_id: App.cache.adm.id, tests: ids, priority: v.priority }); toast("Sent to the lab"); reAdm();
});
on("dcDraft", async el => {
  const f = el.closest("form");
  el.disabled = true; el.textContent = "Drafting…";
  try {
    const d = await api(`/api/admissions/${App.cache.adm.id}/draft-summary`, {});
    Object.entries(d).forEach(([k, v]) => { if (f.elements[k] && v) f.elements[k].value = v; });
    toast("Drafted from the stay's record. Read every field and correct it before discharging.");
  } finally { el.disabled = false; el.textContent = "Draft with AI"; }
});
on("discharge", async f => {
  if (!await dialog("Discharge now?", "<p>This closes the stay, creates the final invoice with all charges, applies the deposits and frees the bed.</p>", { ok: "Discharge" })) return;
  const v = vals(f); if (f.ignore_pending) v.ignore_pending = f.ignore_pending.checked; v.items = DC.items;
  const r = await withOverride((ov, reason) => api(`/api/admissions/${App.cache.adm.id}/discharge`, { ...v, override: ov, override_reason: reason }));
  if (!r) return; DC.items = []; toast(`Discharged. Invoice ${r.inv_no}`); App.cache.admTab = "dc"; reAdm();
});
on("printDc", () => {
  const a = App.cache.adm, s = a.summary || {};
  printHtml(`<div class="hdr"><div><h2>${esc(a.bname)}</h2><div>${esc(a.baddr || "")} · ${esc(a.bphone || "")}</div></div><div style="text-align:right"><b>DISCHARGE SUMMARY</b><div>${a.ip_no}</div></div></div>
    <p><b>${esc(a.pname)}</b> · ${a.code} · ${a.age ?? "?"} yrs · ${esc(a.gender || "")}<br>Admitted ${a.admitted_at} · Discharged ${a.discharged_at} (${esc(a.discharge_type || "")}) · ${esc(a.dname || "")} ${a.dreg ? "· Reg. " + esc(a.dreg) : ""}<br><b>Allergies:</b> ${esc(a.allergies || "none")}</p>
    ${[["Final diagnosis", (s.final_diagnosis || "") + (s.icd ? ` (ICD-10 ${s.icd})` : "")], ["History", s.history], ["Course in hospital", s.course], ["Procedures", s.procedures], ["Investigations", s.investigations], ["Condition at discharge", s.condition]].filter(x => x[1]).map(([l, v]) => `<p><b>${l}</b><br>${esc(v)}</p>`).join("")}
    ${a.rx.length ? `<p><b>Medicines at discharge</b></p><table><tr><th>Medicine</th><th>Dose</th><th>Frequency</th><th>Days</th><th>Qty</th><th>Instructions</th></tr>${a.rx.map(r => `<tr><td>${esc(r.name)}</td><td>${esc(r.dose || "")}</td><td>${esc(r.freq || "")}</td><td>${r.days}</td><td>${r.qty}</td><td>${esc(r.instructions || "")}</td></tr>`).join("")}</table>` : ""}
    ${[["Other medicines / notes", s.medications], ["Advice", s.advice], ["Follow-up", s.followup]].filter(x => x[1]).map(([l, v]) => `<p><b>${l}</b><br>${esc(v)}</p>`).join("")}
    <br><p style="text-align:right">Signature ____________________</p>`);
});
