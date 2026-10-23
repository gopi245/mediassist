/* Accounts: profit and loss, expenses, doctor payouts, GST, Tally export. */
"use strict";
RENDER.accounts = async (main, [pane]) => {
  pane = pane || App.cache.accPane || "pnl"; App.cache.accPane = pane;
  const period = App.cache.period || localDay().slice(0, 7);
  main.innerHTML = `<div class="row-actions" style="margin-bottom:12px;align-items:center"><label style="margin:0">Month</label><input type="month" value="${period}" data-change="accPeriod" style="width:auto"></div>` +
    subtabs([["pnl", "Profit and loss"], ["exp", "Expenses"], ["pay", "Doctor payouts"], ["gst", "GST"], ["tally", "Tally export"]], pane, "accTab") + `<div id="accBody"></div>`;
  await ACC[pane]($("#accBody"), period);
};
on("accTab", el => go("accounts", [el.dataset.k]));
on("accPeriod", el => { App.cache.period = el.value; go("accounts", [App.cache.accPane]); });
const ACC = {};
ACC.pnl = async (el, period) => {
  const d = await api("/api/pnl?period=" + period), t_ = d.total;
  el.innerHTML = `<div class="kpis">${kpi("Revenue", money(t_.revenue), "hospital + pharmacy (excl. GST)")}${kpi("Costs", money(t_.cogs + t_.stock_writeoffs + t_.expenses_total), "medicines sold, write-offs, expenses")}${kpi("Profit", money(t_.profit), t_.margin != null ? `${t_.margin}% margin` : "", t_.profit < 0 ? "crit" : "")}${kpi("GST collected", money(t_.pharmacy_gst), "pharmacy sales")}</div>
  ${card("By branch", `${d.start} to ${d.end}`, tbl(["Branch", "Hospital", "Pharmacy", "Medicine cost", "Write-offs", "Expenses", "Profit", "Margin"], d.branches.map(b => `<tr><td><span class="code">${b.code}</span> ${esc(b.branch)}</td><td class="num">${money(b.hospital)}</td><td class="num">${money(b.pharmacy_net_of_gst)}</td><td class="num">${money(b.cogs)}</td><td class="num">${money(b.stock_writeoffs)}</td><td class="num">${money(b.expenses_total)}</td><td class="num"><b style="color:${b.profit < 0 ? "var(--crit)" : "inherit"}">${money(b.profit)}</b></td><td class="num">${b.margin ?? "–"}%</td></tr>`).join("")))}
  ${d.branches.length === 1 ? card("Expenses by category", "", bars(Object.entries(d.branches[0].expenses), Math.max(1, ...Object.values(d.branches[0].expenses)))) : ""}`;
};
ACC.exp = async (el, period) => {
  const d = await api("/api/expenses?period=" + period);
  el.innerHTML = `<div class="g-form">${App.me.branch ? card("Add an expense", "", `<form data-submit="expSave" class="stack"><div class="fields"><div><label>Category</label><select name="category">${d.categories.map(x => `<option>${x}</option>`).join("")}</select></div><div><label>Amount ₹</label><input name="amount" type="number" step=".01"></div><div><label>Date</label><input name="day" type="date" value="${localDay()}"></div><div><label>Paid by</label><select name="mode"><option value="cash">Cash</option><option value="bank">Bank</option><option value="upi">UPI</option><option value="card">Card</option></select></div><div class="span2"><label>Vendor</label><input name="vendor"></div><div class="span2"><label>Note</label><input name="note"></div></div><div class="btns"><button class="btn">Add expense</button></div></form>`) : card("Choose a branch", "", "<p class='empty'>Expenses are recorded per branch.</p>")}
  ${card("Expenses", `Total ${money(d.total)}`, tbl(["Date", "Branch", "Category", "Vendor", "Mode", "Amount"], d.rows.map(e => `<tr><td class="mono">${e.day}</td><td>${e.code}</td><td>${esc(e.category)}</td><td>${esc(e.vendor || "")}<div class="small muted">${esc(e.note || "")}</div></td><td>${e.mode}</td><td class="num">${money(e.amount)}</td></tr>`).join("")))}</div>`;
};
on("expSave", async f => { await api("/api/expenses", vals(f)); toast("Expense added"); go("accounts", ["exp"]); });
ACC.pay = async (el, period) => {
  const d = await api("/api/payouts?period=" + period);
  el.innerHTML = card("Doctor payouts", "Share of consultation, procedure and inpatient billing under each doctor (set the % in Admin > Staff)",
    tbl(["Doctor", "Share", "Patients", "Billed", "Payout", ""], d.map(x => `<tr><td>${esc(x.name)}</td><td class="num">${x.pct}%</td><td class="num">${x.patients}</td><td class="num">${money(x.billed)}</td><td class="num"><b>${money(x.share)}</b></td><td>${x.paid != null ? pill(`Paid ${money(x.paid)}`, "p-ok") : App.me.branch ? `<button class="btn sm" data-act="payDoc" data-id="${x.doctor_id}" data-a="${x.share}">Record payment</button>` : "<span class='small muted'>choose a branch</span>"}</td></tr>`).join(""), "No doctor has a payout share set."));
};
on("payDoc", async el => { const v = await dialog("Record doctor payout", `<label>Amount ₹</label><input name="amount" type="number" step=".01" value="${el.dataset.a}"><label>Mode</label><select name="mode"><option value="bank">Bank</option><option value="cash">Cash</option><option value="upi">UPI</option></select><label>Note</label><input name="note">`, { ok: "Record" }); if (v) { await api("/api/payouts", { ...v, doctor_id: +el.dataset.id, period: App.cache.period || localDay().slice(0, 7) }); toast("Recorded as an expense too"); go("accounts", ["pay"]); } });
ACC.gst = async (el, period) => {
  if (!App.me.branch) { el.innerHTML = card("Choose a branch", "GST returns are filed per GSTIN", ""); return; }
  const d = await api("/api/gst?period=" + period);
  el.innerHTML = card(`GSTR-1 working · ${esc(d.branch)}`, `GSTIN ${esc(d.gstin || "not set")} · file on the GST portal or through your CA`,
    `<div class="kpis"><div class="kpi"><span class="lab">Taxable sales</span><span class="val">${money(d.b2cs.reduce((a, x) => a + x.taxable, 0))}</span><span class="sub">pharmacy and taxable services</span></div><div class="kpi"><span class="lab">CGST</span><span class="val">${money(d.b2cs.reduce((a, x) => a + x.cgst, 0))}</span><span class="sub">output tax</span></div><div class="kpi"><span class="lab">SGST</span><span class="val">${money(d.b2cs.reduce((a, x) => a + x.sgst, 0))}</span><span class="sub">output tax</span></div><div class="kpi"><span class="lab">Input tax on purchases</span><span class="val">${money(d.input_tax_purchases)}</span><span class="sub">from goods received</span></div></div>
    <h3>B2C small (intra-state)</h3>${tbl(["Rate", "Taxable value", "CGST", "SGST"], d.b2cs.map(x => `<tr><td class="num">${x.rate}%</td><td class="num">${money(x.taxable)}</td><td class="num">${money(x.cgst)}</td><td class="num">${money(x.sgst)}</td></tr>`).join(""))}
     <h3 style="margin-top:12px">HSN summary</h3>${tbl(["HSN", "Rate", "Qty", "Taxable", "Tax"], d.hsn.map(x => `<tr><td class="mono">${x.hsn}</td><td class="num">${x.rate}%</td><td class="num">${x.qty}</td><td class="num">${money(x.taxable)}</td><td class="num">${money(x.tax)}</td></tr>`).join(""))}
     <p class="small">Exempt healthcare services: <b>${money(d.exempt_services)}</b> · Input tax on purchases (match with GSTR-2B): <b>${money(d.input_tax_purchases)}</b></p>
     <button class="btn ghost" data-act="gstCsv">Download CSV</button>`);
};
on("gstCsv", () => download(`/api/gst?period=${App.cache.period || localDay().slice(0, 7)}&format=csv`));
ACC.tally = async el => {
  el.innerHTML = card("Tally export", "Day-wise sales vouchers and expense payments as Tally XML", App.me.branch ? `<p class="small">Ledgers used: <b>Hospital Services Income</b>, <b>Pharmacy Sales</b>, <b>Output CGST</b>, <b>Output SGST</b>, <b>Cash and Bank Collections</b>, expense category names, <b>Cash</b>, <b>Bank</b>. Create these in Tally first, then use Gateway of Tally › Import › Vouchers.</p>
    <form data-submit="tallyDl" class="fields"><div class="span2"><label>Company name in Tally</label><input name="company" value="${esc(App.me.branch.name)}"></div><div style="align-self:end"><button class="btn">Download XML</button></div></form>` : "<p class='empty'>Choose a branch.</p>");
};
on("tallyDl", f => download(`/api/tally?period=${App.cache.period || localDay().slice(0, 7)}&company=${encodeURIComponent(vals(f).company)}`));
