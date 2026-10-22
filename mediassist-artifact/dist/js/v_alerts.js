/* Morning briefing on the dashboard (what the doctor or owner got on WhatsApp), and sending it from Settings. */
"use strict";
async function briefingCard(main) {
  let b; try { b = await api("/api/briefing"); } catch (e) { return; }
  const box = document.createElement("div"); box.style.marginTop = "14px";
  box.innerHTML = card("Morning briefing", "Sent to your WhatsApp every morning. Change the time in Admin > Settings.", `<pre class="msg-pre">${esc(b.text)}</pre>`);
  main.insertBefore(box, main.firstChild.nextSibling);
}
on("briefSend", async el => {
  const r = await withBusy(el, () => api("/api/briefing/send", {}));
  if (!r.sent.length) return toast("No doctor has a WhatsApp number or email yet. Add them in Admin > Staff, and the owner's in Settings.");
  const ok = r.sent.filter(x => x.ok).length;
  toast(ok ? `Sent ${ok} briefing${ok > 1 ? "s" : ""}` : `Not sent: ${r.sent[0].detail}`);
});
