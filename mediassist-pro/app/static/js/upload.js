/* Phone camera page opened from the QR code on a staff computer. No sign-in: the QR link is the key. */
"use strict";
(function () {
  const k = new URLSearchParams(location.search).get("k") || "", $u = s => document.querySelector(s), msg = t => { $u("#upMsg").textContent = t; };
  const api = async (body) => {
    const r = await fetch("/api/public/upload?k=" + encodeURIComponent(k), body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || "Something went wrong"); return d;
  };
  api().then(d => { $u("#upBranch").textContent = d.branch || "MediAssist"; $u("#upLabel").textContent = d.label; if (d.sent) msg(`${d.sent} sent so far.`); })
    .catch(e => { $u("#upCard").innerHTML = `<h2>QR code expired</h2><p>${e.message}</p>`; });
  /* phone photos are large: shrink to ~2000px JPEG before sending (keeps text readable, uploads fast) */
  const shrink = f => new Promise(res => {
    if (!f.type.startsWith("image/")) return res(f);
    const img = new Image(), url = URL.createObjectURL(f);
    img.onload = () => { const s = Math.min(1, 2000 / Math.max(img.width, img.height)), c = document.createElement("canvas"); c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url); c.toBlob(b => res(b ? new File([b], (f.name || "photo").replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : f), "image/jpeg", 0.85); };
    img.onerror = () => res(f); img.src = url;
  });
  $u("#upFile").addEventListener("change", async e => {
    const f0 = e.target.files[0]; e.target.value = ""; if (!f0) return;
    msg("Sending…");
    try {
      const f = await shrink(f0);
      const data = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result.split(",")[1]); fr.readAsDataURL(f); });
      const r = await api({ mime: f.type, data, filename: f.name });
      $u("#upList").insertAdjacentHTML("afterbegin", `<div class="up-item">${f.type.startsWith("image/") ? `<img src="${URL.createObjectURL(f)}" alt="">` : "<span class=\"pdf\">PDF</span>"}<b>Sent ✓</b></div>`);
      msg(`${r.sent} sent. Check the computer, or take another.`);
    } catch (err) { msg(err.message); }
  });
})();
