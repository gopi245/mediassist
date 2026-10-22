/* Staff side of the patient records link: send it on WhatsApp, preview what the patient sees, copy, renew or switch it off. */
"use strict";
on("portalOpen", el => portalDialog(+el.dataset.id));
async function portalDialog(pid, note = "") {
  const s = await api(`/api/patients/${pid}/portal`); App.cache.portal = { pid, ...s };
  dialog("Patient's records link", `<p>${s.active ? `The link is <b>on</b>. Opened ${s.views} time${s.views === 1 ? "" : "s"}${s.last_used ? `, last on <span class="mono">${s.last_used}</span>` : ""}. Works until <span class="mono">${s.expires}</span>.` : "No link yet. Sending one creates it."}</p>
    <p class="small muted">The patient gets a WhatsApp message with a private link to their prescriptions, lab reports, bills, discharge papers and the documents you send them. ${s.auto ? "Every new record is sent to them automatically." : "Automatic sending is off (Admin > Settings)."}</p>
    ${s.public_url ? "" : alertRow("", "Set the <b>Public address</b> in Admin > Settings, so the link opens on the patient's phone outside the hospital.")}
    <div class="row-actions" style="margin:10px 0"><button class="btn sm" data-act="portalSend">Send link on WhatsApp</button><button class="btn sm ghost" data-act="portalPreview">See what the patient sees</button>
      ${s.active ? `<button class="btn sm ghost" data-act="portalCopy">Copy link</button><button class="btn sm ghost" data-act="portalNew">New link</button><button class="btn sm ghost" data-act="portalOff" style="color:var(--crit)">Switch off</button>` : ""}</div>
    <div id="portalMsg">${note}</div>
    ${s.sent.length ? `<h3>Recent messages to the patient</h3>` + tbl(["When", "Message", ""], s.sent.map(m => `<tr><td class="mono small">${esc(m.at)}</td><td class="small">${esc(m.body)}</td><td>${m.ok ? pill("sent", "p-ok") : pill("not sent", "p-warn")}</td></tr>`).join("")) : ""}`,
    { ok: "", cancel: "Close", wide: true });
}
function sendNote(res) {
  if (!res) return "";
  if (!res.length) return alertRow("info", "This patient said no to WhatsApp messages. Use <b>Copy link</b> and give it to them another way.");
  const r = res[0];
  if (r.ok) return alertRow("info", `Sent to <span class="mono">${esc(r.to)}</span>.`);
  return alertRow("", `WhatsApp isn't connected here (${esc(r.detail)}).`) + (r.wa_link ? `<p><a class="btn sm" href="${esc(r.wa_link)}" target="_blank" rel="noopener">Send it from your own WhatsApp</a></p>` : "");
}
on("portalSend", async el => { const r = await withBusy(el, () => api(`/api/patients/${App.cache.portal.pid}/portal`, { send: true })); portalDialog(App.cache.portal.pid, sendNote(r.sent_now)); });
on("portalNew", async () => {
  await api(`/api/patients/${App.cache.portal.pid}/portal`, { fresh: true });
  portalDialog(App.cache.portal.pid, alertRow("info", "New link made. The old one no longer opens. Send the new one to the patient."));
});
on("portalOff", async () => { await api(`/api/patients/${App.cache.portal.pid}/portal/revoke`, {}); portalDialog(App.cache.portal.pid, alertRow("info", "Link switched off. Nothing opens until you send a new one.")); });
on("portalCopy", async () => {
  const url = App.cache.portal.url;
  try { await navigator.clipboard.writeText(url); toast("Link copied"); }
  catch (e) { $("#portalMsg").innerHTML = `<label>Link</label><input value="${esc(url)}" readonly class="mono" id="portalUrl">`; $("#portalUrl").select(); }
});
on("portalPreview", async () => {
  let s = App.cache.portal;
  if (!s.active) s = { ...s, ...(await api(`/api/patients/${s.pid}/portal`, {})) };
  const data = await api("/api/portal?t=" + encodeURIComponent(s.token));
  $("#mCancel").click();
  const ov = document.createElement("div"); ov.className = "pt-overlay"; ov.id = "ptOverlay";
  ov.innerHTML = `<div class="pt-bar"><b>Preview: what ${esc(data.patient.name)} sees on their phone</b><button class="btn sm" data-act="portalClose">Close preview</button></div><main class="pub-wrap pt-wrap" id="ptPrev"></main>`;
  document.body.appendChild(ov);
  renderPortal($("#ptPrev"), data, { token: s.token, preview: true, onPdf: p => download(`/api/portal/pdf/${p}?t=${encodeURIComponent(s.token)}`) });
});
on("pdfDl", el => download(`/api/pdf/${el.dataset.p}`));
on("portalClose", () => { const o = $("#ptOverlay"); if (o) o.remove(); });
