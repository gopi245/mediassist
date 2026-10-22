/* Upload from the phone (QR), supplier dues, and the weekly pharmacy summary. */
"use strict";

/* ---------- phone upload ---------- */
let PHONE = null;
/* Show a QR code; each photo the phone sends is passed to onDoc(doc) as it arrives. */
async function phoneUpload(purpose, links, onDoc, { once = false } = {}) {
  const r = await api("/api/upload-links", { purpose, ...links });
  const qr = qrcode(0, "M"); qr.addData(r.url); qr.make();
  PHONE = { token: r.token, seen: new Set(), onDoc, once, timer: null };
  const dialog_ = dialog("Use your phone camera", `<div class="qr-box"><div class="qr">${qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true })}</div>
    <div class="stack" style="flex:1;min-width:200px"><p><b>1.</b> Open the camera on your phone and point it at the code.<br><b>2.</b> Tap the link, then take the photo.<br><b>3.</b> It appears here by itself.</p>
    <p class="small muted">For: ${esc(r.label)}. The code works for 15 minutes, up to 10 photos.</p>
    ${r.local_only ? alertRow("", "This computer opened MediAssist as <b>localhost</b>, which a phone can't reach. Open MediAssist on this computer using its network address (the one shown when the server starts), or set the Public address in Admin > Settings.") : ""}
    <div id="phoneStatus" class="small">Waiting for the phone…</div></div></div>`, { ok: "", cancel: "Close" });
  const closed = dialog_; PHONE.timer = setInterval(phonePoll, 2000);
  await closed; clearInterval(PHONE && PHONE.timer); const got = PHONE ? [...PHONE.seen] : []; PHONE = null;
  return got;
}
async function phonePoll() {
  const P_ = PHONE; if (!P_) return;
  let s; try { s = await api("/api/upload-links/" + P_.token); } catch (e) { return; }
  if (PHONE !== P_) return;
  const fresh = s.docs.filter(d => !P_.seen.has(d.id)); fresh.forEach(d => P_.seen.add(d.id));
  const st = $("#phoneStatus");
  if (st) st.innerHTML = s.expired ? "This code has expired. Close and make a new one." : P_.seen.size ? `<b>${P_.seen.size} received.</b> Take another, or close.` : "Waiting for the phone…";
  for (const d of fresh) await P_.onDoc(d);
  if (s.expired || (P_.once && fresh.length)) { clearInterval(P_.timer); if (P_.once && fresh.length) $("#mCancel").click(); }
}
/* A document the phone sent, as a File (for the stock photo reader). */
async function docAsFile(d) { const r = await api(`/api/documents/${d.id}/file`, undefined, { raw: true }); const b = await r.blob(); return new File([b], d.filename || "phone-photo.jpg", { type: d.mime || b.type }); }
on("phoneStock", () => phoneUpload("stock", {}, async d => { await pickStockPhoto(await docAsFile(d), d.id); }, { once: true }));
on("phoneDoc", async () => {
  const got = await phoneUpload("doc", UP && UP.link && UP.link.patient_id ? { patient_id: UP.link.patient_id } : {}, () => toast("Photo received from the phone"));
  if (got.length) { toast(got.length > 1 ? `${got.length} photos received. Link each one to the patient.` : "Photo received. Link it to the patient."); go("docs", ["d", got[got.length - 1]]); }
});

/* ---------- supplier dues ---------- */
STOCK.dues = async el => {
  const d = await api("/api/supplier-dues");
  el.innerHTML = `<div class="kpis">${kpi("Overdue", money(d.overdue), "past the due date", d.overdue ? "crit" : "")}${kpi("Due this week", money(d.this_week), "next 7 days, incl. overdue", d.this_week ? "warn" : "")}${kpi("All pending", money(d.total), d.count + " supplier bills")}</div>
    ${card("Supplier bills to pay", "From goods received. Due date is 30 days after receiving unless set on the bill.", tbl(["Supplier", "Bill", "Received", "Due", "Amount", "Paid", "Balance", ""],
      d.rows.map(x => `<tr><td><b>${esc(x.supplier)}</b></td><td class="mono small">${esc(x.invoice_no || "–")}<div class="muted">${x.grn}</div></td><td class="mono small">${x.date}</td>
      <td>${can("stock_admin") ? `<input type="date" value="${x.due_date}" data-change="dueSet" data-id="${x.id}" aria-label="Due date">` : `<span class="mono">${x.due_date}</span>`}<div>${x.days < 0 ? pill(-x.days + " days late", "p-crit") : x.days <= 7 ? pill(x.days ? "in " + x.days + " days" : "today", "p-warn") : ""}</div></td>
      <td class="num">${money(x.amount)}</td><td class="num">${money(x.paid)}</td><td class="num"><b>${money(x.due)}</b></td>
      <td>${can("stock_admin") ? `<button class="btn sm" data-act="supPay" data-id="${x.id}" data-due="${x.due}" data-sup="${esc(x.supplier)}">Record payment</button>` : ""}</td></tr>`).join(""), "Nothing owed to suppliers."))}
    ${d.payments.length ? card("Recent payments", "", tbl(["When", "Supplier", "Amount", "How", "By"], d.payments.map(p => `<tr><td class="mono small">${p.at}</td><td>${esc(p.supplier || "")}</td><td class="num">${money(P2R(p.amount_p))}</td><td>${esc(p.mode)} <span class="mono small">${esc(p.ref || "")}</span></td><td>${esc(p.uname || "")}</td></tr>`).join(""))) : ""}`;
};
on("dueSet", async el => { await api(`/api/purchases/${el.dataset.id}/due`, { due_date: el.value }); toast("Due date changed"); go("stock", ["dues"]); });
on("supPay", async el => {
  const v = await dialog(`Pay ${el.dataset.sup}`, `<p>Balance <b>${money(+el.dataset.due)}</b></p><div class="fields"><div><label>Amount ₹</label><input name="amount" type="number" step=".01" min="0.01" max="${el.dataset.due}" value="${el.dataset.due}"></div>
    <div><label>Paid by</label><select name="mode"><option value="bank">Bank transfer</option><option value="upi">UPI</option><option value="cheque">Cheque</option><option value="cash">Cash</option></select></div>
    <div class="span2"><label>UTR / cheque no.</label><input name="ref"></div></div>`, { ok: "Save payment" });
  if (!v) return;
  const r = await api(`/api/purchases/${el.dataset.id}/pay`, v); toast(r.due ? `Saved. ${money(r.due)} still due.` : "Saved. Bill fully paid."); go("stock", ["dues"]);
});

/* ---------- weekly pharmacy summary ---------- */
STOCK.weekly = async el => {
  const w = await api("/api/stock/weekly"), e = w.expiring, n = w.non_moving, s = w.supplier_dues;
  el.innerHTML = `<div class="kpis">${kpi("Expiring in 6 months", money(e.value), `${e.batches} batches · ${e.this_week} this week`, e.this_week ? "warn" : "")}${kpi("Not sold in 30 days", money(n.value), n.items + " medicines", n.items ? "warn" : "")}
      ${kpi("Below reorder level", w.low_stock.items, "medicines", w.low_stock.items ? "warn" : "")}${kpi("Supplier bills this week", money(s.this_week), `${s.this_week_bills} bills${s.overdue_bills ? ` · ${s.overdue_bills} overdue` : ""}`, s.overdue_bills ? "crit" : "")}</div>
    ${w.expired_on_shelf.batches ? alertRow("high", `<b>${w.expired_on_shelf.batches} expired batches</b> (${money(w.expired_on_shelf.value)}) are still on the shelf. Write them off or return them to the supplier.`) : ""}
    <div class="g2">${card("Expiring soonest", "Sell first, move to another branch, or return", tbl(["Medicine", "Batch", "Expiry", "Qty", "Value"], e.top.map(x => `<tr><td>${esc(x.medicine)}</td><td class="mono small">${esc(x.batch || "")}</td><td class="mono">${x.expiry}</td><td class="num">${x.qty}</td><td class="num">${money(x.value)}</td></tr>`).join(""), "Nothing expiring in 6 months."))}
      ${card("Not moving", "In stock over 30 days with no sale here", tbl(["Medicine", "Qty", "Value"], n.top.map(x => `<tr><td>${esc(x.medicine)}</td><td class="num">${x.qty}</td><td class="num">${money(x.value)}</td></tr>`).join(""), "Everything is selling."))}</div>
    ${card("Message that goes out", `Sent every week to the branch report number and the owner${can("stock_admin") ? "" : ". Ask a manager to send it now"}.`, `<pre class="msg-pre">${esc(w.text)}</pre>${can("stock_admin") ? `<div class="btns"><button class="btn" data-act="weeklySend">Send now</button></div>` : ""}`)}`;
};
on("weeklySend", async el => {
  const r = await withBusy(el, () => api("/api/stock/weekly/send", {}));
  if (!r.sent.length) return toast("No report number or email set. Add one for this branch in Admin > Branches, or the owner's in Settings.");
  const ok = r.sent.filter(x => x.ok).length; toast(ok ? `Sent to ${ok} recipient${ok > 1 ? "s" : ""}` : `Not sent: ${r.sent[0].detail}`);
});
