/* Patient tracker: every patient at the branch today and the step each one is at. Stuck patients first. */
"use strict";
const TRK_ICON = { done: "✓", now: "●", pending: "○", late: "!", na: "–" };
RENDER.tracker = async (main) => {
  const d = await api("/api/tracker?date=" + (App.cache.trkDay || localDay())), tab = App.cache.trkTab || "opd", f = App.cache.trkF || "all";
  const list = (tab === "opd" ? d.opd : d.ipd).filter(r => f === "all" || (f === "stuck" ? r.stuck.length : f === "open" ? !r.done : r.done));
  const k = d.counts;
  main.innerHTML = `<div class="kpis">${kpi("Stuck", k.stuck, "patients need attention", k.stuck ? "crit" : "")}${kpi("Waiting for doctor", k.waiting_doctor, "OPD")}
      ${kpi("OPD today", `${k.opd_done} / ${k.opd}`, "finished")}${kpi("Inpatients", k.ipd, "in hospital now")}</div>
    <div class="trk-bar">${subtabs([["opd", `Outpatients (${d.opd.length})`], ["ipd", `Inpatients (${d.ipd.length})`]], tab, "trkTab")}
      ${subtabs([["all", "All"], ["stuck", "Stuck"], ["open", "In progress"], ["done", "Finished"]], f, "trkF")}
      <input type="date" value="${d.day}" max="${localDay()}" data-change="trkDay" aria-label="Date"><button class="btn sm ghost" data-act="go" data-v="tracker">Refresh</button></div>
    <div class="trk">${list.map(r => `<div class="card trk-row${r.stuck.length ? " stuck" : r.done ? " fin" : ""}">
      <div class="trk-h"><div style="min-width:0"><b>${esc(r.name)}</b> <span class="small muted mono">${r.code}</span>${r.token ? ` <span class="pill p-info">Token ${r.token}</span>` : ""}${r.ip_no ? ` <span class="pill p-info">${esc(r.ip_no)}</span>` : ""}${r.triage === "critical" ? ` <span class="pill p-crit">critical</span>` : ""}
        <div class="small muted">${r.age ?? "?"}${(r.gender || " ")[0]} · ${esc(r.complaint || "")}${r.doctor ? " · " + esc(r.doctor) : ""} · since ${esc(r.since.length > 5 ? r.since.slice(5).replace("-", "/") : r.since)}</div></div>
        <div class="trk-now ${r.stuck.length ? "bad" : r.done ? "ok" : ""}">${esc(r.now)}</div></div>
      <ol class="trk-steps">${r.steps.map(s => `<li class="s-${s.state}" title="${esc(s.note)}"><span class="dot">${TRK_ICON[s.state]}</span><span class="lbl">${esc(s.label)}${s.at ? ` <span class="mono">${s.at}</span>` : ""}</span>${s.note ? `<span class="small muted">${esc(s.note)}</span>` : ""}</li>`).join("")}</ol>
      ${r.stuck.length ? `<div class="trk-why">${r.stuck.map(x => `<span>⚠ ${esc(x)}</span>`).join("")}</div>` : ""}
      <div class="row-actions">${can("hbilling") && r.kind !== "ipd" && (r.steps || []).some(s => s.key === "bill" && s.state === "late") ? `<button class="btn sm" data-act="go" data-v="hbilling" data-p="new/${r.patient_id}">Collect payment</button>` : ""}<button class="btn sm ghost" data-act="go" data-v="patients" data-p="${r.patient_id}">Patient</button>${r.kind === "ipd" ? [
        ["doctor", "owner"].includes(App.me.role) ? `<button class="btn sm" data-act="go" data-v="ipd" data-p="a/${r.id}/care">Write round note</button><button class="btn sm ghost" data-act="go" data-v="ipd" data-p="a/${r.id}/mar">Order medicines</button>` : "",
        can("ipd_nursing") && App.me.role !== "owner" ? `<button class="btn sm" data-act="go" data-v="ipd" data-p="a/${r.id}/mar">Give medicines</button><button class="btn sm ghost" data-act="go" data-v="ipd" data-p="a/${r.id}/care">Vitals and notes</button>` : "",
        can("hbilling") && (r.steps || []).some(s => s.key === "advance" && s.state !== "done") ? `<button class="btn sm ghost" data-act="go" data-v="ipd" data-p="a/${r.id}/bill">Take deposit</button>` : "",
        can("ipd") || can("admit") ? `<button class="btn sm ghost" data-act="go" data-v="ipd" data-p="a/${r.id}">Admission</button>` : ""].join("") : ""}
        ${r.phone ? `<span class="small muted mono">${esc(r.phone)}</span>` : ""}</div></div>`).join("") || `<div class="card"><p class="empty">${f === "stuck" ? "Nobody is stuck. All moving." : "No patients here."}</p></div>`}</div>`;
};
on("trkTab", el => { App.cache.trkTab = el.dataset.k; go("tracker"); });
on("trkF", el => { App.cache.trkF = el.dataset.k; go("tracker"); });
on("trkDay", el => { App.cache.trkDay = el.value; go("tracker"); });
