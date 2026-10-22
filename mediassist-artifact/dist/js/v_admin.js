/* Admin: branches, staff, settings, import, backups, audit, error log. */
"use strict";
RENDER.admin = async (main, [pane]) => {
  const tabs = [["branches", "Branches"], ["staff", "Staff"], ["settings", "Settings"], ["import", "Import data"], ["backups", "Backups"], ["audit", "Audit trail"], ["errors", "Error log"]].filter(x => can("admin") || x[0] === "audit");
  pane = pane || App.cache.admPane || tabs[0][0]; App.cache.admPane = pane;
  main.innerHTML = subtabs(tabs, pane, "admTab2") + `<div id="admBody2"></div>`;
  await ADM[pane]($("#admBody2"));
};
on("admTab2", el => go("admin", [el.dataset.k]));
const ADM = {};
ADM.branches = async el => {
  const brs = await api("/api/branches"); App.cache.brs = brs;
  el.innerHTML = `<div class="g-form">${card("Branch", "", `<form data-submit="brSave" id="brForm" class="stack"><input type="hidden" name="id"><div class="fields"><div><label>Code</label><input name="code" placeholder="CH"></div><div class="span2"><label>Name</label><input name="name"></div>
    <div><label>Type</label><select name="kind"><option value="hospital+pharmacy">Hospital + pharmacy</option><option value="hospital">Hospital / clinic</option><option value="pharmacy">Medical shop</option></select></div><div><label>Phone</label><input name="phone"></div><div class="span2"><label>Address</label><input name="address"></div>
    <div><label>GSTIN</label><input name="gstin"></div><div><label>Drug licence no.</label><input name="dl_no"></div><div class="span2"><label>Daily report email</label><input name="report_email"></div><div><label>Daily report WhatsApp</label><input name="report_whatsapp"></div></div>
    <label class="check"><input type="checkbox" name="active" checked> Active</label><div class="btns"><button class="btn">Save branch</button><button type="button" class="btn ghost" data-act="brNew">New</button></div></form>`)}
  ${card("Branches", "", tbl(["Code", "Name", "Type", "Reports to", ""], brs.map(b => `<tr><td><span class="code">${b.code}</span></td><td>${esc(b.name)}${b.active ? "" : " (closed)"}</td><td>${b.kind}</td><td class="small">${esc(b.report_email || "")} ${esc(b.report_whatsapp || "")}</td><td><button class="btn sm ghost" data-act="brEdit" data-id="${b.id}">Edit</button></td></tr>`).join("")))}</div>`;
};
const fill = (f, o) => { for (const k in o) { const el = f.elements[k]; if (!el || el.tagName === undefined) continue; if (el.type === "checkbox") el.checked = !!o[k]; else el.value = o[k] ?? ""; } };
on("brEdit", el => fill($("#brForm"), App.cache.brs.find(b => b.id === +el.dataset.id)));
on("brNew", () => $("#brForm").reset());
on("brSave", async f => { await api("/api/branches", vals(f)); toast("Saved"); go("admin", ["branches"]); });
ADM.staff = async el => {
  const [us, brs] = await Promise.all([api("/api/users"), api("/api/branches")]); App.cache.us = us;
  el.innerHTML = `<div class="g-form">${card("Staff login", "Each person signs in with their own login", `<form data-submit="uSave" id="uForm" class="stack"><input type="hidden" name="id"><div class="fields"><div><label>Username</label><input name="username"></div><div class="span2"><label>Full name</label><input name="name"></div>
    <div><label>Role</label><select name="role">${["doctor", "nurse", "reception", "pharmacist", "lab_tech", "manager", "accountant", "owner"].map(r => `<option>${r}</option>`).join("")}</select></div><div class="span2"><label>Branch</label><select name="branch_id"><option value="">All branches</option>${brs.map(b => `<option value="${b.id}">${esc(b.code)} · ${esc(b.name)}</option>`).join("")}</select></div>
    <div><label>Medical reg. no.</label><input name="reg_no"></div><div><label>Payout share %</label><input name="payout_pct" type="number" min="0" max="100" step=".5"></div><div class="span2"><label>Email</label><input name="email"></div><div><label>WhatsApp</label><input name="whatsapp"></div>
    <div><label>Language</label><select name="lang"><option value="en">English</option><option value="hi">Hindi</option><option value="te">Telugu</option><option value="ta">Tamil</option></select></div><div class="span2"><label>Password (new staff)</label><input name="password" type="password" autocomplete="new-password"></div></div>
    <label class="check"><input type="checkbox" name="active" checked> Active</label><div class="btns"><button class="btn">Save</button><button type="button" class="btn ghost" data-act="uNew">New</button></div></form>`)}
  ${card("Staff", `${us.length} logins`, tbl(["User", "Role", "Branch", "2-step", ""], us.map(u => `<tr><td><b>${esc(u.name || "")}</b><div class="small muted">${esc(u.username)}${u.active ? "" : " · disabled"}</div></td><td>${u.role}${u.payout_pct ? ` · ${u.payout_pct}%` : ""}</td><td>${esc(u.bname || "All")}</td><td>${u.has_2fa ? pill("On", "p-ok") : "–"}</td><td class="row-actions"><button class="btn sm ghost" data-act="uEdit" data-id="${u.id}">Edit</button><button class="btn sm ghost" data-act="uReset" data-id="${u.id}">Reset password</button></td></tr>`).join("")))}</div>`;
};
on("uEdit", el => { const u = App.cache.us.find(x => x.id === +el.dataset.id), f = $("#uForm"); fill(f, { ...u, branch_id: u.branch_id || "" }); f.elements.username.disabled = true; });
on("uNew", () => { const f = $("#uForm"); f.reset(); f.elements.username.disabled = false; });
on("uSave", async f => { const v = vals(f); if (v.id) delete v.password; await api("/api/users", v); toast("Saved"); App.cache = { ...App.cache, staff_doctor: null }; go("admin", ["staff"]); });
on("uReset", async el => { const v = await dialog("Reset password", `<label>New password (8+ characters)</label><input name="password" type="password"><label class="check"><input type="checkbox" name="clear_2fa"> Also turn off their two-step sign-in (lost phone)</label>`, { ok: "Reset" }); if (v) { await api(`/api/users/${el.dataset.id}/reset`, v); toast("Done. They must sign in again."); } });
ADM.settings = async el => {
  const s = await api("/api/settings"), F = (k, l, type = "text", ph = "") => `<div class="${["smtp_pass", "twilio_token", "anthropic_api_key", "public_url", "opd_hours"].includes(k) ? "span2" : ""}"><label>${l}</label><input name="${k}" type="${type}" value="${esc(s[k] || "")}" placeholder="${ph}"></div>`;
  el.innerHTML = `<form data-submit="setSave" class="stack">${card("Group", "", `<div class="fields">${F("org_name", "Group name")}${F("owner_email", "Owner email")}${F("owner_whatsapp", "Owner WhatsApp")}${F("public_url", "Public address (HTTPS)", "url", "https://care.example.com")}</div>`)}
    ${card("OPD and reminders", "", `<div class="fields">${F("opd_hours", "OPD hours", "text", "09:00-13:00,17:00-20:00")}${F("slot_minutes", "Minutes per appointment", "number")}${F("reminder_time", "Send reminders at", "time")}<div><label>Online booking</label><select name="online_booking"><option value="1" ${s.online_booking === "1" ? "selected" : ""}>On</option><option value="0" ${s.online_booking === "0" ? "selected" : ""}>Off</option></select></div></div>`)}
    ${card("Patient records link", "Patients get a private link to their bills, reports and documents on WhatsApp", `<div class="fields"><div><label>Send new records automatically</label><select name="portal_auto"><option value="1" ${s.portal_auto !== "0" ? "selected" : ""}>On</option><option value="0" ${s.portal_auto === "0" ? "selected" : ""}>Off</option></select></div>${F("portal_days", "Link works for (days without a new record)", "number")}<div><label>Welcome message on registration</label><select name="welcome_msg"><option value="1" ${s.welcome_msg === "1" ? "selected" : ""}>On</option><option value="0" ${s.welcome_msg === "0" ? "selected" : ""}>Off</option></select></div></div>`)}
    ${card("Weekly pharmacy summary", "Expiring and non-moving stock, low stock and supplier dues, sent at the report time", `<div class="fields"><div><label>Send it</label><select name="weekly_pharmacy"><option value="1" ${s.weekly_pharmacy === "1" ? "selected" : ""}>On</option><option value="0" ${s.weekly_pharmacy === "0" ? "selected" : ""}>Off</option></select></div><div><label>On</label><select name="weekly_day"><option value="mon" ${s.weekly_day === "mon" ? "selected" : ""}>Monday</option><option value="tue" ${s.weekly_day === "tue" ? "selected" : ""}>Tuesday</option><option value="wed" ${s.weekly_day === "wed" ? "selected" : ""}>Wednesday</option><option value="thu" ${s.weekly_day === "thu" ? "selected" : ""}>Thursday</option><option value="fri" ${s.weekly_day === "fri" ? "selected" : ""}>Friday</option><option value="sat" ${s.weekly_day === "sat" ? "selected" : ""}>Saturday</option><option value="sun" ${s.weekly_day === "sun" ? "selected" : ""}>Sunday</option></select></div></div>`)}
    ${card("AI assistant", "Staff ask questions by text or voice and get answers from the records. Uses the Anthropic API key below; questions and the records needed to answer them are sent to Anthropic.",
      `<div class="fields"><div><label>Assistant</label><select name="assistant_on"><option value="1" ${s.assistant_on !== "0" ? "selected" : ""}>On</option><option value="0" ${s.assistant_on === "0" ? "selected" : ""}>Off</option></select></div>
      <div class="span2"><label>Can it read patient records?</label><select name="assistant_patients"><option value="1" ${s.assistant_patients !== "0" ? "selected" : ""}>Yes (history, prescriptions, lab results)</option><option value="0" ${s.assistant_patients === "0" ? "selected" : ""}>No, stock and reports only</option></select></div></div>`)}
    ${card("Doctor alerts", "Morning briefing and instant alerts on the doctor's WhatsApp (set each doctor's number in Staff). Alerts also show in the app.",
      `<div class="fields"><div><label>Morning briefing</label><select name="briefing_on"><option value="1" ${s.briefing_on !== "0" ? "selected" : ""}>On</option><option value="0" ${s.briefing_on === "0" ? "selected" : ""}>Off</option></select></div>${F("briefing_time", "Send it at", "time")}
      ${[["alert_critical", "Critical patient arrived"], ["alert_booking", "New online booking"], ["alert_wait", "Patient waiting too long"], ["alert_admit", "Admission under the doctor"]].map(([k, l]) => `<div><label>${l}</label><select name="${k}"><option value="1" ${s[k] !== "0" ? "selected" : ""}>Alert</option><option value="0" ${s[k] === "0" ? "selected" : ""}>Off</option></select></div>`).join("")}
      <div style="align-self:end"><button type="button" class="btn sm ghost" data-act="briefSend">Send today's briefings now</button></div></div>`)}
    ${card("Staff watch", "What gets flagged to the owner and managers", `<div class="fields">${F("watch_amount", "Flag amounts from (Rs)", "number")}${F("watch_discount_pct", "Flag discounts from (%)", "number")}</div>`)}
    ${card("Evening reports and backups", "", `<div class="fields">${F("report_time", "Send reports at", "time")}<div><label>Automatic sending</label><select name="auto_send"><option value="1" ${s.auto_send === "1" ? "selected" : ""}>On</option><option value="0" ${s.auto_send === "0" ? "selected" : ""}>Off</option></select></div>${F("backup_keep_days", "Keep daily backups (days)", "number")}</div>`)}
    ${card("Email (SMTP)", "Gmail: turn on 2-step verification, create an App password, host smtp.gmail.com port 587", `<div class="fields">${F("smtp_host", "Host")}${F("smtp_port", "Port", "number")}${F("smtp_user", "Login email")}${F("smtp_pass", "App password", "password")}${F("smtp_from", "From address")}</div>`)}
    ${card("WhatsApp (Twilio)", "Production use needs approved message templates from Meta", `<div class="fields">${F("twilio_sid", "Account SID")}${F("twilio_token", "Auth token", "password")}${F("twilio_from", "Twilio WhatsApp number")}</div>`)}
    ${card("AI document reader", "Optional. Uses Claude to read bills and invoices. Needs  pip install anthropic  on the server.", `<div class="fields">${F("anthropic_api_key", "Anthropic API key", "password")}</div>`)}
    <div class="btns"><button class="btn">Save settings</button></div></form>`;
};
on("setSave", async f => { await api("/api/settings", vals(f)); toast("Settings saved"); });
on("impGrowth", async el => {
  const f = $("#impG").files[0]; if (!f) return toast("Choose the CSV file first.");
  const r = await withBusy(el, async () => api("/api/import/growth", { csv: await f.text(), sex: $("#gwSex").value, kind: $("#gwKind").value }));
  $("#impGOut").innerHTML = alertRow("info", `Loaded ${r.rows} rows (${r.range_months[0]} to ${r.range_months[1]} months).`);
});
ADM.import = async el => {
  el.innerHTML = `<div class="g2">${card("Import patients", "CSV with a header row: name, phone, age, gender, dob, address, allergies, conditions, blood_group, abha", `<input type="file" accept=".csv,text/csv" id="impP"><div class="btns"><button class="btn" data-act="impRun" data-k="patients" data-f="impP">Import patients</button></div><div id="impPOut"></div>`)}
    ${card("Import opening stock", `CSV: medicine, generic, form, schedule, pack_size, batch, expiry (YYYY-MM-DD), qty, mrp, cost, rack. Loads into ${App.me.branch ? esc(App.me.branch.name) : "the selected branch"}.`, `<input type="file" accept=".csv,text/csv" id="impS"><div class="btns"><button class="btn" data-act="impRun" data-k="stock" data-f="impS" ${App.me.branch ? "" : "disabled"}>Import stock</button></div><div id="impSOut"></div>`)}
    ${card("WHO growth standards", "For percentiles and z-scores on the child growth chart. Download the LMS tables from who.int (Child growth standards > Weight-for-age > z-scores, 'expanded tables' CSV: columns Month/Day, L, M, S) and load one file per sex and measure.", `<div class="fields"><div><label>Sex</label><select id="gwSex"><option value="M">Boys</option><option value="F">Girls</option></select></div><div><label>Measure</label><select id="gwKind"><option value="wfa">Weight-for-age</option><option value="hfa">Height/length-for-age</option></select></div><div class="span2"><input type="file" accept=".csv,.txt,text/csv" id="impG"></div></div><div class="btns"><button class="btn" data-act="impGrowth">Load table</button></div><div id="impGOut"></div>`)}</div>`;
};
on("impRun", async el => {
  const f = $("#" + el.dataset.f).files[0]; if (!f) return toast("Choose a CSV file first.");
  const text = await f.text(); const r = await api(`/api/import/${el.dataset.k}`, { csv: text });
  $("#" + el.dataset.f + "Out").innerHTML = alertRow("info", `Added ${r.added}${r.skipped != null ? ` · skipped ${r.skipped} duplicates` : ""}${r.new_medicines != null ? ` · ${r.new_medicines} new medicines` : ""}`) + r.errors.map(e => alertRow("", esc(e))).join("");
});
ADM.backups = async el => {
  const l = await api("/api/backups");
  el.innerHTML = card("Backups", "A backup is made automatically every day. Copy the backups folder to a pen drive or cloud storage regularly.", `<button class="btn" data-act="bkNow">Back up now</button>` + tbl(["File", "Made", "Size"], l.map(b => `<tr><td class="mono small">${esc(b.name)}</td><td class="mono">${b.at}</td><td class="num">${Math.round(b.size / 1024)} KB</td></tr>`).join(""), "No backups yet."));
};
on("bkNow", async el => { await withBusy(el, () => api("/api/backups", {})); toast("Backup saved"); go("admin", ["backups"]); });
ADM.audit = async el => {
  const l = await api("/api/audit?q=" + encodeURIComponent(App.cache.auQ || ""));
  el.innerHTML = card("Audit trail", "Every action with who, when and where", `<input data-input="auQ" value="${esc(App.cache.auQ || "")}" placeholder="Search action, detail or user (e.g. OVERRIDE, refund, erase)">` + tbl(["When", "User", "Branch", "Action", "Detail"], l.map(a => `<tr><td class="mono">${a.at}</td><td>${esc(a.username || "public")}</td><td>${esc(a.code || "")}</td><td class="mono">${esc(a.action)}</td><td class="small">${/OVERRIDE/.test(a.detail || "") ? pill("override", "p-crit") + " " : ""}${esc(a.detail || "")}</td></tr>`).join("")));
};
on("auQ", debounce(el => { App.cache.auQ = el.value; ADM.audit($("#admBody2")); }, 400));
ADM.errors = async el => { const l = await api("/api/errors"); el.innerHTML = card("Server errors", "Share these with your developer if something breaks", tbl(["When", "Request", "Error"], l.map(e => `<tr><td class="mono">${e.at}</td><td class="mono small">${esc(e.method)} ${esc(e.path)}</td><td class="small">${esc(e.error)}</td></tr>`).join(""), "No errors logged.")); };
