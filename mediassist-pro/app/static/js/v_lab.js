/* Laboratory: worklist, new order, collection, result entry with live flags, verification, report. */
"use strict";
const LAB_ST = { ordered: ["Waiting for sample", "p-warn"], collected: ["Sample collected", "p-info"], resulted: ["Results saved", "p-warn"], verified: ["Done", "p-ok"], cancelled: ["Cancelled", "p-plain"] };
const FLAG_TXT = { H: "High", L: "Low", HH: "Critical high", LL: "Critical low", A: "Abnormal", N: "" };

RENDER.lab = async (main, [mode, id]) => {
  if (mode === "o" && id) return labOrder(main, +id);
  if (mode === "catalog" && can("lab_admin")) return labCatalog(main, id ? +id : null);
  const st = App.cache.labSt || "open";
  let pre = "";   // "new/<patient id>" from the patient's Labs tab: fill the patient in
  if (mode === "new" && id) { try { const p = await api("/api/patients/" + id); pre = `${p.code} ${p.name}`; } catch (e) { /* unknown patient: leave blank */ } }
  const [list, tests] = await Promise.all([api("/api/lab/orders?status=" + st + "&since=" + localDay(-7)), api("/api/lab/tests")]);
  App.cache.labTests = tests;
  main.innerHTML = `<div class="g-main"><div class="card"><div class="card-h"><div><h2>Worklist</h2><p>STAT and urgent orders first</p></div>${can("lab_admin") ? `<button class="btn sm ghost" data-act="go" data-v="lab" data-p="catalog">Tests & ranges</button>` : ""}</div>
    ${subtabs([["open", "Open"], ["verified", "Done (7 days)"], ["cancelled", "Cancelled"]], st, "labTab")}
    ${tbl(["Order", "Patient", "Tests", "Priority", "Status", "Payment", ""], list.map(o => `<tr class="click" data-act="go" data-v="lab" data-p="o/${o.id}"><td class="mono">LAB${o.id}<div class="small muted">${o.created_at.slice(5)}</div></td><td>${esc(o.pname)} <span class="small muted">${o.code} · ${o.age ?? "?"}${(o.gender || " ")[0]}</span></td><td class="small">${esc(o.tests)}</td><td>${o.priority === "routine" ? "Routine" : pill(o.priority.toUpperCase(), "p-crit")}</td><td>${pill(...LAB_ST[o.status])}</td><td>${payPill(o.payment)}</td><td><button class="btn sm ghost">Open</button></td></tr>`).join(""), "No orders here.")}</div>
    ${can("visit_create") || can("lab") ? card("New lab order", "Walk-in tests or a doctor's paper prescription", `<form data-submit="labNew" class="stack"><div class="fields">${patInput("patient", pre)}</div>${newPatBlock()}<div class="fields"><div><label>Priority</label><select name="priority"><option value="routine">Routine</option><option value="urgent">Urgent</option><option value="stat">STAT</option></select></div></div>
      <input data-input="labTestFilter" placeholder="Search tests (${tests.length})" autocomplete="off">
      <div class="stack" style="gap:2px;max-height:340px;overflow:auto">${tests.map(t_ => `<label class="check" style="margin:0" data-name="${esc((t_.name + " " + t_.code).toLowerCase())}"><input type="checkbox" name="t${t_.id}"> ${esc(t_.name)} <span class="muted small">${t_.rate_p ? money(P2R(t_.rate_p)) : ""} · ${t_.sample || ""}</span></label>`).join("")}</div>
      <div class="btns"><button class="btn">Create order</button></div></form>`) : ""}</div>`;
};
/* ---------- payment: lab in-charge or billing desk collects; everyone with the patient sees whether it is paid ---------- */
const canCollect = () => can("lab") || can("lab_admin") || can("hbilling");
function payPill(p) {
  if (!p) return "";
  const cls = { paid: "p-ok", inpatient: "p-info", insurance: "p-info", cancelled: "" }[p.pay] || "p-warn";
  return pill(p.label + (["due", "partial", "unbilled"].includes(p.pay) && p.due ? " · " + money(p.due) : ""), cls);
}
on("labPay", async el => {
  const o = App.cache.labOrder, due = o.payment.due;
  const v = await dialog(`Collect ${money(due)} for LAB${o.id}`, `<p class="small">${esc(o.pname)} · ${o.tests.map(t_ => esc(t_.name)).join(", ")}</p>
    <label>Amount ₹</label><input name="amount" type="number" min="1" step="0.01" value="${due}">
    <label>Mode</label><select name="mode"><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option></select>
    <label>UPI / card reference</label><input name="ref" placeholder="needed for UPI and card">`, { ok: "Mark as paid" });
  if (!v) return;
  const r = await withBusy(el, () => api(`/api/lab/orders/${o.id}/pay`, v));
  toast(`Collected ${money(r.collected)} · ${r.label}${r.inv_no ? " · receipt " + r.inv_no : ""}${waSent(r)}`); go("lab", ["o", o.id]);
});
on("labTab", el => { App.cache.labSt = el.dataset.k; go("lab"); });
on("labNew", async f => {
  const v = vals(f), pid = await opdPatient(f); if (!pid) return;
  const tests = Object.keys(v).filter(k => /^t\d+$/.test(k) && v[k]).map(k => +k.slice(1));
  if (!tests.length) return toast("Tick at least one test.");
  const r = await api("/api/lab/orders", { patient_id: pid, tests, priority: v.priority }); toast(`Order LAB${r.id} created. Enter results, then collect the payment.`); go("lab", ["o", r.id]);
});

const NORMAL_WORDS = new Set(["negative", "neg", "-ve", "absent", "not seen", "nil", "none", "non-reactive", "nonreactive", "non reactive", "normal", "not detected", "nad", "within normal limits", "wnl", "clear"]);
function liveFlag(p, v) {
  if (v === "") return "";
  const n = Number(v);
  if (isNaN(n)) { if (!p.ref_text) return "N"; const nm = s => s.toLowerCase().replace(/_/g, " ").trim().split(/\s+/).join(" "), ref = nm(p.ref_text), val = nm(v); return val === ref || (NORMAL_WORDS.has(ref) && NORMAL_WORDS.has(val)) ? "N" : "A"; }
  if (p.crit_low != null && n < p.crit_low) return "LL"; if (p.crit_high != null && n > p.crit_high) return "HH";
  if (p.low != null && n < p.low) return "L"; if (p.high != null && n > p.high) return "H"; return "N";
}
/* one record, every step: who did what and when, from the doctor's order to the patient's phone */
function labTimeline(o) {
  const step = (done, title, when, who, extra) => `<div class="tl ${done ? "done" : "todo"}"><div class="when">${done ? (when || "").slice(0, 16) : "pending"}${who ? " · " + esc(who) : ""}</div><b>${title}</b>${extra ? `<div class="small muted">${extra}</div>` : ""}</div>`;
  const bill = o.billing, unbilled = !bill && o.admission_id == null && o.status !== "cancelled";
  const tests = o.tests.map(t => esc(t.name)).join(", ");
  return `<h3 style="margin:14px 0 6px">Order timeline</h3><div class="timeline">
    ${step(true, "Ordered", o.created_at, o.dname || "walk-in / reception", `${tests} · ${o.priority}${o.visit_id ? ` · from consultation` : ""}`)}
    ${step(!!bill, bill ? `Billed · ${esc(bill.inv_no)}` : "Billed", bill && bill.at, "", bill ? `${money(bill.total)} · ${bill.status === "paid" ? pill("Paid", "p-ok") : pill(bill.status === "insurance" ? "Insurance" : "Due " + money(bill.due), "p-warn")}` : (o.admission_id ? "on the inpatient bill at discharge" : `not paid · ${money(o.payment.due)}`))}
    ${step(!!o.collected_at, "Sample collected", o.collected_at, o.collected_name, o.rejections ? `${o.rejections} sample(s) rejected before this one` : "")}
    ${step(!!o.resulted_at, "Results entered", o.resulted_at, o.resulted_name, o.amended_at ? `amended ${o.amended_at.slice(0, 16)}: ${esc(o.amend_reason || "")}` : "")}
    ${step(!!o.verified_at, "Report finished and sent", o.verified_at, o.verified_name, o.interp_reviewed_at ? "explanation for the patient reviewed" : "")}
    ${o.critical ? step(!!(o.ack && o.ack.crit_ack_at), "Critical value acknowledged", o.ack && o.ack.crit_ack_at, o.ack && o.ack.name, "") : ""}
    ${step(!!(o.sent && o.sent.ok), o.sent && !o.sent.ok ? "Report sent to patient (not delivered)" : "Report sent to patient", o.sent && o.sent.at, o.sent ? o.sent.channel : "", o.sent && !o.sent.ok ? "WhatsApp isn't set up; see Reports > Messages" : "")}
  </div>${unbilled && o.status !== "ordered" ? alertRow("", "Results are in but the payment isn't collected yet. Press Collect.") : ""}`;
}
async function labOrder(main, id) {
  const o = await api("/api/lab/orders/" + id); App.cache.labOrder = o;
  const editable = can("lab") && ["ordered", "collected", "resulted"].includes(o.status);
  main.innerHTML = `<div class="card"><div class="card-h"><div><h2>LAB${o.id} · ${esc(o.pname)}</h2><p>${o.code} · ${o.age ?? "?"} yrs · ${esc(o.gender || "")} · ordered ${o.created_at}${o.dname ? " by " + esc(o.dname) : ""} · ${o.priority.toUpperCase()}</p></div>${pill(...LAB_ST[o.status])}</div>
    ${o.critical ? alertRow("high", `<b>Critical value.</b> ${o.crit_ack_at ? `Acknowledged ${o.crit_ack_at}.` : "The doctor has been alerted and must acknowledge it. Inform them by phone as well."}`) : ""}
    ${o.amended_at ? alertRow("", `<b>Amended report.</b> ${o.amended_at}: ${esc(o.amend_reason || "")}`) : ""}${o.rejections ? alertRow("", `<b>Sample rejected ${o.rejections} time(s).</b> ${esc(o.reject_note || "")}`) : ""}
    ${o.status === "resulted" && can("lab_verify") ? `<div style="margin:10px 0"><label>Clinical interpretation ${o.clin_interpretation ? '<span class="small muted">(AI draft — read and correct it; it goes on the report)</span>' : '<span class="small muted">(optional; goes on the report)</span>'}</label><textarea id="labInterp">${esc(o.clin_interpretation || "")}</textarea></div>` : ""}
    ${o.status === "verified" && o.clin_interpretation ? `<div style="margin:10px 0"><b>Clinical interpretation</b><p class="small" style="margin:4px 0">${esc(o.clin_interpretation)}</p></div>` : ""}
    <form data-submit="labSave" class="resgrid">${o.tests.map(t_ => `<h3 style="margin:14px 0 6px">${esc(t_.name)} <span class="small muted">${esc(t_.sample || "")}</span></h3>
      ${tbl(["Test", "Result", "Unit", "Normal range", "Flag"], t_.params.map(p => `<tr><td>${esc(p.name)}</td><td>${editable ? `<input name="${t_.item_id}:${p.id}" value="${p.formula ? "" : esc(p.value || "")}" ${p.formula ? `placeholder="${esc(p.value || "auto")}" title="Calculated: ${esc(p.formula)}. Type a value only to override it."` : ""} data-input="labLive" data-p='${esc(JSON.stringify({ low: p.eff_low, high: p.eff_high, crit_low: p.crit_low, crit_high: p.crit_high, ref_text: p.ref_text }))}'>` : `<b>${esc(p.value || "–")}</b>`}</td><td>${esc(p.unit || "")}</td><td class="small">${esc(p.range || "")}</td><td class="flagcell"><span class="flag-${p.flag || ""}">${FLAG_TXT[p.flag] || ""}</span></td></tr>`).join(""))}`).join("")}
    <div class="btns">
      ${canCollect() && o.payment && ["due", "partial", "unbilled"].includes(o.payment.pay) && o.payment.due > 0 ? `<button type="button" class="btn" data-act="labPay">Collect ${money(o.payment.due)}</button>` : ""}
      ${o.status === "ordered" && can("lab") ? `<button type="button" class="btn ghost" data-act="labCollect">Sample collected</button>` : ""}
      ${editable ? `<button class="btn ghost" name="draft" value="1">Save draft</button><button type="button" class="btn" data-act="labSubmit">Submit and send report</button>` : ""}
      ${o.status === "resulted" && can("lab_verify") ? `<button type="button" class="btn" data-act="labVerify">Approve and send to patient</button>` : ""}
      ${["ordered", "collected"].includes(o.status) && can("lab") ? `<button type="button" class="btn ghost" data-act="labCancel">Cancel order</button>` : ""}
      ${o.status === "collected" && can("lab") ? `<button type="button" class="btn ghost" data-act="labReject">Reject sample</button>` : ""}
      ${o.status === "verified" && (can("lab") || can("lab_verify")) ? `<button type="button" class="btn ghost" data-act="labAmend">Amend report</button>` : ""}
      ${o.critical && !o.crit_ack_at && can("consult") ? `<button type="button" class="btn danger" data-act="labAck" data-id="${o.id}">Acknowledge critical result</button>` : ""}
      ${o.status === "verified" ? `<button type="button" class="btn ghost" data-act="labPrint">Print report</button><button type="button" class="btn ghost" data-act="pdfDl" data-p="lab/${o.id}">PDF</button>` : ""}
      <button type="button" class="btn ghost" data-act="go" data-v="lab">Back to worklist</button></div></form>
    ${o.interp ? interpCard(o) : ""}
    ${labTimeline(o)}</div>`;
}
on("labLive", el => { const f = liveFlag(JSON.parse(el.dataset.p), el.value.trim()); el.closest("tr").querySelector(".flagcell").innerHTML = `<span class="flag-${f}">${FLAG_TXT[f] || ""}</span>`; });
const labValues = () => { const o = {}; $$(".resgrid input[name*=':']").forEach(i => o[i.name] = i.value); return o; };
on("labSave", async () => { await api(`/api/lab/orders/${App.cache.labOrder.id}/results`, { values: labValues() }); toast("Draft saved"); });
on("labSubmit", async () => { const r = await api(`/api/lab/orders/${App.cache.labOrder.id}/results`, { values: labValues(), submit: true }); toast((r.critical ? "Report done. CRITICAL value: doctor alerted." : "Report done") + (r.sent && r.sent.some && r.sent.some(x => x.ok) ? " · sent to the patient" : "") + (App.cache.labOrder.payment && App.cache.labOrder.payment.due > 0 && App.cache.labOrder.payment.pay !== "inpatient" ? " · collect the payment" : "")); go("lab", ["o", App.cache.labOrder.id]); });
on("labCollect", async () => { await api(`/api/lab/orders/${App.cache.labOrder.id}/collect`, {}); go("lab", ["o", App.cache.labOrder.id]); });
/* ---------- plain-language interpretation (rules, AI rewrite, doctor's edit) ---------- */
const SRC_LABEL = { rules: "Rule-based", ai: "AI-assisted", doctor: "Edited by doctor" };
function interpCard(o) {
  const i = o.interp, edit = can("lab_verify") && o.status !== "cancelled";
  return `<div class="card interp" style="margin-top:14px"><div class="card-h"><div><h2>What this means</h2><p>Plain-language explanation for the patient · ${pill(SRC_LABEL[i.source] || i.source, "p-info")} ${o.interp_reviewed_at ? pill("Reviewed by doctor", "p-ok") : pill("Not reviewed yet", "p-warn")}</p></div>
      <div class="row-actions">${edit || can("lab") ? `<button type="button" class="btn sm ghost" data-act="interpAI">Rewrite with AI</button><button type="button" class="btn sm ghost" data-act="interpRules">Reset to rules</button>` : ""}</div></div>
    ${i.findings.length ? i.findings.map((f, k) => `<div class="alert ${f.flag === "HH" || f.flag === "LL" ? "high" : ""}"><span class="ic">${f.flag === "N" ? "" : "!"}</span><div class="t"><b>${esc(f.param)} ${esc(String(f.value))} ${esc(f.unit || "")}</b> · ${FLAG_TXT[f.flag] || ""}<br>${edit ? `<textarea data-interp="${k}" rows="2" style="width:100%;margin-top:4px">${esc(f.text)}</textarea>` : esc(f.text)}</div></div>`).join("") : '<p class="small muted">No out-of-range values to explain.</p>'}
    <p class="small"><b>Summary</b></p>${edit ? `<textarea id="interpSummary" rows="3" style="width:100%">${esc(i.summary)}</textarea>` : `<p>${esc(i.summary)}</p>`}
    ${edit ? `<div class="row-actions" style="margin-top:8px"><label class="check"><input type="checkbox" id="interpPatient" ${o.interp_patient ? "checked" : ""}> Include in the patient's report and WhatsApp message</label><button type="button" class="btn sm" data-act="interpSave">Save wording</button></div>` : ""}
    <p class="small muted" style="margin-top:6px">The doctor decides. Verifying the report counts as reviewing this text; the patient sees it only after verification.</p></div>`;
}
const LAB_AI = { rewrite: async oid => api(`/api/lab/orders/${oid}/interpret`, { ai: true }) };
on("interpAI", async el => { try { await withBusy(el, () => LAB_AI.rewrite(App.cache.labOrder.id)); toast("Rewritten"); } catch (e) { toast(e.message); } go("lab", ["o", App.cache.labOrder.id]); });
on("interpRules", async () => { await api(`/api/lab/orders/${App.cache.labOrder.id}/interpret`, {}); go("lab", ["o", App.cache.labOrder.id]); });
on("interpSave", async () => {
  const o = App.cache.labOrder, findings = o.interp.findings.map((f, k) => ({ param: f.param, text: ($(`[data-interp="${k}"]`) || {}).value || f.text }));
  await api(`/api/lab/orders/${o.id}/interpret`, { findings, summary: $("#interpSummary").value, patient: $("#interpPatient").checked });
  toast("Saved"); go("lab", ["o", o.id]);
});
on("labVerify", async () => {
  const r = await api(`/api/lab/orders/${App.cache.labOrder.id}/verify`, $("#labInterp") ? { clin_interpretation: $("#labInterp").value } : {});
  const s = (r.sent || [])[0];
  toast(s ? (s.ok ? "Verified and sent to the patient on WhatsApp" : "Verified. WhatsApp isn't set up, so the report is logged in Reports > Messages to send by hand.") : "Verified");
  go("lab", ["o", App.cache.labOrder.id]);
});
on("labCancel", async () => { const v = await dialog("Cancel this lab order?", `<label>Reason</label><input name="reason">`, { ok: "Cancel order", danger: true, cancel: "Keep" }); if (v) { await api(`/api/lab/orders/${App.cache.labOrder.id}/cancel`, v); go("lab"); } });
on("labPrint", () => {
  const o = App.cache.labOrder;
  printHtml(`<div class="hdr"><div><h2>${esc(o.bname)}</h2><div>${esc(o.baddr || "")} · ${esc(o.bphone || "")}</div></div><div style="text-align:right"><b>LAB${o.id}</b><div>${o.verified_at}</div></div></div>
    <p><b>${esc(o.pname)}</b> · ${o.code} · ${o.age ?? "?"} yrs · ${esc(o.gender || "")}${o.dname ? ` · Referred by ${esc(o.dname)}` : ""}<br>Sample collected ${o.collected_at}</p>
    ${o.tests.map(t_ => `<h3>${esc(t_.name)}</h3><table><tr><th>Test</th><th>Result</th><th>Unit</th><th>Normal range</th><th></th></tr>${t_.params.map(p => `<tr><td>${esc(p.name)}</td><td><b>${esc(p.value || "")}</b></td><td>${esc(p.unit || "")}</td><td>${esc(p.range || "")}</td><td>${FLAG_TXT[p.flag] || ""}</td></tr>`).join("")}</table>`).join("")}
    <br><p style="text-align:right">Verified by ${esc(o.verified_name || "")} ${o.verified_reg ? "(" + esc(o.verified_reg) + ")" : ""}</p>`);
});
on("labTestFilter", el => { const q = el.value.trim().toLowerCase(); el.form.querySelectorAll("label[data-name]").forEach(l => { l.hidden = q && !l.dataset.name.includes(q); }); });

/* ---------- tests & ranges (lab in-charge, manager, owner) ----------
   Sex/age ranges are typed compactly: "M 12-200: 13-17; F 12-200: 12-15; Any 0-12: 11-14.5" (ages in years, upper age not included). */
const SEX_IN = { any: "", m: "Male", male: "Male", f: "Female", female: "Female" }, SEX_OUT = { "": "Any", Male: "M", Female: "F" };
const rangesOut = rs_ => rs_.map(r => `${SEX_OUT[r.gender]} ${+r.age_from}-${+r.age_to}: ${r.low ?? ""}-${r.high ?? ""}`).join("; ");
function rangesIn(s, pname) {
  return s.split(";").map(x => x.trim()).filter(Boolean).map(x => {
    const m = x.match(/^(any|m|f|male|female)\s+(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*:\s*(\d*\.?\d*)\s*-\s*(\d*\.?\d*)$/i);
    if (!m) throw new Error(`${pname}: can't read the range "${x}". Write it like  M 12-200: 13-17`);
    return { gender: SEX_IN[m[1].toLowerCase()], age_from: m[2], age_to: m[3], low: m[4], high: m[5] };
  });
}
async function labCatalog(main, tid) {
  const list = await api("/api/lab/catalog"); App.cache.labCat = list;
  const t_ = tid ? list.find(x => x.id === tid) : null, q = App.cache.labCatQ || "";
  const blank = { name: "", unit: "", low: "", high: "", crit_low: "", crit_high: "", ref_text: "", formula: "", ranges: [] };
  const params = t_ ? t_.params : [blank];
  const n = v => v ?? "";
  const row = p => `<tr data-pid="${p.id || ""}"><td><input data-k="name" value="${esc(p.name)}" aria-label="Value name" style="min-width:130px"></td><td><input data-k="unit" value="${esc(p.unit || "")}" aria-label="Unit" style="width:70px"></td>
    <td><input data-k="low" value="${n(p.low)}" aria-label="Low" style="width:62px"></td><td><input data-k="high" value="${n(p.high)}" aria-label="High" style="width:62px"></td>
    <td><input data-k="crit_low" value="${n(p.crit_low)}" aria-label="Critical low" style="width:62px"></td><td><input data-k="crit_high" value="${n(p.crit_high)}" aria-label="Critical high" style="width:62px"></td>
    <td><input data-k="ref_text" value="${esc(p.ref_text || "")}" placeholder="e.g. Negative" aria-label="Normal text" style="width:110px"></td>
    <td><input data-k="ranges" value="${esc(rangesOut(p.ranges || []))}" placeholder="M 12-200: 13-17; F 12-200: 12-15" aria-label="Ranges by sex and age" style="min-width:210px"></td>
    <td><input data-k="formula" value="${esc(p.formula || "")}" placeholder="{A} - {B}" aria-label="Formula" style="min-width:150px"></td>
    <td><button type="button" class="btn sm ghost" data-act="catDel" aria-label="Remove value">✕</button></td></tr>`;
  main.innerHTML = `<div class="g-form"><div class="card"><div class="card-h"><div><h2>Tests & ranges</h2><p>${list.length} tests · check ranges against your analyser and kit inserts</p></div>
      <button class="btn sm" data-act="go" data-v="lab" data-p="catalog">New test</button></div>
    <input data-input="catQ" value="${esc(q)}" placeholder="Search tests" autocomplete="off">
    <div class="stack" style="gap:0;margin-top:8px;max-height:560px;overflow:auto">${list.map(x => `<button class="linkrow ${x.id === tid ? "on" : ""}" data-act="go" data-v="lab" data-p="catalog/${x.id}" data-name="${esc((x.name + " " + x.code).toLowerCase())}" ${q && !(x.name + " " + x.code).toLowerCase().includes(q.toLowerCase()) ? "hidden" : ""}>
      <b>${esc(x.name)}</b> <span class="mono small muted">${esc(x.code)}</span>${x.active ? "" : ' <span class="small muted">(off)</span>'}<span class="small muted" style="float:right">${money(x.rate)}</span></button>`).join("")}</div>
    <div class="btns"><button class="btn ghost" data-act="go" data-v="lab">Back to worklist</button></div></div>
  <form data-submit="catSave" class="card"><div class="card-h"><div><h2>${t_ ? esc(t_.name) : "New test"}</h2><p>Leave Low/High empty for text results, and put the normal answer under "Normal text".</p></div></div>
    <input type="hidden" name="id" value="${t_ ? t_.id : ""}">
    <div class="fields"><div><label>Code</label><input name="code" value="${esc(t_ ? t_.code : "")}" required maxlength="12" class="mono"></div><div class="span2"><label>Name</label><input name="name" value="${esc(t_ ? t_.name : "")}" required></div>
      <div><label>Sample</label><input name="sample" value="${esc(t_ ? t_.sample || "" : "")}" placeholder="Serum"></div><div><label>Price ₹</label><input name="rate" type="number" min="0" step=".01" value="${t_ ? t_.rate : ""}"></div>
      <div><label>Report in (hours)</label><input name="tat_hours" type="number" min="0" value="${t_ ? n(t_.tat_hours) : ""}"></div>
      <div><label>In use</label><select name="active"><option value="1">Yes</option><option value="0" ${t_ && !t_.active ? "selected" : ""}>No (hidden from orders)</option></select></div></div>
    <h3 style="margin:14px 0 6px">Values on the report</h3>
    <div class="tbl"><table><thead><tr><th>Name</th><th>Unit</th><th>Low</th><th>High</th><th>Critical low</th><th>Critical high</th><th>Normal text</th><th>By sex / age</th><th>Formula</th><th></th></tr></thead>
      <tbody id="catRows">${params.map(p => row(p)).join("")}</tbody></table></div>
    <p class="small muted">By sex / age overrides Low/High for matching patients, e.g. <span class="mono">M 12-200: 13-17; F 12-200: 12-15; Any 0-12: 11-14.5</span> (ages in years).
      A formula is filled in automatically from other values of this test, e.g. <span class="mono">{Total cholesterol} - {HDL} - {Triglycerides} / 5</span>.</p>
    <div class="btns"><button type="button" class="btn ghost" data-act="catAdd">Add a value</button><button class="btn">Save test</button></div></form></div>`;
  App.cache.catBlankRow = row(blank);
}
on("catQ", el => { App.cache.labCatQ = el.value; const q = el.value.trim().toLowerCase(); $$("button.linkrow[data-name]").forEach(b => { b.hidden = q && !b.dataset.name.includes(q); }); });
on("catAdd", () => $("#catRows").insertAdjacentHTML("beforeend", App.cache.catBlankRow));
on("catDel", el => { if ($$("#catRows tr").length > 1) el.closest("tr").remove(); else toast("A test needs at least one value."); });
on("catSave", async f => {
  const v = vals(f);
  try {
    const params = $$("#catRows tr").map(tr => {
      const g = k => tr.querySelector(`[data-k=${k}]`).value.trim();
      return { id: tr.dataset.pid || null, name: g("name"), unit: g("unit"), low: g("low"), high: g("high"), crit_low: g("crit_low"), crit_high: g("crit_high"),
        ref_text: g("ref_text"), formula: g("formula"), ranges: rangesIn(g("ranges"), g("name") || "A value") };
    }).filter(p => p.name || p.id);
    const r = await api("/api/lab/catalog", { id: v.id || null, code: v.code, name: v.name, sample: v.sample, rate: v.rate || 0, tat_hours: v.tat_hours, active: v.active !== "0", params });
    toast("Test saved"); go("lab", ["catalog", r.id]);
  } catch (e) { toast(e.message); }
});
