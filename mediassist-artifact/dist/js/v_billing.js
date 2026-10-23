/* Hospital billing: invoices, dues, refunds, insurance claims, cash closing, service rates. */
"use strict";
const INV_ST = { paid: ["Paid", "p-ok"], partial: ["Part paid", "p-warn"], due: ["Due", "p-crit"], insurance: ["Insurance pending", "p-info"], cancelled: ["Cancelled", "p-plain"] };
const TPAS = ["Star Health", "HDFC ERGO", "ICICI Lombard", "Niva Bupa", "Care Health", "Medi Assist TPA", "Paramount TPA", "Ayushman Bharat (PM-JAY)", "CGHS", "ECHS"];
let INV = [];
RENDER.hbilling = async (main, [pane, id]) => {
  if (pane === "inv" && id) return invoiceView(main, +id);
  pane = pane || App.cache.hbPane || "new"; App.cache.hbPane = pane;
  main.innerHTML = subtabs([["new", "New invoice"], ["list", "Invoices & dues"], ["claims", "Insurance claims"], ["close", "Day closing"], ["rates", "Services & rates"]], pane, "hbTab") + `<div id="hbBody"></div>`;
  await (HB[pane] || HB.new)($("#hbBody"), id);
};
on("hbTab", el => go("hbilling", [el.dataset.k]));
const HB = {};
HB.new = async (el, pid) => {
  await loadServices(); const docs = await staff("doctor"); INV = [];
  let pre = ""; if (pid) { const p = await api("/api/patients/" + pid); pre = `${p.code} · ${p.name} · ${p.phone}`; }
  el.innerHTML = `<div class="g-form"><div class="card"><div class="card-h"><div><h2>Patient and services</h2><p>Unbilled consultations and lab tests appear when you pick the patient</p></div></div>
    <div class="fields">${patInput("patient", pre).replace("<input ", '<input id="hPat" data-change="hbPat" ')}<div><label>Doctor</label>${docSelect(docs, "doctor_id", "", "None")}</div></div>
    <div id="hUnb" style="margin-top:10px"></div>
    <div class="fields" style="margin-top:10px"><div class="span2"><label>Service</label><input id="hSvc" list="svcOpts"></div><div><label>Qty / days</label><input id="hQty" type="number" min="1" value="1"></div><div style="align-self:end"><button class="btn ghost" data-act="hAdd" style="width:100%;justify-content:center">Add</button></div></div>
    <div id="hLines" style="margin-top:12px"></div></div>
  <form class="card" data-submit="hSave"><h2 style="margin-bottom:10px">Payment</h2>
    <div class="fields"><div><label>Invoice discount ₹</label><input name="discount" type="number" min="0" value="0" data-input="hDraw"></div></div>
    <label class="check"><input type="checkbox" name="ins_on" data-change="hDraw"> Insurance / TPA cashless</label>
    <div id="hIns" hidden class="fields"><div><label>Insurer / TPA</label><select name="tpa">${TPAS.map(x => `<option>${x}</option>`).join("")}</select></div><div><label>Policy no.</label><input name="policy"></div><div><label>Pre-auth / claim no.</label><input name="claim_no"></div><div><label>Requested ₹</label><input name="requested" type="number" data-input="hDraw"></div><div><label>ICD-10</label><input name="icd" list="icdOpts" data-input="icdSearch"></div></div>
    <div class="totals" id="hTot"></div>
    <div class="fields"><div><label>Paid now ₹</label><input name="pay_now" type="number" min="0"></div><div><label>Mode</label><select name="mode"><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option></select></div><div><label>Reference</label><input name="ref"></div></div>
    <div style="margin-top:8px"><label>Note</label><input name="notes"></div><p class="small muted">Anything not paid becomes a due you can collect later.</p>
    <div class="btns"><button class="btn">Save invoice</button></div></form></div>`;
  if (pre) ACTIONS.hbPat($("#hPat"));
  hDraw();
};
function hDraw() {
  let sub = 0;
  $("#hLines").innerHTML = INV.length ? tbl(["Service", "Qty", "Rate", "Disc ₹", "Amount", ""], INV.map((l, i) => { const a = l.qty * l.rate - l.disc; sub += a; return `<tr><td><b>${esc(l.name)}</b><div class="small muted">${esc(l.cat || "")}${l.ref ? " · " + l.ref : ""}</div></td><td class="num">${l.qty}</td><td class="num">${money(l.rate)}</td><td><input type="number" min="0" value="${l.disc}" style="width:72px" data-change="hDisc" data-i="${i}"></td><td class="num">${money(a)}</td><td><button class="btn sm ghost" data-act="hRm" data-i="${i}">Remove</button></td></tr>`; }).join("")) : '<p class="empty">Add services or pick unbilled items.</p>';
  const f = $("form[data-submit=hSave]"); if (!f) return;
  const v = vals(f), disc = Math.min(sub, +v.discount || 0), total = sub - disc, ins = v.ins_on ? Math.min(total, +v.requested || total) : 0;
  $("#hIns").hidden = !v.ins_on;
  $("#hTot").innerHTML = `<div><span>Subtotal</span><b>${money(sub)}</b></div><div><span>Discount</span><b>− ${money(disc)}</b></div>${ins ? `<div><span>Insurance share (requested)</span><b>− ${money(ins)}</b></div>` : ""}<div class="grand"><span>Patient pays</span><b>${money(total - ins)}</b></div>`;
}
on("hDraw", () => hDraw());
on("hDisc", el => { INV[+el.dataset.i].disc = Math.max(0, +el.value || 0); hDraw(); });
on("hRm", el => { INV.splice(+el.dataset.i, 1); hDraw(); });
on("hAdd", () => { const s = svcByName($("#hSvc").value); if (!s) return toast("Choose a service from the list."); INV.push({ service_id: s.id, name: s.name, cat: s.cat, qty: +$("#hQty").value || 1, rate: P2R(s.rate_p), disc: 0 }); $("#hSvc").value = ""; $("#hQty").value = 1; hDraw(); });
on("hbPat", async el => {
  const pid = pidOf(el.value); if (!pid) return;
  const u = await api(`/api/patients/${pid}/unbilled`); App.cache.unb = u;
  const cons = svcByName("OPD consultation, general");
  $("#hUnb").innerHTML = (u.dues.length ? alertRow("", `<b>Previous dues:</b> ${u.dues.map(d => `<a href="#hbilling/inv/${d.id}">${d.inv_no}</a> ${money(d.due)}`).join(", ")}`) : "") +
    (u.credit_bills || []).map(cb => alertRow("", `<b>Pharmacy credit bill</b> ${cb.bill_no} · ${cb.date} · <b>${money(cb.due)}</b> <button class="btn sm" data-act="settleBill" data-id="${cb.bill_id}" data-no="${cb.bill_no}" data-amt="${cb.due}">Collect now</button>`)).join("") +
    u.visits.map(v => alertRow("info", `<b>Consultation</b> ${v.completed_at} · ${esc(v.dname || "")} · ${esc(v.diagnosis || "")} <button class="btn sm" data-act="hVisit" data-id="${v.id}" data-doc="${v.doctor_id || ""}">Add consultation fee</button>`)).join("") +
    (u.labs.length ? alertRow("info", `<b>Lab tests ordered, not yet billed:</b> ${[...new Set(u.labs.map(l => l.id))].map(id => `LAB${id}: ${u.labs.filter(l => l.id === id).map(l => esc(l.name)).join(" + ")}`).join(" · ")} <button class="btn sm" data-act="hLabs">Add exactly these tests</button><div class="small muted">The bill is checked against the doctor's order: nothing missing, nothing extra.</div>`) : "");
  App.cache.consSvc = cons;
});
on("hVisit", el => { const s = App.cache.consSvc; INV = INV.filter(l => l.cat !== "Consultation"); INV.unshift({ service_id: s.id, name: s.name, cat: s.cat, qty: 1, rate: P2R(s.rate_p), disc: 0 }); App.cache.hVisit = +el.dataset.id; const ds = $("form[data-submit=hSave]") && $("[name=doctor_id]"); if (ds && el.dataset.doc) ds.value = el.dataset.doc; hDraw(); });
on("hLabs", () => { App.cache.unb.labs.forEach(l => { if (!INV.some(x => x.ref === "LAB" + l.id && x.service_id === l.service_id)) INV.push({ service_id: l.service_id, name: "Lab: " + l.name, cat: "Laboratory", qty: 1, rate: P2R(l.rate_p), disc: 0, ref: "LAB" + l.id }); }); hDraw(); });
on("hSave", async f => {
  const v = vals(f), pid = pidOf($("#hPat").value); if (!pid) return toast("Pick the patient.");
  if (!INV.length) return toast("Add at least one service.");
  const body = { patient_id: pid, doctor_id: $("[name=doctor_id]").value || null, visit_id: App.cache.hVisit || null, discount: v.discount, pay_now: v.pay_now, mode: v.mode, ref: v.ref, notes: v.notes,
    items: INV.map(l => ({ service_id: l.service_id, qty: l.qty, rate: l.rate, disc: l.disc, ref: l.ref })), insurance: v.ins_on ? { tpa: v.tpa, policy: v.policy, claim_no: v.claim_no, requested: v.requested, icd: v.icd } : null };
  const r = await api("/api/invoices", body); INV = []; App.cache.hVisit = null; toast(`Invoice ${r.inv_no} saved · ${INV_ST[r.status][0]}`); go("hbilling", ["inv", r.id]);
});
HB.list = async el => {
  const flt = App.cache.invFlt || "open", q = App.cache.invQ || "";
  const list = await api(`/api/invoices?filter=${flt}&q=${encodeURIComponent(q)}`);
  el.innerHTML = card("Invoices", `${list.length} shown · outstanding ${money(list.reduce((a, i) => a + i.due, 0))}`,
    `<input data-input="invQ" value="${esc(q)}" placeholder="Search name, phone or invoice no.">${subtabs([["open", "Open"], ["due", "Patient dues"], ["insurance", "Insurance pending"], ["paid", "Paid"], ["all", "All"]], flt, "invFlt")}` +
    tbl(["Invoice", "Patient", "Total", "Paid", "Due", "Status"], list.map(i => `<tr class="click" data-act="go" data-v="hbilling" data-p="inv/${i.id}"><td class="mono">${i.inv_no}<div class="small muted">${i.created_at}</div></td><td>${esc(i.pname)} <span class="small muted">${i.code}</span></td><td class="num">${money(i.total)}</td><td class="num">${money(i.paid)}</td><td class="num">${i.due ? `<b>${money(i.due)}</b>` : "–"}</td><td>${pill(...INV_ST[i.status])}</td></tr>`).join(""), "No invoices here."));
};
on("invFlt", el => { App.cache.invFlt = el.dataset.k; go("hbilling", ["list"]); });
on("invQ", debounce(el => { App.cache.invQ = el.value; HB.list($("#hbBody")); }, 350));
async function invoiceView(main, id) {
  const i = await api("/api/invoices/" + id); App.cache.inv = i;
  const isMgr = ["owner", "manager"].includes(App.me.role), open = !i.cancelled_at;
  main.innerHTML = `<div class="g-main"><div class="card"><div class="rx-h"><div><b>${esc(i.bname)}</b><div class="small muted">${esc(i.baddr || "")} · GSTIN ${esc(i.gstin || "–")} · Healthcare services are GST-exempt</div></div><div style="text-align:right"><b class="mono">${i.inv_no}</b><div class="small muted">${i.created_at}</div>${pill(...INV_ST[i.status])}</div></div>
    <p class="small"><b>${esc(i.pname)}</b> · ${i.code} · ${i.age ?? "?"} yrs · <span class="mono">${esc(i.phone)}</span>${i.abha ? ` · ABHA ${esc(i.abha)}` : ""}${i.dname ? ` · ${esc(i.dname)}` : ""} · billed by ${esc(i.cashier || "")}</p>
    ${tbl(["Service", "Qty", "Rate", "Disc.", "Amount"], i.items.map(x => `<tr><td>${esc(x.name)}<div class="small muted">${esc(x.cat || "")}</div></td><td class="num">${x.qty}</td><td class="num">${money(P2R(x.rate_p))}</td><td class="num">${x.disc_p ? money(P2R(x.disc_p)) : "–"}</td><td class="num">${money(P2R(x.amount_p))}</td></tr>`).join(""))}
    <div class="totals"><div><span>Subtotal</span><b>${money(P2R(i.sub_p))}</b></div>${i.discount_p ? `<div><span>Discount</span><b>− ${money(P2R(i.discount_p))}</b></div>` : ""}${i.refunded_p ? `<div><span>Refunds issued (credit notes)</span><b>${money(P2R(i.refunded_p))}</b></div>` : ""}<div class="grand"><span>Total</span><b>${money(P2R(i.total_p))}</b></div><div><span>Paid</span><b>${money(P2R(i.paid_p))}</b></div><div><span>Due</span><b style="color:${i.due_p ? "var(--crit)" : "inherit"}">${money(P2R(i.due_p))}</b></div>${i.insurance_p ? `<div><span>of which insurance</span><b>${money(P2R(i.insurance_p))}</b></div>` : ""}</div>
    <h3>Payments</h3>${tbl(["When", "Mode", "Ref.", "By", "Amount"], i.payments.map(p => `<tr><td class="mono">${p.at}</td><td>${p.kind === "refund" ? "Refund" : p.mode}</td><td class="mono small">${esc(p.ref || "")}</td><td>${esc(p.uname || "")}</td><td class="num">${money(P2R(p.amount_p))}</td></tr>`).join(""), "No payments yet.")}
    <div class="btns"><button class="btn ghost" data-act="invPrint">Print invoice</button><button class="btn ghost" data-act="pdfDl" data-p="invoice/${i.id}">PDF</button><button class="btn ghost" data-act="go" data-v="hbilling" data-p="list">Back</button></div></div>
  <div class="stack">${open && i.excess_p ? card("Excess paid", `The patient paid ${money(P2R(i.excess_p))} more than the bill (usually an unused deposit)`, isMgr ? `<button class="btn" data-act="refundExcess" data-a="${P2R(i.excess_p)}">Refund ${money(P2R(i.excess_p))}</button>` : '<p class="small">Ask a manager to refund it.</p>') : ""}
    ${open && i.patient_due_p ? card("Collect payment", `Patient owes ${money(P2R(i.patient_due_p))}`, `<form data-submit="invPay" class="stack"><input name="amount" type="number" min="1" step=".01" value="${P2R(i.patient_due_p)}"><select name="mode"><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option></select><input name="ref" placeholder="UPI / card reference"><button class="btn">Receive</button></form>`) : ""}
    ${i.claims.map(cl => card(`Claim · ${esc(cl.tpa)}`, `${esc(cl.policy || "")} ${cl.claim_no ? "· " + esc(cl.claim_no) : ""} · requested ${money(P2R(cl.requested_p))}${cl.approved_p ? ` · approved ${money(P2R(cl.approved_p))}` : ""}${cl.settled_p ? ` · settled ${money(P2R(cl.settled_p))}` : ""}`,
      `<div class="timeline">${cl.events.map(e => `<div class="tl"><div class="when">${e.at} · ${esc(e.uname || "")}</div><b>${e.status}</b> ${esc(e.note || "")}</div>`).join("")}</div>${["preauth", "query", "approved", "rejected"].includes(cl.status) ? `<button class="btn sm" data-act="claimMove" data-id="${cl.id}" data-s="${cl.status}">Update claim</button>` : pill(cl.status, "p-ok")}`)).join("")}
    ${open && !i.claims.some(c => ["preauth", "query", "approved"].includes(c.status)) && i.due_p ? card("Insurance", "Send this bill to an insurer or TPA", `<button class="btn ghost" data-act="claimOpen">Start a claim</button>`) : ""}
    ${open && i.paid_p && isMgr ? card("Refund", "Issues a credit note and reduces the invoice", `<form data-submit="invRefund" class="stack"><input name="amount" type="number" min="1" step=".01" placeholder="Amount ₹"><select name="mode"><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option></select><input name="reason" placeholder="Reason"><button class="btn ghost">Refund</button></form>`) : ""}
    ${open && !i.paid_p ? `<button class="btn ghost" data-act="invCancel" style="color:var(--crit);border-color:var(--crit)">Cancel invoice</button>` : ""}
    ${can("documents") ? `<button class="btn ghost" data-act="go" data-v="docs" data-p="up/invoice/${i.id}">Attach a document</button>` : ""}</div></div>`;
}
const reInv = () => go("hbilling", ["inv", App.cache.inv.id]);
on("invPay", async f => { const r = await api(`/api/invoices/${App.cache.inv.id}/pay`, vals(f)); toast(`Received · ${INV_ST[r.status][0]}`); reInv(); });
on("refundExcess", async el => { const v = await dialog("Refund the excess", `<p>Pay back <b>${money(+el.dataset.a)}</b> to the patient.</p><label>Mode</label><select name="mode"><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option></select>`, { ok: "Refund" }); if (!v) return; const r = await api(`/api/invoices/${App.cache.inv.id}/refund`, { ...v, amount: el.dataset.a, reason: "Excess deposit returned", excess: true }); toast(`Refunded · credit note ${r.credit_note}`); reInv(); });
on("invRefund", async f => { if (!await dialog("Issue refund?", "<p>A credit note will be created and the invoice total reduced.</p>", { ok: "Refund", danger: true })) return; const r = await api(`/api/invoices/${App.cache.inv.id}/refund`, vals(f)); toast(`Credit note ${r.credit_note}`); reInv(); });
on("invCancel", async () => { const v = await dialog("Cancel invoice", `<label>Reason</label><input name="reason" placeholder="e.g. billed to wrong patient">`, { ok: "Cancel invoice", danger: true, cancel: "Keep" }); if (v) { await api(`/api/invoices/${App.cache.inv.id}/cancel`, v); reInv(); } });
on("claimOpen", async () => {
  const i = App.cache.inv;
  const v = await dialog("Start an insurance claim", `<label>Insurer / TPA</label><select name="tpa">${TPAS.map(x => `<option>${x}</option>`).join("")}</select><label>Policy no.</label><input name="policy"><label>Pre-auth / claim no.</label><input name="claim_no"><label>Amount requested ₹</label><input name="requested" type="number" value="${P2R(i.due_p)}"><label>ICD-10</label><input name="icd" list="icdOpts" data-input="icdSearch"><label>Notes</label><input name="notes">`, { ok: "Submit pre-auth" });
  if (v) { await api(`/api/invoices/${i.id}/claim`, v); toast("Claim started"); reInv(); }
});
const NEXT = { preauth: [["query", "Insurer raised a query"], ["approved", "Approved"], ["rejected", "Rejected"]], query: [["preauth", "Query answered, resubmitted"], ["approved", "Approved"], ["rejected", "Rejected"]], approved: [["settled", "Payment received (settled)"], ["query", "Query raised"], ["rejected", "Rejected"]], rejected: [["query", "Appeal / resubmit"]] };
on("claimMove", async el => {
  const v = await dialog("Update claim", `<label>New status</label><select name="status">${NEXT[el.dataset.s].map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select><label>Approved amount ₹ (when approving)</label><input name="approved" type="number" step=".01"><label>Amount received ₹ (when settling)</label><input name="settled" type="number" step=".01"><label>Claim number</label><input name="claim_no"><label>Note</label><input name="note">`, { ok: "Update" });
  if (v) { await api(`/api/claims/${el.dataset.id}`, v); toast("Claim updated"); if (App.view === "hbilling" && App.params[0] === "inv") reInv(); else go("hbilling", ["claims"]); }
});
on("invPrint", () => {
  const i = App.cache.inv;
  printHtml(`<div class="hdr"><div><h2>${esc(i.bname)}</h2><div>${esc(i.baddr || "")} · ${esc(i.bphone || "")}<br>GSTIN ${esc(i.gstin || "–")}</div></div><div style="text-align:right"><b>${i.kind === "ipd" ? "INPATIENT BILL" : "INVOICE"}</b><div>${i.inv_no}</div><div>${i.created_at}</div></div></div>
    <p><b>${esc(i.pname)}</b> · ${i.code} · ${i.age ?? "?"} yrs${i.dname ? ` · ${esc(i.dname)}` : ""}</p>
    <table><tr><th>Service</th><th class="r">Qty</th><th class="r">Rate</th><th class="r">Amount</th></tr>${i.items.map(x => `<tr><td>${esc(x.name)}</td><td class="r">${x.qty}</td><td class="r">${P2R(x.rate_p).toFixed(2)}</td><td class="r">${P2R(x.amount_p).toFixed(2)}</td></tr>`).join("")}</table>
    <p class="r">Subtotal ${money(P2R(i.sub_p))}${i.discount_p ? ` · Discount ${money(P2R(i.discount_p))}` : ""}<br><b>Total ${money(P2R(i.total_p))}</b> · Paid ${money(P2R(i.paid_p))} · Due ${money(P2R(i.due_p))}</p>
    <p class="small">Healthcare services by a clinical establishment are exempt from GST.</p><br><p style="text-align:right">Authorised signatory ____________</p>`);
});
HB.claims = async el => {
  const list = await api("/api/claims?status=all");
  const cols = [["preauth", "Pre-auth sent"], ["query", "Query"], ["approved", "Approved"], ["settled", "Settled"], ["rejected", "Rejected"]];
  el.innerHTML = `<div class="kpis">${kpi("Open claims", list.filter(c => ["preauth", "query", "approved"].includes(c.status)).length, "")}${kpi("Waiting over 7 days", list.filter(c => ["preauth", "query"].includes(c.status) && c.age_days > 7).length, "chase the insurer", "warn")}${kpi("Approved, not received", money(P2R(list.filter(c => c.status === "approved").reduce((a, c) => a + c.approved_p, 0))), "")}${kpi("Rejected", list.filter(c => c.status === "rejected").length, "", "crit")}</div>
  <div class="claimcol">${cols.map(([k, l]) => `<div class="col"><div class="col-h"><b>${l}</b><span class="small muted">${list.filter(c => c.status === k).length}</span></div>${list.filter(c => c.status === k).map(c => `<div class="claim" data-act="go" data-v="hbilling" data-p="inv/${c.invoice_id}"><b>${esc(c.pname)}</b><div class="small muted">${esc(c.tpa)} · ${esc(c.inv_no || "")}</div><div class="small">${money(P2R(c.approved_p || c.requested_p))} · ${c.age_days} days</div></div>`).join("") || '<p class="empty">None</p>'}</div>`).join("")}</div>`;
};
HB.close = async el => {
  const day = App.cache.closeDay || localDay(), d = await api("/api/closing?date=" + day), cl = d.closing;
  el.innerHTML = `<div class="kpis">${kpi("Cash expected in drawer", money(d.expected_cash), "after cash refunds")}${kpi("UPI", money(d.by_mode.upi || 0))}${kpi("Card", money(d.by_mode.card || 0))}${kpi("Insurance", money(d.by_mode.insurance || 0))}</div>
  <div class="g-main">${card("Receipts", `Hospital and pharmacy at ${esc(App.me.branch.name)}`, tbl(["Time", "Source", "Ref.", "From", "Mode", "Amount"], d.receipts.map(r => `<tr><td class="mono">${r.at.slice(11)}</td><td>${r.src}</td><td class="mono small">${esc(r.ref || "")}</td><td>${esc(r.who || "")}</td><td>${r.mode}</td><td class="num">${r.amount < 0 ? `<span style="color:var(--crit)">${money(r.amount)}</span>` : money(r.amount)}</td></tr>`).join(""), "No receipts."), `<input type="date" value="${day}" data-change="closeDay" style="width:auto">`)}
  <div class="stack">${card("Close the cash drawer", cl ? `Closed by ${esc(cl.uname)} at ${cl.at.slice(11)}: counted ${money(P2R(cl.counted_p))}, ${cl.diff_p ? (cl.diff_p > 0 ? "excess " : "short ") + money(Math.abs(P2R(cl.diff_p))) : "matched"}` : "Count the cash and enter it",
    `<form data-submit="closeSave" class="stack"><input name="counted" type="number" step=".01" placeholder="${d.expected_cash}"><input name="note" placeholder="Note"><button class="btn">${cl ? "Close again" : "Close day"}</button></form>`)}
    ${card("By staff", "", Object.entries(d.by_user).map(([u, a]) => `<div class="totrow"><span>${esc(u)}</span><b>${money(a)}</b></div>`).join("") || '<p class="empty">Nobody collected money.</p>')}</div></div>`;
};
on("closeDay", el => { App.cache.closeDay = el.value; HB.close($("#hbBody")); });
on("closeSave", async f => { const r = await api("/api/closing", { ...vals(f), date: App.cache.closeDay || localDay() }); toast(r.diff ? `Closed with ${r.diff > 0 ? "excess" : "shortage"} of ${money(Math.abs(r.diff))}` : "Closed. Cash matches."); HB.close($("#hbBody")); });
HB.rates = async el => {
  const s = await api("/api/services?all=1"), ed = can("stock_admin");
  el.innerHTML = card("Services and rates", "Healthcare services are GST-exempt; room rent above ₹5,000/day may attract GST", (ed ? `<form data-submit="svcSave" class="fields" style="margin-bottom:12px"><input type="hidden" name="id"><div class="span2"><label>Service</label><input name="name"></div><div><label>Category</label><select name="cat">${["Consultation", "Procedure", "Laboratory", "Imaging", "Diagnostics", "Inpatient", "Package", "Admin", "Other"].map(x => `<option>${x}</option>`).join("")}</select></div><div><label>Rate ₹</label><input name="rate" type="number" step=".01"></div><div><label>GST %</label><select name="gst_pct"><option>0</option><option>5</option><option>12</option><option>18</option></select></div><div style="align-self:end"><button class="btn sm">Save</button></div></form>` : "") +
    tbl(["Service", "Category", "Rate", "GST", ""], s.map(x => `<tr><td>${esc(x.name)}${x.active ? "" : " (hidden)"}</td><td>${esc(x.cat)}</td><td class="num">${money(P2R(x.rate_p))}</td><td class="num">${x.gst_pct}%</td><td>${ed ? `<button class="btn sm ghost" data-act="svcEdit" data-j='${esc(JSON.stringify(x))}'>Edit</button>` : ""}</td></tr>`).join("")));
};
on("svcEdit", el => { const x = JSON.parse(el.dataset.j), f = $("form[data-submit=svcSave]"); f.id.value = x.id; f.name.value = x.name; f.cat.value = x.cat; f.rate.value = P2R(x.rate_p); f.gst_pct.value = x.gst_pct; f.name.focus(); });
on("svcSave", async f => { await api("/api/services", vals(f)); toast("Saved"); App.cache.services = null; go("hbilling", ["rates"]); });
