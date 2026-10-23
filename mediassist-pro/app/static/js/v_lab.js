/* Laboratory: worklist, new order, collection, result entry with live flags, verification, report. */
"use strict";
const LAB_ST = { ordered: ["Waiting for sample", "p-warn"], collected: ["Sample collected", "p-info"], resulted: ["Needs verification", "p-crit"], verified: ["Verified", "p-ok"], cancelled: ["Cancelled", "p-plain"] };
const FLAG_TXT = { H: "High", L: "Low", HH: "Critical high", LL: "Critical low", A: "Abnormal", N: "" };

RENDER.lab = async (main, [mode, id]) => {
  if (mode === "o" && id) return labOrder(main, +id);
  const st = App.cache.labSt || "open";
  const [list, tests] = await Promise.all([api("/api/lab/orders?status=" + st + "&since=" + localDay(-7)), api("/api/lab/tests")]);
  App.cache.labTests = tests;
  main.innerHTML = `<div class="g-main"><div class="card"><div class="card-h"><div><h2>Worklist</h2><p>STAT and urgent orders first</p></div></div>
    ${subtabs([["open", "Open"], ["resulted", "Needs verification"], ["verified", "Verified (7 days)"], ["cancelled", "Cancelled"]], st, "labTab")}
    ${tbl(["Order", "Patient", "Tests", "Priority", "Status", ""], list.map(o => `<tr class="click" data-act="go" data-v="lab" data-p="o/${o.id}"><td class="mono">LAB${o.id}<div class="small muted">${o.created_at.slice(5)}</div></td><td>${esc(o.pname)} <span class="small muted">${o.code} · ${o.age ?? "?"}${(o.gender || " ")[0]}</span></td><td class="small">${esc(o.tests)}</td><td>${o.priority === "routine" ? "Routine" : pill(o.priority.toUpperCase(), "p-crit")}</td><td>${pill(...LAB_ST[o.status])}</td><td><button class="btn sm ghost">Open</button></td></tr>`).join(""), "No orders here.")}</div>
    ${can("visit_create") || can("lab") ? card("New lab order", "Walk-in tests or a doctor's paper prescription", `<form data-submit="labNew" class="stack"><div class="fields">${patInput()}<div><label>Priority</label><select name="priority"><option value="routine">Routine</option><option value="urgent">Urgent</option><option value="stat">STAT</option></select></div></div>
      <div class="stack" style="gap:2px">${tests.map(t_ => `<label class="check" style="margin:0"><input type="checkbox" name="t${t_.id}"> ${esc(t_.name)} <span class="muted small">${t_.rate_p ? money(P2R(t_.rate_p)) : ""} · ${t_.sample || ""}</span></label>`).join("")}</div>
      <div class="btns"><button class="btn">Create order</button></div></form>`) : ""}</div>`;
};
on("labTab", el => { App.cache.labSt = el.dataset.k; go("lab"); });
on("labNew", async f => {
  const v = vals(f), pid = pidOf(v.patient); if (!pid) return toast("Pick the patient from the list.");
  const tests = Object.keys(v).filter(k => /^t\d+$/.test(k) && v[k]).map(k => +k.slice(1));
  if (!tests.length) return toast("Tick at least one test.");
  const r = await api("/api/lab/orders", { patient_id: pid, tests, priority: v.priority }); toast(`Order LAB${r.id} created. Bill it in Hospital billing.`); go("lab", ["o", r.id]);
});

const NORMAL_WORDS = new Set(["negative", "neg", "-ve", "absent", "not seen", "nil", "none", "non-reactive", "nonreactive", "non reactive", "normal", "not detected", "nad", "within normal limits", "wnl", "clear"]);
function liveFlag(p, v) {
  if (v === "") return "";
  const n = Number(v);
  if (isNaN(n)) { if (!p.ref_text) return "N"; const nm = s => s.toLowerCase().replace(/_/g, " ").trim().split(/\s+/).join(" "), ref = nm(p.ref_text), val = nm(v); return val === ref || (NORMAL_WORDS.has(ref) && NORMAL_WORDS.has(val)) ? "N" : "A"; }
  if (p.crit_low != null && n < p.crit_low) return "LL"; if (p.crit_high != null && n > p.crit_high) return "HH";
  if (p.low != null && n < p.low) return "L"; if (p.high != null && n > p.high) return "H"; return "N";
}
async function labOrder(main, id) {
  const o = await api("/api/lab/orders/" + id); App.cache.labOrder = o;
  const editable = can("lab") && (o.status === "collected" || o.status === "resulted");
  main.innerHTML = `<div class="card"><div class="card-h"><div><h2>LAB${o.id} · ${esc(o.pname)}</h2><p>${o.code} · ${o.age ?? "?"} yrs · ${esc(o.gender || "")} · ordered ${o.created_at}${o.dname ? " by " + esc(o.dname) : ""} · ${o.priority.toUpperCase()}</p></div>${pill(...LAB_ST[o.status])}</div>
    ${o.critical ? alertRow("high", `<b>Critical value.</b> ${o.crit_ack_at ? `Acknowledged ${o.crit_ack_at}.` : "The doctor has been alerted and must acknowledge it. Inform them by phone as well."}`) : ""}
    ${o.amended_at ? alertRow("", `<b>Amended report.</b> ${o.amended_at}: ${esc(o.amend_reason || "")}`) : ""}${o.rejections ? alertRow("", `<b>Sample rejected ${o.rejections} time(s).</b> ${esc(o.reject_note || "")}`) : ""}
    <form data-submit="labSave" class="resgrid">${o.tests.map(t_ => `<h3 style="margin:14px 0 6px">${esc(t_.name)} <span class="small muted">${esc(t_.sample || "")}</span></h3>
      ${tbl(["Test", "Result", "Unit", "Normal range", "Flag"], t_.params.map(p => `<tr><td>${esc(p.name)}</td><td>${editable ? `<input name="${t_.item_id}:${p.id}" value="${esc(p.value || "")}" data-input="labLive" data-p='${esc(JSON.stringify({ low: p.low, high: p.high, crit_low: p.crit_low, crit_high: p.crit_high, ref_text: p.ref_text }))}'>` : `<b>${esc(p.value || "–")}</b>`}</td><td>${esc(p.unit || "")}</td><td class="small">${esc(p.range || "")}</td><td class="flagcell"><span class="flag-${p.flag || ""}">${FLAG_TXT[p.flag] || ""}</span></td></tr>`).join(""))}`).join("")}
    <div class="btns">
      ${o.status === "ordered" && can("lab") ? `<button type="button" class="btn" data-act="labCollect">Sample collected</button>` : ""}
      ${editable ? `<button class="btn ghost" name="draft" value="1">Save draft</button><button type="button" class="btn" data-act="labSubmit">Submit results</button>` : ""}
      ${o.status === "resulted" && can("lab_verify") ? `<button type="button" class="btn" data-act="labVerify">Verify and send to patient</button>` : ""}
      ${["ordered", "collected"].includes(o.status) && can("lab") ? `<button type="button" class="btn ghost" data-act="labCancel">Cancel order</button>` : ""}
      ${o.status === "collected" && can("lab") ? `<button type="button" class="btn ghost" data-act="labReject">Reject sample</button>` : ""}
      ${o.status === "verified" && can("lab_verify") ? `<button type="button" class="btn ghost" data-act="labAmend">Amend report</button>` : ""}
      ${o.critical && !o.crit_ack_at && can("consult") ? `<button type="button" class="btn danger" data-act="labAck" data-id="${o.id}">Acknowledge critical result</button>` : ""}
      ${o.status === "verified" ? `<button type="button" class="btn ghost" data-act="labPrint">Print report</button><button type="button" class="btn ghost" data-act="pdfDl" data-p="lab/${o.id}">PDF</button>` : ""}
      <button type="button" class="btn ghost" data-act="go" data-v="lab">Back to worklist</button></div></form>
    ${o.interp ? interpCard(o) : ""}
    <p class="small muted">Collected: ${o.collected_at ? `${o.collected_at} by ${esc(o.collected_name)}` : "–"} · Resulted: ${o.resulted_at ? `${o.resulted_at} by ${esc(o.resulted_name)}` : "–"} · Verified: ${o.verified_at ? `${o.verified_at} by ${esc(o.verified_name)}` : "–"}</p></div>`;
}
on("labLive", el => { const f = liveFlag(JSON.parse(el.dataset.p), el.value.trim()); el.closest("tr").querySelector(".flagcell").innerHTML = `<span class="flag-${f}">${FLAG_TXT[f] || ""}</span>`; });
const labValues = () => { const o = {}; $$(".resgrid input[name*=':']").forEach(i => o[i.name] = i.value); return o; };
on("labSave", async () => { await api(`/api/lab/orders/${App.cache.labOrder.id}/results`, { values: labValues() }); toast("Draft saved"); });
on("labSubmit", async () => { const r = await api(`/api/lab/orders/${App.cache.labOrder.id}/results`, { values: labValues(), submit: true }); toast(r.critical ? "Submitted. CRITICAL value: doctor alerted." : "Submitted for verification"); go("lab", ["o", App.cache.labOrder.id]); });
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
  const r = await api(`/api/lab/orders/${App.cache.labOrder.id}/verify`, {});
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
