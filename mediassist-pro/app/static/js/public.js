/* Public pages: online booking, token display, feedback. No sign-in, no patient names shown. */
"use strict";
const q = new URLSearchParams(location.search);
const $p = s => document.querySelector(s);
const escP = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
async function call(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const d = await r.json().catch(() => ({ error: "Unexpected response" }));
  if (!r.ok) throw new Error(d.error || "Error");
  return d;
}
const today = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };

/* ---------- online booking ---------- */
if ($p("#bookForm")) {
  const br = (q.get("branch") || "").toUpperCase(), f = $p("#bookForm"), msg = $p("#bMsg");
  f.day.value = today(); f.day.min = today();
  const loadSlots = async () => {
    if (!f.doctor_id.value || !f.day.value) return;
    try {
      const d = await call(`/api/public/booking?branch=${br}&doctor_id=${f.doctor_id.value}&day=${f.day.value}`);
      f.slot.innerHTML = (d.slots || []).map(s => `<option>${s}</option>`).join("") || '<option value="">No free times this day</option>';
    } catch (e) { msg.textContent = e.message; }
  };
  call(`/api/public/booking?branch=${br}`).then(d => {
    $p("#bName").textContent = d.branch; document.title = `Book · ${d.branch}`;
    f.doctor_id.innerHTML = d.doctors.map(x => `<option value="${x.id}">${escP(x.name)}</option>`).join("");
    loadSlots();
  }).catch(e => { msg.textContent = e.message; f.querySelector("button").disabled = true; });
  f.doctor_id.addEventListener("change", loadSlots); f.day.addEventListener("change", loadSlots);
  f.addEventListener("submit", async e => {
    e.preventDefault(); msg.textContent = "";
    if (!f.consent.checked) { msg.textContent = "Please tick the agreement to book."; return; }
    const v = Object.fromEntries(new FormData(f)); v.consent = true; v.branch = br;
    try {
      const r = await call("/api/public/book", v);
      f.innerHTML = `<h2>Booked</h2><p>Your appointment with <b>${escP(r.doctor)}</b> is on <b>${r.day}</b>${r.slot ? ` at <b>${r.slot}</b>` : ""}.</p><p style="font-size:28px;margin:6px 0">Token <b>${r.token}</b></p><p class="small muted">Please arrive 10 minutes early with any old reports. A confirmation is sent on WhatsApp.</p>`;
    } catch (err) { msg.textContent = err.message; }
  });
}

/* ---------- token display (TV screen) ---------- */
if ($p("#dBoard")) {
  const br = (q.get("branch") || "").toUpperCase();
  const draw = async () => {
    try {
      const d = await call(`/api/public/tokens?branch=${br}`);
      $p("#dBranch").textContent = d.branch; $p("#dTime").textContent = d.time;
      $p("#dBoard").innerHTML = d.doctors.map(x => `<section class="disp-doc"><h2>${escP(x.doctor)}</h2><div class="disp-now"><span>Now</span><b>${x.now ?? "–"}</b></div><div class="disp-next">Next: ${x.next.length ? x.next.join(" · ") : "–"}</div></section>`).join("") || '<p class="disp-empty">No appointments today</p>';
    } catch (e) { $p("#dBoard").innerHTML = `<p class="disp-empty">${escP(e.message)}</p>`; }
  };
  draw(); setInterval(draw, 10000);
}

/* ---------- feedback ---------- */
if ($p("#fbForm")) {
  const tok = q.get("t") || "", f = $p("#fbForm"), msg = $p("#fbMsg");
  call(`/api/public/feedback?t=${encodeURIComponent(tok)}`).then(d => {
    $p("#fbTitle").textContent = `How was your visit to ${d.branch}?`;
    if (d.answered) f.innerHTML = "<h2>Thank you</h2><p>We already have your feedback.</p>";
  }).catch(e => { f.innerHTML = `<p>${escP(e.message)}</p>`; });
  f.addEventListener("submit", async e => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(f));
    if (!v.rating) { msg.textContent = "Choose a rating from 1 to 5."; return; }
    try { await call("/api/public/feedback", { t: tok, rating: +v.rating, comment: v.comment }); f.innerHTML = "<h2>Thank you</h2><p>Your feedback helps us improve.</p>"; }
    catch (err) { msg.textContent = err.message; }
  });
}
