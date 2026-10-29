/* Laboratory: worklist, new order, collection, result entry with live flags, verification, report. */
"use strict";
const LAB_ST = { ordered: ["Waiting for sample", "p-warn"], collected: ["Sample collected", "p-info"], resulted: ["Needs verification", "p-crit"], verified: ["Verified", "p-ok"], cancelled: ["Cancelled", "p-plain"] };
const FLAG_TXT = { H: "High", L: "Low", HH: "Critical high", LL: "Critical low", A: "Abnormal", N: "" };

RENDER.lab = async (main, [mode, id]) => {
  if (mode === "o" && id) return labOrder(main, +id);
  if (mode === "catalog" && can("lab_admin")) return labCatalog(main, id ? +id : null);
  const st = App.cache.labSt || "open";
  const [list, tests] = await Promise.all([api("/api/lab/orders?status=" + st + "&since=" + localDay(-7)), api("/api/lab/tests")]);
  App.cache.labTests = tests;
  main.innerHTML = `<div class="g-main"><div class="card"><div class="card-h"><div><h2>Worklist</h2><p>STAT and urgent orders first</p></div>${can("lab_admin") ? `<button class="btn sm ghost" data-act="go" data-v="lab" data-p="catalog">Tests & ranges</button>` : ""}</div>
    ${subtabs([["open", "Open"], ["resulted", "Needs verification"], ["verified", "Verified (7 days)"], ["cancelled", "Cancelled"]], st, "labTab")}
    ${tbl(["Order", "Patient", "Tests", "Priority", "Status", ""], list.map(o => `<tr class="click" data-act="go" data-v="lab" data-p="o/${o.id}"><td class="mono">LAB${o.id}<div class="small muted">${o.created_at.slice(5)}</div></td><td>${esc(o.pname)} <span class="small muted">${o.code} · ${o.age ?? "?"}${(o.gender || " ")[0]}</span></td><td class="small">${esc(o.tests)}</td><td>${o.priority === "routine" ? "Routine" : pill(o.priority.toUpperCase(), "p-crit")}</td><td>${pill(...LAB_ST[o.status])}</td><td><button class="btn sm ghost">Open</button></td></tr>`).join(""), "No orders here.")}</div>
    ${can("visit_create") || can("lab") ? card("New lab order", "Walk-in tests or a doctor's paper prescription", `<form data-submit="labNew" class="stack"><div class="fields">${patInput()}<div><label>Priority</label><select name="priority"><option value="routine">Routine</option><option value="urgent">Urgent</option><option value="stat">STAT</option></select></div></div>
      <input data-input="labTestFilter" placeholder="Search tests (${tests.length})" autocomplete="off">
      <div class="stack" style="gap:2px;max-height:340px;overflow:auto">${tests.map(t_ => `<label class="check" style="margin:0" data-name="${esc((t_.name + " " + t_.code).toLowerCase())}"><input type="checkbox" name="t${t_.id}"> ${esc(t_.name)} <span class="muted small">${t_.rate_p ? money(P2R(t_.rate_p)) : ""} · ${t_.sample || ""}</span></label>`).join("")}</div>
      <div class="btns"><button class="btn">Create order</button></div></form>`) : ""}</div>`;
};
on("labTab", el => { App.cache.labSt = el.dataset.k; go("lab"); });
on("labNew", async f => {
  const v = vals(f), pid = pidOf(v.patient); if (!pid) return toast("Pick the patient from the list.");
  const tests = Object.keys(v).filter(k => /^t\d+$/.test(k) && v[k]).map(k => +k.slice(1));
  if (!tests.length) return toast("Tick at least one test.");
  const r = await api("/api/lab/orders", { patient_id: pid, tests, priority: v.priority }); toast(`Order LAB${r.id} created. Bill it in Hospital billing.`); go("lab", ["o", r.id]);
});

function liveFlag(p, v) {
  if (v === "") return "";
  const n = Number(v);
  if (isNaN(n)) return p.ref_text && !p.ref_text.toLowerCase().includes(v.toLowerCase()) ? "A" : "N";
  if (p.crit_low != null && n < p.crit_low) return "LL"; if (p.crit_high != null && n > p.crit_high) return "HH";
  if (p.low != null && n < p.low) return "L"; if (p.high != null && n > p.high) return "H"; return "N";
}
async function labOrder(main, id) {
  const o = await api("/api/lab/orders/" + id); App.cache.labOrder = o;
  const editable = can("lab") && (o.status === "collected" || o.status === "resulted");
  main.innerHTML = `<div class="card"><div class="card-h"><div><h2>LAB${o.id} · ${esc(o.pname)}</h2><p>${o.code} · ${o.age ?? "?"} yrs · ${esc(o.gender || "")} · ordered ${o.created_at}${o.dname ? " by " + esc(o.dname) : ""} · ${o.priority.toUpperCase()}</p></div>${pill(...LAB_ST[o.status])}</div>
    ${o.critical ? alertRow("high", "<b>Critical value.</b> The ordering doctor has been alerted. Inform them by phone as well.") : ""}
    ${o.status === "resulted" && can("lab_verify") ? `<div style="margin:10px 0"><label>Interpretation ${o.interpretation ? '<span class="small muted">(AI draft — read and correct it; it goes on the report)</span>' : '<span class="small muted">(optional; goes on the report)</span>'}</label><textarea id="labInterp">${esc(o.interpretation || "")}</textarea></div>` : ""}
    ${o.status === "verified" && o.interpretation ? `<div style="margin:10px 0"><b>Interpretation</b><p class="small" style="margin:4px 0">${esc(o.interpretation)}</p></div>` : ""}
    <form data-submit="labSave" class="resgrid">${o.tests.map(t_ => `<h3 style="margin:14px 0 6px">${esc(t_.name)} <span class="small muted">${esc(t_.sample || "")}</span></h3>
      ${tbl(["Test", "Result", "Unit", "Normal range", "Flag"], t_.params.map(p => `<tr><td>${esc(p.name)}</td><td>${editable ? `<input name="${t_.item_id}:${p.id}" value="${p.formula ? "" : esc(p.value || "")}" ${p.formula ? `placeholder="${esc(p.value || "auto")}" title="Calculated: ${esc(p.formula)}. Type a value only to override it."` : ""} data-input="labLive" data-p='${esc(JSON.stringify({ low: p.eff_low, high: p.eff_high, crit_low: p.crit_low, crit_high: p.crit_high, ref_text: p.ref_text }))}'>` : `<b>${esc(p.value || "–")}</b>`}</td><td>${esc(p.unit || "")}</td><td class="small">${esc(p.range || "")}</td><td class="flagcell"><span class="flag-${p.flag || ""}">${FLAG_TXT[p.flag] || ""}</span></td></tr>`).join(""))}`).join("")}
    <div class="btns">
      ${o.status === "ordered" && can("lab") ? `<button type="button" class="btn" data-act="labCollect">Sample collected</button>` : ""}
      ${editable ? `<button class="btn ghost" name="draft" value="1">Save draft</button><button type="button" class="btn" data-act="labSubmit">Submit results</button>` : ""}
      ${o.status === "resulted" && can("lab_verify") ? `<button type="button" class="btn" data-act="labVerify">Verify and send to patient</button>` : ""}
      ${["ordered", "collected"].includes(o.status) && can("lab") ? `<button type="button" class="btn ghost" data-act="labCancel">Cancel order</button>` : ""}
      ${o.status === "verified" ? `<button type="button" class="btn ghost" data-act="labPrint">Print report</button><button type="button" class="btn ghost" data-act="pdfDl" data-p="lab/${o.id}">PDF</button>` : ""}
      <button type="button" class="btn ghost" data-act="go" data-v="lab">Back to worklist</button></div></form>
    <p class="small muted">Collected: ${o.collected_at ? `${o.collected_at} by ${esc(o.collected_name)}` : "–"} · Resulted: ${o.resulted_at ? `${o.resulted_at} by ${esc(o.resulted_name)}` : "–"} · Verified: ${o.verified_at ? `${o.verified_at} by ${esc(o.verified_name)}` : "–"}</p></div>`;
}
on("labLive", el => { const f = liveFlag(JSON.parse(el.dataset.p), el.value.trim()); el.closest("tr").querySelector(".flagcell").innerHTML = `<span class="flag-${f}">${FLAG_TXT[f] || ""}</span>`; });
const labValues = () => { const o = {}; $$(".resgrid input[name*=':']").forEach(i => o[i.name] = i.value); return o; };
on("labSave", async () => { await api(`/api/lab/orders/${App.cache.labOrder.id}/results`, { values: labValues() }); toast("Draft saved"); });
on("labSubmit", async () => { const r = await api(`/api/lab/orders/${App.cache.labOrder.id}/results`, { values: labValues(), submit: true }); toast(r.critical ? "Submitted. CRITICAL value: doctor alerted." : "Submitted for verification"); go("lab", ["o", App.cache.labOrder.id]); });
on("labCollect", async () => { await api(`/api/lab/orders/${App.cache.labOrder.id}/collect`, {}); go("lab", ["o", App.cache.labOrder.id]); });
on("labVerify", async () => {
  const r = await api(`/api/lab/orders/${App.cache.labOrder.id}/verify`, $("#labInterp") ? { interpretation: $("#labInterp").value } : {});
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
