/* Artifact-only additions: demo sign-in buttons, downloads through the viewer, print preview. */
"use strict";
const DEMO_USERS = [["owner", "Owner", "all branches"], ["dr.rao", "Dr. Rao", "doctor · City Hospital"], ["reception.ch", "Anita", "reception"], ["nurse.ch", "Sister Mary", "nurse"],
  ["pharma.ch", "Suresh", "pharmacist"], ["lab.ch", "Ravi Teja", "lab technician"], ["manager.ch", "Priya", "branch manager"], ["accounts", "Lakshman", "accountant"]];
(function () {
  const card = document.querySelector(".login-card");
  if (card) {
    const div = document.createElement("div");
    div.className = "demo-logins";
    div.innerHTML = `<p class="small muted" style="margin:6px 0">Demo: sign in as anyone (password <span class="mono">demo1234</span>)</p>
      <div class="demo-grid">${DEMO_USERS.map(([u, n, r]) => `<button type="button" class="btn ghost sm" data-act="demoLogin" data-u="${u}"><b>${n}</b><span>${r}</span></button>`).join("")}</div>
      <button type="button" class="linkbtn" data-act="demoReset" style="color:var(--muted)">Reset demo data</button>`;
    card.appendChild(div);
  }
})();
on("demoLogin", el => { $("#lu").value = el.dataset.u; $("#lp").value = "demo1234"; $(".login-card").requestSubmit(); });
on("demoReset", async () => { if (await dialog("Reset demo data?", "<p>Everything you changed in this browser is cleared and the demo group is created again.</p>", { ok: "Reset", danger: true })) window.MA_DEMO.reset(); });

/* Files: the viewer offers them through its own save dialog. */
download = async (path, filename) => {
  try {
    const r = await api(path, undefined, { raw: true });
    const name = filename || decodeURIComponent((r.headers.get("Content-Disposition") || "").split("''")[1] || "download.csv");
    const dl = window.claude && window.claude.use ? await window.claude.use("downloads") : null;
    if (!dl) return toast("Downloads aren't available in this view. They work in the installed version.");
    await dl.save({ filename: name, data: await r.blob() });
  } catch (e) { if (e && e.code !== "declined") toast(e.message || "Download failed"); }
};
/* Printing isn't allowed inside the viewer: show the printable page instead. */
printHtml = html => dialog("Print preview", `<div class="printprev">${html}</div><p class="small muted">Printing works in the installed version.</p>`, { ok: "", cancel: "Close", wide: true });

/* No sign-in screen in the demo: "Sign out" becomes "Switch user". */
on("logout", () => dialog("Switch user", `<p class="small muted">See the system as another member of staff.</p><div class="demo-grid">${DEMO_USERS.map(([u, n, r]) => `<button type="button" class="btn ghost sm" data-act="demoSwitch" data-u="${u}"><b>${n}</b><span>${r}</span></button>`).join("")}</div>
  <p><button type="button" class="linkbtn" data-act="demoReset">Reset demo data</button></p>`, { ok: "", cancel: "Close" }));
on("demoSwitch", el => window.MA_DEMO.switchUser(el.dataset.u));
new MutationObserver(() => document.querySelectorAll('[data-act="logout"]').forEach(b => { if (b.textContent !== "Switch user") b.textContent = "Switch user"; }))
  .observe(document.documentElement, { childList: true, subtree: true });

/* Stock photos: in the artifact the photo is read by Claude through the viewer (the viewer's own
   Claude account, asked first). Only the photo and the medicine list are sent; matching to our
   own records then happens here in the browser. */
const DEMO_SCHEMA = '{"doc_type":"stock|invoice","supplier":"","document_no":"","summary":"one sentence","items":[{"medicine":"","batch":"","expiry":"YYYY-MM or YYYY-MM-DD","qty":0,"mrp":0,"cost":0}]}';
STOCK_AI.ready = async () => {
  try { const s = window.claude && window.claude.use ? await window.claude.use("sample") : null; if (!s) return false; const l = await s.limits(); return !!(l && l.images); } catch (e) { return false; }
};
STOCK_AI.read = async (mime, data, file) => {
  const s = await window.claude.use("sample");
  if (!s) throw new Error("Reading photos isn't available in this view.");
  const meds = (App.cache.ed ? App.cache.ed.medicines : App.cache.meds || []).map(m => m.name).join(", ");
  const prompt = "The image is a photo taken in an Indian pharmacy: either medicines on a shelf, rack or in a carton (doc_type stock), or a supplier's bill/invoice (doc_type invoice).\n" +
    "List every medicine you can see. For each: medicine = brand name as printed, batch = batch/lot number, expiry = expiry date, " +
    "qty = how many strips, bottles or boxes (on a bill: the billed quantity; on a shelf: how many you can count), mrp = MRP in rupees per strip/bottle as printed, cost = rate per strip/bottle on a bill (0 on a shelf photo).\n" +
    "Use empty strings or 0 for anything you cannot read. Do not guess.\n" +
    "Brands this pharmacy stocks (use this spelling when the printed name matches one): " + meds + "\n" +
    "Answer with JSON only, exactly this shape: " + DEMO_SCHEMA;
  let out;
  try { out = await s.json(prompt, { images: [file], cache: false }); }
  catch (e) {
    const why = { not_granted: "Reading needs your permission to use Claude. Allow it and try again.", rate_limited: "Too many requests just now. Wait a minute and try again.",
      images_unavailable: "Sending photos to Claude isn't available in this view.", image_rejected: "This photo couldn't be used. Try a smaller JPG or PNG.", cancelled: "Stopped." }[e && e.code];
    throw new Error(why || (e && e.message) || "Reading failed");
  }
  if (!out || !Array.isArray(out.items)) throw new Error("The answer couldn't be read. Try again.");
  return api("/api/ai/match", out);
};

/* Phone upload needs a server the phone can reach. In this demo the server runs inside this page. */
phoneUpload = async () => {
  await dialog("Use your phone camera", `<p>In the installed MediAssist, this shows a QR code. Staff scan it with their phone, take the photo, and it appears on this screen by itself.</p>
    <p class="small muted">It can't work in this demo, because here the whole hospital server runs inside this browser tab and a phone can't reach it. Choose a photo from this device instead.</p>`, { ok: "", cancel: "OK" });
  return [];
};

/* AI assistant in the demo: Claude answers through the viewer (the viewer's own Claude account, asked first),
   using the same read-only look-ups as the installed server, run here as the signed-in demo user. */
ASSIST.ask = async (text, voice) => {
  const s = window.claude && window.claude.use ? await window.claude.use("sample") : null;
  if (!s) throw new Error("The assistant isn't available in this view. In the installed version it uses your Anthropic API key.");
  const lim = await s.limits().catch(() => null);
  if (!lim || !lim.tools) throw new Error("Asking with look-ups isn't available in this view.");
  const info = ASSIST.info;
  const tools = info.tools.slice(0, lim.tools.maxCount || 8).map(t => ({
    name: t.name, description: t.description, inputSchema: t.input_schema,
    execute: async input => { const r = await api("/api/assistant/tool", { name: t.name, input }); if (!r.ok) throw new Error(r.result); return r.result; },
  }));
  const who = `[Signed in: ${App.me.name}, role ${App.me.role}${App.me.branch ? ", branch " + App.me.branch.name : ", all branches"}. Today ${localDay()}.${voice ? " " + info.voice_note : ""}]`;
  const turns = [...ASSIST.history.slice(-8), { role: "user", content: who + "\n" + text }];
  turns[0] = { role: "user", content: info.system + "\n\n" + turns[0].content };  // instructions ride on the first turn
  try { return (await s(turns, { tools, cache: false })).text; }
  catch (e) {
    const why = { not_granted: "The assistant needs your permission to use Claude. Allow it and ask again.", rate_limited: "Too many questions just now. Wait a minute.",
      tools_unavailable: "Asking with look-ups isn't available in this view.", cancelled: "Stopped." }[e && e.code];
    throw new Error(why || (e && e.message) || "The assistant couldn't answer.");
  }
};

/* The Claude viewer usually blocks microphones on published pages. The mic button tries real speech recognition first
   (it works when the viewer or browser allows it); only when the microphone is refused does it hand over to the
   device's own voice typing (Windows+H on a PC, the mic key on a phone keyboard), which types into the box. */
const realMic = ACTIONS.askMic;
function micFallback() {
  const inp = $("#askText"); if (!inp) return;
  const pc = !/Android|iPhone|iPad/i.test(navigator.userAgent);
  inp.placeholder = pc ? "Press Windows + H and speak…" : "Tap the mic on your keyboard and speak…";
  dialog("Speak your question", `<p>This view doesn't let the page use the microphone. Use your device's voice typing instead. It types straight into the question box:</p>
    <ul><li><b>Windows PC:</b> press <span class="mono">Windows + H</span>, speak, then press Send.</li><li><b>Mac:</b> press <span class="mono">Fn</span> twice (Dictation).</li><li><b>Phone:</b> tap the 🎤 on your keyboard.</li></ul>
    <p class="small muted">In the installed MediAssist (Chrome or Edge), the mic button listens directly in English, Telugu and Hindi. Voice replies work here too: choose <b>Voice reply</b>.</p>`, { ok: "", cancel: "Got it" }).then(() => inp.focus());
}
on("askMic", async () => {
  if (typeof REC !== "undefined" && REC) return realMic();  // already listening: the real handler stops it
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return micFallback();
  try { const st = navigator.permissions && await navigator.permissions.query({ name: "microphone" }); if (st && st.state === "denied") return micFallback(); } catch (e) {}
  realMic();
  if (typeof REC === "undefined" || !REC) return;
  const orig = REC.onerror;
  REC.onerror = e => { if (e.error === "not-allowed" || e.error === "service-not-allowed" || e.error === "audio-capture") { stopListening(); $("#askText").placeholder = "Type or tap the mic and speak"; micFallback(); } else orig(e); };
});
