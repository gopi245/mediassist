/* Pharmacy > Edit stock & photos: change stock directly, add stock by hand, and keep or read stock photos
   (shelf, rack, carton or supplier bill). Reading a photo proposes changes; nothing is saved until the pharmacist confirms. */
"use strict";

/* The photo reader. The installed server reads with its own AI key; the in-browser demo swaps this out. */
const STOCK_AI = {
  ready: async () => { try { return !!(await api("/api/ai/status")).ready; } catch (e) { return false; } },
  read: (mime, data) => api("/api/ai/read-document", { mime, data }),
};
let SPHOTO = null;

const edReasons = (sel, skip = "photo") => Object.entries(App.cache.ed.reasons).filter(([k]) => k !== skip).map(([k, l]) => `<option value="${k}" ${k === sel ? "selected" : ""}>${l}</option>`).join("");
const lastDayOf = e => /^\d{4}-\d{2}$/.test(e || "") ? new Date(Date.UTC(+e.slice(0, 4), +e.slice(5, 7), 0)).toISOString().slice(0, 10) : (e || "").slice(0, 10);

STOCK.edit = async el => {
  const [d, docs, aiOk] = await Promise.all([api("/api/stock/edit"), api("/api/documents?type=stock"), STOCK_AI.ready()]);
  App.cache.ed = d; App.cache.edAi = aiOk;
  el.innerHTML = `<div class="g2">
    ${card("Stock photo", "Photograph a shelf, rack, carton or supplier bill. Keep it as a record, or let AI read it and suggest the stock changes.",
      `<label class="drop" id="spDrop"><input type="file" id="spFile" accept="image/jpeg,image/png,image/webp"><b>Take a photo or choose one</b><span class="small muted">JPG, PNG or WebP up to 15 MB</span></label>
      <div class="btns" style="justify-content:flex-start"><button type="button" class="btn ghost sm" data-act="phoneStock">Use your phone camera (QR)</button></div><div id="spStage"></div>`)}
    ${card("Quick stock entry", "Scan the barcode or type the name, press Enter after each box, and keep going. Save all the lines at once.",
      `<div class="qs-row" id="qsRow">
        <div class="qs-med"><label for="qsMed">Barcode or medicine</label><input id="qsMed" list="medOpts" autocomplete="off" placeholder="Scan or type"></div>
        <div><label for="qsQty">Qty</label><input id="qsQty" type="number" min="1" inputmode="numeric"></div>
        <div><label for="qsUnit">Counted in</label><select id="qsUnit"><option value="pack">Strips / bottles</option><option value="unit">Tablets</option></select></div>
        <div><label for="qsBatch">Batch</label><input id="qsBatch" class="mono" autocomplete="off"></div>
        <div><label for="qsExp">Expiry</label><input id="qsExp" placeholder="MM/YY" inputmode="numeric" autocomplete="off"></div>
        <div><label for="qsMrp">MRP ₹ each</label><input id="qsMrp" type="number" step=".01" min="0" inputmode="decimal"></div>
        <div><label for="qsCost">Cost ₹ each</label><input id="qsCost" type="number" step=".01" min="0" inputmode="decimal" placeholder="buy price"></div>
        <div><button type="button" class="btn" data-act="qsAdd">Add</button></div></div>
      <div id="qsInfo" class="small muted" style="min-height:18px;margin-top:6px"></div><div id="qsList"></div>`)}
  </div>
  <div id="spReview"></div>
  ${card("Edit stock", "Change any box and press Save on that row. Quantities are in single units (tablets, bottles). Every change is logged with who, when and why.",
    `<div class="fields"><div class="span2"><label>Find</label><input data-input="edFilter" id="edQ" placeholder="Medicine or generic name" value="${esc(App.cache.edQ || "")}" autocomplete="off"></div>
      <div><label>Reason for changes</label><select id="edReason">${edReasons("count")}</select></div>
      <div style="align-self:end"><label class="check"><input type="checkbox" id="edLow" data-change="edDraw" ${App.cache.edLow ? "checked" : ""}> Only low or out of stock</label></div></div><div id="edTbl"></div>`)}
  ${card("Stock photos", `${docs.rows.length} photo${docs.rows.length === 1 ? "" : "s"} · open one to see it full size or change its links`,
    `<div class="dgrid">${docs.rows.map(x => `<button class="dcard" data-act="go" data-v="docs" data-p="d/${x.id}"><div class="th"><img src="/api/documents/${x.id}/file" alt="Stock photo" loading="lazy"></div>
      <div class="b"><span class="small mono">${esc(x.doc_date || "")}</span>${x.mname ? `<b>${esc(x.mname)}</b>` : ""}${x.note ? `<span class="small muted">${esc(x.note)}</span>` : ""}</div></button>`).join("") || '<p class="empty">No stock photos yet.</p>'}</div>`)}`;
  const inp = $("#spFile"), drop = $("#spDrop");
  inp.addEventListener("change", e => pickStockPhoto(e.target.files[0]));
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => pickStockPhoto(e.dataTransfer.files[0]));
  $("#qsRow").addEventListener("keydown", qsKey);
  $("#qsMed").addEventListener("change", () => qsPick());
  edDraw(); qsDraw(); $("#qsMed").focus();
};

/* ---------- edit table ---------- */
function edDraw() {
  const q = (App.cache.edQ || "").toLowerCase(), low = $("#edLow") && $("#edLow").checked; App.cache.edLow = low;
  const meds = App.cache.ed.medicines.filter(m => (!q || (m.name + " " + (m.generic || "")).toLowerCase().includes(q)) && (!low || m.qty < m.reorder_level));
  const rowsHtml = meds.slice(0, 150).map(m => {
    const head = `<td rowspan="${Math.max(1, m.batches.length)}"><b>${esc(m.name)}</b><div class="small muted">${esc(m.generic || "")} · pack ${m.pack_size}</div>
      <div>${pill(m.qty ? m.qty + " usable" : "out of stock", !m.qty ? "p-crit" : m.qty < m.reorder_level ? "p-warn" : "p-ok")}</div></td>`;
    if (!m.batches.length) return `<tr>${head}<td colspan="6" class="small muted">No stock at this branch. Usual rack <span class="rack sm">${esc(m.rack)}</span></td><td><button class="btn sm" data-act="edAddFor" data-id="${m.id}">Add stock</button></td></tr>`;
    return m.batches.map((b, i) => `<tr data-batch="${b.id}">${i ? "" : head}
      <td><input name="batch" value="${esc(b.batch || "")}" class="mono" style="width:96px" aria-label="Batch"></td>
      <td><input name="expiry" type="date" value="${b.expiry}" aria-label="Expiry">${b.days_left < 0 ? `<div>${pill("expired", "p-crit")}</div>` : b.days_left <= 90 ? `<div>${pill(b.days_left + " days left", "p-warn")}</div>` : ""}</td>
      <td><input name="rack" value="${esc(b.rack || "")}" class="mono" style="width:76px" aria-label="Rack"></td>
      <td><input name="qty" type="number" min="0" value="${b.qty}" style="width:84px" aria-label="Quantity in units">${m.pack_size > 1 ? `<div class="small muted">${Math.floor(b.qty / m.pack_size)} strips${b.qty % m.pack_size ? " + " + (b.qty % m.pack_size) : ""}</div>` : ""}</td>
      <td><input name="mrp" type="number" step=".01" min="0" value="${b.mrp}" style="width:84px" aria-label="MRP per unit"></td>
      <td class="row-actions"><button class="btn sm" data-act="edSave" data-id="${b.id}">Save</button></td>
      <td>${i === m.batches.length - 1 ? `<button class="btn sm ghost" data-act="edAddFor" data-id="${m.id}">New batch</button>` : ""}</td></tr>`).join("");
  }).join("");
  $("#edTbl").innerHTML = tbl(["Medicine", "Batch", "Expiry", "Rack", "Qty (units)", "MRP ₹/unit", "", ""], rowsHtml, "No medicines match.") +
    (meds.length > 150 ? `<p class="small muted">Showing 150 of ${meds.length}. Type a name to narrow it down.</p>` : "");
}
on("edDraw", () => edDraw());
on("edFilter", debounce(el => { App.cache.edQ = el.value; edDraw(); }, 200));
on("edSave", async el => {
  const tr = el.closest("tr"), v = vals(tr), reason = $("#edReason").value;
  await withBusy(el, () => api("/api/stock/update", { reason, lines: [{ batch_id: +el.dataset.id, unit: "unit", ...v }] }));
  toast("Stock saved"); App.cache.meds = null; await edReload();
});
async function edReload() { App.cache.ed = await api("/api/stock/edit"); edDraw(); }
on("edAddFor", el => {
  const m = App.cache.ed.medicines.find(x => x.id === +el.dataset.id);
  $("#qsMed").value = m.name; qsPick(); $("#qsRow").scrollIntoView({ behavior: "smooth", block: "center" }); $("#qsQty").focus();
});

/* ---------- quick stock entry ---------- */
const edMed = name => App.cache.ed.medicines.find(m => m.name.toLowerCase() === String(name || "").trim().toLowerCase());
const QS_FIELDS = ["qsMed", "qsQty", "qsUnit", "qsBatch", "qsExp", "qsMrp", "qsCost"];
const qsLines = () => App.cache.qs || (App.cache.qs = []);
/* Expiry as printed on the strip: 05/27, 5-2027, 0527, 2027-05 or a full date. Month-only means the month's last day. */
function parseExpiry(s) {
  s = String(s || "").trim(); let m;
  const end = (y, mo) => mo >= 1 && mo <= 12 ? new Date(Date.UTC(y, mo, 0)).toISOString().slice(0, 10) : null;
  if ((m = s.match(/^(\d{1,2})\s*[\/.\-]\s*(\d{2}|\d{4})$/))) return end(+m[2] < 100 ? 2000 + +m[2] : +m[2], +m[1]);
  if ((m = s.match(/^(\d{2})(\d{2})$/))) return end(2000 + +m[2], +m[1]);
  if ((m = s.match(/^(\d{4})-(\d{2})$/))) return end(+m[1], +m[2]);
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  return null;
}
function qsFind(v) {
  v = String(v || "").trim(); if (!v) return null;
  const byCode = (App.cache.meds || []).find(m => m.barcode && m.barcode === v.replace(/\s/g, ""));
  return edMed(byCode ? byCode.name : v);
}
function qsPick() {
  const m = qsFind($("#qsMed").value);
  if (!m) { $("#qsInfo").textContent = $("#qsMed").value.trim() ? "Not in the medicine list. Check the spelling, or add it in Medicine master." : ""; return null; }
  $("#qsMed").value = m.name; $("#qsUnit").value = m.pack_size > 1 ? "pack" : "unit";
  const mult = $("#qsUnit").value === "pack" ? m.pack_size : 1;
  if (m.last && !$("#qsMrp").value) $("#qsMrp").value = (m.last.mrp * mult).toFixed(2);
  $("#qsInfo").innerHTML = `<b>${esc(m.name)}</b> · pack of ${m.pack_size} · ${m.qty} usable now · rack <span class="rack sm">${esc(m.rack)}</span>${m.last ? ` · last MRP ${money(m.last.mrp * mult)} per ${mult > 1 ? "strip" : "unit"}` : ""}`;
  return m;
}
function qsKey(e) {
  if (e.key !== "Enter") return;
  e.preventDefault();
  const i = QS_FIELDS.indexOf(e.target.id);
  if (e.target.id === "qsMed" && !qsPick()) return;
  if (i === QS_FIELDS.length - 1 || e.target.dataset.act === "qsAdd") return ACTIONS.qsAdd();
  const next = $("#" + QS_FIELDS[i + 1]); next.focus(); if (next.select) next.select();
}
on("qsAdd", () => {
  const m = qsFind($("#qsMed").value), qty = +$("#qsQty").value, exp = parseExpiry($("#qsExp").value), mrp = +$("#qsMrp").value, unit = $("#qsUnit").value, batch = $("#qsBatch").value.trim();
  const fail = (msg, id) => { toast(msg); $("#" + id).focus(); };
  if (!m) return fail("Choose a medicine from the list, or scan its barcode.", "qsMed");
  if (!(qty > 0)) return fail("Enter how many.", "qsQty");
  if (!exp) return fail("Enter the expiry as printed, like 05/27.", "qsExp");
  if (exp <= localDay()) return fail("This batch has already expired. Don't put it on the shelf.", "qsExp");
  if (!(mrp > 0)) return fail("Enter the MRP printed on the pack.", "qsMrp");
  const cost = $("#qsCost").value === "" ? null : +$("#qsCost").value;
  if (cost === null && !m.last) return fail(`First time stocking ${m.name}: enter the cost (what you paid per ${unit === "pack" ? "strip" : "tablet"}).`, "qsCost");
  if (cost !== null && cost > mrp) return fail("Cost is higher than MRP. Check both.", "qsCost");
  const same = qsLines().find(l => l.medicine_id === m.id && l.batch.toLowerCase() === batch.toLowerCase() && l.unit === unit && l.expiry === exp);
  if (same) same.qty += qty;
  else qsLines().push({ medicine_id: m.id, name: m.name, pack: m.pack_size, qty, unit, batch, expiry: exp, mrp, cost });
  ["qsMed", "qsQty", "qsBatch", "qsExp", "qsMrp", "qsCost"].forEach(id => $("#" + id).value = "");
  $("#qsInfo").textContent = `Added ${m.name}. Next one.`; qsDraw(); $("#qsMed").focus();
});
function qsDraw() {
  const L = qsLines(), box = $("#qsList"); if (!box) return;
  if (!L.length) { box.innerHTML = ""; return; }
  const units = l => l.qty * (l.unit === "pack" ? l.pack : 1);
  box.innerHTML = tbl(["Medicine", "Qty", "Batch", "Expiry", "MRP ₹", "Cost ₹", ""], L.map((l, i) => `<tr><td><b>${esc(l.name)}</b></td><td class="num">${l.qty} ${l.unit === "pack" ? (l.pack > 1 ? "strips" : "") : "tablets"}<div class="small muted">${units(l)} units</div></td><td class="mono">${esc(l.batch || "–")}</td><td class="mono">${l.expiry.slice(0, 7)}</td><td class="num">${money(l.mrp)}</td><td class="num">${l.cost === null || l.cost === undefined ? '<span class="small muted">last</span>' : money(l.cost)}</td><td><button class="btn sm ghost" data-act="qsDel" data-i="${i}" aria-label="Remove line">Remove</button></td></tr>`).join(""))
    + `<div class="fields" style="margin-top:8px"><div><label for="qsReason">Reason</label><select id="qsReason">${edReasons("opening")}</select></div>
       <div style="align-self:end" class="btns"><button class="btn" data-act="qsSave">Save ${L.length} line${L.length === 1 ? "" : "s"} to stock</button><button class="btn ghost" data-act="qsClear">Clear</button></div></div>`;
}
on("qsDel", el => { qsLines().splice(+el.dataset.i, 1); qsDraw(); });
on("qsClear", () => { App.cache.qs = []; qsDraw(); });
on("qsSave", async el => {
  const L = qsLines();
  const r = await withBusy(el, () => api("/api/stock/update", { reason: $("#qsReason").value, lines: L.map(l => ({ medicine_id: l.medicine_id, batch: l.batch, expiry: l.expiry, qty: l.qty, unit: l.unit, mrp: l.mrp, cost: l.cost ?? "" })) }));
  toast(`${r.added} batch${r.added === 1 ? "" : "es"} added to stock`); App.cache.qs = []; App.cache.meds = null; await edReload(); qsDraw(); $("#qsMed").focus();
});

/* ---------- stock photo ---------- */
async function pickStockPhoto(f, savedId = null) {
  if (!f) return;
  if (!["image/jpeg", "image/png", "image/webp"].includes(f.type)) return toast("Choose a JPG, PNG or WebP photo.");
  if (f.size > 15 * 1024 * 1024) return toast("Photos must be under 15 MB.");
  const data = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result.split(",")[1]); fr.readAsDataURL(f); });
  SPHOTO = { file: f, data, id: savedId };
  $("#spReview").innerHTML = "";
  $("#spStage").innerHTML = `<div class="preview" style="margin-top:12px"><img src="${URL.createObjectURL(f)}" alt="Selected stock photo"></div>
    <form class="stack" id="spForm" data-submit="spSave" style="margin-top:10px"><div class="fields">
      <div><label>What is in the photo</label><select name="kind"><option value="stock">Shelf, rack or carton</option><option value="invoice">Supplier bill / invoice</option></select></div>
      <div><label>Medicine (optional)</label><input name="med" list="medOpts" autocomplete="off"></div>
      <div class="span2"><label>Note</label><input name="note" placeholder="e.g. Rack A2, evening count"></div></div>
      ${App.cache.edAi ? `<div class="aibar"><div><b>Read the photo and update stock</b><span class="small muted"> AI lists the medicines, batches, expiry dates and counts it can see. You check every line before anything changes.</span></div><button type="button" class="btn" data-act="spRead">Read photo</button></div>`
        : `<p class="small muted">AI reading is off, so the photo is kept as a record only. To turn it on, add an Anthropic API key in Admin > Settings.</p>`}
      <div class="btns"><button class="btn ghost">Save photo only</button></div></form>`;
}
async function spStore() {
  if (SPHOTO.id) return SPHOTO.id;
  const v = vals($("#spForm")), m = medByName(v.med);
  const r = await api("/api/documents", { doc_type: v.kind, medicine_id: m ? m.id : null, note: v.note, mime: SPHOTO.file.type, data: SPHOTO.data, filename: SPHOTO.file.name });
  SPHOTO.id = r.id; return r.id;
}
on("spSave", async () => { await spStore(); toast("Photo saved"); SPHOTO = null; go("stock", ["edit"]); });
on("spRead", async el => {
  const kind = vals($("#spForm")).kind;
  await withBusy(el, async () => {
    $("#spReview").innerHTML = card("Reading the photo…", "This can take up to a minute.", "");
    let r;
    try { r = await STOCK_AI.read(SPHOTO.file.type, SPHOTO.data, SPHOTO.file); }
    catch (e) { $("#spReview").innerHTML = card("Couldn't read the photo", "", alertRow("", esc(e.message || "Reading failed")) + `<p class="small muted">You can still save the photo, and edit the stock in the table below.</p>`); return; }
    App.cache.spRead = { ...r, kind };
    spDrawReview();
  });
});

/* Each line read from the photo: an existing batch gets its count set, anything else is added as a new batch. */
function spDrawReview() {
  const r = App.cache.spRead, kind = r.kind, items = r.items || [];
  if (!items.length) { $("#spReview").innerHTML = card("Nothing to update", "", alertRow("info", "No medicines could be read from this photo. Try a closer, sharper photo with the labels facing the camera.")); return; }
  $("#spReview").innerHTML = card("Check what the photo shows", (kind === "invoice" ? "Supplier bill: each line is added as new stock." : "Shelf photo: lines that match a batch on the shelf set its count; new batches are added.") +
    (r.summary ? " " + esc(r.summary) : ""),
    `<form data-submit="spApply" id="spApply">${tbl(["", "Read from photo", "Medicine", "Batch", "Expiry", "Qty", "Counted in", "MRP ₹", "Cost ₹", "What happens"], items.map((it, i) => `<tr data-i="${i}">
      <td><input type="checkbox" name="use" ${it.medicine_id && it.qty > 0 ? "checked" : ""} aria-label="Use this line"></td>
      <td class="small">${esc(it.medicine || "")}</td>
      <td><input name="med" list="medOpts" value="${esc(it.matched || "")}" data-change="spRow" style="min-width:150px" autocomplete="off"></td>
      <td><input name="batch" value="${esc(it.batch || "")}" class="mono" style="width:96px" data-change="spRow"></td>
      <td><input name="expiry" type="date" value="${lastDayOf(it.expiry)}"></td>
      <td><input name="qty" type="number" min="0" value="${it.qty || ""}" style="width:72px" data-change="spRow"></td>
      <td><select name="unit" data-change="spRow"><option value="pack">Strips / bottles</option><option value="unit">Single units</option></select></td>
      <td><input name="mrp" type="number" step=".01" value="${it.mrp || ""}" style="width:80px"></td>
      <td><input name="cost" type="number" step=".01" value="${it.cost || ""}" style="width:80px" placeholder="last"></td>
      <td class="small" data-what></td></tr>`).join(""))}
      <div class="btns"><button class="btn">Update stock</button><button type="button" class="btn ghost" data-act="spCancel">Cancel</button></div></form>`);
  $$("#spApply tr[data-i]").forEach(spWhat);
  $("#spReview").scrollIntoView({ behavior: "smooth", block: "start" });
}
function spMatch(tr) {
  const v = vals(tr), m = edMed(v.med);
  if (!m) return { m: null };
  const b = App.cache.spRead.kind === "invoice" || !v.batch ? null : m.batches.find(x => (x.batch || "").toLowerCase() === v.batch.toLowerCase());
  return { m, b, v };
}
function spWhat(tr) {
  const { m, b, v } = spMatch(tr), cell = tr.querySelector("[data-what]");
  if (!m) { cell.innerHTML = '<span class="allergy">Not in the medicine list</span><div class="muted">Add it in Medicine master first</div>'; tr.querySelector("[name=use]").checked = false; return; }
  const units = (+v.qty || 0) * (v.unit === "pack" ? m.pack_size : 1);
  cell.innerHTML = b ? `Set batch ${esc(b.batch)} to <b>${units}</b> units<div class="muted">now ${b.qty} (${units - b.qty >= 0 ? "+" : ""}${units - b.qty})</div>` : `Add new batch: <b>+${units}</b> units`;
}
on("spRow", el => spWhat(el.closest("tr")));
on("spCancel", () => { $("#spReview").innerHTML = ""; });
on("spApply", async f => {
  const lines = [];
  for (const tr of $$("tr[data-i]", f)) {
    if (!tr.querySelector("[name=use]").checked) continue;
    const { m, b, v } = spMatch(tr);
    if (!m) return toast(`"${v ? v.med : "A line"}" is not in the medicine list. Untick it or choose a medicine.`);
    if (b) lines.push({ batch_id: b.id, qty: v.qty, unit: v.unit, expiry: v.expiry || undefined });
    else lines.push({ medicine_id: m.id, batch: v.batch, expiry: v.expiry, qty: v.qty, unit: v.unit, mrp: v.mrp, cost: v.cost });
  }
  if (!lines.length) return toast("Tick at least one line.");
  const id = await spStore();
  const r = await api("/api/stock/update", { reason: "photo", doc_id: id, lines });
  toast(`Stock updated from the photo: ${r.changed} batch${r.changed === 1 ? "" : "es"} corrected, ${r.added} added`);
  SPHOTO = null; App.cache.meds = null; go("stock", ["edit"]);
});
