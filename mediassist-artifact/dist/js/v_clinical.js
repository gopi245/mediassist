/* Patients (register, profile, EMR), OPD & appointments, consultation. */
"use strict";

/* ================= patients ================= */
RENDER.patients = async (main, [pid]) => {
  main.innerHTML = `<div class="g-form"><div class="stack">
    ${card("Find a patient", "Name, phone, ID or ABHA number", `<input id="pSearch" data-input="pSearch" placeholder="Search…" value="${esc(App.cache.pq || "")}"><div id="pList" style="margin-top:10px"></div>`)}
    ${can("patients_write") ? card("Register a new patient", "Consent is recorded with the record (DPDP Act 2023)", patientForm({}, "regPatient")) : ""}
  </div><div id="pProfile" class="card"><p class="empty" style="padding:40px 0"><b>Select a patient</b><br>Their visits, labs, admissions, bills and documents from every branch appear here.</p></div></div>`;
  await listPatients();
  if (pid) openPatient(+pid);
};
function patientForm(p, act) {
  return `<form data-submit="${act}" class="stack"><input type="hidden" name="id" value="${p.id || ""}"><div class="fields">
    <div class="span2"><label>Full name</label><input name="name" value="${esc(p.name)}" required></div><div><label>Mobile</label><input name="phone" inputmode="tel" value="${esc(p.phone)}" required></div>
    <div><label>Date of birth</label><input name="dob" type="date" value="${esc(p.dob)}"></div><div><label>Age</label><input name="age" type="number" min="0" max="130" value="${p.age ?? ""}"></div>
    <div><label>Gender</label><select name="gender">${["Male", "Female", "Other"].map(g => `<option ${p.gender === g ? "selected" : ""}>${g}</option>`).join("")}</select></div>
    <div><label>Weight (kg)</label><input name="weight" type="number" step=".1" value="${p.weight ?? ""}"></div><div><label>Blood group</label><input name="blood_group" value="${esc(p.blood_group)}"></div>
    <div><label>Language for messages</label><select name="lang">${[["en", "English"], ["hi", "हिन्दी"], ["te", "తెలుగు"], ["ta", "தமிழ்"]].map(([k, l]) => `<option value="${k}" ${(p.lang || "en") === k ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    <div><label>ABHA number (14 digits)</label><input name="abha" inputmode="numeric" value="${esc(p.abha)}"></div><div><label>ABHA address</label><input name="abha_address" value="${esc(p.abha_address)}" placeholder="name@abdm"></div><div class="span2"><label>Address</label><input name="address" value="${esc(p.address)}"></div>
    <div class="span2"><label>Allergies</label><input name="allergies" value="${esc(p.allergies)}" placeholder="penicillin, sulfa, nsaid"></div>
    <div class="span2"><label>Conditions</label><input name="conditions" value="${esc(p.conditions)}" placeholder="asthma, kidney disease, ulcer, heart failure"></div>
    <div><label>LMP (if pregnant)</label><input name="lmp" type="date" value="${esc(p.lmp)}"></div>
    <div><label>Gravida / Para</label><div style="display:flex;gap:6px"><input name="gravida" type="number" min="0" max="20" value="${p.gravida ?? ""}" placeholder="G"><input name="para" type="number" min="0" max="20" value="${p.para ?? ""}" placeholder="P"></div></div></div>
    ${p.id ? "" : `<label class="check"><input type="checkbox" name="consent"> Patient agrees to their health data being stored and used for treatment and billing</label>
    <label class="check"><input type="checkbox" name="whatsapp_ok" checked> Send reports and reminders on WhatsApp</label>`}
    <div class="btns"><button class="btn">${p.id ? "Save changes" : "Register patient"}</button></div></form>`;
}
on("pSearch", debounce(el => { App.cache.pq = el.value; listPatients(); }, 250));
async function listPatients() {
  const l = await api("/api/patients?q=" + encodeURIComponent(App.cache.pq || ""));
  $("#pList").innerHTML = tbl(["Patient", "Mobile", "Allergies"], l.map(p => `<tr class="click" data-act="openPatient" data-id="${p.id}"><td><b>${esc(p.name)}</b><div class="small muted"><span class="mono">${p.code}</span> · ${p.age ?? "?"}${(p.gender || " ")[0]}</div></td><td class="mono">${esc(p.phone)}</td><td class="allergy small">${esc(p.allergies)}</td></tr>`).join(""), "No match. Register them below.");
}
const welcomeNote = w => !w ? "" : !w.length ? "" : w[0].ok ? ". Welcome message sent on WhatsApp." : ". Welcome message not sent (WhatsApp isn't set up).";
on("regPatient", async f => {
  const v = vals(f);
  if (!v.consent) return toast("Tick the consent box after explaining it to the patient.");
  try { const r = await api("/api/patients", v); toast(`Registered as ${r.code}` + welcomeNote(r.welcome)); f.reset(); await listPatients(); openPatient(r.id); }
  catch (e) {
    if (e.status !== 409) throw e;
    const ok = await dialog("This mobile number is already registered", e.data.matches.map(m => `<p><b>${m.code}</b> ${esc(m.name)}, ${m.age ?? "?"} yrs</p>`).join("") + `<p class="small muted">Register a new record only for a different person, such as a family member who shares the phone.</p>`, { ok: "Register as new patient" });
    if (ok) { const r = await api("/api/patients", { ...v, force: true }); toast(`Registered as ${r.code}`); f.reset(); await listPatients(); openPatient(r.id); }
    else openPatient(e.data.matches[0].id);
  }
});
on("openPatient", el => openPatient(+el.dataset.id));
async function openPatient(id, tab = "summary") {
  const p = await api("/api/patients/" + id); App.cache.patient = p;
  const box = $("#pProfile"); if (!box) return;
  const tabs = [["summary", "Summary"], ["visits", `Visits (${p.visits.length})`], ["vitals", "Vitals"], ["labs", `Labs (${p.labs.length})`], ["vacc", "Vaccinations"],
    ["ipd", `Admissions (${p.admissions.length})`], ["care", `Imaging & referrals (${p.imaging.length + p.referrals.length + p.procedures.length})`],
    ...((p.gender || "").toLowerCase().startsWith("f") && (p.pregnancy || p.anc.length) ? [["anc", `Antenatal (${p.anc.length})`]] : []),
    ...(p.age != null && p.age < 18 ? [["growth", "Growth"]] : []), ["dental", "Dental"], ["physio", "Physio"], ["money", "Bills"], ["docs", `Documents (${p.documents.length})`]];
  box.innerHTML = `<div class="phead"><div class="avatar">${initials(p.name)}</div><div style="flex:1;min-width:0"><h2>${esc(p.name)}</h2>
    <div class="small muted"><span class="mono">${p.code}</span> · ${p.age ?? "?"} yrs · ${esc(p.gender || "")} · <span class="mono">${esc(p.phone)}</span>${p.abha ? ` · ABHA <span class="mono">${esc(p.abha)}</span>` : ""}${p.blood_group ? " · " + esc(p.blood_group) : ""}</div></div></div>
    ${p.allergies ? `<div class="banner" style="margin-top:10px">Allergic to ${esc(p.allergies)}</div>` : ""}
    <div class="row-actions" style="margin:12px 0">
      ${can("visit_create") && H_() ? `<button class="btn sm" data-act="queuePatient" data-id="${p.id}">Add to OPD queue</button>` : ""}
      ${can("appointments") && H_() ? `<button class="btn sm ghost" data-act="bookFor" data-id="${p.id}">Book appointment</button>` : ""}
      ${can("ipd") && H_() ? `<button class="btn sm ghost" data-act="go" data-v="ipd" data-p="admit/${p.id}">Admit</button>` : ""}
      ${can("billing") && PH_() ? `<button class="btn sm ghost" data-act="go" data-v="billing" data-p="p/${p.id}">Pharmacy bill</button>` : ""}
      ${can("hbilling") && H_() ? `<button class="btn sm ghost" data-act="go" data-v="hbilling" data-p="new/${p.id}">Hospital bill</button>` : ""}
      <button class="btn sm ghost" data-act="portalOpen" data-id="${p.id}">Patient's records link</button>
      ${can("patients_write") ? `<button class="btn sm ghost" data-act="editPatient">Edit details</button>` : ""}
      ${can("admin") ? `<button class="btn sm ghost" data-act="exportPatient" data-id="${p.id}">Export records</button><button class="btn sm ghost" data-act="erasePatient" data-id="${p.id}">Erase (DPDP)</button>` : ""}
    </div>${subtabs(tabs, tab, "pTab")}<div id="pTabBody"></div>`;
  box.dataset.id = id; renderPTab(tab);
}
on("pTab", el => { $$("#pProfile .sub button").forEach(b => b.classList.toggle("on", b === el)); renderPTab(el.dataset.k); });
function renderPTab(tab) {
  const p = App.cache.patient, el = $("#pTabBody");
  if (tab === "summary") {
    el.innerHTML = `${p.pregnancy ? alertRow("info", `<b>Pregnant</b> · ${p.pregnancy.weeks} weeks ${p.pregnancy.days} days · trimester ${p.pregnancy.trimester} · EDD <b>${p.pregnancy.edd}</b>`) : ""}
      <p class="small"><b>Conditions:</b> ${esc(p.conditions || "none recorded")}<br><b>Currently taking:</b> ${p.current_meds.map(m => esc(m.name)).join(", ") || "nothing active"}<br><b>Consent:</b> ${p.consent_at ? "recorded " + p.consent_at : '<span class="allergy">not recorded</span>'}</p>
      <h3 style="margin:12px 0 6px">Past reactions to medicines</h3>${tbl(["Medicine", "Reaction", "Severity", "When", ""], p.reactions.map(r => `<tr><td><b>${esc(r.drug)}</b></td><td>${esc(r.reaction)}</td><td>${pill(r.severity, r.severity === "severe" ? "p-crit" : r.severity === "moderate" ? "p-warn" : "p-plain")}</td><td class="mono small">${r.reacted_on || r.created_at.slice(0, 10)}</td><td>${can("patients_write") ? `<button class="btn sm ghost" data-act="adrDel" data-id="${r.id}">Wrong</button>` : ""}</td></tr>`).join(""), "None recorded.")}
      ${can("patients_write") ? `<button class="btn sm ghost" data-act="adrAdd" data-pid="${p.id}" style="margin-top:6px">Record a reaction</button>` : ""}
      <h3 style="margin:12px 0 6px">Problem list</h3>${tbl(["ICD-10", "Problem", "Since", "Status", ""], p.problems.map(x => `<tr><td class="mono">${esc(x.icd || "")}</td><td>${esc(x.title)}</td><td class="mono">${esc(x.since || "")}</td><td>${pill(x.status, x.status === "active" ? "p-warn" : "p-ok")}</td><td>${can("patients_write") ? `<button class="btn sm ghost" data-act="toggleProblem" data-id="${x.id}" data-s="${x.status === "active" ? "resolved" : "active"}">${x.status === "active" ? "Resolve" : "Reopen"}</button>` : ""}</td></tr>`).join(""), "No problems recorded.")}
      ${can("patients_write") ? `<form data-submit="addProblem" class="fields" style="margin-top:8px"><div class="span2"><input name="icd" list="icdOpts" data-input="icdSearch" placeholder="ICD-10 code or search diagnosis"></div><div><input name="title" placeholder="Or describe"></div><div><button class="btn sm">Add problem</button></div></form>` : ""}
      <h3 style="margin:12px 0 6px">Upcoming appointments</h3>${tbl(["Day", "Time", "Doctor", "Token", "Status"], p.appointments.map(a => `<tr><td class="mono">${a.day}</td><td class="mono">${a.slot || "–"}</td><td>${esc(a.dname || "")}</td><td>${a.token}</td><td>${a.status}</td></tr>`).join(""), "None booked.")}`;
  } else if (tab === "visits") {
    el.innerHTML = `<div class="timeline">${p.visits.map(v => `<div class="tl"><div class="when">${v.created_at} · ${v.bcode} · ${esc(v.dname || "")}</div><b>${esc(v.diagnosis || v.status)}</b> ${v.icd ? `<span class="mono small">${v.icd}</span>` : ""} ${triPill(v.triage)}<div class="small muted">${esc(v.complaint || "")}</div>${v.rx.length ? `<div class="small">℞ ${v.rx.map(r => `${esc(r.name)} ${esc(r.freq || "")} ×${r.days || "?"}d`).join(" · ")}</div>` : ""}</div>`).join("") || '<p class="empty">No visits yet.</p>'}</div>`;
  } else if (tab === "vitals") {
    const vs = p.vitals.slice().reverse(), ser = k => vs.filter(v => v[k] != null);
    const sys = ser("bp_sys"), wt = ser("weight"), sg = ser("sugar");
    el.innerHTML = `<div class="g2">${card("Blood pressure (systolic)", `${sys.length} readings`, sys.length > 1 ? `<div class="chart" id="vBp"></div>` : '<p class="empty">Not enough readings.</p>')}
      ${card("Weight", `${wt.length} readings`, wt.length > 1 ? `<div class="chart" id="vWt"></div>` : '<p class="empty">Not enough readings.</p>')}</div>
      ${sg.length > 1 ? card("Blood sugar", "", `<div class="chart" id="vSg"></div>`) : ""}
      ${tbl(["When", "Temp", "Pulse", "BP", "RR", "SpO₂", "GCS", "Pain", "Weight", "Height", "Sugar"], p.vitals.slice(0, 30).map(v => `<tr><td class="mono">${v.at}</td><td>${v.temp ?? "–"}</td><td>${v.pulse ?? "–"}</td><td>${v.bp_sys ?? "–"}/${v.bp_dia ?? "–"}</td><td>${v.resp_rate ?? "–"}</td><td>${v.spo2 ?? "–"}</td><td>${v.gcs ?? "–"}</td><td>${v.pain ?? "–"}</td><td>${v.weight ?? "–"}</td><td>${v.height ?? "–"}</td><td>${v.sugar ?? "–"}</td></tr>`).join(""))}`;
    const f = n => String(Math.round(n));
    if (sys.length > 1) lineChart($("#vBp"), sys.map(v => v.at), [{ name: "Systolic", color: "--s1", values: sys.map(v => v.bp_sys) }], f);
    if (wt.length > 1) lineChart($("#vWt"), wt.map(v => v.at), [{ name: "kg", color: "--s3", values: wt.map(v => v.weight) }], f);
    if (sg.length > 1) lineChart($("#vSg"), sg.map(v => v.at), [{ name: "mg/dL", color: "--s2", values: sg.map(v => v.sugar) }], f);
  } else if (tab === "labs") {
    el.innerHTML = tbl(["Order", "Date", "Tests", "Status", ""], p.labs.map(o => `<tr><td class="mono">LAB${o.id}</td><td class="mono">${o.created_at}</td><td>${esc(o.tests)}</td><td>${pill(o.status, o.status === "verified" ? "p-ok" : "p-info")}</td><td><button class="btn sm ghost" data-act="go" data-v="lab" data-p="o/${o.id}">Open</button></td></tr>`).join(""), "No lab orders.") + `<div id="trend"></div>`;
    api(`/api/patients/${p.id}/lab-trend`).then(rs_ => {
      const byP = {}; rs_.forEach(r => (byP[r.name] = byP[r.name] || []).push(r));
      $("#trend").innerHTML = Object.entries(byP).filter(([, l]) => l.length > 1).map(([n, l]) => `<div class="small" style="margin-top:6px"><b>${esc(n)}</b> ${l.map(r => `<span class="flag-${r.flag}">${esc(r.value)}</span>`).join(" → ")} ${esc(l[0].unit || "")}</div>`).join("");
    });
  } else if (tab === "vacc") {
    el.innerHTML = tbl(["Vaccine", "Dose", "Given", "Batch", "Next due"], p.vaccinations.map(v => `<tr><td>${esc(v.vaccine)}</td><td>${esc(v.dose || "")}</td><td class="mono">${v.given_on}</td><td class="mono">${esc(v.batch || "")}</td><td class="mono">${v.due_next || "–"}</td></tr>`).join(""), "No vaccinations recorded.") +
      (can("visit_create") ? `<form data-submit="addVaccine" class="fields" style="margin-top:10px"><div><label>Vaccine</label><select name="vaccine">${["BCG", "OPV", "Hepatitis B", "Pentavalent", "Rotavirus", "PCV", "IPV", "MR (Measles-Rubella)", "JE", "DPT booster", "Td", "Typhoid conjugate", "Influenza", "COVID-19", "Tetanus toxoid (pregnancy)", "HPV"].map(x => `<option>${x}</option>`).join("")}</select></div>
        <div><label>Dose</label><input name="dose" placeholder="1st"></div><div><label>Given on</label><input name="given_on" type="date" value="${localDay()}"></div><div><label>Batch</label><input name="batch"></div><div><label>Next due</label><input name="due_next" type="date"></div><div style="align-self:end"><button class="btn sm">Record</button></div></form>` : "");
  } else if (tab === "ipd") {
    el.innerHTML = tbl(["IP no.", "Branch", "Admitted", "Diagnosis", "Status", ""], p.admissions.map(a => `<tr><td class="mono">${a.ip_no}</td><td>${a.bcode}</td><td class="mono">${a.admitted_at}</td><td>${esc(a.diagnosis || "")}</td><td>${a.status}</td><td><button class="btn sm ghost" data-act="go" data-v="ipd" data-p="a/${a.id}">Open</button></td></tr>`).join(""), "Never admitted.");
  } else if (tab === "money") {
    el.innerHTML = `<h3 style="margin-bottom:6px">Hospital invoices</h3>${tbl(["Invoice", "Date", "Branch", "Total"], p.invoices.map(i => `<tr class="click" data-act="go" data-v="hbilling" data-p="inv/${i.id}"><td class="mono">${i.inv_no}</td><td class="mono">${i.created_at}</td><td>${i.bcode}</td><td class="num">${i.cancelled_at ? "cancelled" : money(P2R(i.total_p))}</td></tr>`).join(""))}
      <h3 style="margin:12px 0 6px">Pharmacy bills</h3>${tbl(["Bill", "Date", "Branch", "Total"], p.bills.map(b => `<tr><td class="mono">${b.bill_no}</td><td class="mono">${b.created_at}</td><td>${b.bcode}</td><td class="num">${money(P2R(b.total_p - b.returned_p))}</td></tr>`).join(""))}`;
  } else if (tab === "docs") {
    el.innerHTML = docThumbs(p.documents) + (can("documents") ? `<div class="btns"><button class="btn sm" data-act="go" data-v="docs" data-p="up/patient/${p.id}">Upload a document</button></div>` : "");
  } else if (CARE_TABS[tab]) {
    CARE_TABS[tab](el, p);
  }
}
on("icdSearch", debounce(async el => { if (el.value.length < 2) return; const l = await api("/api/icd10?q=" + encodeURIComponent(el.value)); $("#icdOpts").innerHTML = l.map(x => `<option value="${x.code}">${esc(x.title)}</option>`).join(""); }, 250));
on("addProblem", async f => { await api(`/api/patients/${App.cache.patient.id}/problems`, vals(f)); openPatient(App.cache.patient.id); });
on("adrDel", async el => { const v = await dialog("Remove this reaction record", `<label>Why is it wrong?</label><input name="reason">`, { ok: "Remove", danger: true }); if (v && v.reason) { await api(`/api/reactions/${el.dataset.id}/delete`, v); openPatient(App.cache.patient.id); } });
on("toggleProblem", async el => { await api(`/api/problems/${el.dataset.id}`, { status: el.dataset.s }); openPatient(App.cache.patient.id); });
on("addVaccine", async f => { await api(`/api/patients/${App.cache.patient.id}/vaccinations`, vals(f)); toast("Vaccination recorded"); openPatient(App.cache.patient.id, "vacc"); });
on("editPatient", async () => {
  const p = App.cache.patient; $("#pProfile").innerHTML = `<h2>Edit ${esc(p.code)}</h2>` + patientForm(p, "savePatient");
});
on("savePatient", async f => { const v = vals(f); await api("/api/patients/" + v.id, v); toast("Saved"); openPatient(+v.id); listPatients(); });
on("exportPatient", el => download(`/api/patients/${el.dataset.id}/export`));
on("erasePatient", async el => {
  const p = App.cache.patient;
  const v = await dialog("Erase patient identity (DPDP)", `<p>Removes the name, phone, address, ABHA and date of birth for <b>${esc(p.name)}</b>. Clinical and billing records stay, de-identified, as medical and tax law require.</p>
    <label>Reason</label><input name="reason" placeholder="Patient's written request dated…"><label>Type <b>${p.code}</b> to confirm</label><input name="confirm">`, { ok: "Erase", danger: true });
  if (!v) return;
  await api(`/api/patients/${el.dataset.id}/erase`, v); toast("Identity erased"); openPatient(+el.dataset.id);
});
on("queuePatient", el => go("opd", ["walkin", el.dataset.id]));
on("bookFor", el => go("opd", ["book", el.dataset.id]));
const docThumbs = list => list.length ? `<div class="dgrid">${list.map(d => `<button class="dcard" data-act="go" data-v="docs" data-p="d/${d.id}"><div class="th">${d.mime.startsWith("image/") ? `<img src="/api/documents/${d.id}/file" alt="" loading="lazy">` : '<span class="pdf">PDF</span>'}</div><div class="b"><span class="pill p-info p-plain">${esc(d.doc_type)}</span><span class="mono small muted">${esc(d.doc_date || "")}</span></div></button>`).join("")}</div>` : '<p class="empty">No documents.</p>';

/* ================= OPD & appointments ================= */
RENDER.opd = async (main, [mode, pid]) => {
  const docs = await staff("doctor"), day = App.cache.opdDay || localDay();
  const [appts, waiting, done] = await Promise.all([api("/api/appointments?day=" + day), api("/api/visits?status=waiting"), api("/api/visits?status=done")]);
  let pre = "";
  if (pid) { const p = await api("/api/patients/" + pid); pre = `${p.code} · ${p.name} · ${p.phone}`; }
  const col = (lvl, lab, c) => { const l = waiting.filter(v => v.triage === lvl); return `<div class="col"><div class="col-h">${pill(lab, c)}<span class="small muted">${l.length} waiting</span></div>${l.map(v => `<div class="pcard ${lvl}">
      <div class="nm"><b>${esc(v.pname)}</b><span class="mono small muted">${v.token ? "T" + v.token + " · " : ""}${v.created_at.slice(11)}</span></div>
      <div class="small muted">${v.code} · ${v.age ?? "?"}${(v.gender || " ")[0]} · ${esc(v.complaint || "")}${v.dname ? " · " + esc(v.dname) : ""}</div>
      <div class="vit"><span class="${v.temp >= 38 ? "bad" : ""}">${v.temp ?? "–"}°C</span><span class="${v.pulse > 100 ? "bad" : ""}">P ${v.pulse ?? "–"}</span><span class="${v.bp_sys > 160 ? "bad" : ""}">BP ${v.bp_sys ?? "–"}/${v.bp_dia ?? "–"}</span><span class="${v.spo2 && v.spo2 < 92 ? "bad" : ""}">SpO₂ ${v.spo2 ?? "–"}</span>${v.sugar ? `<span>RBS ${v.sugar}</span>` : ""}</div>
      ${v.allergies ? `<div class="allergy small">Allergic to ${esc(v.allergies)}</div>` : ""}${v.emergency ? pill("Emergency", "p-crit") : ""}${v.mlc ? pill("MLC" + (v.mlc_no ? " " + esc(v.mlc_no) : ""), "p-warn") : ""}${v.status === "in_consult" ? pill("With doctor", "p-info") : ""}
      <div class="row-actions" style="margin-top:6px">${can("consult") ? `<button class="btn sm ${lvl === "critical" ? "danger" : ""}" data-act="go" data-v="consult" data-p="${v.id}">Consult</button>` : ""}${can("visit_create") ? `<button class="btn sm ghost" data-act="cancelVisit" data-id="${v.id}">Remove</button>` : ""}</div></div>`).join("") || '<p class="empty">Nobody here.</p>'}</div>`; };
  main.innerHTML = `<div class="g2">
    ${card("Walk-in arrival", "Vitals decide the triage level", `<form data-submit="walkin" class="stack"><div class="fields">${patInput("patient", mode === "walkin" ? pre : "")}<div class="span2"><label>Complaint</label><input name="complaint" placeholder="fever 3 days, cough"></div>
      <div><label>Doctor</label>${docSelect(docs)}</div><div><label>Temp °C</label><input name="temp" type="number" step=".1"></div><div><label>Pulse</label><input name="pulse" type="number"></div><div><label>BP systolic</label><input name="bp_sys" type="number"></div><div><label>BP diastolic</label><input name="bp_dia" type="number"></div>
      <div><label>SpO₂ %</label><input name="spo2" type="number"></div><div><label>Sugar (RBS)</label><input name="sugar" type="number"></div><div><label>Weight kg</label><input name="weight" type="number" step=".1"></div>
      <div><label>Resp. rate /min</label><input name="resp_rate" type="number"></div><div><label>GCS (3-15)</label><input name="gcs" type="number" min="3" max="15"></div><div><label>Pain (0-10)</label><input name="pain" type="number" min="0" max="10"></div><div><label>Height cm</label><input name="height" type="number"></div>
      <div><label>Arrival</label><select name="arrival"><option value="">Walked in</option><option value="ambulance">Ambulance</option><option value="carried">Carried / stretcher</option><option value="wheelchair">Wheelchair</option><option value="police">Brought by police</option></select></div><div><label>Brought by</label><input name="brought_by" placeholder="relative, police, bystander"></div></div>
      <div class="row-actions"><label class="check"><input type="checkbox" name="emergency" value="1"> <b>Emergency</b> (goes to the top of the queue)</label><label class="check"><input type="checkbox" name="mlc" value="1" data-change="mlcToggle"> Medico-legal case</label><input name="mlc_no" placeholder="MLC / police ref. no." style="width:auto" hidden></div>
      <div class="btns"><button class="btn">Add to queue</button></div></form>`)}
    ${card("Book an appointment", "Patients can also book online at /book", `<form data-submit="book" class="stack"><div class="fields">${patInput("patient", mode === "book" ? pre : "")}<div><label>Doctor</label>${docSelect(docs, "doctor_id", "", "")}</div>
      <div><label>Day</label><input name="day" type="date" value="${localDay()}" data-change="loadSlots"></div><div class="span2"><label>Time</label><select name="slot" id="slotSel"><option value="">Pick doctor and day</option></select></div><div class="span2"><label>Note</label><input name="note"></div></div>
      <div class="btns"><button class="btn">Book</button></div></form>`)}
  </div>
  <div class="board" style="margin-top:14px">${col("critical", "Critical", "p-crit")}${col("urgent", "Urgent", "p-warn")}${col("normal", "Routine", "p-ok")}</div>
  ${card(`Appointments · ${shortDay(day)}`, `${appts.length} booked · token screen: <a href="/display?branch=${App.me.branch.code}" target="_blank" rel="noopener">/display?branch=${App.me.branch.code}</a>`,
    tbl(["Token", "Time", "Patient", "Doctor", "Source", "Status", ""], appts.map(a => `<tr><td><b>${a.token}</b></td><td class="mono">${a.slot || "–"}</td><td>${esc(a.pname)} <span class="small muted">${a.code}</span></td><td>${esc(a.dname || "")}</td><td>${a.source}</td><td>${pill(a.status.replace("_", " "), a.status === "booked" ? "p-info" : a.status === "no_show" || a.status === "cancelled" ? "p-plain" : "p-ok")}</td>
      <td class="row-actions">${a.status === "booked" && day === localDay() && can("visit_create") ? `<button class="btn sm" data-act="checkin" data-id="${a.id}">Check in</button>` : ""}${a.status === "booked" ? `<button class="btn sm ghost" data-act="apptStatus" data-id="${a.id}" data-s="no_show">No-show</button><button class="btn sm ghost" data-act="apptStatus" data-id="${a.id}" data-s="cancelled">Cancel</button>` : ""}</td></tr>`).join(""), "No appointments."),
    `<input type="date" value="${day}" data-change="opdDay" style="width:auto">`)}
  ${card("Seen today", "", tbl(["Time", "Patient", "Diagnosis", "Doctor", ""], done.map(v => `<tr><td class="mono">${v.completed_at.slice(11)}</td><td>${esc(v.pname)}</td><td>${esc(v.diagnosis || "")} <span class="mono small">${esc(v.icd || "")}</span></td><td>${esc(v.dname || "")}</td><td><button class="btn sm ghost" data-act="printRx" data-id="${v.id}">Print ℞</button></td></tr>`).join(""), "No consultations yet today."))}`;
};
on("opdDay", el => { App.cache.opdDay = el.value; go("opd"); });
on("walkin", async f => {
  const v = vals(f), pid = pidOf(v.patient); if (!pid) return toast("Pick the patient from the list. Register them first if new.");
  const r = await api("/api/visits", { ...v, patient_id: pid }); toast(`Added. Triage: ${r.triage.toUpperCase()}${r.reasons ? " · " + r.reasons : ""}`); go("opd");
});
on("loadSlots", async el => {
  const f = el.closest("form"), v = vals(f); if (!v.doctor_id || !v.day) return;
  const s = await api(`/api/appointments/slots?doctor_id=${v.doctor_id}&day=${v.day}`);
  $("#slotSel").innerHTML = `<option value="">Walk-in time (token only)</option>` + s.map(x => `<option>${x}</option>`).join("");
});
document.addEventListener("change", e => { if (e.target.name === "doctor_id" && e.target.closest("form[data-submit=book]")) ACTIONS.loadSlots(e.target); });
on("book", async f => {
  const v = vals(f), pid = pidOf(v.patient); if (!pid) return toast("Pick the patient from the list.");
  const r = await api("/api/appointments", { ...v, patient_id: pid }); toast(`Booked. Token ${r.token}`); go("opd");
});
on("checkin", async el => { const r = await api(`/api/appointments/${el.dataset.id}/checkin`, {}); toast(`Checked in. Triage ${r.triage}`); go("opd"); });
on("apptStatus", async el => { await api(`/api/appointments/${el.dataset.id}/status`, { status: el.dataset.s }); go("opd"); });
on("cancelVisit", async el => { if (await dialog("Remove from queue?", "<p>The patient will be removed from today's waiting list.</p>", { ok: "Remove", danger: true })) { await api(`/api/visits/${el.dataset.id}/cancel`, {}); go("opd"); } });

/* ================= consultation ================= */
let CX = null, CX_VISITS = [];
RENDER.consult = async (main, [vid]) => {
  if (!vid) {
    const w = await api("/api/visits?status=waiting");
    main.innerHTML = card("Patients waiting", "Pick a patient to start", tbl(["Priority", "Patient", "Complaint", "Since", ""], w.map(v => `<tr><td>${triPill(v.triage)}</td><td>${esc(v.pname)} <span class="small muted">${v.code}</span></td><td>${esc(v.complaint || "")}</td><td class="mono">${v.created_at.slice(11)}</td><td><button class="btn sm" data-act="go" data-v="consult" data-p="${v.id}">Consult</button></td></tr>`).join(""), "Nobody is waiting."));
    return;
  }
  const [d, tpl, tests] = await Promise.all([api("/api/visits/" + vid), api("/api/templates"), api("/api/lab/tests"), loadMeds()]);
  if (d.visit.status === "waiting") api(`/api/visits/${vid}/start`, {}).catch(() => {});
  const v = d.visit, p = d.patient;
  CX = { vid: +vid, pid: p.id, items: d.rx.map(r => ({ medicine_id: r.medicine_id, name: r.name, dose: r.dose || "1", freq: r.freq, days: r.days, instructions: r.instructions || "" })), labs: new Set(), tests, tpl, weight: p.weight };
  CX_VISITS = p.visits;
  const vt = (lab, val, unit, bad) => `<div class="vt ${bad ? "bad" : ""}"><span>${lab}</span><b>${val ?? "–"}</b> <small class="muted">${val == null ? "" : unit}</small></div>`;
  main.innerHTML = `<div class="card" style="margin-bottom:14px"><div class="phead"><div class="avatar">${initials(p.name)}</div><div style="flex:1;min-width:0"><h2>${esc(p.name)}</h2><div class="small muted"><span class="mono">${p.code}</span> · ${p.age ?? "?"} yrs · ${esc(p.gender || "")}${p.weight ? ` · ${p.weight} kg` : ""} · ${esc(v.bname)} · arrived ${v.created_at.slice(11)}</div></div>${triPill(v.triage)}</div>
    <div class="vitals" style="margin-top:12px">${vt("Temp", v.temp, "°C", v.temp >= 38)}${vt("Pulse", v.pulse, "/min", v.pulse > 100)}${vt("BP", v.bp_sys != null ? v.bp_sys + "/" + (v.bp_dia ?? "–") : null, "", v.bp_sys > 160)}${vt("SpO₂", v.spo2, "%", v.spo2 && v.spo2 < 92)}${vt("Sugar", v.sugar, "mg/dL", v.sugar > 200)}</div>
    <p class="small" style="margin:10px 0 0"><b>Complaint:</b> ${esc(v.complaint || "–")}${v.triage_reasons ? ` · <span class="muted">${esc(v.triage_reasons)}</span>` : ""}${d.creatinine ? ` · last creatinine <b>${d.creatinine}</b>` : ""}</p></div>
  <div class="g-form"><div class="stack">
    ${p.allergies ? `<div class="banner">Allergic to ${esc(p.allergies)}</div>` : ""}${p.pregnancy ? alertRow("info", `Pregnant · ${p.pregnancy.weeks} weeks · EDD ${p.pregnancy.edd}`) : ""}
    ${card("Clinical context", "", `<p class="small" style="margin:0"><b>Conditions:</b> ${esc(p.conditions || "none")}<br><b>Problems:</b> ${p.problems.filter(x => x.status === "active").map(x => esc(x.title)).join(", ") || "none"}<br><b>Currently taking:</b> ${p.current_meds.map(m => esc(m.name)).join(", ") || "nothing"}${v.mlc ? `<br><b class="allergy">Medico-legal case${v.mlc_no ? " " + esc(v.mlc_no) : ""}</b>` : ""}${v.arrival ? `<br><b>Arrival:</b> ${esc(v.arrival)}${v.brought_by ? ", brought by " + esc(v.brought_by) : ""}` : ""}</p>
      ${p.imaging.length ? `<p class="small"><b>Imaging:</b> ${p.imaging.slice(0, 4).map(i => `${esc(i.modality)} ${esc(i.study)} (${i.status === "reported" ? esc(i.impression || "reported") : i.status})`).join("; ")}</p>` : ""}
      <div class="row-actions" style="margin-top:8px"><button type="button" class="btn sm ghost" data-act="careRefer" data-pid="${p.id}" data-vid="${v.id}">Refer</button><button type="button" class="btn sm ghost" data-act="careImaging" data-pid="${p.id}" data-vid="${v.id}">Order imaging</button><button type="button" class="btn sm ghost" data-act="careProcedure" data-pid="${p.id}" data-vid="${v.id}">Procedure note</button></div>`)}
    ${p.reactions.length ? `<div class="banner">Past reactions: ${p.reactions.map(r => `<b>${esc(r.drug)}</b> (${esc(r.reaction)}, ${r.severity}${r.reacted_on ? ", " + r.reacted_on : ""})`).join("; ")}</div>` : ""}
    ${card("Patient history", "Previous medicines, tests and reactions, from every branch", `
      <h3 style="margin:0 0 6px">Previous medicines</h3><div class="timeline">${p.visits.filter(x => x.id !== v.id && x.status === "done").slice(0, 8).map(x => `<div class="tl"><div class="when">${x.created_at.slice(0, 10)} · ${x.bcode} · ${esc(x.dname || "")}${x.rx.length ? ` · <button type="button" class="linkbtn" data-act="cxRepeat" data-vid="${x.id}">Repeat these medicines</button>` : ""}</div><b>${esc(x.diagnosis || "")}</b><div class="small muted">${x.rx.map(r => `${esc(r.name)} ${esc(r.dose || "")} ${esc(r.freq || "")} ×${r.days || "?"}d`).join(" · ") || "no medicines"}</div></div>`).join("") || '<p class="empty">First visit.</p>'}
        ${p.admissions.length ? `<p class="small"><b>Admissions:</b> ${p.admissions.slice(0, 3).map(a => `${a.admitted_at.slice(0, 10)} ${esc(a.diagnosis || "")} (${a.status})`).join("; ")}</p>` : ""}</div>
      <h3 style="margin:12px 0 6px">Previous tests</h3>${p.lab_abnormal.length ? `<div class="small">${p.lab_abnormal.map(x => `<span class="flag-${x.flag}">${esc(x.name)} ${esc(x.value)} ${esc(x.unit || "")}</span> <span class="muted">${x.day}</span>`).join(" · ")}</div><p class="small muted" style="margin:4px 0 0">Out-of-range values from verified reports. </p>` : '<p class="small muted">No out-of-range results on file.</p>'}
        ${p.labs.length ? `<p class="small" style="margin:4px 0 0"><b>Orders:</b> ${p.labs.slice(0, 5).map(o => `<a href="#lab/o/${o.id}">LAB${o.id}</a> ${esc(o.tests)} (${o.status})`).join("; ")}</p>` : ""}
        ${p.imaging.length ? `<p class="small" style="margin:4px 0 0"><b>Imaging:</b> ${p.imaging.slice(0, 4).map(i => `${esc(i.modality)} ${esc(i.study)} (${i.status === "reported" ? esc(i.impression || "reported") : i.status})`).join("; ")}</p>` : ""}
      <h3 style="margin:12px 0 6px">Past reactions</h3>${p.reactions.length ? tbl(["Medicine", "Reaction", "Severity", "When"], p.reactions.map(r => `<tr><td><b>${esc(r.drug)}</b>${r.generic ? `<div class="small muted">${esc(r.generic)}</div>` : ""}</td><td>${esc(r.reaction)}</td><td>${pill(r.severity, r.severity === "severe" ? "p-crit" : r.severity === "moderate" ? "p-warn" : "p-plain")}</td><td class="mono small">${r.reacted_on || r.created_at.slice(0, 10)}</td></tr>`).join("")) : '<p class="small muted">None recorded. Allergies on the record: ' + esc(p.allergies || "none") + '</p>'}
      <button type="button" class="btn sm ghost" data-act="adrAdd" data-pid="${p.id}" data-vid="${v.id}">Record a reaction</button>`)}
  </div>
  <div class="card"><div class="card-h"><div><h2>Consultation</h2><p>Warnings update as you prescribe</p></div><select data-change="applyTpl" style="width:auto"><option value="">Apply a template…</option>${tpl.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></div>
    <div class="dictate" style="margin-bottom:10px"><div class="row-actions"><button type="button" class="btn sm" data-act="cxDictate" id="cxDictBtn">🎤 Dictate</button><select id="cxDictLang" style="width:auto"><option value="en-IN">English</option><option value="te-IN">Telugu</option><option value="hi-IN">Hindi</option><option value="ta-IN">Tamil</option></select><button type="button" class="btn sm ghost" data-act="cxStructure">Fill the casesheet with AI</button><span class="small muted">Speak the complaint, findings, diagnosis and medicines; AI drafts the note and prescription, you review.</span></div><textarea id="cxDictText" rows="2" placeholder="Dictation appears here (or type)"></textarea></div>
    <form data-submit="saveConsult" id="cxForm" class="stack"><div class="fields">
      <div class="span2"><label>Presenting complaint</label><input name="complaint" value="${esc(v.complaint || "")}"></div>
      <div class="span2"><label>Vitals</label><div class="small muted" style="padding-top:8px">${v.temp ?? "–"}°C · P ${v.pulse ?? "–"} · BP ${v.bp_sys ?? "–"}/${v.bp_dia ?? "–"} · RR ${v.resp_rate ?? "–"} · SpO₂ ${v.spo2 ?? "–"} · GCS ${v.gcs ?? "–"} · pain ${v.pain ?? "–"}</div></div>
      <div class="span2"><label>History</label><textarea name="history" rows="3" placeholder="Onset, duration, associated symptoms, past and drug history">${esc(v.history || "")}</textarea></div>
      <div class="span2"><label>Examination</label><textarea name="examination" rows="3" placeholder="General, systemic findings">${esc(v.examination || "")}</textarea></div>
      <div class="span2"><label>Diagnosis</label><input name="diagnosis" value="${esc(v.diagnosis || "")}" required></div>
      <div><label>ICD-10</label><input name="icd" list="icdOpts" data-input="icdSearch" value="${esc(v.icd || "")}" placeholder="code"></div>
      <div><label>Weight kg (dose check)</label><input name="weight" type="number" step=".1" value="${p.weight ?? ""}" data-input="cxWeight"></div></div>
      <div><label>Advice and notes</label><textarea name="notes">${esc(v.notes || "")}</textarea></div>
      <h3>Prescription</h3>
      <div class="fields"><div class="span2"><input id="cxMed" list="medOpts" placeholder="Medicine" data-input="cxLook"></div><div><input id="cxDose" value="1" placeholder="Dose (1, 1/2, 250 mg, 5 ml)" title="Tablets or capsules as a count; syrups in mg or ml. Doses in mg are checked against the limits."></div><div><input id="cxFreq" value="1-0-1" placeholder="1-0-1 / OD / BD"></div><div><input id="cxDays" type="number" min="1" value="5" placeholder="Days"></div><div class="span2"><input id="cxIns" placeholder="Instructions, e.g. after food"></div><div><button type="button" class="btn ghost" data-act="cxAdd">Add</button></div></div>
      <div id="cxInfo"></div><div id="cxRx"></div><div id="cxWarn"></div>
      <h3>Lab tests</h3><div class="row-actions">${tests.map(t_ => `<label class="check" style="margin:0 10px 0 0"><input type="checkbox" data-change="cxLab" value="${t_.id}"> ${esc(t_.name)}</label>`).join("")}</div>
      <div class="fields"><div><label>Lab priority</label><select name="lab_priority"><option value="routine">Routine</option><option value="urgent">Urgent</option><option value="stat">STAT</option></select></div><div><label>Follow-up</label><input name="followup" type="date" value="${esc(v.followup || "")}"></div></div>
      <label class="check"><input type="checkbox" name="add_problem" checked> Add the diagnosis to the problem list (chronic conditions)</label>
      <div class="btns"><button class="btn">Save and complete</button><button type="button" class="btn ghost" data-act="printRx" data-id="${v.id}">Print ℞</button>${v.status === "done" ? `<button type="button" class="btn ghost" data-act="pdfDl" data-p="rx/${v.id}">PDF</button>` : ""}</div></form></div></div>`;
  drawCx();
};
/* shorthand -> words for the doctor's own eyes; the server does the patient's language */
function rxWords(it) {
  const f = (it.freq || "").trim().toUpperCase(), nums = (f.match(/\d+(?:\.\d+)?/g) || []).map(Number);
  const dose = (it.dose || "1").trim(), unit = /^\d+(?:\.\d+)?\s*(ml|mg|g|mcg|drops?|puffs?)/i.test(dose) ? dose : null;
  const d = n => unit ? unit : (n === 0.5 ? "½" : n === 1.5 ? "1½" : String(n)) + (n === 1 ? " tablet" : " tablets");
  const per = unit ? 1 : (dose.includes("/") ? +dose.split("/")[0] / +dose.split("/")[1] : +dose || 1);
  let s;
  if (f.includes("-") && nums.length) { const slots = nums.length === 4 ? ["morning", "afternoon", "evening", "night"] : ["morning", "afternoon", "night"]; s = nums.map((n, i) => n ? `${slots[i]} ${d(n * per)}` : "").filter(Boolean).join(", ") || "only when needed"; }
  else s = ({ OD: "morning", BD: "morning, night", TDS: "morning, afternoon, night", QID: "morning, afternoon, evening, night", HS: "at bedtime", SOS: "only when needed", STAT: "once, now" }[f] || f.toLowerCase()) + (f === "SOS" || f === "STAT" ? "" : ` ${d(per)}`);
  const days = it.days && !["SOS", "STAT"].includes(f) ? `, for ${it.days} day${it.days > 1 ? "s" : ""}` : "";
  return s + days;
}
async function drawCx() {
  $("#cxRx").innerHTML = CX.items.length ? tbl(["Medicine", "Dose", "Freq", "Days", ""], CX.items.map((it, i) => `<tr><td><b>${esc(it.name)}</b><div class="small muted">${esc(rxWords(it))}${it.instructions ? " · " + esc(it.instructions) : ""}</div></td><td>${esc(it.dose)}</td><td class="mono">${esc(it.freq)}</td><td>${it.days}</td><td><button type="button" class="btn sm ghost" data-act="cxRm" data-i="${i}">Remove</button></td></tr>`).join("")) : "";
  if (!CX.items.length) { $("#cxWarn").innerHTML = ""; return; }
  const r = await api("/api/rx/check", { patient_id: CX.pid, visit_id: CX.vid, weight: CX.weight, items: CX.items });
  $("#cxWarn").innerHTML = r.warnings.length ? warnHtml(r.warnings) : alertRow("info", "No allergy, interaction, dose or condition conflicts found.");
}
on("cxWeight", debounce(el => { CX.weight = el.value; drawCx(); }, 400));
on("cxLook", debounce(async el => { const m = medByName(el.value); $("#cxInfo").innerHTML = m ? stockCard(await api("/api/stock/lookup?id=" + m.id)) : ""; }, 250));
on("cxAdd", () => {
  const m = medByName($("#cxMed").value); if (!m) return toast("Choose a medicine from the list.");
  CX.items.push({ medicine_id: m.id, name: m.name, dose: $("#cxDose").value || "1", freq: $("#cxFreq").value, days: +$("#cxDays").value || 1, instructions: $("#cxIns").value });
  $("#cxMed").value = ""; $("#cxIns").value = ""; $("#cxInfo").innerHTML = ""; drawCx(); $("#cxMed").focus();
});
on("cxRm", el => { CX.items.splice(+el.dataset.i, 1); drawCx(); });
let DICT = null;
on("cxDictate", el => {
  if (DICT) { const d = DICT; DICT = null; try { d.stop(); } catch (e) {} el.classList.remove("on"); el.textContent = "🎤 Dictate"; return; }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition; if (!SR) return toast("Dictation needs Chrome or Edge. Type into the box instead.");
  const box = $("#cxDictText"), base = box.value ? box.value + " " : "";
  DICT = new SR(); DICT.lang = $("#cxDictLang").value; DICT.continuous = true; DICT.interimResults = true;
  DICT.onresult = e => { box.value = base + [...e.results].map(r => r[0].transcript).join(" "); };
  DICT.onerror = e => { if (e.error === "not-allowed") { toast("Microphone is blocked in this view. Type the dictation instead."); DICT = null; el.classList.remove("on"); el.textContent = "🎤 Dictate"; } };
  DICT.onend = () => { if (DICT) { try { DICT.start(); } catch (e) {} } };
  try { DICT.start(); el.classList.add("on"); el.textContent = "■ Stop"; } catch (e) { toast("Couldn't start the microphone."); DICT = null; }
});
const CASESHEET_AI = { run: async (pid, text) => api("/api/ai/casesheet", { patient_id: pid, text }) };
on("cxStructure", async el => {
  const text = $("#cxDictText").value.trim(); if (text.length < 10) return toast("Dictate or type the consultation first.");
  let r; try { r = await withBusy(el, () => CASESHEET_AI.run(CX.pid, text)); } catch (e) { return toast(e.message); }
  const f = $("#cxForm"); const put = (n, v) => { if (!v || !f[n]) return; f[n].value = f[n].value && f[n].value !== v ? f[n].value + "\n" + v : v; };
  put("complaint", r.complaint); put("history", r.history); put("examination", r.examination); if (r.diagnosis) f.diagnosis.value = r.diagnosis; if (r.icd) f.icd.value = r.icd; put("notes", r.advice);
  if (r.followup_days) f.followup.value = localDay(r.followup_days);
  r.items.forEach(i => { if (!CX.items.some(x => x.medicine_id === i.medicine_id)) CX.items.push(i); });
  r.lab_tests.forEach(id => { CX.labs.add(id); const cb = $(`input[data-change=cxLab][value="${id}"]`); if (cb) cb.checked = true; });
  const notes = [r.unknown_medicines.length ? `not in the medicine master: ${r.unknown_medicines.join(", ")}` : "", r.unknown_tests.length ? `tests not in the catalogue: ${r.unknown_tests.join(", ")}` : ""].filter(Boolean).join("; ");
  toast(`Draft filled: ${r.items.length} medicines, ${r.lab_tests.length} tests. Review everything before saving.` + (notes ? " " + notes : "")); drawCx();
});
on("cxRepeat", el => {
  const visit = CX_VISITS.find(v => v.id === +el.dataset.vid); if (!visit) return;
  let n = 0;
  visit.rx.forEach(r => { if (!CX.items.some(i => i.medicine_id === r.medicine_id)) { CX.items.push({ medicine_id: r.medicine_id, name: r.name, dose: r.dose || "1", freq: r.freq, days: r.days, instructions: r.instructions || "" }); n++; } });
  toast(n ? `${n} medicine${n > 1 ? "s" : ""} added from ${visit.created_at.slice(0, 10)}; the safety check runs again` : "Already on today's prescription"); drawCx();
});
on("adrAdd", async el => {
  await loadMeds();
  const v = await dialog("Record a reaction to a medicine", `<label>Medicine</label><input name="drug" list="medOpts" placeholder="Brand from the list, or type any drug"><label>What happened</label><input name="reaction" placeholder="rash, swelling, vomiting, breathlessness"><label>Severity</label><select name="severity"><option value="mild">Mild</option><option value="moderate" selected>Moderate</option><option value="severe">Severe (also added to allergies)</option></select><label>When</label><input name="reacted_on" type="date"><label>Notes</label><input name="notes">`, { ok: "Save" });
  if (!v) return;
  const m = medByName(v.drug);
  await api(`/api/patients/${el.dataset.pid}/reactions`, { ...v, medicine_id: m ? m.id : null, visit_id: el.dataset.vid ? +el.dataset.vid : null });
  toast("Reaction recorded"); if (el.dataset.vid) go("consult", [el.dataset.vid]); else openPatient(+el.dataset.pid);
});
on("cxLab", el => { el.checked ? CX.labs.add(+el.value) : CX.labs.delete(+el.value); });
on("applyTpl", el => {
  const t_ = CX.tpl.find(x => x.id === +el.value); if (!t_) return; const f = $("#cxForm");
  f.diagnosis.value = t_.diagnosis || ""; f.icd.value = t_.icd || ""; f.notes.value = t_.advice || "";
  if (t_.followup_days) f.followup.value = localDay(t_.followup_days);
  t_.items.forEach(i => { const m = (App.cache.meds || []).find(x => x.id === i.medicine_id); if (m) CX.items.push({ medicine_id: m.id, name: m.name, dose: i.dose || "1", freq: i.freq, days: i.days, instructions: i.instructions || "" }); });
  t_.tests.forEach(id => { CX.labs.add(id); const cb = $(`input[data-change=cxLab][value="${id}"]`); if (cb) cb.checked = true; });
  el.value = ""; drawCx();
});
on("saveConsult", async f => {
  const v = vals(f);
  const body = { ...v, items: CX.items, lab_tests: [...CX.labs] };
  const r = await withOverride((ov, reason) => api(`/api/visits/${CX.vid}/complete`, { ...body, override: ov, override_reason: reason }));
  if (!r) return;
  const vid = CX.vid;
  const p = await dialog("Consultation saved", `<p>${r.lab_order_id ? `Lab order <b>LAB${r.lab_order_id}</b> was sent to the lab. ` : ""}Any pharmacy in the group can now fill this prescription.</p>`, { ok: "Print prescription", cancel: "Done" });
  if (p) ACTIONS.printRx({ dataset: { id: vid } });
  go("consult");
});
on("printRx", async el => {
  const d = await api("/api/visits/" + el.dataset.id), v = d.visit, p = d.patient;
  printHtml(`<div class="hdr"><div><h2>${esc(v.bname)}</h2><div>${esc(v.baddr || "")} · ${esc(v.bphone || "")}</div></div><div style="text-align:right"><b>${esc(v.dname || "")}</b><div>Reg. ${esc(v.dreg || "–")}</div><div>${esc((v.completed_at || v.created_at))}</div></div></div>
    <p><b>${esc(p.name)}</b> · ${p.code} · ${p.age ?? "?"} yrs · ${esc(p.gender || "")}${p.weight ? ` · ${p.weight} kg` : ""} · <b>Allergies:</b> ${esc(p.allergies || "none")}</p>
    <p><b>Vitals:</b> ${v.temp ?? "–"}°C, pulse ${v.pulse ?? "–"}, BP ${v.bp_sys ?? "–"}/${v.bp_dia ?? "–"}, SpO₂ ${v.spo2 ?? "–"}%</p>
    <p><b>Complaint:</b> ${esc(v.complaint || "–")}${v.history ? `<br><b>History:</b> ${esc(v.history)}` : ""}${v.examination ? `<br><b>Examination:</b> ${esc(v.examination)}` : ""}<br><b>Diagnosis:</b> ${esc(v.diagnosis || "–")} ${v.icd ? "(" + esc(v.icd) + ")" : ""}</p>
    <h2 style="font-size:22px">℞</h2><table><tr><th>Medicine</th><th>Dose</th><th>Frequency</th><th>Days</th><th>Qty</th><th>How to take</th></tr>${d.rx.map(r => `<tr><td>${esc(r.name)}<br><small>${esc(r.generic || "")}</small></td><td>${esc(r.dose || "1")}</td><td>${esc(r.freq)}</td><td>${r.days}</td><td>${r.qty}</td><td>${esc(r.how || r.instructions || "")}${r.how_lang ? `<br><b>${esc(r.how_lang)}</b>` : ""}</td></tr>`).join("")}</table>
    ${d.labs.length ? `<p><b>Tests:</b> ${d.labs.map(l => esc(l.name)).join(", ")}</p>` : ""}<p>${esc(v.notes || "")}</p>${v.followup ? `<p><b>Follow-up:</b> ${v.followup}</p>` : ""}<br><br><p style="text-align:right">Signature ____________________</p>`);
});
