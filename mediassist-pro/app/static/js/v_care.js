/* Care records: referrals, procedures with consent, imaging, antenatal visits, growth, critical-result acknowledgement,
   lab sample rejection and amendment, discharge prescription builder, credit-bill settlement. */
"use strict";
const CARE_TABS = {};
const DC = { items: [] };
const MODALITIES = ["X-ray", "USG", "CT", "MRI", "ECG", "Echo", "Endoscopy", "Other"];
const refPill = s => pill(s, s === "seen" || s === "returned" ? "p-ok" : s === "declined" ? "p-crit" : "p-info");

/* ---------------- patient profile tabs ---------------- */
CARE_TABS.care = (el, p) => {
  el.innerHTML = `<h3 style="margin:0 0 6px">Imaging</h3>${tbl(["Ordered", "Study", "Status", "Impression", ""], p.imaging.map(i => `<tr><td class="mono">${i.ordered_at.slice(0, 10)}</td><td><b>${esc(i.modality)}</b> ${esc(i.study)}<div class="small muted">${esc(i.indication || "")}</div></td><td>${pill(i.status, i.status === "reported" ? "p-ok" : i.status === "cancelled" ? "p-plain" : "p-warn")}</td><td class="small">${esc(i.impression || i.findings || "")}</td>
      <td class="row-actions">${i.status === "ordered" && (can("consult") || can("lab")) ? `<button class="btn sm" data-act="careReport" data-id="${i.id}">Report</button>` : ""}${i.status === "reported" ? `<button class="btn sm ghost" data-act="careViewImg" data-i="${p.imaging.indexOf(i)}">View</button>` : ""}</td></tr>`).join(""), "No imaging ordered.")}
    ${can("visit_create") ? `<div class="btns"><button class="btn sm ghost" data-act="careImaging" data-pid="${p.id}">Order imaging</button></div>` : ""}
    <h3 style="margin:14px 0 6px">Referrals</h3>${tbl(["Date", "To", "Reason", "Status", ""], p.referrals.map(r => `<tr><td class="mono">${r.at.slice(0, 10)}</td><td><b>${esc(r.to_facility)}</b>${r.to_doctor ? ", " + esc(r.to_doctor) : ""}<div class="small muted">${esc(r.specialty || "")} · ${r.urgency}</div></td><td class="small">${esc(r.reason)}${r.outcome ? `<div class="muted">Outcome: ${esc(r.outcome)}</div>` : ""}</td><td>${refPill(r.status)}</td>
      <td class="row-actions"><button class="btn sm ghost" data-act="pdfDl" data-p="referral/${r.id}">Letter</button>${can("consult") ? `<button class="btn sm ghost" data-act="careOutcome" data-id="${r.id}">Outcome</button>` : ""}</td></tr>`).join(""), "No referrals.")}
    ${can("consult") ? `<div class="btns"><button class="btn sm ghost" data-act="careRefer" data-pid="${p.id}">Refer</button></div>` : ""}
    <h3 style="margin:14px 0 6px">Procedures</h3>${tbl(["Date", "Procedure", "Anaesthesia", "Consent", ""], p.procedures.map(x => `<tr><td class="mono">${(x.started_at || x.created_at).slice(0, 10)}</td><td><b>${esc(x.name)}</b> <span class="small muted">${x.kind}</span><div class="small muted">${esc(x.surgeon || "")}${x.complications ? ` · <span class="allergy">${esc(x.complications)}</span>` : ""}</div></td><td>${esc(x.anaesthesia)}</td><td class="small">${esc(x.consent_by)} (${esc(x.consent_relation)})</td><td><button class="btn sm ghost" data-act="careViewProc" data-i="${p.procedures.indexOf(x)}">Note</button></td></tr>`).join(""), "No procedures recorded.")}
    ${can("consult") ? `<div class="btns"><button class="btn sm ghost" data-act="careProcedure" data-pid="${p.id}">Record a procedure</button></div>` : ""}`;
};
CARE_TABS.anc = (el, p) => {
  const g = p.pregnancy;
  el.innerHTML = `${g ? alertRow("info", `<b>${g.weeks} weeks ${g.days} days</b> · trimester ${g.trimester} · EDD <b>${g.edd}</b> · G${p.gravida ?? "?"} P${p.para ?? "?"}`) : '<p class="small muted">No LMP recorded: set it in Edit details to track gestation.</p>'}
    ${tbl(["Date", "GA", "Weight", "BP", "Fundal", "FHR", "Pres.", "Urine A/S", "Hb", "Risk", "Plan"], p.anc.map(a => `<tr${a.risk ? ' class="flag-high"' : ""}><td class="mono">${a.at.slice(0, 10)}</td><td>${a.ga_weeks ?? "–"}w</td><td>${a.weight ?? "–"}</td><td>${a.bp_sys ?? "–"}/${a.bp_dia ?? "–"}</td><td>${a.fundal_cm ?? "–"}</td><td>${a.fhr ?? "–"}</td><td>${esc(a.presentation || "–")}</td><td>${esc(a.urine_albumin || "–")}/${esc(a.urine_sugar || "–")}</td><td>${a.hb ?? "–"}</td><td class="small">${a.risk ? `<span class="allergy">${esc(a.risk)}</span>` : "–"}</td><td class="small">${esc(a.plan || "")}${a.next_visit ? `<div class="muted">next ${a.next_visit}</div>` : ""}</td></tr>`).join(""), "No antenatal visits recorded.")}
    ${can("visit_create") ? card("Antenatal visit", "BP, weight, fundal height, FHR, urine, Hb. Risk flags are worked out automatically.", `<form data-submit="ancAdd" class="stack"><div class="fields">
      <div><label>GA weeks</label><input name="ga_weeks" type="number" min="4" max="45" value="${g ? g.weeks : ""}"></div><div><label>Gravida</label><input name="gravida" type="number" min="0" value="${p.gravida ?? ""}"></div><div><label>Para</label><input name="para" type="number" min="0" value="${p.para ?? ""}"></div><div><label>Weight kg</label><input name="weight" type="number" step=".1"></div>
      <div><label>BP sys</label><input name="bp_sys" type="number"></div><div><label>BP dia</label><input name="bp_dia" type="number"></div><div><label>Fundal height cm</label><input name="fundal_cm" type="number" step=".5"></div><div><label>FHR /min</label><input name="fhr" type="number"></div>
      <div><label>Presentation</label><select name="presentation"><option value="">–</option><option>cephalic</option><option>breech</option><option>transverse</option><option>oblique</option></select></div><div><label>Urine albumin</label><select name="urine_albumin"><option value="">–</option><option>nil</option><option>trace</option><option>1+</option><option>2+</option><option>3+</option></select></div><div><label>Urine sugar</label><select name="urine_sugar"><option value="">–</option><option>nil</option><option>trace</option><option>1+</option><option>2+</option></select></div><div><label>Hb g/dL</label><input name="hb" type="number" step=".1"></div>
      <div class="span2"><label>Complaints</label><input name="complaints" placeholder="bleeding, pain, reduced movements, headache"></div><div class="span2"><label>Plan</label><input name="plan" placeholder="iron/folic acid, TT, USG, next visit"></div><div><label>Next visit</label><input name="next_visit" type="date"></div><div style="align-self:end"><label class="check"><input type="checkbox" name="oedema"> Pedal oedema</label></div></div>
      <div class="btns"><button class="btn">Record visit</button></div></form>`) : ""}`;
};
on("ancAdd", async f => { const v = vals(f); v.oedema = f.oedema.checked; const r = await api(`/api/patients/${App.cache.patient.id}/anc`, v); toast(r.risk ? "Recorded. RISK: " + r.risk : "Recorded"); openPatient(App.cache.patient.id, "anc"); });

CARE_TABS.growth = async (el, p) => {
  const g = await api(`/api/patients/${p.id}/growth`);
  const pts = g.points.filter(x => x.weight != null && x.age != null);
  const zcls = z => z == null ? "" : z < -2 || z > 2 ? "allergy" : "";
  el.innerHTML = `${card("Weight for age", g.note, pts.length ? `<div class="chart" id="gChart"></div><div class="legend"><span><i style="background:var(--s1)"></i>${esc(p.name)}</span>${g.has_who ? `<span><i style="background:var(--s4)"></i>WHO 50th</span><span><i style="background:var(--s2)"></i>3rd / 97th</span>` : `<span><i style="background:var(--s4)"></i>WHO median (${g.sex === "F" ? "girls" : "boys"})</span>`}</div>` : '<p class="empty">Record the date of birth and weights to see the chart.</p>')}
    ${tbl(["When", "Age (y)", "Weight", "z (WFA)", "Height", "z (HFA)", "BMI"], g.points.slice().reverse().map(x => `<tr><td class="mono">${x.at.slice(0, 10)}</td><td>${x.age ?? "–"}</td><td>${x.weight ?? "–"}</td><td class="${zcls(x.z_weight)}">${x.z_weight ?? "–"}${x.flag && x.flag !== "normal range" ? ` <span class="small">${x.flag}</span>` : ""}</td><td>${x.height ?? "–"}</td><td class="${zcls(x.z_height)}">${x.z_height ?? "–"}</td><td>${x.bmi ?? "–"}</td></tr>`).join(""), "No weight or height recorded.")}`;
  if (!pts.length) return;
  const f = n => String(Math.round(n));
  if (g.has_who) {
    const maxAge = Math.max(2, ...pts.map(x => x.age)), cur = g.curves.filter(c_ => c_.age <= maxAge + 0.5);
    const near = a => { const n = pts.filter(x => Math.abs(x.age - a) <= (cur.length > 70 ? 0.05 : 0.15)); return n.length ? n[n.length - 1].weight : null; };
    lineChart($("#gChart"), cur.map(c_ => c_.months <= 24 ? c_.months + "m" : c_.age.toFixed(1) + "y"), [{ name: "kg", color: "--s1", values: cur.map(c_ => near(c_.age) ?? 0) }, { name: "P50", color: "--s4", values: cur.map(c_ => c_.p50) }, { name: "P3", color: "--s2", values: cur.map(c_ => c_.p3) }, { name: "P97", color: "--s2", values: cur.map(c_ => c_.p97) }], f);
    return;
  }
  const maxAge = Math.max(10, ...pts.map(x => x.age)), ages = [];
  for (let a = 0; a <= Math.min(maxAge, 10); a += 0.5) ages.push(a);
  const ref = a => { const r = g.reference; let lo = r[0], hi = r[r.length - 1]; for (const q of r) { if (q.age <= a) lo = q; if (q.age >= a) { hi = q; break; } } return lo.age === hi.age ? lo.weight : lo.weight + (hi.weight - lo.weight) * (a - lo.age) / (hi.age - lo.age); };
  const labels = ages.map(a => a + "y"), child = ages.map(a => { const n = pts.filter(x => Math.abs(x.age - a) <= 0.25); return n.length ? n[n.length - 1].weight : null; });
  lineChart($("#gChart"), labels, [{ name: "kg", color: "--s1", values: child.map(v => v ?? 0) }, { name: "WHO", color: "--s4", values: ages.map(ref) }], f);
};

/* ---------------- dialogs ---------------- */
on("careRefer", async el => {
  const v = await dialog("Refer the patient", `<label>Referred to (facility)</label><input name="to_facility" required><label>Doctor there (optional)</label><input name="to_doctor"><label>Specialty</label><input name="specialty" placeholder="cardiology, surgery">
    <label>Urgency</label><select name="urgency"><option value="routine">Routine</option><option value="urgent">Urgent</option><option value="emergency">Emergency</option></select>
    <label>Reason for referral</label><textarea name="reason" rows="2"></textarea><label>Clinical summary</label><textarea name="summary" rows="3" placeholder="History, findings, investigations, diagnosis"></textarea>
    <label>Treatment given</label><input name="treatment_given"><label>Transport</label><input name="transport" placeholder="own vehicle / ambulance">`, { ok: "Create referral letter", wide: true });
  if (!v) return;
  if (!v.to_facility || !v.reason) return toast("Enter the facility and the reason.");
  const r = await api(`/api/patients/${el.dataset.pid}/referrals`, { ...v, visit_id: el.dataset.vid ? +el.dataset.vid : null, admission_id: el.dataset.aid ? +el.dataset.aid : null });
  toast("Referral recorded. The letter is in the patient's records."); download(`/api/pdf/referral/${r.id}`);
  if (App.cache.patient && $("#pTabBody")) openPatient(App.cache.patient.id, "care");
});
on("careOutcome", async el => {
  const v = await dialog("Referral outcome", `<label>Status</label><select name="status"><option value="accepted">Accepted</option><option value="seen">Seen there</option><option value="returned">Returned to us</option><option value="declined">Declined</option></select><label>Outcome / advice received</label><textarea name="outcome" rows="3"></textarea>`, { ok: "Save" });
  if (v) { await api(`/api/referrals/${el.dataset.id}/outcome`, v); openPatient(App.cache.patient.id, "care"); }
});
on("careImaging", async el => {
  const v = await dialog("Order imaging", `<label>Modality</label><select name="modality">${MODALITIES.map(m => `<option>${m}</option>`).join("")}</select><label>Study</label><input name="study" placeholder="Chest PA, USG abdomen, CT brain plain"><label>Indication</label><input name="indication">`, { ok: "Order" });
  if (!v) return;
  if (!v.study) return toast("Enter the study.");
  await api(`/api/patients/${el.dataset.pid}/imaging`, { ...v, visit_id: el.dataset.vid ? +el.dataset.vid : null, admission_id: el.dataset.aid ? +el.dataset.aid : null });
  toast("Imaging ordered"); if (App.cache.patient && $("#pTabBody")) openPatient(App.cache.patient.id, "care"); else if (App.cache.adm && $("#admBody")) reAdm();
});
on("careReport", async el => {
  const v = await dialog("Imaging report", `<label>Findings</label><textarea name="findings" rows="5"></textarea><label>Impression</label><input name="impression"><label>Reported by</label><input name="reported_by" value="${esc(App.me.name)}">`, { ok: "Save report", wide: true });
  if (!v) return;
  await api(`/api/imaging/${el.dataset.id}/report`, v); toast("Reported");
  if (App.cache.patient && $("#pTabBody")) openPatient(App.cache.patient.id, "care"); else if (App.cache.adm && $("#admBody")) reAdm(); else go("lab", ["img"]);
});
on("careViewImg", async el => { const i = (App.cache.patient || App.cache.adm).imaging[+el.dataset.i]; await dialog(`${i.modality} ${esc(i.study)}`, `<p class="small muted">Reported ${i.reported_at} by ${esc(i.reported_by || "")}</p><p><b>Findings</b><br>${esc(i.findings || "")}</p><p><b>Impression</b><br>${esc(i.impression || "")}</p>`, { ok: "", cancel: "Close", wide: true }); });
on("careProcedure", async el => {
  const docs = await staff("doctor");
  const v = await dialog("Procedure / operation note", `<div class="fields"><div class="span2"><label>Procedure</label><input name="name" required></div><div><label>Kind</label><select name="kind"><option value="minor">Minor</option><option value="major">Major</option><option value="daycare">Day care</option><option value="bedside">Bedside</option></select></div>
    <div><label>Anaesthesia</label><select name="anaesthesia"><option value="none">None</option><option value="local">Local</option><option value="regional">Regional</option><option value="spinal">Spinal</option><option value="general">General</option><option value="sedation">Sedation</option></select></div>
    <div><label>Surgeon</label>${docSelect(docs, "surgeon_id", App.me.id, "")}</div><div><label>Anaesthetist</label><input name="anaesthetist"></div><div><label>Started</label><input name="started_at" type="datetime-local"></div><div><label>Ended</label><input name="ended_at" type="datetime-local"></div>
    <div class="span2"><label>Indication</label><input name="indication"></div><div class="span2"><label>Findings</label><textarea name="findings" rows="2"></textarea></div><div class="span2"><label>Technique / steps</label><textarea name="technique" rows="3"></textarea></div>
    <div><label>Implants / specimens</label><input name="implants"></div><div><label>Blood loss</label><input name="blood_loss" placeholder="minimal / 200 ml"></div><div class="span2"><label>Complications</label><input name="complications" placeholder="none"></div><div class="span2"><label>Post-op orders</label><textarea name="post_op" rows="2"></textarea></div></div>
    <h3>Informed consent</h3><div class="fields"><div><label>Consent given by</label><input name="consent_by" placeholder="patient's name or relative"></div><div><label>Relationship</label><input name="consent_relation" placeholder="self / husband / mother"></div><div><label>Witness</label><input name="consent_witness"></div><div class="span2"><label>What was explained</label><input name="consent_text" placeholder="nature, risks, alternatives, anaesthesia risk"></div></div>
    <label class="check"><input type="checkbox" name="consent_explained"> The procedure, its risks, benefits and alternatives were explained in a language the person understood, and consent was given freely.</label>`, { ok: "Save note", wide: true });
  if (!v) return;
  v.consent_explained = !!v.consent_explained; v.surgeon_id = +v.surgeon_id || null;
  await api(`/api/patients/${el.dataset.pid}/procedures`, { ...v, visit_id: el.dataset.vid ? +el.dataset.vid : null, admission_id: el.dataset.aid ? +el.dataset.aid : null, service_id: el.dataset.sid ? +el.dataset.sid : null });
  toast("Procedure recorded"); if (App.cache.patient && $("#pTabBody")) openPatient(App.cache.patient.id, "care"); else if (App.cache.adm && $("#admBody")) reAdm();
});
on("careViewProc", async el => {
  const x = (App.cache.patient || App.cache.adm).procedures[+el.dataset.i];
  await dialog(esc(x.name), `<p class="small muted">${x.kind} · ${x.anaesthesia} · ${esc(x.surgeon || "")} · ${x.started_at || ""}${x.ended_at ? " to " + x.ended_at : ""}</p>
    ${[["Indication", x.indication], ["Findings", x.findings], ["Technique", x.technique], ["Implants / specimens", x.implants], ["Blood loss", x.blood_loss], ["Complications", x.complications], ["Post-op orders", x.post_op]].filter(p => p[1]).map(([l, v]) => `<p><b>${l}</b><br>${esc(v)}</p>`).join("")}
    <p class="small"><b>Consent:</b> ${esc(x.consent_by)} (${esc(x.consent_relation)}) on ${x.consent_at}${x.consent_witness ? ", witness " + esc(x.consent_witness) : ""}. ${esc(x.consent_text || "")}</p>`, { ok: "", cancel: "Close", wide: true });
});

/* ---------------- admission tab ---------------- */
function careAdmissionTab(a, open, isDoc) {
  return `<div class="g-main"><div class="stack">${card("Procedures and operation notes", "", tbl(["When", "Procedure", "Anaesthesia", "Consent", ""], a.procedures.map((x, i) => `<tr><td class="mono">${(x.started_at || x.created_at).slice(5, 16)}</td><td><b>${esc(x.name)}</b> <span class="small muted">${x.kind} · ${esc(x.surgeon || "")}</span>${x.complications ? `<div class="allergy small">${esc(x.complications)}</div>` : ""}</td><td>${esc(x.anaesthesia)}</td><td class="small">${esc(x.consent_by)} (${esc(x.consent_relation)})</td><td><button class="btn sm ghost" data-act="careViewProc" data-i="${i}">Note</button></td></tr>`).join(""), "No procedures yet."),
      open && isDoc ? `<button class="btn sm" data-act="careProcedure" data-pid="${a.patient_id}" data-aid="${a.id}">Record a procedure</button>` : "")}</div>
    <div class="stack">${card("Imaging", "", tbl(["Ordered", "Study", "Status", "Impression", ""], a.imaging.map((i, k) => `<tr><td class="mono">${i.ordered_at.slice(5, 16)}</td><td><b>${esc(i.modality)}</b> ${esc(i.study)}</td><td>${pill(i.status, i.status === "reported" ? "p-ok" : "p-warn")}</td><td class="small">${esc(i.impression || "")}</td><td class="row-actions">${i.status === "ordered" && (can("consult") || can("lab")) ? `<button class="btn sm" data-act="careReport" data-id="${i.id}">Report</button>` : ""}${i.status === "reported" ? `<button class="btn sm ghost" data-act="careViewImg" data-i="${k}">View</button>` : ""}</td></tr>`).join(""), "No imaging ordered."),
      open && can("visit_create") ? `<button class="btn sm" data-act="careImaging" data-pid="${a.patient_id}" data-aid="${a.id}">Order imaging</button>` : "")}
      ${open && isDoc ? card("Refer", "Transfer to another facility with a letter", `<button class="btn sm ghost" data-act="careRefer" data-pid="${a.patient_id}" data-aid="${a.id}">Write a referral</button>`) : ""}</div></div>`;
}

/* ---------------- discharge prescription builder ---------------- */
function dcDraw() {
  const box = $("#dcRx"); if (!box) return;
  box.innerHTML = DC.items.length ? tbl(["Medicine", "Dose", "Freq", "Days", ""], DC.items.map((it, i) => `<tr><td><b>${esc(it.name)}</b>${it.instructions ? `<div class="small muted">${esc(it.instructions)}</div>` : ""}</td><td>${esc(it.dose)}</td><td class="mono">${esc(it.freq)}</td><td>${it.days}</td><td><button type="button" class="btn sm ghost" data-act="dcRm" data-i="${i}">Remove</button></td></tr>`).join("")) : "";
}
on("dcAdd", () => {
  const m = medByName($("#dcMed").value); if (!m) return toast("Choose a medicine from the list.");
  DC.items.push({ medicine_id: m.id, name: m.name, dose: $("#dcDose").value || "1", freq: $("#dcFreq").value, days: +$("#dcDays").value || 1, instructions: $("#dcIns").value });
  $("#dcMed").value = ""; $("#dcIns").value = ""; dcDraw(); $("#dcMed").focus();
});
on("dcRm", el => { DC.items.splice(+el.dataset.i, 1); dcDraw(); });
on("dcType", el => { const r = $("#dcReferral"); if (r) r.hidden = el.value !== "referred"; });
on("mlcToggle", el => { const n = el.closest("form").querySelector("[name=mlc_no]"); if (n) n.hidden = !el.checked; });

/* ---------------- lab: reject, amend, acknowledge ---------------- */
on("labReject", async () => {
  const v = await dialog("Reject the sample", `<label>Reason</label><select name="reason"><option>Haemolysed</option><option>Clotted</option><option>Insufficient quantity</option><option>Wrong container</option><option>Unlabelled / mislabelled</option><option>Lipaemic</option><option>Other</option></select><p class="small muted">The order goes back to "waiting for sample" and the doctor is told a fresh sample is needed.</p>`, { ok: "Reject sample", danger: true });
  if (v) { await api(`/api/lab/orders/${App.cache.labOrder.id}/reject`, v); toast("Sample rejected"); go("lab", ["o", App.cache.labOrder.id]); }
});
on("labAmend", async () => {
  const v = await dialog("Amend a verified report", `<label>Why</label><input name="reason" placeholder="transcription error in Hb, re-run confirmed"><p class="small muted">Results reopen for correction and must be verified again. The report is then marked AMENDED and re-sent.</p>`, { ok: "Reopen for amendment", danger: true });
  if (v && v.reason) { await api(`/api/lab/orders/${App.cache.labOrder.id}/amend`, v); go("lab", ["o", App.cache.labOrder.id]); }
});
on("labAck", async el => {
  const v = await dialog("Acknowledge critical result", `<label>Action taken</label><input name="action" placeholder="patient called back / admitted / treatment started">`, { ok: "Acknowledge" });
  if (!v) return;
  await api(`/api/lab/orders/${el.dataset.id}/ack`, v); toast("Acknowledged");
  if (App.cache.labOrder && $(".resgrid")) go("lab", ["o", el.dataset.id]); else go("dashboard");
});
async function criticalCard(main) {
  let l; try { l = await api("/api/lab/critical"); } catch (e) { return; }
  if (!l.length) return;
  const box = document.createElement("div"); box.style.marginTop = "14px";
  box.innerHTML = card("Critical results to acknowledge", `${l.length} unacknowledged · ${l.filter(x => !x.assigned).length} with no ordering doctor`,
    l.map(o => alertRow("high", `<b>${esc(o.pname)}</b> <span class="mono small">${o.code}</span> · LAB${o.id} · ${o.at.slice(5, 16)}: ${o.values.map(v => `<b>${esc(v.name)} ${esc(v.value)} ${esc(v.unit || "")}</b>`).join(", ")} <button class="btn danger sm" data-act="labAck" data-id="${o.id}">Acknowledge</button> <button class="btn sm ghost" data-act="go" data-v="lab" data-p="o/${o.id}">Open</button>`)).join(""));
  main.insertBefore(box, main.firstChild.nextSibling);
}

/* ---------------- pharmacy credit bills ---------------- */
on("settleBill", async el => {
  const v = await dialog(`Collect ${money(el.dataset.amt)} for ${el.dataset.no}`, `<label>Mode</label><select name="mode"><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option></select><label>Reference</label><input name="ref">`, { ok: "Record payment" });
  if (!v) return;
  const r = await api(`/api/bills/${el.dataset.id}/settle`, v); toast(`Collected ${money(r.amount)}${waSent(r)}`);
  const inp = $("[data-input=hbPat]"); if (inp) ACTIONS.hbPat(inp);
  if (App.view === "billing" && App.cache.bill && App.cache.bill.id === +el.dataset.id) ACTIONS.viewBill({ dataset: { id: el.dataset.id } });
});

/* owner's dashboard: what is still to be set up */
async function setupCard(main) {
  let d; try { d = await api("/api/setup/checklist"); } catch (e) { return; }
  if (!d.required_left) return;
  const box = document.createElement("div"); box.style.marginTop = "14px";
  box.innerHTML = card("Finish setting up", `${d.required_left} step${d.required_left > 1 ? "s" : ""} before real patients`, d.items.filter(i => !i.done && !i.optional).slice(0, 5).map(i => alertRow("", `${esc(i.title)} <button class="btn sm ghost" data-act="go" data-v="${i.view}" data-p="${esc(i.param)}">Do it</button>`)).join(""), `<button class="btn sm ghost" data-act="go" data-v="admin" data-p="start">All steps</button>`);
  main.insertBefore(box, main.firstChild.nextSibling);
}

/* dashboard: inpatients who need eyes on them */
async function wardWatchCard(main) {
  let l; try { l = await api("/api/ward/watch"); } catch (e) { return; }
  if (!l.length) return;
  const box = document.createElement("div"); box.style.marginTop = "14px";
  box.innerHTML = card("Ward watch", `${l.length} inpatient${l.length > 1 ? "s" : ""} flagged by early-warning score or overdue vitals`,
    l.map(x => alertRow(x.band === "high" ? "high" : "", `<b>${esc(x.pname)}</b> <span class="mono small">${x.ip_no}</span> · bed ${esc(x.bed || "–")} · ${x.flags.map(esc).join(" · ")} <button class="btn sm ghost" data-act="go" data-v="ipd" data-p="a/${x.admission_id}">Open</button>`)).join(""));
  main.insertBefore(box, main.firstChild.nextSibling);
}

/* ---------- dental chart (FDI) ---------- */
const TOOTH_COLOR = { caries: "var(--crit)", filled: "var(--s2)", missing: "var(--muted)", extracted: "var(--muted)", crown: "var(--s3)", "root canal": "var(--warn)", implant: "var(--s4)", fracture: "var(--crit)", mobile: "var(--warn)", sealant: "var(--ok)", other: "var(--s1)" };
CARE_TABS.dental = async (el, p) => {
  const d = await api(`/api/patients/${p.id}/dental`); App.cache.dental = d;
  const child = p.age != null && p.age < 13;
  const row = (teeth) => `<div class="teeth">${teeth.map(t => { const l = d.latest[t]; return `<button type="button" class="tooth ${l ? "has" : ""}" data-act="toothPick" data-t="${t}" style="${l ? `border-color:${TOOTH_COLOR[l.state] || "var(--s1)"};background:${TOOTH_COLOR[l.state] || "var(--s1)"}22` : ""}" title="${l ? `${l.state}${l.procedure ? " · " + l.procedure : ""} (${l.at.slice(0, 10)})` : "no findings"}">${t}${l ? `<span>${l.state === "root canal" ? "RCT" : l.state.slice(0, 4)}</span>` : ""}</button>`; }).join("")}</div>`;
  const adult = d.teeth, upper = adult.slice(0, 16), lower = adult.slice(16);
  el.innerHTML = `${card("Tooth chart", "FDI numbering · click a tooth to record a finding or treatment · colours show the latest state", `<div class="small muted" style="margin-bottom:6px">Upper right → upper left</div>${row(upper)}<div class="small muted" style="margin:8px 0 6px">Lower right → lower left</div>${row(lower)}${child ? `<div class="small muted" style="margin:8px 0 6px">Primary teeth</div>${row(d.child_teeth)}` : ""}
    <div class="row-actions small" style="margin-top:8px">${Object.entries(TOOTH_COLOR).slice(0, 8).map(([k, v]) => `<span><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${v};margin-right:4px"></i>${k}</span>`).join("")}</div>`)}
    ${card("Dental history", "", tbl(["When", "Tooth", "", "Finding", "Procedure", "Surfaces", "By"], d.history.map(x => `<tr><td class="mono small">${x.at.slice(0, 10)}</td><td><b>${x.tooth}</b></td><td>${pill(x.kind, x.kind === "treatment" ? "p-ok" : "p-warn")}</td><td>${esc(x.state)}</td><td>${esc(x.procedure || "")}${x.notes ? `<div class="small muted">${esc(x.notes)}</div>` : ""}</td><td class="mono">${esc(x.surfaces || "")}</td><td class="small">${esc(x.uname || "")}</td></tr>`).join(""), "Nothing charted yet."))}`;
};
on("toothPick", async el => {
  if (!can("consult")) return;
  const d = App.cache.dental, t = +el.dataset.t, l = d.latest[t];
  const v = await dialog(`Tooth ${t}${l ? ` · now: ${l.state}` : ""}`, `<label>Record</label><select name="kind"><option value="finding">Finding</option><option value="treatment">Treatment done</option></select><label>State</label><select name="state">${d.states.map(s => `<option ${l && l.state === s ? "selected" : ""}>${s}</option>`).join("")}</select><label>Procedure (for treatments)</label><input name="procedure" placeholder="composite filling, extraction, RCT, crown"><label>Surfaces</label><input name="surfaces" placeholder="M O D B L" maxlength="10"><label>Notes</label><input name="notes">`, { ok: "Save" });
  if (!v) return;
  await api(`/api/patients/${App.cache.patient.id}/dental`, { ...v, tooth: t }); toast(`Tooth ${t} recorded`); openPatient(App.cache.patient.id, "dental");
});

/* ---------- physiotherapy ---------- */
CARE_TABS.physio = async (el, p) => {
  const plans = await api(`/api/patients/${p.id}/physio`);
  el.innerHTML = `${plans.map(pl => card(`${esc(pl.diagnosis)} ${pill(pl.status, pl.status === "active" ? "p-info" : "p-ok")}`, `${pl.done} of ${pl.planned_sessions} sessions · started ${pl.started}${pl.goals ? " · goals: " + esc(pl.goals) : ""}`,
      `<div class="boot-bar" style="width:100%;background:var(--line);margin:4px 0 10px"><i style="width:${Math.min(100, Math.round(pl.done / pl.planned_sessions * 100))}%;background:var(--ok)"></i></div>
      ${pl.pain_trend.length > 1 ? `<p class="small"><b>Pain after sessions:</b> ${pl.pain_trend.map(x => `<span class="${x >= 7 ? "allergy" : ""}">${x}</span>`).join(" → ")} /10</p>` : ""}
      ${tbl(["Session", "When", "Exercises", "Min", "Pain before → after", "ROM / notes", "By"], pl.sessions.map((s, i) => `<tr><td>${i + 1}</td><td class="mono small">${s.at.slice(0, 16)}</td><td class="small">${esc(s.exercises || "")}</td><td class="num">${s.duration_min ?? "–"}</td><td class="num">${s.pain_before ?? "–"} → ${s.pain_after ?? "–"}</td><td class="small">${esc(s.rom || "")}${s.notes ? " · " + esc(s.notes) : ""}</td><td class="small">${esc(s.uname || "")}</td></tr>`).join(""), "No sessions yet.")}
      ${pl.status === "active" && can("visit_create") ? `<form data-submit="physioSession" class="fields" style="margin-top:8px"><input type="hidden" name="plan" value="${pl.id}"><div class="span2"><label>Exercises done</label><input name="exercises" placeholder="quad sets, heel slides, TENS 15 min"></div><div><label>Minutes</label><input name="duration_min" type="number" min="5" max="180" value="30"></div><div><label>Pain before</label><input name="pain_before" type="number" min="0" max="10"></div><div><label>Pain after</label><input name="pain_after" type="number" min="0" max="10"></div><div class="span2"><label>Range of motion / notes</label><input name="rom" placeholder="knee flexion 0-95°"></div><div style="align-self:end"><button class="btn sm">Record session</button><button type="button" class="btn sm ghost" data-act="physioClose" data-id="${pl.id}">Close plan</button></div></form>` : ""}`)).join("") || '<p class="empty">No physiotherapy plans.</p>'}
    ${can("visit_create") ? card("New physiotherapy plan", "", `<form data-submit="physioPlan" class="fields"><div class="span2"><label>Condition</label><input name="diagnosis" placeholder="post-op knee, frozen shoulder, low back pain"></div><div><label>Planned sessions</label><input name="planned_sessions" type="number" min="1" max="100" value="10"></div><div class="span2"><label>Goals</label><input name="goals" placeholder="full ROM, walk without aid"></div><div style="align-self:end"><button class="btn sm">Start plan</button></div></form>`) : ""}`;
};
on("physioPlan", async f => { await api(`/api/patients/${App.cache.patient.id}/physio`, vals(f)); toast("Plan started"); openPatient(App.cache.patient.id, "physio"); });
on("physioSession", async f => { const v = vals(f); const r = await api(`/api/physio/${v.plan}/session`, v); toast(`Session ${r.done} of ${r.planned} recorded`); openPatient(App.cache.patient.id, "physio"); });
on("physioClose", async el => { const v = await dialog("Close this plan", `<label>Outcome</label><select name="status"><option value="completed">Completed</option><option value="stopped">Stopped</option><option value="referred">Referred on</option></select><label>Notes</label><input name="outcome">`, { ok: "Close plan" }); if (v) { await api(`/api/physio/${el.dataset.id}/close`, v); openPatient(App.cache.patient.id, "physio"); } });
