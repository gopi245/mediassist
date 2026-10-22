/* Documents: upload, link to patient/doctor/bill/invoice/admission/lab/claim/stock, AI reader, library. */
"use strict";
let UP = null;
RENDER.docs = async (main, [mode, a, b]) => {
  const [d, ai] = await Promise.all([api("/api/documents?" + (App.cache.docQ ? "q=" + encodeURIComponent(App.cache.docQ) : "") + (App.cache.docT ? "&type=" + App.cache.docT : "")), api("/api/ai/status"), loadMeds()]);
  App.cache.docTypes = d.types; App.cache.ai = ai;
  const link = mode === "up" ? { [a + "_id"]: +b } : {};
  main.innerHTML = `<div class="g-form"><div class="card"><div class="card-h"><div><h2>Add a document</h2><p>Photos of bills, invoices, prescriptions, reports, IDs or insurance papers. PDFs too.</p></div></div>
    <label class="drop" id="drop"><input type="file" id="upFile" accept="image/jpeg,image/png,image/webp,application/pdf"><b>Take a photo or choose a file</b><span class="small muted">JPG, PNG, WebP or PDF up to 15 MB</span></label>
    <div class="btns" style="justify-content:flex-start"><button type="button" class="btn ghost sm" data-act="phoneDoc">Use your phone camera (QR)</button></div>
    <div id="upStage"></div>${Object.keys(link).length ? `<p class="small muted">Will be linked to ${esc(a)} #${b}</p>` : ""}</div>
  <div class="stack"><div class="card" id="docView" hidden></div>${card("Library", `${d.rows.length} documents`, `<input data-input="docQ" value="${esc(App.cache.docQ || "")}" placeholder="Search patient, bill, invoice, medicine">
    ${subtabs([["", "All"], ...Object.entries(d.types)], App.cache.docT || "", "docT")}<div class="dgrid">${d.rows.map(x => `<button class="dcard" data-act="docOpen" data-id="${x.id}"><div class="th">${x.mime.startsWith("image/") ? `<img src="/api/documents/${x.id}/file" alt="" loading="lazy">` : '<span class="pdf">PDF</span>'}</div>
    <div class="b"><span class="pill p-info p-plain">${esc(x.type_label)}</span>${docTags(x)}</div></button>`).join("") || '<p class="empty">No documents yet.</p>'}</div>`)}</div></div>`;
  UP = { link };
  $("#upFile").addEventListener("change", e => pickDoc(e.target.files[0]));
  const drop = $("#drop");
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => pickDoc(e.dataTransfer.files[0]));
  if (mode === "d" && a) ACTIONS.docOpen({ dataset: { id: a } });
};
const docTags = x => `<div class="tags">${[["Patient", x.pname], ["Doctor", x.dname], ["Bill", x.bill_no], ["Invoice", x.inv_no], ["IP", x.ip_no], ["Stock", x.mname], ["Branch", x.bcode]].filter(t_ => t_[1]).map(([k, v]) => `<span class="tagc"><b>${k}</b>${esc(v)}</span>`).join("") || '<span class="tagc">Not linked</span>'}${x.shared_at ? '<span class="tagc"><b>Sent</b>to patient</span>' : ""}</div>`;
on("docQ", debounce(el => { App.cache.docQ = el.value; go("docs"); }, 400));
on("docT", el => { App.cache.docT = el.dataset.k; go("docs"); });
function linkFields(d = {}) {
  const types = App.cache.docTypes;
  return `<div class="fields"><div><label>Type</label><select name="doc_type">${Object.entries(types).map(([k, l]) => `<option value="${k}" ${d.doc_type === k ? "selected" : ""}>${l}</option>`).join("")}</select></div><div><label>Date</label><input name="doc_date" type="date" value="${d.doc_date || localDay()}"></div>
    ${patInput("patient", d.patient_id ? `P${String(d.patient_id).padStart(5, "0")} · ${d.pname || ""}` : "")}
    <div><label>Doctor</label><select name="doctor_id" id="docDoc"><option value="">None</option></select></div><div><label>Pharmacy bill id</label><input name="bill_id" type="number" value="${d.bill_id || ""}"></div><div><label>Invoice id</label><input name="invoice_id" type="number" value="${d.invoice_id || ""}"></div>
    <div><label>Admission id</label><input name="admission_id" type="number" value="${d.admission_id || ""}"></div><div><label>Lab order id</label><input name="lab_order_id" type="number" value="${d.lab_order_id || ""}"></div><div><label>Claim id</label><input name="claim_id" type="number" value="${d.claim_id || ""}"></div>
    <div class="span2"><label>Stock item</label><input name="med" list="medOpts" value="${esc(d.mname || "")}"></div><div class="span2"><label>Note</label><input name="note" value="${esc(d.note || "")}"></div></div>`;
}
async function fillDocDoctor(sel) { const docs = await staff("doctor"); $("#docDoc").innerHTML = `<option value="">None</option>` + docs.map(d => `<option value="${d.id}" ${String(sel) === String(d.id) ? "selected" : ""}>${esc(d.name)}</option>`).join(""); }
function readLinks(root) {
  const v = vals(root), m = medByName(v.med), o = { doc_type: v.doc_type, doc_date: v.doc_date, note: v.note, patient_id: pidOf(v.patient), doctor_id: v.doctor_id || null, medicine_id: m ? m.id : null };
  ["bill_id", "invoice_id", "admission_id", "lab_order_id", "claim_id"].forEach(k => o[k] = v[k] || null);
  if (v.patient && !o.patient_id) throw new Error("Pick the patient from the list, or clear the field.");
  return o;
}
async function pickDoc(f) {
  if (!f) return;
  if (!["image/jpeg", "image/png", "image/webp", "application/pdf"].includes(f.type)) return toast("Choose a JPG, PNG, WebP photo or a PDF.");
  if (f.size > 15 * 1024 * 1024) return toast("Files must be under 15 MB.");
  const data = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result.split(",")[1]); fr.readAsDataURL(f); });
  UP = { ...UP, file: f, data };
  const url = URL.createObjectURL(f), ai = App.cache.ai;
  $("#upStage").innerHTML = `<div class="preview" style="margin-top:12px">${f.type.startsWith("image/") ? `<img src="${url}" alt="Selected document">` : `<div class="sinfo"><span class="pdf">PDF</span> ${esc(f.name)}</div>`}</div>
    ${ai.ready ? `<div class="aibar"><div><b>Let AI read it</b><span class="small muted"> Fills in the type, date, patient, doctor and items. Check before saving.</span></div><button class="btn" data-act="aiRead">Read with AI</button></div>` : `<p class="small muted">AI reading is off. ${ai.sdk ? "Add an Anthropic API key in Admin > Settings." : "Install it on the server with: pip install anthropic"}</p>`}
    <div id="aiOut"></div><form data-submit="docSave" class="stack" style="margin-top:10px"><h3>Link this document</h3>${linkFields(UP.link.patient_id ? { patient_id: UP.link.patient_id } : UP.link)}
    <label class="check"><input type="checkbox" name="share" checked> Send to the patient now (WhatsApp message + their records page)</label><div class="btns"><button class="btn">Save document</button></div></form>`;
  fillDocDoctor();
}
on("docSave", async f => {
  const body = { ...readLinks(f), ...Object.fromEntries(Object.entries(UP.link).filter(([, v]) => v)), mime: UP.file.type, data: UP.data, filename: UP.file.name };
  body.share = f.share.checked && !!body.patient_id;
  const r = await api("/api/documents", body);
  toast(r.shared ? (r.sent && r.sent.some(x => x.ok) ? "Saved and sent to the patient" : "Saved. It's on the patient's records page (WhatsApp not sent)") : "Document saved and linked");
  UP = null; go("docs", ["d", r.id]);
});
on("aiRead", async el => {
  await withBusy(el, async () => {
    $("#aiOut").innerHTML = alertRow("info", "Reading the document. This can take up to a minute.");
    try {
      const r = await api("/api/ai/read-document", { mime: UP.file.type, data: UP.data }), f = $("form[data-submit=docSave]");
      if (App.cache.docTypes[r.doc_type]) f.doc_type.value = r.doc_type;
      if (/^\d{4}-\d{2}-\d{2}$/.test(r.date || "")) f.doc_date.value = r.date;
      if (r.match.patient) f.patient.value = `${r.match.patient.code} · ${r.match.patient.name}`;
      if (r.match.doctor) await fillDocDoctor(r.match.doctor.id);
      if (r.match.bill) f.bill_id.value = r.match.bill.id;
      if (r.match.invoice) f.invoice_id.value = r.match.invoice.id;
      const first = (r.items || []).find(i => i.medicine_id); if (first) f.med.value = first.matched;
      if (r.supplier && !f.note.value) f.note.value = `${r.supplier}${r.document_no ? " · " + r.document_no : ""}`;
      App.cache.aiItems = r;
      const stockable = (r.items || []).filter(i => i.medicine_id && i.qty > 0 && i.mrp > 0 && /^\d{4}-\d{2}/.test(i.expiry || ""));
      $("#aiOut").innerHTML = alertRow("info", `<b>Read by AI.</b> Check every field before saving.${r.summary ? "<br>" + esc(r.summary) : ""}`) +
        (r.items && r.items.length ? tbl(["Printed", "Matched", "Batch", "Expiry", "Qty", "MRP"], r.items.map(i => `<tr><td>${esc(i.medicine)}</td><td>${i.matched ? `<b>${esc(i.matched)}</b>` : '<span class="muted small">not in catalogue</span>'}</td><td class="mono">${esc(i.batch || "–")}</td><td class="mono">${esc(i.expiry || "–")}</td><td class="num">${i.qty || "–"}</td><td class="num">${i.mrp ? money(i.mrp) : "–"}</td></tr>`).join("")) : "") +
        (r.doc_type === "invoice" && stockable.length && can("stock") && PH_() ? `<div class="btns"><button class="btn ghost" data-act="aiStock">Fill "Receive goods" with ${stockable.length} line(s)</button></div>` : "");
    } catch (e) { $("#aiOut").innerHTML = alertRow("", esc(e.message)); }
  });
});
on("aiStock", async () => {
  const r = App.cache.aiItems, lines = r.items.filter(i => i.medicine_id && i.qty > 0 && i.mrp > 0);
  const norm = e => /^\d{4}-\d{2}$/.test(e) ? new Date(+e.slice(0, 4), +e.slice(5, 7), 0, 12).toISOString().slice(0, 10) : e.slice(0, 10);
  await go("stock", ["grn"]);
  const rows_ = $$("#grnRows tr").slice(1); rows_.forEach(tr => tr.remove());
  for (const i of lines) {
    $("#grnRows").insertAdjacentHTML("beforeend", App.cache.grnRow({ name: i.matched }));
    const tr = $$("#grnRows tr").pop();
    tr.querySelector("[name=batch]").value = i.batch || ""; tr.querySelector("[name=expiry]").value = norm(i.expiry); tr.querySelector("[name=qty]").value = i.qty; tr.querySelector("[name=cost]").value = i.cost || ""; tr.querySelector("[name=mrp]").value = i.mrp;
  }
  if (r.document_no) $("[name=invoice_no]").value = r.document_no;
  toast("Check the lines, then press Receive stock. Upload the invoice photo to Documents to keep it.");
});
on("docOpen", async el => {
  const d = (await api("/api/documents")).rows.find(x => x.id === +el.dataset.id); if (!d) return;
  const box = $("#docView"); box.hidden = false; App.cache.doc = d;
  box.innerHTML = `<div class="card-h"><div><h2>${esc(d.type_label)}</h2><p>${esc(d.filename || "")} · ${Math.round(d.size / 1024)} KB · ${d.created_at}</p></div><button class="btn sm ghost" data-act="docClose">Close</button></div>
    <div class="preview">${d.mime.startsWith("image/") ? `<img src="/api/documents/${d.id}/file" alt="${esc(d.type_label)}">` : `<div class="sinfo"><span class="pdf">PDF</span><a href="/api/documents/${d.id}/file" target="_blank" rel="noopener">Open the PDF</a></div>`}</div>
    ${docTags(d)}<form data-submit="docUpdate" class="stack" style="margin-top:10px"><h3>Change links</h3>${linkFields(d)}
    <label class="check"><input type="checkbox" name="share" ${d.shared_at ? "checked" : ""}> Patient can see this on their records page${d.shared_at ? ` <span class="small muted">(sent ${esc(d.shared_at)})</span>` : ""}</label><div class="btns"><button class="btn">Save</button><button type="button" class="btn ghost" data-act="docDel" style="color:var(--crit);border-color:var(--crit)">Delete</button></div></form>`;
  fillDocDoctor(d.doctor_id); box.scrollIntoView({ behavior: "smooth", block: "nearest" });
});
on("docClose", () => { $("#docView").hidden = true; });
on("docUpdate", async f => { const o = readLinks(f); o.share = f.share.checked && !!o.patient_id; await api(`/api/documents/${App.cache.doc.id}`, o); toast("Links saved"); go("docs", ["d", App.cache.doc.id]); });
on("docDel", async () => { if (!await dialog("Delete this document?", "<p>The file is removed from the server. This can't be undone.</p>", { ok: "Delete", danger: true })) return; await api(`/api/documents/${App.cache.doc.id}/delete`, {}); toast("Deleted"); go("docs"); });
