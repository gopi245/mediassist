/* Bed board: every bed on one screen for the whole team. Free, occupied, cleaning and blocked, ward by ward,
   cleaning timers, expected discharges, refreshed on its own every 30 seconds. */
"use strict";
const BED_LABEL = { free: "Free", occupied: "Occupied", cleaning: "Cleaning", blocked: "Blocked" };
const STALE_CLEAN_MIN = 45;

function bedCard(b, opts = {}) {
  const tag = `<span class="num-tag">${esc(b.number)} · ${b.kind}${opts.branch ? " · " + esc(b.bcode) : ""}</span>`;
  if (b.status === "occupied") {
    const who = b.pname ? `<b>${esc(b.pname)}</b><span class="small muted">${b.age ?? "?"}${(b.gender || " ")[0]} · ${esc(b.diagnosis || "")}</span>` : `<b>Occupied</b>`;
    const soon = b.planned_discharge ? `<span class="small ${b.planned_discharge <= localDay() ? "allergy" : "muted"}">${b.planned_discharge <= localDay() ? "Discharge expected today" : "Discharge planned " + b.planned_discharge.slice(5)}</span>` : "";
    const inner = `${tag}${who}<span class="small muted">${esc(b.dname || "")}${b.admitted_at ? " · since " + b.admitted_at.slice(5, 10) : ""}</span>${soon}`;
    return b.adm_id && (can("ipd") || can("admit")) ? `<button class="bed occupied" data-act="go" data-v="ipd" data-p="a/${b.adm_id}">${inner}</button>` : `<div class="bed occupied">${inner}</div>`;
  }
  const mins = b.status === "cleaning" && b.minutes != null ? b.minutes : null;
  const stale = mins != null && mins >= STALE_CLEAN_MIN;
  const acts = [];
  if (can("admit") && b.status === "free") acts.push(`<button class="btn sm" data-act="bedAdmit" data-id="${b.id}" data-b="${b.branch_id}">Admit here</button>`);
  if ((can("ipd_nursing") || can("admit")) && b.status !== "free") acts.push(`<button class="btn sm ${stale ? "" : "ghost"}" data-act="bedFree" data-id="${b.id}">Mark free</button>`);
  if ((can("ipd_nursing") || can("admit")) && b.status === "free") acts.push(`<button class="btn sm ghost" data-act="bedBlock" data-id="${b.id}" title="Take this bed out of use (repair, isolation, reserved)">Block</button>`);
  return `<div class="bed ${b.status}${stale ? " stale" : ""}">${tag}<b>${BED_LABEL[b.status] || b.status}</b>${mins != null ? `<span class="small ${stale ? "allergy" : "muted"}">${mins < 60 ? mins + " min" : Math.floor(mins / 60) + " h " + (mins % 60) + " min"} ago${stale ? " · needs attention" : ""}</span>` : ""}${acts.length ? `<div class="row-actions">${acts.join("")}</div>` : ""}</div>`;
}

RENDER.beds = async (main, [wardSel]) => {
  const beds = await api("/api/beds" + (App.me.branch ? "" : "?all=1"));
  const org = !App.me.branch;
  const ward = wardSel || App.cache.bedWard || "";
  App.cache.bedWard = ward;
  const wards = [...new Set(beds.map(b => (org ? b.bcode + " · " : "") + b.ward))];
  const shown = ward ? beds.filter(b => (org ? b.bcode + " · " : "") + b.ward === ward) : beds;
  const n = s => shown.filter(b => b.status === s).length;
  const stale = shown.filter(b => b.status === "cleaning" && b.minutes >= STALE_CLEAN_MIN).length;
  const today = shown.filter(b => b.status === "occupied" && b.planned_discharge && b.planned_discharge <= localDay()).length;
  const groups = {};
  shown.forEach(b => { const k = (org ? b.bcode + " · " : "") + b.ward; (groups[k] = groups[k] || []).push(b); });
  main.innerHTML = `<div class="kpis">${kpi("Available", n("free"), "ready for admission", n("free") ? "" : "crit")}${kpi("Occupied", n("occupied"), `of ${shown.length} beds${today ? ` · ${today} discharge${today > 1 ? "s" : ""} expected today` : ""}`)}${kpi("Cleaning", n("cleaning"), stale ? `${stale} waiting over ${STALE_CLEAN_MIN} min` : "mark free when ready", stale ? "warn" : "")}${kpi("Blocked", n("blocked"), "")}</div>
    <div class="row-actions" style="margin-bottom:12px"><select data-change="bedWard" style="width:auto"><option value="">All wards</option>${wards.map(w => `<option ${w === ward ? "selected" : ""}>${esc(w)}</option>`).join("")}</select><span class="small muted">Updates by itself every 30 s · last ${new Date().toTimeString().slice(0, 5)}</span>${can("ipd") && !org ? `<button class="btn sm ghost" data-act="go" data-v="ipd">Inpatients</button>` : ""}</div>
    ${Object.entries(groups).map(([w, l]) => card(`${esc(w)}`, `${l.filter(b => b.status === "free").length} free · ${l.filter(b => b.status === "occupied").length} occupied · ${l.filter(b => b.status === "cleaning").length} cleaning · ${l.length} beds`, `<div class="beds">${l.map(b => bedCard(b, { branch: org })).join("")}</div>`)).join("") || card("No beds yet", "", `<p class="empty">${can("stock_admin") ? "Add wards and beds in Inpatients." : "No beds have been set up for this branch."}</p>`)}`;
};
on("bedWard", el => { App.cache.bedWard = el.value; go("beds"); });
on("bedFree", async el => { await api(`/api/beds/${el.dataset.id}/status`, { status: "free" }); toast("Bed is free"); go(App.view, App.params); });
on("bedBlock", async el => { const v = await dialog("Block this bed", `<label>Why</label><input name="reason" placeholder="repair, isolation, reserved">`, { ok: "Block" }); if (v) { await api(`/api/beds/${el.dataset.id}/status`, { status: "blocked", reason: v.reason }); go(App.view, App.params); } });
on("bedAdmit", async el => {
  try { sessionStorage.setItem("ma-admit-bed", el.dataset.id); } catch (e) {}
  App.cache.admitBed = +el.dataset.id;
  if (!App.me.branch || (App.me.branch.id !== +el.dataset.b)) {  // viewing all branches: step into the bed's branch first
    await api("/api/branch", { branch_id: +el.dataset.b }); location.hash = "#ipd/admit"; await start(); return;
  }
  go("ipd", ["admit"]);
});
on("planDischarge", async el => {
  const v = await dialog("Expected discharge", `<label>Date</label><input name="planned_discharge" type="date" value="${esc(el.dataset.d || localDay(1))}"><p class="small muted">Shows on the bed board so the team knows which beds free up soon. Clear the date to remove it.</p>`, { ok: "Save" });
  if (v) { await api(`/api/admissions/${el.dataset.id}/plan`, v); reAdm(); }
});
/* auto refresh while the board is open */
setInterval(() => { if (App.me && App.view === "beds" && document.visibilityState === "visible" && $("#overlay").hidden) RENDER.beds($("#view"), App.params).catch(() => {}); }, 30000);

/* dashboard card for hospital branches: free beds by ward and stalled cleaning */
async function bedsCard(main) {
  let beds; try { beds = await api("/api/beds"); } catch (e) { return; }
  if (!beds.length) return;
  const wards = {}; beds.forEach(b => { const w = wards[b.ward] = wards[b.ward] || { free: 0, total: 0, cleaning: 0, stale: 0 }; w.total++; if (b.status === "free") w.free++; if (b.status === "cleaning") { w.cleaning++; if (b.minutes >= STALE_CLEAN_MIN) w.stale++; } });
  const box = document.createElement("div"); box.style.marginTop = "14px";
  box.innerHTML = card("Beds", `${beds.filter(b => b.status === "free").length} free of ${beds.length}`, tbl(["Ward", "Free", "Cleaning", "Total"], Object.entries(wards).map(([w, x]) => `<tr><td>${esc(w)}</td><td class="num"><b style="color:${x.free ? "var(--ok)" : "var(--crit)"}">${x.free}</b></td><td class="num">${x.cleaning}${x.stale ? ` <span class="allergy small">${x.stale} over ${STALE_CLEAN_MIN} min</span>` : ""}</td><td class="num">${x.total}</td></tr>`).join("")),
    `<button class="btn sm ghost" data-act="go" data-v="beds">Open bed board</button>`);
  main.appendChild(box);
}
