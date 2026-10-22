/* Staff watch: cancellations, refunds, returns, discounts and stock reductions, with who did them and why they
   stand out. For owners and managers (audit permission). */
"use strict";
const watchReasons = it => it.reasons.length ? it.reasons.map(r => pill(r, it.high ? "p-crit" : "p-warn")).join(" ") : '<span class="small muted">routine</span>';
const watchRow = it => `<tr${it.high ? ' class="flag-high"' : ""}><td class="mono small">${esc(it.at.slice(5, 16).replace("-", "/"))}</td><td><b>${esc(it.user)}</b>${it.branch ? `<div class="small muted">${esc(it.branch)}</div>` : ""}</td>
  <td>${esc(it.label)}<div class="small mono">${esc(it.ref || "")}</div></td><td class="num"><b>${money(it.amount)}</b></td><td class="small">${esc(it.detail || "")}</td><td>${watchReasons(it)}</td>
  <td class="row-actions">${it.link ? `<button class="btn sm ghost" data-act="go" data-v="${it.link.view}" data-p="${esc(it.link.p)}">Open</button>` : ""}<button class="btn sm ghost" data-act="watchAudit" data-q="${esc(it.ref || it.user)}">Audit</button></td></tr>`;
const WATCH_HEAD = ["When", "Staff", "What", "Amount", "Details", "Why it's flagged", ""];

REP.watch = async el => {
  const days = App.cache.watchDays || 1, w = await api("/api/watch?days=" + days), only = App.cache.watchFlagged !== false;
  const list = only ? w.items.filter(x => x.reasons.length) : w.items;
  el.innerHTML = `<div class="fields" style="margin-bottom:12px"><div><label>Period</label><select data-change="watchDays">${[[1, "Today"], [7, "Last 7 days"], [30, "Last 30 days"]].map(([v, l]) => `<option value="${v}" ${v === days ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <div style="align-self:end"><label class="check"><input type="checkbox" data-change="watchFlagged" ${only ? "checked" : ""}> Only flagged items</label></div></div>
    <div class="kpis">${kpi("Flagged", w.flagged, `${w.high} need a closer look`, w.high ? "crit" : w.flagged ? "warn" : "")}${w.totals.map(t => kpi(t.label, money(t.amount), `${t.count} time${t.count > 1 ? "s" : ""}`)).join("")}</div>
    ${card("By staff member", "Who cancelled, refunded, discounted or reduced stock in this period", tbl(["Staff", "Actions", "Flagged", "Amount", "Breakdown"],
      w.staff.map(s => `<tr><td><b>${esc(s.user)}</b></td><td class="num">${s.count}</td><td class="num">${s.flagged ? `<b style="color:var(--crit)">${s.flagged}</b>` : 0}</td><td class="num">${money(s.amount)}</td>
        <td class="small">${Object.entries(s.kinds).map(([k, n]) => `${esc(k)} ×${n}`).join(", ")}</td></tr>`).join(""), "Nothing to show for this period."))}
    ${card(only ? "Flagged items" : "Everything", "Each flag says why it stands out. Most will have an innocent reason; the point is that none go unseen.", tbl(WATCH_HEAD, list.map(watchRow).join(""), only ? "Nothing flagged. All clear." : "Nothing in this period."))}`;
};
on("watchDays", el => { App.cache.watchDays = +el.value; go("reports", ["watch"]); });
on("watchFlagged", el => { App.cache.watchFlagged = el.checked; go("reports", ["watch"]); });
on("watchAudit", el => { App.cache.auQ = el.dataset.q; go("admin", ["audit"]); });

/* dashboard card: today's flagged items */
async function watchCard(main) {
  let w; try { w = await api("/api/watch?days=1"); } catch (e) { return; }
  const f = w.items.filter(x => x.reasons.length);
  const box = document.createElement("div"); box.style.marginTop = "14px";
  box.innerHTML = card("Staff watch today", f.length ? `${f.length} flagged · ${w.items.length} cancellations, refunds, discounts and stock cuts in all` : `${w.items.length} routine actions, nothing flagged`,
    f.length ? tbl(WATCH_HEAD, f.slice(0, 6).map(watchRow).join("")) + (f.length > 6 ? `<p class="small muted">${f.length - 6} more in Reports.</p>` : "") : '<p class="empty">All clear.</p>',
    `<button class="btn sm ghost" data-act="go" data-v="reports" data-p="watch">Open Staff watch</button>`);
  main.appendChild(box);
}
