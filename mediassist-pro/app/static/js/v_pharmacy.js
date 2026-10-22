/* Pharmacy: POS billing (barcode, Rx, strip/loose, offline), bills and returns; stock management. */
"use strict";
let CART = [], CART_VISIT = null;
let CART_ADM = null;

/* ================= billing counter ================= */
RENDER.billing = async (main, [mode, id]) => {
  await loadMeds(true);
  const bills = await api("/api/bills?date=" + localDay());
  let pre = "";
  if (mode === "p" && id) { const p = await api("/api/patients/" + id); pre = `${p.code} · ${p.name} · ${p.phone}`; }
  main.innerHTML = `<div class="g-form"><div class="card"><div class="card-h"><div><h2>New bill</h2><p>Scan a barcode or type a name. Stock comes from the batch that expires first.</p></div></div>
    <div class="fields"><div class="span2"><label>Barcode</label><input id="bcScan" placeholder="Scan here" autocomplete="off" inputmode="numeric"></div>${patInput("patient", pre, "Patient (blank for walk-in OTC)").replace('<input ', '<input id="bPat" data-change="billPat" ')}</div>
    <div id="bRx" style="margin-top:10px"></div>
    <div class="fields" style="margin-top:10px"><div class="span2"><label>Medicine</label><input id="bMed" list="medOpts" data-input="bLook" autocomplete="off"></div><div><label>Qty</label><input id="bQty" type="number" min="1" value="1"></div>
      <div><label>Sell by</label><select id="bUnit"><option value="strip">Strip / pack</option><option value="unit">Loose tablets</option></select></div><div style="align-self:end"><button class="btn ghost" data-act="bAdd" style="width:100%;justify-content:center">Add line</button></div></div>
    <div id="bInfo"></div><div id="bLines" style="margin-top:12px"></div>
    <form data-submit="saveBill" class="stack"><div class="fields" id="bDocBox" hidden><div><label>Prescribing doctor</label><input name="doctor_name"></div><div><label>Doctor reg. no</label><input name="doctor_reg"></div></div>
      <div class="fields"><div><label>Walk-in name</label><input name="customer"></div><div><label>Discount ₹</label><input name="discount" type="number" min="0" step=".5" value="0" data-input="bRedraw"></div>
      <div><label>Payment</label><select name="pay_mode"><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option><option value="credit">Credit (patient account)</option></select></div></div>
      <div class="btns"><button class="btn">Save bill</button><button type="button" class="btn ghost" data-act="bClear">Clear</button></div></form></div>
  <div class="stack"><div class="card" id="bView" hidden></div>${card("Today's bills", `${bills.length} bills · ${money(bills.reduce((a, b) => a + b.total - b.returned, 0))}`,
    tbl(["Bill", "Customer", "Pay", "Total"], bills.map(b => `<tr class="click" data-act="viewBill" data-id="${b.id}"><td class="mono">${b.bill_no}<div class="small muted">${b.created_at.slice(11)}</div></td><td>${esc(b.customer)}</td><td>${b.pay_mode}</td><td class="num">${money(b.total - b.returned)}</td></tr>`).join(""), "No bills yet today."),
    `<button class="btn sm ghost" data-act="h1csv">H1 register</button>`)}</div></div>`;
  drawCart();
  $("#bcScan").addEventListener("keydown", async e => {
    if (e.key !== "Enter") return; e.preventDefault(); const code = e.target.value.trim(); e.target.value = ""; if (!code) return;
    try { const s = await api("/api/stock/lookup?barcode=" + encodeURIComponent(code)); addLine(s.medicine, 1, "strip"); $("#bInfo").innerHTML = stockCard(s); }
    catch (err) { toast(err.message); }
  });
  if (pre) ACTIONS.billPat($("#bPat"));
  $("#bcScan").focus();
};
function addLine(m, qty, unit, rx) {
  const ex = CART.find(l => l.medicine_id === m.id && !l.rx_item_id && l.unit === unit && !rx);
  if (ex) ex.qty += qty; else CART.push({ medicine_id: m.id, name: m.name, schedule: m.schedule, pack: m.pack_size || 1, mrp: m.mrp, rack: m.rack, stock: m.stock, qty, unit, rx_item_id: rx || null });
  drawCart();
}
function drawCart() {
  let sub = 0;
  $("#bLines").innerHTML = CART.length ? tbl(["Medicine", "Qty", "Amount", ""], CART.map((l, i) => {
    const units = l.qty * (l.unit === "strip" ? l.pack : 1), a = (l.mrp || 0) * units; sub += a;
    return `<tr><td><b>${esc(l.name)}</b> ${l.rx_item_id ? pill("Rx", "p-info") : ""} <span class="small muted">${l.schedule}</span><div class="small muted">${l.rack ? `<span class="rack sm">${esc(l.rack)}</span>` : ""}${units} tablet(s)/unit(s)${l.stock < units ? ` · <span class="allergy">only ${l.stock} in stock</span>` : ""}</div></td>
      <td class="num">${l.qty} ${l.unit === "strip" && l.pack > 1 ? "strip" : ""}</td><td class="num">${money(a)}</td><td><button class="btn sm ghost" data-act="bRm" data-i="${i}">Remove</button></td></tr>`;
  }).join("") + `<tr><td colspan="2"><b>Total</b> <span class="small muted">MRP incl. GST, less discount</span></td><td class="num"><b>${money(Math.max(0, sub - (+($("[name=discount]") || {}).value || 0)))}</b></td><td></td></tr>`) : '<p class="empty">Scan or add medicines, or load a prescription.</p>';
  $("#bDocBox").hidden = !CART.some(l => ["H", "H1"].includes(l.schedule) && !l.rx_item_id);
}
on("bRedraw", () => drawCart());
on("bLook", debounce(async el => { const m = medByName(el.value); $("#bInfo").innerHTML = m ? stockCard(await api("/api/stock/lookup?id=" + m.id)) : ""; if (m) $("#bUnit").value = m.pack_size > 1 ? "strip" : "unit"; }, 200));
on("bAdd", () => { const m = medByName($("#bMed").value); if (!m) return toast("Choose a medicine from the list."); addLine(m, Math.max(1, +$("#bQty").value || 1), $("#bUnit").value); $("#bMed").value = ""; $("#bQty").value = 1; $("#bInfo").innerHTML = ""; $("#bMed").focus(); });
on("bRm", el => { CART.splice(+el.dataset.i, 1); drawCart(); });
on("bClear", () => { CART = []; CART_VISIT = null; go("billing"); });
on("billPat", async el => {
  const pid = pidOf(el.value); CART = CART.filter(l => !l.rx_item_id); CART_VISIT = null; drawCart(); if (!pid) { $("#bRx").innerHTML = ""; return; }
  const [p, pend] = await Promise.all([api("/api/patients/" + pid), api("/api/rx/pending?patient_id=" + pid)]);
  $("#bRx").innerHTML = (p.allergies ? `<div class="banner">Allergic to ${esc(p.allergies)}</div>` : "") + (pend.map((r, i) => alertRow("info", `<b>${r.admission_id ? "Discharge prescription" : "Prescription"}</b> · ${r.date.slice(0, 10)} · ${esc(r.doctor || "")} · ${esc(r.branch)}<br>${esc(r.diagnosis || "")}: ${r.items.map(i => `${esc(i.name)} ×${i.remaining}`).join(", ")}<div class="btns" style="margin-top:6px"><button class="btn sm" data-act="loadRx" data-i="${i}">Add to bill</button></div>`)).join("") || '<p class="small muted">No pending prescriptions.</p>');
  App.cache.pendRx = pend;
});
on("loadRx", el => {
  const r = App.cache.pendRx[+el.dataset.i]; CART_VISIT = r.visit_id || null; CART_ADM = r.admission_id || null; CART = CART.filter(l => !l.rx_item_id); const miss = [];
  for (const i of r.items) { const m = (App.cache.meds || []).find(x => x.id === i.medicine_id) || {}; const q = Math.min(i.remaining, m.stock || 0); if (q < i.remaining) miss.push(`${i.name} (${q} of ${i.remaining})`); if (q) CART.push({ medicine_id: i.medicine_id, name: i.name, schedule: i.schedule, pack: 1, mrp: m.mrp, rack: m.rack, stock: m.stock, qty: q, unit: "unit", rx_item_id: i.id }); }
  drawCart(); if (miss.length) toast("Short here: " + miss.join(", ") + ". The rest stays on the prescription for any branch.");
});
on("saveBill", async f => {
  if (!CART.length) return toast("Add medicines first.");
  const v = vals(f), pid = pidOf($("#bPat").value);
  const body = { ...v, patient_id: pid, visit_id: CART.some(l => l.rx_item_id) ? CART_VISIT : null, rx_admission_id: CART.some(l => l.rx_item_id) ? CART_ADM : null, items: CART.map(l => ({ medicine_id: l.medicine_id, qty: l.qty, unit: l.unit, rx_item_id: l.rx_item_id })), created_at: new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 16).replace("T", " ") };
  const r = await withOverride((ov, reason) => apiSafe("/api/bills", { ...body, override: ov, override_reason: reason }, "Bill"), "Safety warnings at the counter");
  if (!r) return;
  if (!r.queued) { toast(`Bill ${r.bill_no} saved · ${money(r.total)}`); CART = []; CART_VISIT = null; await RENDER.billing($("#view"), []); ACTIONS.viewBill({ dataset: { id: r.id } }); }
  else { CART = []; drawCart(); }
});
on("viewBill", async el => {
  const b = await api("/api/bills/" + el.dataset.id), box = $("#bView"); App.cache.bill = b; box.hidden = false;
  box.innerHTML = `<div class="card-h"><div><h2 class="mono">${b.bill_no}</h2><p>${b.created_at} · ${esc(b.customer)} ${b.patient_code} · ${b.pay_mode.toUpperCase()}${b.doctor_name ? " · Rx " + esc(b.doctor_name) : ""}</p></div><div class="row-actions"><button class="btn sm ghost" data-act="printBill">Print receipt</button><button class="btn sm ghost" data-act="pdfDl" data-p="bill/${b.id}">PDF</button></div></div>
    <form data-submit="billReturn">${tbl(["Item", "Batch / rack", "Qty", "Amount", "Return"], b.items.map(i => `<tr><td>${esc(i.name)} <span class="small muted">${i.schedule}</span></td><td class="small"><span class="mono">${esc(i.batch)}</span> <span class="rack sm">${esc(i.rack || "–")}</span><div class="muted">exp ${i.expiry.slice(0, 7)}</div></td><td class="num">${i.qty}${i.returned ? `<div class="small muted">ret ${i.returned}</div>` : ""}</td><td class="num">${money(i.net)}</td><td>${i.qty - i.returned ? `<input type="number" min="0" max="${i.qty - i.returned}" value="0" name="r${i.id}" style="width:64px">` : "–"}</td></tr>`).join(""))}
    <div class="totals"><div><span>Subtotal</span><b>${money(b.subtotal)}</b></div><div><span>Discount</span><b>− ${money(b.discount)}</b></div><div class="grand"><span>Total</span><b>${money(b.total)}</b></div><div><span>includes GST</span><b>${money(b.gst)}</b></div>${b.returned ? `<div><span>Refunded</span><b>${money(b.returned)}</b></div>` : ""}</div>
    ${can("billing") && b.branch_id === App.me.branch.id ? `<div class="fields"><div class="span2"><input name="reason" placeholder="Return reason"></div><div><button class="btn sm ghost">Process return</button></div></div>` : ""}</form>`;
});
on("billReturn", async f => {
  const v = vals(f), items = Object.keys(v).filter(k => /^r\d+$/.test(k) && +v[k] > 0).map(k => ({ bill_item_id: +k.slice(1), qty: +v[k] }));
  if (!items.length) return toast("Enter how many to return.");
  const r = await api(`/api/bills/${App.cache.bill.id}/return`, { items, reason: v.reason }); toast(`Refund ${money(r.refund)} · credit note ${r.credit_note}`); ACTIONS.viewBill({ dataset: { id: App.cache.bill.id } });
});
on("printBill", () => {
  const b = App.cache.bill; $("#printArea").classList.add("receipt");
  printHtml(`<div style="text-align:center"><b>${esc(b.branch)}</b><br>${esc(b.baddr || "")}<br>Ph ${esc(b.bphone || "")}<br>GSTIN ${esc(b.gstin || "-")} · DL ${esc(b.dl_no || "-")}</div><hr>
    <div>Bill ${b.bill_no} · ${b.created_at}<br>${esc(b.customer)} ${b.patient_code}${b.doctor_name ? `<br>Rx: ${esc(b.doctor_name)} ${esc(b.doctor_reg || "")}` : ""}</div><hr>
    <table>${b.items.map(i => `<tr><td>${esc(i.name)}<br><small>${esc(i.batch)} exp ${i.expiry.slice(0, 7)} · ${i.qty} x ${i.mrp.toFixed(2)}</small></td><td class="r">${i.net.toFixed(2)}</td></tr>`).join("")}</table><hr>
    <table><tr><td>Subtotal</td><td class="r">${b.subtotal.toFixed(2)}</td></tr><tr><td>Discount</td><td class="r">-${b.discount.toFixed(2)}</td></tr><tr><td><b>TOTAL</b></td><td class="r"><b>${b.total.toFixed(2)}</b></td></tr><tr><td>incl. GST</td><td class="r">${b.gst.toFixed(2)}</td></tr><tr><td>Paid by</td><td class="r">${b.pay_mode.toUpperCase()}</td></tr></table>
    <hr><div style="text-align:center">Cashier ${esc(b.cashier || "")} · Get well soon</div>`);
  setTimeout(() => $("#printArea").classList.remove("receipt"), 1500);
});
on("h1csv", () => download(`/api/files/h1.csv?from=${localDay().slice(0, 8)}01&to=${localDay()}`));

/* ================= stock ================= */
RENDER.stock = async (main, [pane]) => {
  await loadMeds(true);
  if (!App.me.branch) {
    const d = await api("/api/stock");
    main.innerHTML = card("Stock across all pharmacies", `Usable units · total value at cost ${money(d.value)} · red is below the reorder level`, tbl(["Medicine", ...d.branches, "Total"], d.rows.map(r => `<tr><td>${esc(r.name)}</td>${d.branches.map(b => { const q = r.per_branch[b]; return `<td class="num">${q < r.reorder_level ? `<b style="color:var(--crit)">${q}</b>` : q}</td>`; }).join("")}<td class="num">${r.total}</td></tr>`).join("")));
    return;
  }
  pane = pane || App.cache.stockPane || "overview"; App.cache.stockPane = pane;
  const panes = [["overview", "Overview"]].concat(can("stock") ? [["edit", "Edit stock & photos"]] : [], [["insights", "Reorder & expiry"], ["batches", "Batches & racks"]]).concat(can("stock") ? [["po", "Purchase orders"], ["grn", "Receive goods"], ["returns", "Supplier returns"], ["cold", "Fridge log"], ["count", "Stock count"], ["dues", "Supplier dues"], ["weekly", "Weekly summary"], ["master", "Medicine master"]] : []);
  main.innerHTML = subtabs(panes, pane, "stockTab") + `<div id="stockBody"><p class="empty">Loading…</p></div>`;
  await (STOCK[pane] || STOCK.overview)($("#stockBody"));
};
on("stockTab", el => go("stock", [el.dataset.k]));
const STOCK = {};
STOCK.overview = async el => {
  const sv = await api("/api/stock"); App.cache.sv = sv;
  const st = { out: "p-crit", low: "p-warn", ok: "p-ok" }, exp = sv.batches.filter(b => b.days_left < 0);
  el.innerHTML = `<div class="kpis">${kpi("Stock value", money(sv.batches.filter(b => b.days_left >= 0).reduce((a, b) => a + b.value, 0)), "usable, at cost")}${kpi("Out of stock", sv.summary.filter(s => s.status === "out").length, "medicines", "crit")}${kpi("Below reorder level", sv.summary.filter(s => s.status === "low").length, "medicines", "warn")}${kpi("Expired on shelf", money(exp.reduce((a, b) => a + b.value, 0)), exp.length + " batches", exp.length ? "crit" : "")}</div>
  ${card("Medicines", "Sales speed is the 30-day average", tbl(["Medicine", "Rack", "Usable", "Sells/day", "Days cover", "Status"], sv.summary.map(s => `<tr><td><b>${esc(s.name)}</b> <span class="small muted">${s.schedule} · pack ${s.pack_size}</span><div class="small muted">${esc(s.generic || "")}${s.expired ? ` · <span class="allergy">${s.expired} expired</span>` : ""}</div></td><td>${s.racks.map(r => `<span class="rack sm">${esc(r)}</span>`).join("")}</td><td class="num">${s.usable}</td><td class="num">${s.per_day}</td><td class="num">${s.days_cover ?? "–"}</td><td>${pill(s.status, st[s.status])}</td></tr>`).join("")))}`;
};
STOCK.insights = async el => {
  const sv = await api("/api/stock"), phs = App.me.branches.filter(b => b.kind.includes("pharmacy") && b.id !== App.me.branch.id);
  el.innerHTML = card("Reorder suggestions", "From sales speed and reorder levels", tbl(["Medicine", "Have", "Sells/day", "Order", "Why"], sv.reorder.map(r => `<tr><td><b>${esc(r.medicine)}</b></td><td class="num">${r.have}</td><td class="num">${r.per_day}</td><td class="num"><b>${r.order}</b></td><td class="small muted">${esc(r.why)}</td></tr>`).join(""), "Nothing to reorder."),
    can("stock") && sv.reorder.length ? `<button class="btn sm" data-act="poFromSuggest">Create purchase order</button>` : "") +
    card("Expiry rescue", "Stock that won't sell here before it expires", tbl(["Medicine", "Batch", "Days left", "Qty", "Suggestion", ""], sv.transfers.map(t_ => `<tr><td><b>${esc(t_.medicine)}</b></td><td class="mono">${esc(t_.batch || "")}</td><td class="num">${t_.days_left}</td><td class="num">${t_.qty}</td><td>${t_.to_branch ? `Move to <b>${esc(t_.to_name)}</b>` : "Return to supplier or run an offer"}<div class="small muted">${esc(t_.why)}</div></td><td>${t_.to_branch && can("stock_admin") ? `<button class="btn sm" data-act="transfer" data-b="${t_.batch_id}" data-to="${t_.to_branch}" data-q="${t_.qty}">Transfer</button>` : ""}</td></tr>`).join(""), "Nothing at risk."));
  App.cache.sv = sv;
};
STOCK.batches = async el => {
  const sv = await api("/api/stock"); App.cache.sv = sv;
  el.innerHTML = card("All batches", "Soonest expiry first", tbl(["Medicine", "Batch", "Rack", "Qty", "Expires", "MRP", ""], sv.batches.map(b => `<tr><td><b>${esc(b.medicine)}</b></td><td class="mono">${esc(b.batch || "")}</td>
    <td>${can("stock") ? `<input value="${esc(b.rack || "")}" data-change="setRack" data-id="${b.id}" class="mono" style="width:84px" aria-label="Rack">` : `<span class="rack sm">${esc(b.rack || "–")}</span>`}</td><td class="num">${b.qty}</td>
    <td>${pill(b.days_left < 0 ? "expired" : b.days_left + " d", b.days_left <= 30 ? "p-crit" : b.days_left <= 90 ? "p-warn" : "p-ok")} <span class="mono small">${b.effective_expiry}</span>${b.opened ? `<div class="small muted">opened ${b.opened}</div>` : ""}</td><td class="num">${money(b.mrp)}</td>
    <td class="row-actions">${can("stock") ? `<button class="btn sm ghost" data-act="writeOff" data-id="${b.id}" data-q="${b.qty}" data-x="${b.days_left < 0 ? 1 : 0}">Write off</button>` : ""}${can("stock_admin") && b.days_left >= 0 ? `<button class="btn sm ghost" data-act="transferAsk" data-id="${b.id}" data-q="${b.qty}">Transfer</button>` : ""}${can("stock") && b.form === "Syrup" && !b.opened ? `<button class="btn sm ghost" data-act="openBatch" data-id="${b.id}">Opened</button>` : ""}</td></tr>`).join("")));
};
on("setRack", async el => { await api("/api/batches/" + el.dataset.id, { rack: el.value }); toast("Rack updated"); });
on("openBatch", async el => { await api("/api/batches/" + el.dataset.id, { opened: localDay() }); toast("Marked opened. It now expires in 30 days."); go("stock", ["batches"]); });
on("writeOff", async el => {
  const v = await dialog("Write off stock", `<label>Quantity</label><input name="qty" type="number" min="1" max="${el.dataset.q}" value="${el.dataset.q}"><label>Reason</label><select name="reason"><option value="expired" ${el.dataset.x === "1" ? "selected" : ""}>Expired</option><option value="damaged">Damaged</option><option value="count_correction">Count correction</option></select><label>Note</label><input name="note">`, { ok: "Write off", danger: true });
  if (v) { await api("/api/writeoff", { ...v, batch_id: +el.dataset.id }); toast("Written off"); go("stock", ["batches"]); }
});
on("transfer", async el => {
  if (!await dialog("Transfer stock", `<p>Move <b>${el.dataset.q}</b> units to the other branch?</p>`, { ok: "Transfer" })) return;
  await api("/api/transfers", { batch_id: +el.dataset.b, to_branch: +el.dataset.to, qty: +el.dataset.q }); toast("Transferred"); go("stock", [App.cache.stockPane]);
});
on("transferAsk", async el => {
  const phs = App.me.branches.filter(b => b.kind.includes("pharmacy") && b.id !== App.me.branch.id);
  if (!phs.length) return toast("There is no other pharmacy branch.");
  const v = await dialog("Transfer to another branch", `<label>To</label><select name="to_branch">${phs.map(b => `<option value="${b.id}">${esc(b.name)}</option>`).join("")}</select><label>Quantity</label><input name="qty" type="number" min="1" max="${el.dataset.q}" value="${el.dataset.q}">`, { ok: "Transfer" });
  if (v) { await api("/api/transfers", { ...v, batch_id: +el.dataset.id }); toast("Transferred"); go("stock", ["batches"]); }
});
STOCK.po = async el => {
  const [pos, sups] = await Promise.all([api("/api/purchase-orders"), api("/api/suppliers")]); App.cache.sups = sups;
  el.innerHTML = card("Purchase orders", "Send to the supplier, then receive against the order", tbl(["PO", "Date", "Supplier", "Lines", "Status", ""], pos.map(p => `<tr><td class="mono">PO-${p.id}</td><td class="mono">${(p.created_at || "").slice(0, 10)}</td><td>${esc(p.supplier || "–")}</td><td class="small">${p.items.map(i => `${esc(i.name)} ${i.received}/${i.qty}`).join(", ")}</td><td>${pill(p.status, p.status === "received" ? "p-ok" : p.status === "cancelled" ? "p-plain" : "p-info")}</td>
    <td class="row-actions">${["sent", "partial", "draft"].includes(p.status) ? `<button class="btn sm" data-act="go" data-v="stock" data-p="grn/${p.id}">Receive</button>` : ""}${p.status === "draft" ? `<button class="btn sm ghost" data-act="poStatus" data-id="${p.id}" data-s="sent">Mark sent</button>` : ""}${["draft", "sent"].includes(p.status) ? `<button class="btn sm ghost" data-act="poStatus" data-id="${p.id}" data-s="cancelled">Cancel</button>` : ""}<button class="btn sm ghost" data-act="poPrint" data-id="${p.id}">Print</button></td></tr>`).join(""), "No purchase orders."),
    `<button class="btn sm" data-act="poFromSuggest">New from reorder suggestions</button>`);
  App.cache.pos = pos;
};
on("poStatus", async el => { await api(`/api/purchase-orders/${el.dataset.id}/status`, { status: el.dataset.s }); go("stock", ["po"]); });
on("poFromSuggest", async () => {
  const [sv, sups] = await Promise.all([api("/api/stock"), api("/api/suppliers")]);
  const v = await dialog("New purchase order", `<label>Supplier</label><select name="supplier_id">${sups.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select>` +
    tbl(["Medicine", "Have", "Order"], sv.reorder.map(r => `<tr><td>${esc(r.medicine)}</td><td class="num">${r.have}</td><td><input type="number" min="0" name="m${r.medicine_id}" value="${r.order}" style="width:90px"></td></tr>`).join("")) +
    `<label class="check"><input type="checkbox" name="send" checked> Mark as sent to the supplier</label>`, { ok: "Create PO", wide: true });
  if (!v) return;
  const items = Object.keys(v).filter(k => /^m\d+$/.test(k) && +v[k] > 0).map(k => ({ medicine_id: +k.slice(1), qty: +v[k] }));
  const r = await api("/api/purchase-orders", { supplier_id: v.supplier_id, send: v.send, items }); toast(`PO-${r.id} created`); go("stock", ["po"]);
});
on("poPrint", el => {
  const p = App.cache.pos.find(x => x.id === +el.dataset.id), b = App.me.branch;
  printHtml(`<div class="hdr"><div><h2>${esc(b.name)}</h2></div><div style="text-align:right"><b>PURCHASE ORDER PO-${p.id}</b><div>${p.created_at}</div></div></div><p>To: <b>${esc(p.supplier || "")}</b></p>
    <table><tr><th>Medicine</th><th>Pack</th><th class="r">Quantity (units)</th></tr>${p.items.map(i => `<tr><td>${esc(i.name)}</td><td>${i.pack_size}</td><td class="r">${i.qty}</td></tr>`).join("")}</table><br><p>Authorised signatory ____________</p>`);
});
STOCK.grn = async (el) => {
  const poId = +(App.params[1] || 0), sups = await api("/api/suppliers"), po = poId ? (await api("/api/purchase-orders")).find(p => p.id === poId) : null;
  const row = (it = {}) => `<tr><td><input name="med" list="medOpts" value="${esc(it.name || "")}" data-change="grnRack"></td><td><input name="batch"></td><td><input name="expiry" type="date"></td><td><select name="unit"><option value="unit">Units</option><option value="pack">Packs</option></select></td><td><input name="qty" type="number" min="1" value="${it.qty ? it.qty - it.received : ""}" style="width:80px"></td><td><input name="free" type="number" min="0" value="0" style="width:64px"></td><td><input name="cost" type="number" step=".01" style="width:84px"></td><td><input name="mrp" type="number" step=".01" style="width:84px"></td><td><input name="rack" style="width:76px"></td></tr>`;
  el.innerHTML = card(po ? `Receive goods against PO-${po.id}` : "Receive goods", "Expired batches and cost above MRP are rejected. Upload the supplier invoice in Documents; the AI reader can fill this for you.",
    `<form data-submit="grnSave" class="stack"><div class="fields"><div><label>Supplier</label><select name="supplier_id">${sups.map(s => `<option value="${s.id}" ${po && po.supplier_id === s.id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></div><div><label>Invoice no.</label><input name="invoice_no"></div><div><label>Pay supplier by</label><input name="due_date" type="date" title="Blank = 30 days from today"></div><div><label>New supplier</label><input name="new_sup" placeholder="Name"></div><div style="align-self:end"><button type="button" class="btn sm ghost" data-act="addSup">Add supplier</button></div></div>
    <input type="hidden" name="po_id" value="${po ? po.id : ""}"><div class="tbl"><table id="grnRows"><tr><th>Medicine</th><th>Batch</th><th>Expiry</th><th>Unit</th><th>Qty</th><th>Free</th><th>Cost ₹</th><th>MRP ₹</th><th>Rack</th></tr>${po ? po.items.filter(i => i.received < i.qty).map(row).join("") : row() + row() + row()}</table></div>
    <div class="btns"><button type="button" class="btn ghost" data-act="grnRow">Add line</button><button class="btn">Receive stock</button></div></form>`);
  App.cache.grnRow = row;
};
on("grnRow", () => $("#grnRows").insertAdjacentHTML("beforeend", App.cache.grnRow()));
on("grnRack", async el => { const m = medByName(el.value), tr = el.closest("tr"); if (m && !tr.querySelector("[name=rack]").value) { const s = await api("/api/stock/lookup?id=" + m.id); tr.querySelector("[name=rack]").value = (s.batches[0] || {}).rack || ""; tr.querySelector("[name=mrp]").value = (s.batches[0] || {}).mrp || ""; } });
on("addSup", async el => { const f = el.closest("form"), n = f.new_sup.value.trim(); if (!n) return; await api("/api/suppliers", { name: n }); toast("Supplier added"); go("stock", ["grn", ...(App.params.slice(1))]); });
on("grnSave", async f => {
  const lines = [];
  for (const tr of $$("#grnRows tr").slice(1)) { const v = vals(tr); if (!v.med) continue; const m = medByName(v.med); if (!m) return toast(`Unknown medicine "${v.med}". Add it in the medicine master first.`); lines.push({ ...v, medicine_id: m.id }); }
  if (!lines.length) return toast("Add at least one line.");
  const v = vals(f); delete v.med;
  const r = await api("/api/purchases", { supplier_id: v.supplier_id, invoice_no: v.invoice_no, due_date: v.due_date || null, po_id: v.po_id || null, lines }); toast(`Received. GRN${r.id} · ${money(r.total)}`); go("stock", ["batches"]);
});
STOCK.returns = async el => {
  const [rets, sv, sups] = await Promise.all([api("/api/supplier-returns"), api("/api/stock"), api("/api/suppliers")]);
  const cand = sv.batches.filter(b => b.days_left <= 60 && b.qty > 0);
  el.innerHTML = `<div class="g2">${card("Return to supplier", "Expired or near-expiry stock for credit", `<form data-submit="retSave" class="stack"><div class="fields"><div><label>Supplier</label><select name="supplier_id">${sups.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select></div><div><label>Reason</label><select name="reason"><option value="expired">Expired</option><option value="near_expiry">Near expiry</option><option value="damaged">Damaged</option></select></div></div>
    ${tbl(["Batch", "Days", "Qty", "Return"], cand.map(b => `<tr><td>${esc(b.medicine)} <span class="mono small">${esc(b.batch || "")}</span></td><td class="num">${b.days_left}</td><td class="num">${b.qty}</td><td><input type="number" min="0" max="${b.qty}" value="${b.days_left < 0 ? b.qty : 0}" name="b${b.id}" style="width:72px"></td></tr>`).join(""), "No expired or near-expiry stock.")}<div class="btns"><button class="btn">Create return</button></div></form>`)}
    ${card("Returns", "Record the supplier's credit note when it arrives", tbl(["Return", "Supplier", "Value", "Status", ""], rets.map(r => `<tr><td class="mono">SR${r.id}<div class="small muted">${(r.created_at || "").slice(0, 10)}</div></td><td>${esc(r.supplier || "")}</td><td class="num">${money(P2R(r.total_p))}</td><td>${r.status === "credited" ? pill("Credit " + r.credit_note_no, "p-ok") : pill("Waiting for credit", "p-warn")}</td><td>${r.status !== "credited" ? `<button class="btn sm ghost" data-act="retCredit" data-id="${r.id}">Credit note</button>` : ""}</td></tr>`).join("")))}</div>`;
};
on("retSave", async f => { const v = vals(f), items = Object.keys(v).filter(k => /^b\d+$/.test(k) && +v[k] > 0).map(k => ({ batch_id: +k.slice(1), qty: +v[k] })); if (!items.length) return toast("Enter quantities to return."); const r = await api("/api/supplier-returns", { supplier_id: v.supplier_id, reason: v.reason, items }); toast(`SR${r.id} created · ${money(r.total)} to be credited`); go("stock", ["returns"]); });
on("retCredit", async el => { const v = await dialog("Supplier credit note", `<label>Credit note number</label><input name="credit_note_no">`, { ok: "Save" }); if (v) { await api(`/api/supplier-returns/${el.dataset.id}/credit`, v); go("stock", ["returns"]); } });
STOCK.cold = async el => {
  const d = await api("/api/temp-logs");
  el.innerHTML = `<div class="g-main">${card("Fridge temperature log", `${d.today_count} reading(s) today · log at least twice a day · safe range 2–8 °C`, tbl(["When", "Fridge", "°C", "By", ""], d.logs.map(x => `<tr><td class="mono">${x.at}</td><td>${esc(x.fridge)}</td><td class="num"><b>${x.temp_c}</b></td><td>${esc(x.uname || "")}</td><td>${x.ok ? pill("OK", "p-ok") : pill("Out of range", "p-crit")} <span class="small muted">${esc(x.note || "")}</span></td></tr>`).join("")))}
    ${card("Record a reading", "", `<form data-submit="tempSave" class="stack"><input name="fridge" value="FRIDGE-1"><input name="temp_c" type="number" step=".1" placeholder="°C"><input name="note" placeholder="Note (optional)"><button class="btn">Save reading</button></form>`)}</div>`;
};
on("tempSave", async f => { const r = await api("/api/temp-logs", vals(f)); if (r.message) await dialog("Temperature out of range", alertRow("high", esc(r.message)), { ok: "Understood", cancel: "Close" }); else toast("Reading saved"); go("stock", ["cold"]); });
STOCK.count = async el => {
  const counts = await api("/api/stock-counts"), open = counts.find(c => c.status === "open");
  el.innerHTML = open ? card(`Stock count #${open.id}`, `Started ${open.created_at} · ${open.items.length} batches · sales during the count are allowed`, `<form data-submit="countSave">${tbl(["Rack", "Medicine", "Batch", "System", "Counted"], open.items.map(i => `<tr><td><span class="rack sm">${esc(i.rack || "–")}</span></td><td>${esc(i.name)}</td><td class="mono">${esc(i.batch || "")}</td><td class="num">${i.system_qty}</td><td><input type="number" min="0" name="c${i.id}" value="${i.counted_qty ?? ""}" style="width:84px"></td></tr>`).join(""))}
      <div class="btns"><button class="btn ghost" name="save">Save progress</button><button type="button" class="btn" data-act="countClose">Finish and adjust stock</button></div></form>`)
    : card("Stock count", "Count one rack at a time, or the whole pharmacy", `<form data-submit="countStart" class="fields"><div><label>Rack (blank = all)</label><input name="rack" placeholder="A1"></div><div style="align-self:end"><button class="btn">Start count</button></div></form>`) +
      card("Past counts", "", tbl(["#", "Started", "Closed", "Lines"], counts.map(c => `<tr><td>${c.id}</td><td class="mono">${c.created_at}</td><td class="mono">${c.closed_at || ""}</td><td>${c.items.length}</td></tr>`).join("")));
  App.cache.count = open;
};
on("countStart", async f => { const r = await api("/api/stock-counts", vals(f)); toast(`${r.lines} batches to count`); go("stock", ["count"]); });
const countItems = f => Object.entries(vals(f)).filter(([k, v]) => /^c\d+$/.test(k) && v !== "").map(([k, v]) => ({ id: +k.slice(1), counted: +v }));
on("countSave", async f => { await api(`/api/stock-counts/${App.cache.count.id}`, { items: countItems(f) }); toast("Progress saved"); });
on("countClose", async el => { const f = el.closest("form"); if (!await dialog("Finish the count?", "<p>Stock will be adjusted to the counted quantities. Lines left blank are not changed.</p>", { ok: "Adjust stock" })) return; const r = await api(`/api/stock-counts/${App.cache.count.id}`, { items: countItems(f), close: true }); toast(`${r.adjusted} batches adjusted · value ${money(r.value)}`); go("stock", ["count"]); });
STOCK.master = async el => {
  const meds = await api("/api/medicines?all=1"); App.cache.allMeds = meds;
  el.innerHTML = `<div class="g-form">${card("Medicine", "Dose limits power the prescribing checks", `<form data-submit="medSave" id="medForm" class="stack"><input type="hidden" name="id"><div class="fields">
    <div class="span2"><label>Brand name</label><input name="name" required></div><div class="span2"><label>Generic / salt</label><input name="generic"></div>
    <div><label>Form</label><select name="form">${["Tablet", "Capsule", "Syrup", "Injection", "Cream", "Drops", "Sachet", "Other"].map(x => `<option>${x}</option>`).join("")}</select></div>
    <div><label>Schedule</label><select name="schedule"><option>OTC</option><option>H</option><option>H1</option><option>X</option></select></div><div><label>GST %</label><select name="gst_pct"><option>5</option><option>12</option><option>18</option><option>0</option></select></div>
    <div><label>HSN</label><input name="hsn"></div><div><label>Pack size</label><input name="pack_size" type="number" min="1" value="10"></div><div><label>Reorder level</label><input name="reorder_level" type="number" value="50"></div>
    <div class="span2"><label>Barcode</label><input name="barcode"></div><div><label>Strength mg</label><input name="strength_mg" type="number" step="any"></div><div><label>Max mg/day</label><input name="max_daily_mg" type="number" step="any"></div><div><label>Child mg/kg/day</label><input name="ped_mg_per_kg_day" type="number" step="any"></div></div>
    <label class="check"><input type="checkbox" name="renal_caution"> Caution in kidney disease</label><label class="check"><input type="checkbox" name="pregnancy_avoid"> Avoid in pregnancy</label><label class="check"><input type="checkbox" name="cold_chain"> Keep at 2–8 °C</label>
    <div class="btns"><button class="btn">Save medicine</button><button type="button" class="btn ghost" data-act="medNew">New</button></div></form>`)}
    ${card("Medicines", `${meds.length} items`, `<input data-input="medFilter" placeholder="Filter…"><div id="medTbl"></div>`)}</div>`;
  ACTIONS.medFilter({ value: "" });
};
on("medFilter", el => { const q = el.value.toLowerCase(); $("#medTbl").innerHTML = tbl(["Name", "Sch.", "Pack", "Barcode", "Stock", ""], App.cache.allMeds.filter(m => !q || (m.name + m.generic + (m.barcode || "")).toLowerCase().includes(q)).map(m => `<tr><td><b>${esc(m.name)}</b>${m.active ? "" : " (inactive)"}<div class="small muted">${esc(m.generic || "")}</div></td><td>${m.schedule}</td><td>${m.pack_size}</td><td class="mono small">${esc(m.barcode || "")}</td><td class="num">${m.stock}</td><td><button class="btn sm ghost" data-act="medEdit" data-id="${m.id}">Edit</button></td></tr>`).join("")); });
on("medEdit", el => { const m = App.cache.allMeds.find(x => x.id === +el.dataset.id), f = $("#medForm"); for (const k in m) if (f[k]) { if (f[k].type === "checkbox") f[k].checked = !!m[k]; else f[k].value = m[k] ?? ""; } f.name.focus(); });
on("medNew", () => $("#medForm").reset());
on("medSave", async f => { await api("/api/medicines", vals(f)); toast("Saved"); App.cache.meds = null; go("stock", ["master"]); });
