/* Dashboard, daily/doctor reports with sending, analytics, messages, follow-ups, feedback. */
"use strict";
const SERIES = ["--s1", "--s2", "--s3", "--s4"];
RENDER.dashboard = async main => {
  const d = await api("/api/dashboard"), r = d.report;
  const delta = (a, b) => b ? `<span style="color:${a >= b ? "var(--ok)" : "var(--crit)"};font-weight:600">${a >= b ? "▲" : "▼"} ${Math.abs(Math.round((a - b) / b * 100))}%</span> vs yesterday` : "";
  const alerts = r.alerts.map(a => alertRow(a.level, esc(a.text))).join("") || '<p class="empty">All clear.</p>';
  if (d.mode === "org") {
    const brs = d.branches, series = brs.slice(0, 4).map((b, i) => ({ name: b.code, color: SERIES[i], values: d.trend.map(t_ => t_[String(b.id)] || 0) }));
    main.innerHTML = `<div class="kpis">${kpi("Revenue today", money(r.total), delta(r.total, r.prev_total))}${kpi("Patients seen", r.seen, `${r.new} new · ${r.triage.critical || 0} critical`)}${kpi("Inpatients", r.admitted_now, `${r.admissions} admitted, ${r.discharges} discharged today`)}${kpi("Dues outstanding", money(r.dues), "all branches", r.dues ? "warn" : "")}</div>
    <div class="g-main"><div class="stack">${card("Revenue by branch", "Last 14 days, hospital + pharmacy", `<div class="chart" id="orgChart"></div><div class="legend">${series.map(s => `<span><i style="background:var(${s.color})"></i>${esc(s.name)}</span>`).join("")}</div>`)}
      ${card("Branches today", "Select one to open it", `<div class="branches">${brs.map(b => `<button class="bcard" data-act="openBranch" data-id="${b.id}"><div class="h"><span class="code">${b.code}</span><div><b>${esc(b.name)}</b><span>${b.kind.replace("+", " + ")}</span></div></div><div class="bstats"><div><b>${b.seen}</b><span>Seen</span></div><div><b style="color:${b.critical ? "var(--crit)" : "inherit"}">${b.waiting}</b><span>Waiting</span></div><div><b>${rupees(b.hosp + b.pharm)}</b><span>Revenue</span></div></div><div class="small muted">${b.inpatients} inpatients · ${b.invoices} invoices · ${b.bills} pharmacy bills</div></button>`).join("")}</div>`)}</div>
      ${card("Needs attention", `${r.alerts.length} items`, alerts)}</div>`;
    if (can("audit")) watchCard(main);
    briefingCard(main);
    lineChart($("#orgChart"), d.trend.map(t_ => t_.day), series);
    return;
  }
  const H = d.branch.kind.includes("hospital"), tr = d.trend, MONEY = can("reports") || can("hbilling") || can("billing");
  main.innerHTML = `<div class="kpis">${H ? kpi("Patients seen", r.seen, `${d.appointments.arrived} of ${d.appointments.total} appointments arrived`, "", sparkline(tr.map(x => x.seen))) + kpi("Waiting now", d.waiting, d.critical.length ? `${d.critical.length} critical` : "no critical", d.critical.length ? "crit" : "") : ""}
    ${H && d.beds.total ? kpi("Beds free", d.beds.free, `${d.beds.occupied} occupied · ${d.beds.cleaning} cleaning · ${d.beds.total} total`, d.beds.free ? "" : "crit") : ""}${H ? kpi("Lab", d.lab.ordered + d.lab.collected, `${d.lab.resulted} waiting for verification`, d.lab.resulted ? "warn" : "") : ""}
    ${MONEY ? kpi("Revenue today", money(r.total), delta(r.total, r.prev_total), "", sparkline(tr.map(x => x.hosp + x.pharm))) + kpi("Collected", money(r.collected), `dues ${money(r.dues)}`) : ""}</div>
  <div class="g-main"><div class="stack">
    ${H ? card("Critical patients waiting", "", d.critical.map(v => alertRow("high", `<b>${esc(v.name)}</b> · ${esc(v.triage_reasons || "")} · since ${v.created_at.slice(11)} ${can("consult") ? `<button class="btn danger sm" data-act="go" data-v="consult" data-p="${v.id}">See now</button>` : ""}`)).join("") || '<p class="empty">None waiting.</p>') : ""}
    ${card("Needs attention", "", alerts)}
    ${H ? card("Follow-up calls today", "", d.followups.map(f => `<p>${esc(f.name)} · <span class="mono">${esc(f.phone)}</span> · ${esc(f.diagnosis || "")}</p>`).join("") || '<p class="empty">None due.</p>') : ""}</div>
    ${MONEY ? card("Today's report so far", "Sent automatically in the evening", `<pre class="rep">${esc(r.text.replace(/\*/g, ""))}</pre>`) : ""}</div>`;
  if (can("audit")) watchCard(main);
  if (can("consult") && H) criticalCard(main);
  if (H && d.beds.total) bedsCard(main);
  if (App.me.role === "doctor" || App.me.all_access || App.me.role === "manager") briefingCard(main);
};
on("openBranch", async el => { await api("/api/branch", { branch_id: +el.dataset.id }); App.cache = {}; await start(); });

RENDER.reports = async (main, [pane]) => {
  pane = pane || App.cache.repPane || (App.me.role === "doctor" ? "doctor" : "daily"); App.cache.repPane = pane;
  const tabs = [["daily", "Daily report"], ["doctor", "Doctor summary"], ["analytics", "Analytics"], ...(can("audit") ? [["watch", "Staff watch"]] : []), ["followups", "Follow-ups"], ["feedback", "Feedback"], ["messages", "Messages"]].filter(x => App.me.role !== "doctor" || ["doctor", "followups"].includes(x[0]));
  main.innerHTML = subtabs(tabs, pane, "repTab") + `<div id="repBody"></div>`;
  await REP[pane]($("#repBody"));
};
on("repTab", el => go("reports", [el.dataset.k]));
const REP = {};
REP.daily = async el => {
  const day = App.cache.repDay || localDay(), r = await api("/api/reports/daily?date=" + day);
  let wa = ""; try { wa = localStorage.getItem("ma-wa") || ""; } catch (e) {}
  const waLink = n => `https://wa.me/${String(n).replace(/\D/g, "").replace(/^(\d{10})$/, "91$1")}?text=${encodeURIComponent(r.text)}`;
  el.innerHTML = `<div class="card rhead"><div><div class="crumb">${esc(r.label)}</div><h2 style="font-size:22px">Daily report · ${shortDay(day)}</h2><p class="small muted" style="margin:4px 0 0">${day === localDay() ? "So far today" : "Full day"}</p></div>
    <div class="share"><div><label>Date</label><input type="date" value="${day}" data-change="repDay"></div><div><label>WhatsApp number</label><input id="waNum" value="${esc(wa)}" data-input="waNum" placeholder="98765 43210"></div><a class="btn" id="waBtn" target="_blank" rel="noopener" href="${waLink(wa)}">Open in WhatsApp</a>
    ${can("org_reports") || App.me.branch ? `<button class="btn ghost" data-act="sendRep">Send now (email/WhatsApp)</button>` : ""}<button class="btn ghost" data-act="copyRep">Copy</button></div></div>
  <div class="kpis">${kpi("Patients seen", r.seen, `${r.new} new · ${r.triage.critical || 0} critical`)}${kpi("Revenue", money(r.total), `yesterday ${money(r.prev_total)} · 7-day avg ${money(r.avg7_total)}`)}${kpi("Collected", money(r.collected), `dues ${money(r.dues)}`)}${kpi("Inpatients", r.admitted_now, `${r.admissions} in · ${r.discharges} out · ${r.labs} lab orders`)}</div>
  <div class="g-main"><div class="stack">${card("Revenue by department", "", bars(Object.entries(r.dept).sort((a, b) => b[1] - a[1]), Math.max(1, ...Object.values(r.dept))))}
    ${card("Doctors", "", tbl(["Doctor", "Patients", "Billed"], r.doctors.map(d => `<tr><td>${esc(d.name)}</td><td class="num">${d.seen}</td><td class="num">${money(d.billed)}</td></tr>`).join("")))}</div>
    <div class="stack">${card("Collections by mode", "", bars(Object.entries(r.modes), Math.max(1, ...Object.values(r.modes))))}${card("Message", "This text is sent", `<pre class="rep" id="repTxt">${esc(r.text)}</pre>`)}</div></div>`;
  App.cache.repText = r.text; App.cache.waLink = waLink;
};
on("repDay", el => { App.cache.repDay = el.value; REP.daily($("#repBody")); });
on("waNum", el => { try { localStorage.setItem("ma-wa", el.value); } catch (e) {} $("#waBtn").href = App.cache.waLink(el.value); });
on("copyRep", () => navigator.clipboard.writeText(App.cache.repText.replace(/\*/g, "")).then(() => toast("Copied"), () => toast("Select the text and copy it")));
on("sendRep", async () => {
  const kindR = App.me.branch ? "branch" : "all";
  const res = await api("/api/reports/send", { kind: kindR, date: App.cache.repDay || localDay() });
  await dialog("Report sent", res.map(x => alertRow(x.ok ? "info" : "", `${x.channel} → ${esc(x.to || "")}: ${esc(x.detail)}${x.wa_link ? ` · <a href="${esc(x.wa_link)}" target="_blank" rel="noopener">send by hand</a>` : ""}`)).join(""), { ok: "", cancel: "Close" });
});
REP.doctor = async el => {
  const docs = await staff("doctor"), uid = App.cache.repDoc || (App.me.role === "doctor" ? App.me.id : (docs[0] || {}).id), day = App.cache.repDay || localDay();
  const r = uid ? await api(`/api/reports/doctor?doctor_id=${uid}&date=${day}`) : { text: "No doctors yet." };
  el.innerHTML = card("Doctor summary", "Patients seen, lab results to review, inpatients and tomorrow's follow-ups",
    `<div class="fields">${App.me.role === "doctor" ? "" : `<div><label>Doctor</label>${docSelect(docs, "doc", uid, "").replace("<select ", '<select data-change="repDoc" ')}</div>`}<div><label>Date</label><input type="date" value="${day}" data-change="repDay2"></div><div style="align-self:end"><button class="btn ghost" data-act="sendDoc" data-id="${uid}">Send to doctor</button></div></div><pre class="rep" style="margin-top:12px">${esc(r.text)}</pre>`);
};
on("repDoc", el => { App.cache.repDoc = +el.value; REP.doctor($("#repBody")); });
on("repDay2", el => { App.cache.repDay = el.value; REP.doctor($("#repBody")); });
on("sendDoc", async el => { const res = await api("/api/reports/send", { kind: "doctor", doctor_id: +el.dataset.id, date: App.cache.repDay || localDay() }); toast(res.map(x => `${x.channel}: ${x.ok ? "sent" : x.detail}`).join(" · ")); });
REP.analytics = async el => {
  const days = App.cache.anDays || 30, a = await api("/api/analytics?days=" + days), mx = Math.max(1, ...a.heat.flat());
  const dn = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  el.innerHTML = `<div class="row-actions" style="margin-bottom:12px">${[30, 90, 365].map(n => `<button class="btn sm ${n === days ? "" : "ghost"}" data-act="anDays" data-n="${n}">${n} days</button>`).join("")}</div>
  <div class="kpis">${kpi("Patients", a.patients, `${a.repeat} came back (${a.repeat_pct}%)`)}${kpi("Patient rating", a.feedback_avg ? a.feedback_avg + " / 5" : "–", `${a.feedback_n} responses`)}${kpi("No-show rate", a.no_show_pct != null ? a.no_show_pct + "%" : "–", "booked appointments")}${kpi("Top diagnosis", esc((a.diagnoses[0] || {}).diagnosis || "–"), a.diagnoses[0] ? a.diagnoses[0].n + " visits" : "")}</div>
  <div class="g-main">${card("Busiest hours", "Arrivals by weekday and hour: staff the darker cells", `<div class="tbl"><div class="heat" style="min-width:520px"><span></span>${Array.from({ length: 24 }, (_, h) => `<span>${h % 3 ? "" : h}</span>`).join("")}${a.heat.map((row, i) => `<span>${dn[i]}</span>${row.map(v => `<i title="${dn[i]} ${v} arrivals" style="opacity:${v ? (0.12 + 0.88 * v / mx).toFixed(2) : 0.05}"></i>`).join("")}`).join("")}</div></div>`)}
    ${card("Top diagnoses", "", tbl(["Diagnosis", "ICD-10", "Visits"], a.diagnoses.map(x => `<tr><td>${esc(x.diagnosis)}</td><td class="mono">${esc(x.icd)}</td><td class="num">${x.n}</td></tr>`).join("")))}</div>
  ${card("Doctors", "", tbl(["Doctor", "Visits", "Patients", "Revenue billed"], a.doctors.map(d => `<tr><td>${esc(d.name)}</td><td class="num">${d.visits}</td><td class="num">${d.patients}</td><td class="num">${money(d.revenue)}</td></tr>`).join("")))}`;
};
on("anDays", el => { App.cache.anDays = +el.dataset.n; REP.analytics($("#repBody")); });
REP.followups = async el => {
  const day = App.cache.fuDay || localDay(), l = await api("/api/followups?date=" + day);
  el.innerHTML = card("Follow-ups due", "Call patients who haven't booked", `<input type="date" value="${day}" data-change="fuDay" style="width:auto;margin-bottom:10px">` + tbl(["Branch", "Patient", "Phone", "Diagnosis", "Doctor"], l.map(f => `<tr><td>${f.bcode}</td><td>${esc(f.name)} <span class="small muted">${f.code}</span></td><td class="mono">${esc(f.phone)}</td><td>${esc(f.diagnosis || "")}</td><td>${esc(f.dname || "")}</td></tr>`).join(""), "No follow-ups due."));
};
on("fuDay", el => { App.cache.fuDay = el.value; REP.followups($("#repBody")); });
REP.feedback = async el => {
  const l = await api("/api/feedback");
  el.innerHTML = card("Patient feedback", "Sent by WhatsApp the evening after each visit (needs the public address set in Admin > Settings)", tbl(["When", "Branch", "Patient", "Rating", "Comment"], l.map(f => `<tr><td class="mono">${f.answered_at}</td><td>${f.bcode}</td><td>${esc(f.pname)}</td><td>${"★".repeat(f.rating)}${"☆".repeat(5 - f.rating)}</td><td>${esc(f.comment || "")}</td></tr>`).join(""), "No feedback yet."));
};
REP.messages = async el => {
  const l = await api("/api/messages");
  el.innerHTML = card("Messages", "Every WhatsApp and email the system sent or tried to send", tbl(["When", "Type", "To", "Result", ""], l.map(m => `<tr><td class="mono">${m.at}</td><td>${esc(m.kind)}</td><td class="mono small">${esc(m.to_addr)} · ${m.channel}</td><td>${m.ok ? pill("Sent", "p-ok") : pill("Not sent", "p-crit")} <span class="small muted">${esc(m.detail || "")}</span></td><td>${m.wa_link ? `<a class="btn sm ghost" href="${esc(m.wa_link)}" target="_blank" rel="noopener">Send by hand</a>` : ""}</td></tr>`).join(""), "Nothing sent yet."));
};
