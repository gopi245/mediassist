/* MediAssist core: API client with offline outbox, router, actions, dialogs, i18n, formatting. */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = n => "₹" + Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const rupees = n => { n = Number(n || 0); return n >= 100000 ? "₹" + (n / 100000).toFixed(1) + "L" : n >= 1000 ? "₹" + (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : "₹" + Math.round(n); };
const P2R = p => (p || 0) / 100;
const localDay = (o = 0) => { const d = new Date(Date.now() + o * 864e5); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
const shortDay = d => new Date(d.slice(0, 10) + "T12:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });
const pill = (t, c) => `<span class="pill ${c}">${esc(t)}</span>`;
const triPill = t => pill(t || "normal", t === "critical" ? "p-crit" : t === "urgent" ? "p-warn" : "p-ok");
const initials = n => String(n || "?").replace(/^Dr\.?\s*/i, "").split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
const debounce = (f, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => f(...a), ms); }; };
const pidOf = v => { const m = String(v || "").match(/^P0*(\d+)/i); return m ? +m[1] : null; };

/* ---------------- state ---------------- */
const App = { me: null, view: "dashboard", params: {}, cache: {} };
const can = p => !!App.me && App.me.perms.includes(p);
const kind = () => (App.me && App.me.branch ? App.me.branch.kind : "");

/* ---------------- i18n (navigation, buttons and common labels) ---------------- */
const I18N = {
  hi: { Dashboard: "डैशबोर्ड", Patients: "मरीज़", "OPD & appointments": "ओपीडी और अपॉइंटमेंट", Consultation: "परामर्श", Laboratory: "लैब", Inpatients: "भर्ती मरीज़",
    "Pharmacy billing": "फार्मेसी बिल", Stock: "स्टॉक", "Hospital billing": "अस्पताल बिल", Documents: "दस्तावेज़", Accounts: "खाते", Reports: "रिपोर्ट", Admin: "प्रशासन",
    Save: "सेव करें", Cancel: "रद्द करें", Search: "खोजें", "Sign out": "साइन आउट", "My account": "मेरा खाता", Branch: "शाखा", "All branches": "सभी शाखाएँ",
    "Signed in as": "साइन इन", "Clock in": "हाज़िरी लगाएँ", "Clock out": "छुट्टी दर्ज करें", Offline: "ऑफ़लाइन", "waiting to sync": "सिंक होना बाकी" },
  te: { Dashboard: "డాష్‌బోర్డ్", Patients: "రోగులు", "OPD & appointments": "ఓపీడీ & అపాయింట్‌మెంట్లు", Consultation: "సంప్రదింపు", Laboratory: "ల్యాబ్", Inpatients: "ఇన్‌పేషెంట్లు",
    "Pharmacy billing": "ఫార్మసీ బిల్లు", Stock: "స్టాక్", "Hospital billing": "ఆసుపత్రి బిల్లు", Documents: "పత్రాలు", Accounts: "ఖాతాలు", Reports: "నివేదికలు", Admin: "నిర్వహణ",
    Save: "సేవ్ చేయండి", Cancel: "రద్దు", Search: "వెతకండి", "Sign out": "సైన్ అవుట్", "My account": "నా ఖాతా", Branch: "శాఖ", "All branches": "అన్ని శాఖలు",
    "Signed in as": "సైన్ ఇన్", "Clock in": "హాజరు", "Clock out": "బయటకు", Offline: "ఆఫ్‌లైన్", "waiting to sync": "సింక్ కావాలి" },
  ta: { Dashboard: "டாஷ்போர்டு", Patients: "நோயாளிகள்", "OPD & appointments": "ஓபிடி & முன்பதிவு", Consultation: "ஆலோசனை", Laboratory: "ஆய்வகம்", Inpatients: "உள்நோயாளிகள்",
    "Pharmacy billing": "மருந்தக பில்", Stock: "இருப்பு", "Hospital billing": "மருத்துவமனை பில்", Documents: "ஆவணங்கள்", Accounts: "கணக்குகள்", Reports: "அறிக்கைகள்", Admin: "நிர்வாகம்",
    Save: "சேமி", Cancel: "ரத்து", Search: "தேடு", "Sign out": "வெளியேறு", "My account": "என் கணக்கு", Branch: "கிளை", "All branches": "அனைத்து கிளைகள்",
    "Signed in as": "உள்நுழைந்தவர்", "Clock in": "வருகை", "Clock out": "வெளியேற்றம்", Offline: "இணைப்பு இல்லை", "waiting to sync": "ஒத்திசைக்க காத்திருக்கிறது" },
};
const t = s => (App.me && I18N[App.me.lang] && I18N[App.me.lang][s]) || s;

/* ---------------- API with offline outbox ---------------- */
class ApiError extends Error { constructor(msg, status, data) { super(msg); this.status = status; this.data = data || {}; } }
const OUTBOX = "mediassist-outbox";
const outbox = { list() { try { return JSON.parse(localStorage.getItem(OUTBOX) || "[]"); } catch (e) { return []; } },
  save(l) { try { localStorage.setItem(OUTBOX, JSON.stringify(l)); } catch (e) {} renderSync(); },
  add(item) { const l = this.list(); l.push(item); this.save(l); } };

async function api(path, body, opts = {}) {
  const init = body === undefined ? { headers: {} } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  if (opts.key) init.headers["Idempotency-Key"] = opts.key;
  let r;
  try { r = await fetch(path, init); }
  catch (e) { throw new ApiError("No connection to the server.", 0); }
  if (opts.raw) { if (!r.ok) throw new ApiError((await r.json().catch(() => ({}))).error || "Download failed", r.status); return r; }
  const data = await r.json().catch(() => ({ error: "Unexpected response from the server" }));
  if (r.status === 401 && !path.startsWith("/api/login") && !path.startsWith("/api/2fa/verify")) { showLogin(data.mfa_required); throw new ApiError(data.error || "Please sign in", 401, data); }
  if (!r.ok) throw new ApiError(data.error || "Error", r.status, data);
  return data;
}
/* Save that survives a dropped connection: queued and retried with the same idempotency key. */
async function apiSafe(path, body, label) {
  const key = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).replace(/-/g, "");
  body = { ...body, offline_key: body.offline_key || key };
  try { return await api(path, body, { key }); }
  catch (e) {
    if (e.status !== 0) throw e;
    outbox.add({ path, body, key, label, at: new Date().toISOString() });
    toast(`${label} saved on this device. It will sync when the connection is back.`);
    return { queued: true };
  }
}
async function flushOutbox() {
  const l = outbox.list(); if (!l.length || !navigator.onLine) return;
  const left = [];
  for (const it of l) {
    try { await api(it.path, it.body, { key: it.key }); }
    catch (e) { if (e.status === 0) left.push(it); else { left.push({ ...it, error: e.message }); } }
  }
  outbox.save(left);
  if (left.length < l.length) toast(`${l.length - left.length} saved item(s) synced to the server.`);
}
function renderSync() {
  const el = $("#syncChip"); if (!el) return;
  const n = outbox.list().length, off = !navigator.onLine;
  el.hidden = !n && !off;
  el.textContent = off ? `${t("Offline")}${n ? ` · ${n} ${t("waiting to sync")}` : ""}` : `${n} ${t("waiting to sync")}`;
}
addEventListener("online", () => { renderSync(); flushOutbox(); });
addEventListener("offline", renderSync);
setInterval(flushOutbox, 30000);

async function download(path, filename) {
  try {
    const r = await api(path, undefined, { raw: true });
    const blob = await r.blob(), a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = filename || (r.headers.get("Content-Disposition") || "").split("''")[1] || "download";
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  } catch (e) { toast(e.message); }
}

/* ---------------- actions (CSP-safe event delegation) ---------------- */
const ACTIONS = {};
const on = (name, fn) => { ACTIONS[name] = fn; };
document.addEventListener("click", e => {
  const el = e.target.closest("[data-act]"); if (!el || el.disabled) return;
  const fn = ACTIONS[el.dataset.act]; if (!fn) return;
  e.preventDefault();
  Promise.resolve(fn(el, e)).catch(err => { console.error(err); toast(err.message || "Something went wrong"); });
});
document.addEventListener("submit", e => { const f = e.target.closest("form[data-submit]"); if (f) { e.preventDefault(); const fn = ACTIONS[f.dataset.submit]; fn && Promise.resolve(fn(f, e)).catch(err => toast(err.message)); } });
document.addEventListener("change", e => { const el = e.target.closest("[data-change]"); if (el && ACTIONS[el.dataset.change]) Promise.resolve(ACTIONS[el.dataset.change](el, e)).catch(err => toast(err.message)); });
document.addEventListener("input", e => { const el = e.target.closest("[data-input]"); if (el && ACTIONS[el.dataset.input]) ACTIONS[el.dataset.input](el, e); });

/* Collect [name] fields inside a container into an object (checkbox -> boolean). */
function vals(root) {
  const o = {};
  $$("[name]", root).forEach(el => { if (el.type === "checkbox") o[el.name] = el.checked; else if (el.type === "radio") { if (el.checked) o[el.name] = el.value; } else o[el.name] = el.value.trim(); });
  return o;
}
async function withBusy(btn, fn) { const old = btn.textContent; btn.disabled = true; btn.textContent = "Working…"; try { return await fn(); } finally { btn.disabled = false; btn.textContent = old; } }

/* ---------------- feedback ---------------- */
let toastT;
function toast(msg) { const el = $("#toast"); el.textContent = msg; el.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => el.hidden = true, 4500); }
function dialog(title, bodyHtml, { ok = "Continue", danger = false, cancel = "Cancel", wide = false } = {}) {
  return new Promise(res => {
    const ov = $("#overlay"); $("#mTitle").textContent = title; $("#mBody").innerHTML = bodyHtml;
    const okb = $("#mOk"); okb.textContent = ok; okb.className = "btn" + (danger ? " danger" : ""); okb.hidden = !ok;
    $("#mCancel").textContent = cancel; ov.querySelector(".card").classList.toggle("wide", wide);
    ov.hidden = false; (ov.querySelector("input,select,textarea") || okb).focus();
    const done = v => { ov.hidden = true; okb.onclick = null; $("#mCancel").onclick = null; res(v); };
    okb.onclick = () => done(vals($("#mBody")));
    $("#mCancel").onclick = () => done(null);
  });
}
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#overlay").hidden) $("#mCancel").click(); });
const warnHtml = ws => ws.map(w => `<div class="alert ${w.severity === "high" ? "high" : ""}"><span class="ic">!</span><div class="t"><b>${w.severity === "high" ? "High risk" : "Caution"}</b> · ${esc(w.text)}</div></div>`).join("");
const alertRow = (k, html) => `<div class="alert ${k}"><span class="ic">${k === "info" ? "i" : "!"}</span><div class="t">${html}</div></div>`;
/* Run a save that may return 409 safety warnings: ask, then retry with override. */
async function withOverride(fn, title = "Review safety warnings") {
  try { return await fn(false); }
  catch (e) {
    if (e.status !== 409 || !e.data.warnings) throw e;
    const ok = await dialog(title, warnHtml(e.data.warnings) + `<p class="small muted">Continuing records that you reviewed these warnings. It goes in the audit trail.</p>`, { ok: "Reviewed, continue", danger: true });
    if (!ok) return null;
    return await fn(true);
  }
}

/* ---------------- tiny chart helpers (SVG) ---------------- */
function sparkline(vals_, color = "var(--accent)") {
  const W = 200, H = 34, max = Math.max(1, ...vals_), n = Math.max(2, vals_.length), x = i => i * (W - 6) / (n - 1) + 3, y = v => H - 3 - (H - 8) * v / max;
  const pts = vals_.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><polygon points="3,${H} ${pts} ${x(vals_.length - 1)},${H}" fill="${color}" opacity=".12"/><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}
function niceMax(v) { const p = Math.pow(10, Math.floor(Math.log10(Math.max(v, 1)))); for (const f of [1, 2, 2.5, 5, 10]) if (f * p >= v) return f * p; return v; }
/* Line chart with hover crosshair. series: [{name, color(css var), values}] */
function lineChart(host, labels, series, fmt = rupees) {
  const draw = () => {
    const W = Math.max(300, host.clientWidth || 600), H = 240, m = { l: 52, r: W < 520 ? 12 : 100, t: 12, b: 28 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
    const max = niceMax(Math.max(1, ...series.flatMap(s => s.values))), x = i => m.l + iw * i / Math.max(1, labels.length - 1), y = v => m.t + ih * (1 - v / max);
    let g = ""; for (let k = 0; k <= 4; k++) { const v = max * k / 4; g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="${k ? "var(--grid)" : "var(--axis)"}"/><text x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`; }
    labels.forEach((d, i) => { if (i % (W < 520 ? 4 : 2) === 0 || i === labels.length - 1) g += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${i === labels.length - 1 ? "Today" : shortDay(d)}</text>`; });
    let p = ""; const ends = [];
    series.forEach(s => { p += `<polyline points="${s.values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")}" fill="none" stroke="var(${s.color})" stroke-width="2" stroke-linejoin="round"/>`; const L = s.values.length - 1; p += `<circle cx="${x(L)}" cy="${y(s.values[L])}" r="4" fill="var(${s.color})" stroke="var(--surface)" stroke-width="2"/>`; ends.push({ s, y: y(s.values[L]) }); });
    if (W >= 520) { ends.sort((a, b) => a.y - b.y); for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 15) ends[i].y = ends[i - 1].y + 15; ends.forEach(e => p += `<text class="lbl" x="${W - m.r + 10}" y="${e.y + 4}">${esc(e.s.name)}</text>`); }
    host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Chart">${g}${p}<line class="xh" y1="${m.t}" y2="${H - m.b}" stroke="var(--axis)" visibility="hidden"/><g class="xd"></g><rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent" class="hit"/></svg><div class="tip" hidden></div>`;
    const svg = $("svg", host), tip = $(".tip", host), xh = $(".xh", host), xd = $(".xd", host), hit = $(".hit", host);
    hit.addEventListener("mousemove", e => {
      const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * W / r.width, i = Math.max(0, Math.min(labels.length - 1, Math.round((px - m.l) / iw * (labels.length - 1))));
      xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.setAttribute("visibility", "visible");
      xd.innerHTML = series.map(s => `<circle cx="${x(i)}" cy="${y(s.values[i])}" r="4" fill="var(${s.color})" stroke="var(--surface)" stroke-width="2"/>`).join("");
      tip.hidden = false; tip.innerHTML = `<b>${i === labels.length - 1 ? "Today" : shortDay(labels[i])}</b><br>` + series.map(s => `<span class="sw" style="background:var(${s.color})"></span>${esc(s.name)}: ${fmt === rupees ? money(s.values[i]) : s.values[i]}`).join("<br>");
      const k = host.clientWidth / W; tip.style.left = Math.min(Math.max(x(i) * k, 90), host.clientWidth - 90) + "px"; tip.style.top = (Math.min(...series.map(s => y(s.values[i]))) * k - 10) + "px";
    });
    hit.addEventListener("mouseleave", () => { tip.hidden = true; xh.setAttribute("visibility", "hidden"); xd.innerHTML = ""; });
  };
  draw(); host._redraw = draw;
}
addEventListener("resize", debounce(() => $$(".chart").forEach(c => c._redraw && c.offsetParent && c._redraw()), 200));
function bars(list, max, fmt = money) { max = Math.max(1, max); return `<div class="bars">${list.map(([l, v]) => `<div class="row"><span>${esc(l)}</span><div class="track"><div class="fill" style="width:${(Math.max(0, v) / max * 100).toFixed(1)}%"></div></div><span class="v">${fmt(v)}</span></div>`).join("") || '<p class="empty">Nothing recorded.</p>'}</div>`; }

/* ---------------- pickers ---------------- */
async function patientOptions(q) {
  if (!q || q.length < 2) return;
  const l = await api("/api/patients?q=" + encodeURIComponent(q.replace(/\s·.*$/, "")));
  $("#patOpts").innerHTML = l.map(p => `<option value="${p.code} · ${esc(p.name)} · ${esc(p.phone)}">`).join("");
}
on("patSearch", debounce(el => patientOptions(el.value), 250));
async function loadMeds(force) {
  if (!App.cache.meds || force) App.cache.meds = await api("/api/medicines");
  $("#medOpts").innerHTML = App.cache.meds.map(m => `<option value="${esc(m.name)}">${esc(m.generic || "")} · ${m.schedule}${kind().includes("pharmacy") ? " · stock " + m.stock : ""}</option>`).join("");
  return App.cache.meds;
}
const medByName = n => (App.cache.meds || []).find(m => m.name.toLowerCase() === String(n || "").trim().toLowerCase());
async function loadServices(force) {
  if (!App.cache.services || force) App.cache.services = await api("/api/services");
  $("#svcOpts").innerHTML = App.cache.services.map(s => `<option value="${esc(s.name)}">${esc(s.cat)} · ${money(P2R(s.rate_p))}</option>`).join("");
  return App.cache.services;
}
const svcByName = n => (App.cache.services || []).find(s => s.name.toLowerCase() === String(n || "").trim().toLowerCase());
async function staff(role) { const k = "staff_" + role; if (!App.cache[k]) App.cache[k] = await api("/api/staff?role=" + role); return App.cache[k]; }
const patInput = (name = "patient", value = "", label = "Patient") => `<div class="span2"><label>${label}</label><input name="${name}" list="patOpts" data-input="patSearch" value="${esc(value)}" placeholder="Type name, phone or ID" autocomplete="off"></div>`;
const docSelect = (docs, name = "doctor_id", sel = "", none = "Any doctor") => `<select name="${name}">${none ? `<option value="">${none}</option>` : ""}${docs.map(d => `<option value="${d.id}" ${String(sel) === String(d.id) ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select>`;
const tbl = (head, rowsHtml, empty = "Nothing here yet.") => `<div class="tbl"><table><tr>${head.map(h => `<th${/^#|₹|Qty|Amount|Total|Due|Paid|Balance|Days|Rate/.test(h) ? ' class="num"' : ""}>${h}</th>`).join("")}</tr>${rowsHtml || `<tr><td colspan="${head.length}" class="empty">${empty}</td></tr>`}</table></div>`;
const kpi = (lab, val, sub = "", cls = "", spark = "") => `<div class="kpi"><span class="lab">${lab}</span><span class="val ${cls}">${val}</span><span class="sub">${sub}</span>${spark}</div>`;
const card = (title, sub, body, right = "") => `<div class="card"><div class="card-h"><div><h2>${title}</h2>${sub ? `<p>${sub}</p>` : ""}</div>${right}</div>${body}</div>`;
const subtabs = (items, cur, act) => `<div class="sub">${items.map(([k, l]) => `<button data-act="${act}" data-k="${k}" class="${k === cur ? "on" : ""}">${l}</button>`).join("")}</div>`;
function printHtml(html) { const box = $("#printArea"); box.innerHTML = html; document.body.classList.add("printing"); setTimeout(() => { print(); document.body.classList.remove("printing"); }, 50); }
