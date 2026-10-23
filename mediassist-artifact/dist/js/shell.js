/* Shell: sign-in, navigation, router, branch switch, global stock lookup, my account. */
"use strict";
const ICON = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  patients: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>', tracker: '<circle cx="5" cy="5" r="2"/><circle cx="5" cy="12" r="2"/><circle cx="5" cy="19" r="2"/><path d="M10 5h10M10 12h10M10 19h6"/>', opd: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  consult: '<path d="M6 3v6a4 4 0 0 0 8 0V3"/><path d="M10 13v3a5 5 0 0 0 10 0v-2"/><circle cx="20" cy="12" r="2"/>',
  lab: '<path d="M9 3h6M10 3v6L4 19a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-6-10V3"/><path d="M7 15h10"/>',
  ipd: '<path d="M3 18V8M3 14h18v4M21 14v-2a3 3 0 0 0-3-3h-7v5"/><circle cx="7" cy="11" r="2"/>',
  billing: '<path d="M6 2h12v20l-3-2-3 2-3-2-3 2z"/><path d="M9 7h6M9 11h6M9 15h4"/>', stock: '<path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/><path d="M12 13v8"/>',
  hbilling: '<path d="M6 4h12M6 9h12M14 20l-7-7h3a4 4 0 0 0 0-8"/>', docs: '<path d="M21 11l-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 7"/>',
  accounts: '<path d="M4 19V5M4 19h16"/><path d="M8 15l4-5 3 3 5-6"/>', reports: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
  admin: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
};
const H_ = () => kind().includes("hospital"), PH_ = () => kind().includes("pharmacy");
const VIEWS = [
  ["dashboard", "Dashboard", () => true], ["patients", "Patients", () => can("patients_read")],
  ["opd", "OPD & appointments", () => H_() && (can("appointments") || can("visit_create"))], ["tracker", "Patient tracker", () => H_() && can("patients_read")], ["consult", "Consultation", () => H_() && can("consult")],
  ["lab", "Laboratory", () => H_() && (can("lab") || can("lab_verify"))], ["beds", "Bed board", () => H_() || (App.me && !App.me.branch && App.me.all_access)], ["ipd", "Inpatients", () => H_() && can("ipd")],
  ["billing", "Pharmacy billing", () => PH_() && can("billing")], ["stock", "Stock", () => (PH_() || (App.me && !App.me.branch && App.me.all_access)) && (can("stock") || can("billing"))],
  ["hbilling", "Hospital billing", () => H_() && can("hbilling")], ["docs", "Documents", () => can("documents")],
  ["accounts", "Accounts", () => can("accounts")], ["reports", "Reports", () => can("reports")], ["admin", "Admin", () => can("admin") || can("audit")],
];
const RENDER = {};   // view name -> async render(main, params)

/* ---------------- sign-in ---------------- */
let mfaStep = false;
function showLogin(mfa) {
  $("#app").hidden = true; $("#login").hidden = false; mfaStep = !!mfa;
  $("#loginStep1").hidden = mfaStep; $("#loginStep2").hidden = !mfaStep;
  (mfaStep ? $("#lc") : $("#lu")).focus();
}
on("login", async form => {
  const v = vals(form);
  try {
    if (!mfaStep) {
      const r = await api("/api/login", { username: v.username, password: v.password });
      $("#lp").value = "";
      if (r.mfa_required) return showLogin(true);
    } else {
      await api("/api/2fa/verify", { code: v.code });
      $("#lc").value = "";
    }
    $("#lmsg").textContent = ""; start();
  } catch (e) { $("#lmsg").textContent = e.message; }
});
on("logout", async () => { const open = App.me && App.me.open_access; await api("/api/logout", {}).catch(() => {}); App.me = null; if (open) return location.reload(); showLogin(false); });

async function start() {
  try { App.me = await api("/api/me"); } catch (e) { return; }
  if (App.me.mfa_required) return showLogin(true);
  App.cache = {};
  $("#login").hidden = true; $("#app").hidden = false;
  $("#orgName").textContent = App.me.org_name;
  $("#whoAv").textContent = initials(App.me.name); $("#whoName").textContent = App.me.name || App.me.username;
  $("#whoRole").textContent = App.me.role[0].toUpperCase() + App.me.role.slice(1) + (App.me.reg_no ? " · " + App.me.reg_no : "");
  $("#branchSel").innerHTML = (App.me.all_access && can("all_branches") ? `<option value="0">${t("All branches")}</option>` : "") +
    App.me.branches.map(b => `<option value="${b.id}">${esc(b.code)} · ${esc(b.name)}</option>`).join("");
  $("#branchSel").value = App.me.branch ? App.me.branch.id : 0; $("#branchSel").disabled = !App.me.all_access;
  $$("[data-i18n]").forEach(el => el.textContent = t(el.dataset.i18n));
  renderNav(); renderSync(); flushOutbox(); refreshAlerts();
  ["#askFab", "#askPanel"].forEach(s => { const el = $(s); if (el) el.remove(); });
  if (typeof assistantBoot === "function") assistantBoot();
  const h = location.hash.slice(1).split("/");
  go(VIEWS.some(v => v[0] === h[0] && v[2]()) || h[0] === "me" ? h[0] : "dashboard", h.slice(1));
  if (App.me.suggest_2fa && !sessionStorage.getItem("nag2fa")) { sessionStorage.setItem("nag2fa", 1); toast("Protect the owner account: turn on two-step sign-in in My account."); }
}
function renderNav() {
  $("#nav").innerHTML = VIEWS.filter(v => v[2]()).map(v => `<button data-act="go" data-v="${v[0]}"><svg viewBox="0 0 24 24" aria-hidden="true">${ICON[v[0]]}</svg>${esc(t(v[1]))}<span class="badge" data-badge="${v[0]}" hidden></span></button>`).join("");
}
on("switchBranch", async el => { await api("/api/branch", { branch_id: +el.value }); App.cache = {}; await start(); });

/* ---------------- router ---------------- */
async function go(view, params = []) {
  if (typeof view !== "string") { params = view.dataset.p ? view.dataset.p.split("/") : []; view = view.dataset.v; }
  App.view = view; App.params = params;
  const label = view === "me" ? "My account" : (VIEWS.find(v => v[0] === view) || [, "Dashboard"])[1];
  history.replaceState(null, "", "#" + [view, ...params].join("/"));
  $$("#nav button").forEach(b => b.classList.toggle("on", b.dataset.v === view));
  $("#pageTitle").textContent = t(label);
  $("#crumb").textContent = `${App.me.org_name} / ${App.me.branch ? App.me.branch.name : t("All branches")}`;
  const main = $("#view"); main.innerHTML = '<p class="empty">Loading…</p>';
  try { await (RENDER[view] || RENDER.dashboard)(main, params); }
  catch (e) { if (e.status !== 401) main.innerHTML = `<div class="card">${alertRow("high", esc(e.message))}</div>`; }
  if (innerWidth < 900) scrollTo({ top: 0 });
}
on("go", el => go(el));
addEventListener("hashchange", () => { const h = location.hash.slice(1).split("/"); if (App.me && h[0] && (h[0] !== App.view || h.slice(1).join("/") !== App.params.join("/"))) go(h[0], h.slice(1)); });

async function refreshAlerts() {
  try { const a = await api("/api/alerts"), recent = a.filter(x => x.at >= localDay(-1)); const el = $("#alertChip"); el.hidden = !recent.length; el.textContent = `${recent.length} alert${recent.length === 1 ? "" : "s"}`; } catch (e) {}
}
setInterval(() => App.me && refreshAlerts(), 60000);

/* ---------------- global medicine lookup (stock + rack) ---------------- */
function stockCard(s) {
  const m = s.medicine;
  if (s.no_pharmacy) return `<div class="sinfo"><b>${esc(m.name)}</b> <span class="small muted">${esc(m.generic || "")}</span>${s.others.length ? tbl(["Pharmacy", "Qty", "Rack"], s.others.map(o => `<tr><td>${esc(o.branch)}</td><td class="num">${o.qty}</td><td><span class="rack sm">${esc(o.rack || "–")}</span></td></tr>`).join("")) : '<p class="small allergy">Not in stock at any pharmacy.</p>'}</div>`;
  const st = s.status === "out" ? pill("Out of stock", "p-crit") : s.status === "low" ? pill(`Low · ${s.qty}`, "p-warn") : pill(`In stock · ${s.qty}`, "p-ok");
  return `<div class="sinfo"><div><b>${esc(m.name)}</b> <span class="small muted">${esc(m.generic || "")} · ${esc(m.form || "")} · ${m.schedule} · pack of ${m.pack_size}</span> ${st}</div>
  ${s.batches.map((b, i) => `<div class="rackrow${i ? "" : " first"}"><span class="rack">${esc(b.rack || "–")}</span><span class="mono small">${esc(b.batch || "")}</span><span class="small muted">exp ${b.effective_expiry}</span><b class="small">${b.qty}</b>${i ? "" : pill("Pick first", "p-info")}</div>`).join("")}
  ${s.expired.map(b => `<div class="small allergy">Batch ${esc(b.batch)} on rack ${esc(b.rack || "–")} (${b.qty}) has expired. Don't sell it.</div>`).join("")}
  ${s.status !== "ok" && s.others.length ? `<div class="small">Available at ${s.others.map(o => `<b>${esc(o.branch)}</b> ${o.qty} on <span class="rack sm">${esc(o.rack || "–")}</span>`).join(", ")}</div>` : ""}
  ${s.alternatives.length ? `<div class="small">Same salt in stock here: ${s.alternatives.map(a => `${esc(a.name)} (${a.stock})`).join(", ")}</div>` : ""}</div>`;
}
on("gLook", debounce(async el => {
  const box = $("#gLookBox"), q = el.value.trim();
  if (!App.cache.meds) await loadMeds();
  const m = medByName(q);
  if (m) { box.innerHTML = stockCard(await api("/api/stock/lookup?id=" + m.id)); box.hidden = false; return; }
  if (q.length < 2) { box.hidden = true; return; }
  let l; try { l = await api("/api/stock/find?q=" + encodeURIComponent(q)); } catch (e) { box.hidden = true; return; }
  box.innerHTML = l.length ? `<div class="sinfo">${l.map(x => `<button type="button" class="findrow" data-act="findPick" data-id="${x.id}"><span class="rack">${esc(x.rack || (x.no_pharmacy ? "" : "no rack"))}</span><span><b>${esc(x.name)}</b> <span class="small muted">${esc(x.generic || "")} · ${esc(x.form || "")}</span></span>
      <span class="small">${x.no_pharmacy ? (x.others.length ? x.others.map(o => `${esc(o.code)} ${o.qty}`).join(", ") : '<span class="allergy">none</span>') : x.qty ? `<b>${x.qty}</b> in stock${x.racks.length > 1 ? ` · also ${x.racks.slice(1).join(", ")}` : ""}${x.days_left != null && x.days_left <= 90 ? ` · <span class="allergy">exp ${x.pick_expiry}</span>` : ""}` : `<span class="allergy">out</span>${x.others.length ? ` · at ${x.others.map(o => `${esc(o.code)} ${o.qty}`).join(", ")}` : ""}`}</span></button>`).join("")}</div>`
    : `<div class="sinfo"><p class="small muted">Nothing matches "${esc(q)}". Try part of the brand or the salt name.</p></div>`;
  box.hidden = false;
}, 200));
on("findPick", async el => { const box = $("#gLookBox"); const m = (App.cache.meds || []).find(x => x.id === +el.dataset.id); if (m) $("#gLook").value = m.name; box.innerHTML = stockCard(await api("/api/stock/lookup?id=" + el.dataset.id)); box.hidden = false; });
document.addEventListener("click", e => { if (!e.target.closest(".lookup")) $("#gLookBox").hidden = true; });

/* ---------------- my account ---------------- */
RENDER.me = async main => {
  const att = await api("/api/attendance"), me = App.me, a = att.me;
  main.innerHTML = `<div class="g2">
  ${card("Attendance", a ? `Clocked in at ${a.in_at.slice(11)}${a.out_at ? `, out at ${a.out_at.slice(11)}` : ""}` : "Not clocked in today",
    `<button class="btn" data-act="clock" ${a && a.out_at ? "disabled" : ""}>${a ? t("Clock out") : t("Clock in")}</button>`)}
  ${card("Language", "Navigation and common buttons", `<select data-change="setLang">${[["en", "English"], ["hi", "हिन्दी"], ["te", "తెలుగు"], ["ta", "தமிழ்"]].map(([k, l]) => `<option value="${k}" ${me.lang === k ? "selected" : ""}>${l}</option>`).join("")}</select>`)}
  ${card("Password", "At least 8 characters", `<form data-submit="changePw" class="stack"><input type="password" name="old" placeholder="Current password" autocomplete="current-password"><input type="password" name="new" placeholder="New password" autocomplete="new-password"><button class="btn">Change password</button></form>`)}
  ${card("Two-step sign-in", me.has_2fa ? "On. A code from your phone is needed at every sign-in." : "Off. Recommended for owners, managers and accountants.",
    me.has_2fa ? `<form data-submit="tfaOff" class="stack"><input name="code" inputmode="numeric" placeholder="Current 6-digit code"><button class="btn ghost">Turn off</button></form>` : `<button class="btn" data-act="tfaSetup">Set up</button><div id="tfaBox"></div>`)}
  </div>${att.rows ? card("Staff attendance this month", "", tbl(["Date", "Staff", "Role", "Branch", "In", "Out"], att.rows.map(r => `<tr><td class="mono">${r.day}</td><td>${esc(r.name)}</td><td>${r.role}</td><td>${esc(r.code || "")}</td><td class="mono">${(r.in_at || "").slice(11)}</td><td class="mono">${(r.out_at || "").slice(11) || "–"}</td></tr>`).join(""))) : ""}
  <div id="myAlerts"></div>`;
  const al = await api("/api/alerts");
  $("#myAlerts").innerHTML = al.length ? card("Alerts for you", "", al.map(x => alertRow("high", `<span class="mono small">${x.at}</span> ${esc(x.body)}`)).join("")) : "";
};
on("clock", async () => { const r = await api("/api/attendance", {}); toast(r.state === "in" ? "Clocked in" : "Clocked out"); go("me"); });
on("setLang", async el => { await api("/api/me/lang", { lang: el.value }); await start(); go("me"); });
on("changePw", async f => { await api("/api/password", vals(f)); f.reset(); toast("Password changed. Other devices were signed out."); });
on("tfaSetup", async () => {
  const r = await api("/api/2fa/setup", {});
  $("#tfaBox").innerHTML = `<div class="stack" style="margin-top:10px"><p class="small">In Google Authenticator or Microsoft Authenticator choose <b>Enter a setup key</b>, and type this key:</p>
  <p class="mono" style="font-size:15px;letter-spacing:.08em;word-break:break-all">${esc(r.secret.match(/.{1,4}/g).join(" "))}</p>
  <form data-submit="tfaEnable" class="stack"><input name="code" inputmode="numeric" placeholder="6-digit code from the app"><button class="btn">Turn on</button></form></div>`;
});
on("tfaEnable", async f => { await api("/api/2fa/enable", vals(f)); toast("Two-step sign-in is on."); await start(); go("me"); });
on("tfaOff", async f => { await api("/api/2fa/disable", vals(f)); toast("Two-step sign-in is off."); await start(); go("me"); });
