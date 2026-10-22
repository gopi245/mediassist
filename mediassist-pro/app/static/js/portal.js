/* The patient's own records page (/my?t=...). Also used inside the staff app to preview what the patient sees.
   No sign-in: the private link is the key. Nothing here depends on the staff app's scripts. */
"use strict";
(function () {
  const e = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const rs = n => "₹" + Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const when = s => { if (!s) return ""; const d = new Date(s.replace(" ", "T")); return isNaN(d) ? s : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) + (s.length > 10 ? " · " + s.slice(11, 16) : ""); };
  const FLAG = { H: ["High", "p-warn"], L: ["Low", "p-warn"], HH: ["Critical high", "p-crit"], LL: ["Critical low", "p-crit"], A: ["Abnormal", "p-warn"] };
  const FILTERS = [["all", "All"], ["lab", "Reports"], ["rx", "Prescriptions"], ["money", "Bills"], ["discharge", "Discharge"], ["doc", "Documents"]];
  const inFilter = (r, f) => f === "all" || r.kind === f || (f === "money" && (r.kind === "bill" || r.kind === "invoice"));
  const tableP = (head, rows) => `<div class="tbl"><table><tr>${head.map(h => `<th${/₹|Qty/.test(h) ? ' class="num"' : ""}>${h}</th>`).join("")}</tr>${rows}</table></div>`;

  function body(r, fileUrl) {
    if (r.kind === "lab") return r.tests.map(t => `<h3 class="pt-sub">${e(t.name)}</h3>` + tableP(["Test", "Result", "Normal range"], t.params.map(p => {
      const f = FLAG[p.flag]; return `<tr><td>${e(p.name)}</td><td><b>${e(p.value)}</b> ${e(p.unit || "")} ${f ? `<span class="pill ${f[1]}">${f[0]}</span>` : ""}</td><td class="small muted">${e(p.range || "")}</td></tr>`;
    }).join(""))).join("") + `<p class="small muted">Checked by ${e(r.verified_by || "the lab")}. Show this report to your doctor${r.abnormal ? "; results marked High or Low need their review" : ""}.</p>`;
    if (r.kind === "rx") return (r.items.length ? tableP(["Medicine", "How to take", "Days"], r.items.map(i => `<tr><td><b>${e(i.name)}</b>${i.instructions ? `<div class="small muted">${e(i.instructions)}</div>` : ""}</td><td>${e([i.dose, i.freq].filter(Boolean).join(" · "))}</td><td class="num">${i.days ?? ""}</td></tr>`).join("")) : '<p class="small muted">No medicines prescribed.</p>')
      + (Object.keys(r.vitals || {}).length ? `<p class="small muted">Checked at the visit: ${[r.vitals.bp_sys ? `BP ${r.vitals.bp_sys}/${r.vitals.bp_dia}` : "", r.vitals.pulse ? `pulse ${r.vitals.pulse}` : "", r.vitals.temp ? `temp ${Number(r.vitals.temp).toFixed(1)}°C` : "", r.vitals.spo2 ? `SpO₂ ${r.vitals.spo2}%` : "", r.vitals.weight ? `weight ${r.vitals.weight} kg` : "", r.vitals.sugar ? `sugar ${r.vitals.sugar}` : ""].filter(Boolean).join(", ")}</p>` : "")
      + (r.followup ? `<p class="pt-note">Come back on <b>${when(r.followup)}</b>.</p>` : "") + `<p class="small muted">Prescribed by ${e(r.doctor || "")}${r.doctor_reg ? `, reg. ${e(r.doctor_reg)}` : ""}.</p>`;
    if (r.kind === "bill") return tableP(["Medicine", "Qty", "₹"], r.items.map(i => `<tr><td>${e(i.name)}<div class="small muted mono">batch ${e(i.batch || "")} · exp ${e(i.expiry || "")}</div></td><td class="num">${i.qty}</td><td class="num">${rs(i.amount)}</td></tr>`).join("")
      + `<tr><td colspan="2"><b>Total</b>${r.returned ? ` <span class="small muted">(${rs(r.returned)} returned)</span>` : ""}</td><td class="num"><b>${rs(r.total - (r.returned || 0))}</b></td></tr>`) + `<p class="small muted">Paid by ${e(r.pay_mode)}.</p>`;
    if (r.kind === "invoice") return tableP(["Service", "Qty", "₹"], r.items.map(i => `<tr><td>${e(i.name)}</td><td class="num">${i.qty}</td><td class="num">${rs(i.amount)}</td></tr>`).join("")
      + `<tr><td colspan="2"><b>Total</b></td><td class="num"><b>${rs(r.total)}</b></td></tr><tr><td colspan="2">Paid</td><td class="num">${rs(r.paid)}</td></tr>`
      + (r.insurance ? `<tr><td colspan="2">Insurance (waiting)</td><td class="num">${rs(r.insurance)}</td></tr>` : "")
      + (r.due ? `<tr><td colspan="2"><b>Still to pay</b></td><td class="num"><b>${rs(r.due)}</b></td></tr>` : ""));
    if (r.kind === "discharge") { const s = r.summary || {}, L = { final_diagnosis: "Diagnosis", course: "In hospital", procedures: "Procedures", condition: "Condition at discharge", medications: "Medicines to take", advice: "Advice", followup: "Follow-up" };
      return `<p class="small muted">Admitted ${when(r.admitted_at)} under ${e(r.doctor || "")}.</p>` + Object.entries(L).filter(([k]) => s[k]).map(([k, l]) => `<h3 class="pt-sub">${l}</h3><p style="white-space:pre-wrap;margin:0">${e(k === "followup" ? when(s[k]) : s[k])}</p>`).join(""); }
    if (r.kind === "doc") return (r.mime || "").startsWith("image/") ? `<div class="preview"><img src="${fileUrl(r.doc_id)}" alt="${e(r.title)}" loading="lazy"></div>${r.note ? `<p class="small muted">${e(r.note)}</p>` : ""}`
      : `<p><a class="btn sm" href="${fileUrl(r.doc_id)}" target="_blank" rel="noopener">Open the PDF</a></p>${r.note ? `<p class="small muted">${e(r.note)}</p>` : ""}`;
    return "";
  }

  /* data: the /api/portal answer. opts.fileUrl(docId) builds file links; opts.preview marks the staff preview; opts.onPdf(path) replaces PDF links. */
  window.renderPortal = function (root, data, opts = {}) {
    let filter = "all";
    const p = data.patient, fileUrl = opts.fileUrl || (id => `/api/portal/file/${id}?t=${encodeURIComponent(opts.token || "")}`);
    const draw = () => {
      const list = data.records.filter(r => inFilter(r, filter)), counts = Object.fromEntries(FILTERS.map(([k]) => [k, data.records.filter(r => inFilter(r, k)).length]));
      root.innerHTML = `<div class="pt-head"><div class="brand dark"><div class="mark"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M8 2h4v6h6v4h-6v6H8v-6H2V8h6z"/></svg></div><div><b>${e(data.org || "My health records")}</b><span>Your records, ready the moment they are</span></div></div></div>
        <div class="card pt-me"><div class="avatar">${e(String(p.name || "?").split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase())}</div><div style="min-width:0"><h2>${e(p.name)}</h2>
          <div class="small muted"><span class="mono">${e(p.code)}</span>${p.age != null ? ` · ${p.age} yrs` : ""}${p.gender ? " · " + e(p.gender) : ""}${p.blood_group ? " · " + e(p.blood_group) : ""}${p.abha ? ` · ABHA <span class="mono">${e(p.abha)}</span>` : ""}</div></div></div>
        ${p.allergies ? `<div class="banner">Allergies on record: ${e(p.allergies)}. Tell every doctor and pharmacist.</div>` : ""}
        <div class="sub pt-filters">${FILTERS.filter(([k]) => k === "all" || counts[k]).map(([k, l]) => `<button type="button" data-pf="${k}" class="${k === filter ? "on" : ""}">${l} <span class="muted">${counts[k]}</span></button>`).join("")}</div>
        ${list.map(r => `<details class="card pt-rec"${r === list[0] ? " open" : ""}><summary><span class="pill ${r.kind === "lab" && r.critical ? "p-crit" : r.kind === "lab" && r.abnormal ? "p-warn" : "p-info"}">${e(data.labels[r.kind] || r.kind)}</span>
          <span class="pt-t"><b>${e(r.title)}</b><span class="small muted">${when(r.at)} · ${e(r.branch || "")}${r.kind === "invoice" && r.due ? ` · <b>${rs(r.due)} to pay</b>` : r.total != null ? " · " + rs(r.kind === "bill" ? r.total - (r.returned || 0) : r.total) : ""}${r.kind === "lab" && r.abnormal ? ` · ${r.abnormal} result${r.abnormal > 1 ? "s" : ""} outside the normal range` : ""}</span></span></summary>
          <div class="pt-body">${body(r, fileUrl)}${r.pdf ? `<p><a class="btn sm" data-pdf="${e(r.pdf)}" href="/api/portal/pdf/${e(r.pdf)}?t=${encodeURIComponent(opts.token || "")}" target="_blank" rel="noopener">Download PDF</a></p>` : ""}</div></details>`).join("") || '<div class="card"><p class="empty">Nothing here yet. Your bills, reports and prescriptions appear as soon as they are ready.</p></div>'}
        <p class="small muted pt-foot">This page is private to you. Don't forward the link. It stays active until ${when(data.expires)} and renews with every new record.${opts.preview ? "" : ' Lost your phone? Ask reception to switch the old link off.'}</p>`;
      root.querySelectorAll("[data-pf]").forEach(b => b.addEventListener("click", () => { filter = b.dataset.pf; draw(); }));
      if (opts.onPdf) root.querySelectorAll("[data-pdf]").forEach(a => a.addEventListener("click", ev => { ev.preventDefault(); opts.onPdf(a.dataset.pdf); }));
    };
    draw();
  };

  /* standalone page */
  const root = document.getElementById("portalRoot");
  if (root) {
    const t = new URLSearchParams(location.search).get("t") || "";
    fetch("/api/portal?t=" + encodeURIComponent(t)).then(async r => { const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || "This link doesn't work."); return d; })
      .then(d => { document.title = `${d.patient.name} · Health records`; window.renderPortal(root, d, { token: t }); })
      .catch(err => { root.innerHTML = `<div class="card"><h2>Link not working</h2><p>${e(err.message)}</p></div>`; });
  }
})();
