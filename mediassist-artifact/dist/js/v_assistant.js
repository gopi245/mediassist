/* AI assistant: a floating "Ask AI" panel on every screen. Ask by typing or speaking (English, Telugu, Hindi);
   get the answer as text or read aloud. Answers come from the system's own records through read-only lookups
   that run as the signed-in staff member. */
"use strict";
const ASSIST = {
  info: null, chatId: null, history: [], busy: false,
  /* installed server: Claude runs on the server with its API key. The in-browser demo replaces this. */
  ask: async (text, voice) => {
    const r = await api("/api/assistant/ask", { text, voice, chat_id: ASSIST.chatId });
    ASSIST.chatId = r.chat_id; return r.answer;
  },
};
const ASK_LANGS = [["en-IN", "English"], ["te-IN", "తెలుగు"], ["hi-IN", "हिन्दी"]];
const askPref = (k, d) => { try { return localStorage.getItem("ma-ask-" + k) || d; } catch (e) { return d; } };
const askSave = (k, v) => { try { localStorage.setItem("ma-ask-" + k, v); } catch (e) {} };
const ASK_SUGGEST = {
  doctor: ["Who is waiting for me?", "Summary of P00004", "Is Brufen safe for P00004?", "Today's collection"],
  pharmacist: ["Where is Dolo 650 and how many?", "What is expiring soon?", "Substitute for Augmentin", "What is below reorder level?"],
  default: ["Today's collection", "Who is stuck right now?", "What is expiring soon?", "Stock of Pan 40"],
};

async function assistantBoot() {
  if (!App.me || $("#askFab")) return;
  try { ASSIST.info = await api("/api/assistant/info"); } catch (e) { return; }
  if (!ASSIST.info.enabled) return;
  const fab = document.createElement("button");
  fab.id = "askFab"; fab.className = "ask-fab"; fab.dataset.act = "askOpen"; fab.setAttribute("aria-label", "Ask the AI assistant");
  fab.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3c4.97 0 9 3.36 9 7.5S16.97 18 12 18c-.9 0-1.77-.1-2.6-.3L4 20l1.4-4.1C3.9 14.6 3 12.6 3 10.5 3 6.36 7.03 3 12 3z"/></svg><span>Ask AI</span>`;
  document.body.appendChild(fab);
}

function askPanel() {
  let p = $("#askPanel");
  if (p) return p;
  p = document.createElement("section");
  p.id = "askPanel"; p.className = "ask-panel"; p.setAttribute("aria-label", "AI assistant");
  const reply = askPref("reply", "text"), lang = askPref("lang", "en-IN");
  const sug = ASK_SUGGEST[App.me.role] || ASK_SUGGEST.default;
  p.innerHTML = `<header class="ask-h"><div><b>Ask MediAssist</b><span>Answers from your hospital's records</span></div><button class="btn sm ghost" data-act="askClose" aria-label="Close">✕</button></header>
    <div class="ask-opts"><div class="seg" role="group" aria-label="Reply as"><button data-act="askReply" data-v="text" class="${reply === "text" ? "on" : ""}">Text reply</button><button data-act="askReply" data-v="voice" class="${reply === "voice" ? "on" : ""}">Voice reply</button></div>
      <select id="askLang" data-change="askLang" aria-label="Language">${ASK_LANGS.map(([v, l]) => `<option value="${v}" ${v === lang ? "selected" : ""}>${l}</option>`).join("")}</select>
      <button class="linkbtn small" data-act="askNew">New chat</button></div>
    <div class="ask-log" id="askLog" aria-live="polite"><div class="ask-msg bot"><p>Ask me about stock and racks, a patient's history, safety of a medicine, who is waiting, or today's collection. ${ASSIST.info.patients ? "" : "<br><i>Patient records are switched off for the assistant.</i>"}</p>
      <div class="ask-sug">${sug.map(s => `<button class="chip" data-act="askSug">${esc(s)}</button>`).join("")}</div></div></div>
    <form class="ask-in" data-submit="askSend"><button type="button" class="ask-mic" id="askMic" data-act="askMic" aria-label="Speak your question"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg></button>
      <input id="askText" autocomplete="off" placeholder="Type or tap the mic and speak" aria-label="Your question"><button class="btn" aria-label="Send">Send</button></form>
    <p class="ask-foot small muted">The assistant can read but not change anything. Check important details in the record.</p>`;
  document.body.appendChild(p);
  return p;
}
on("askOpen", () => { const p = askPanel(); p.hidden = false; $("#askFab").hidden = true; $("#askText").focus(); });
on("askClose", () => { $("#askPanel").hidden = true; $("#askFab").hidden = false; stopSpeaking(); stopListening(); });
on("askReply", el => { askSave("reply", el.dataset.v); $$("#askPanel .seg button").forEach(b => b.classList.toggle("on", b === el)); if (el.dataset.v === "text") stopSpeaking(); });
on("askLang", el => askSave("lang", el.value));
on("askNew", () => { ASSIST.chatId = null; ASSIST.history = []; stopSpeaking(); $("#askLog").innerHTML = ""; addMsg("bot", "New conversation. What would you like to know?"); });
on("askSug", el => { $("#askText").value = el.textContent; ACTIONS.askSend(); });

/* light formatting for answers: **bold**, "- " bullets, line breaks. Everything is escaped first. */
function fmt(t) {
  const lines = esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").split("\n");
  let html = "", inList = false;
  for (const l of lines) {
    const m = l.match(/^\s*[-•*]\s+(.*)/);
    if (m) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${m[1]}</li>`; continue; }
    if (inList) { html += "</ul>"; inList = false; }
    html += l.trim() ? `<p>${l}</p>` : "";
  }
  return html + (inList ? "</ul>" : "");
}
function addMsg(who, text, extra = "") {
  const d = document.createElement("div"); d.className = "ask-msg " + who;
  d.innerHTML = who === "me" ? `<p>${esc(text)}</p>` : fmt(text) + extra;
  $("#askLog").appendChild(d); d.scrollIntoView({ block: "end", behavior: "smooth" }); return d;
}

on("askSend", async () => {
  const inp = $("#askText"), text = inp.value.trim();
  if (!text || ASSIST.busy) return;
  inp.value = ""; stopSpeaking(); addMsg("me", text);
  const voice = askPref("reply", "text") === "voice", wait = addMsg("bot", "Looking it up…"); wait.classList.add("wait");
  ASSIST.busy = true;
  try {
    const answer = await ASSIST.ask(text, voice);
    ASSIST.history.push({ role: "user", content: text }, { role: "assistant", content: answer });
    wait.remove();
    const d = addMsg("bot", answer, `<button class="linkbtn small ask-say" data-act="askSay">▶ Read aloud</button>`);
    d.dataset.text = answer;
    if (voice) speak(answer);
  } catch (e) { wait.remove(); addMsg("bot err", e.message || "Something went wrong"); }
  finally { ASSIST.busy = false; }
});
on("askSay", el => speak(el.closest(".ask-msg").dataset.text));

/* ---------- voice out: the browser's own speech, in the chosen language ---------- */
function speak(text) {
  if (!window.speechSynthesis) return toast("This browser can't read aloud.");
  stopSpeaking();
  const lang = askPref("lang", "en-IN"), plain = text.replace(/\*\*/g, "").replace(/^\s*[-•*]\s+/gm, "").replace(/Rs\.?\s?/g, "rupees ");
  const u = new SpeechSynthesisUtterance(plain); u.lang = lang; u.rate = 1;
  const v = speechSynthesis.getVoices().find(x => x.lang === lang) || speechSynthesis.getVoices().find(x => x.lang.startsWith(lang.slice(0, 2)));
  if (v) u.voice = v;
  speechSynthesis.speak(u);
}
function stopSpeaking() { try { window.speechSynthesis && speechSynthesis.cancel(); } catch (e) {} }

/* ---------- voice in: speech recognition (Chrome, Edge, Android) ---------- */
let REC = null;
function stopListening() { if (REC) { try { REC.abort(); } catch (e) {} REC = null; } const m = $("#askMic"); if (m) m.classList.remove("on"); }
on("askMic", () => {
  if (REC) return stopListening();
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return toast("Speaking isn't supported in this browser. Use Chrome or Edge, or type your question.");
  stopSpeaking();
  REC = new SR(); REC.lang = askPref("lang", "en-IN"); REC.interimResults = true; REC.maxAlternatives = 1;
  const inp = $("#askText"), mic = $("#askMic"); mic.classList.add("on"); inp.placeholder = "Listening…";
  REC.onresult = e => { inp.value = [...e.results].map(r => r[0].transcript).join(" "); if (e.results[e.results.length - 1].isFinal) { stopListening(); inp.placeholder = "Type or tap the mic and speak"; ACTIONS.askSend(); } };
  REC.onerror = e => { stopListening(); inp.placeholder = "Type or tap the mic and speak"; if (e.error === "not-allowed" || e.error === "service-not-allowed") toast("Microphone permission is blocked. Allow it in the browser, or type."); else if (e.error !== "aborted" && e.error !== "no-speech") toast("Couldn't hear that. Try again."); };
  REC.onend = () => { if (REC) stopListening(); inp.placeholder = "Type or tap the mic and speak"; };
  try { REC.start(); } catch (e) { stopListening(); toast("Couldn't start the microphone."); }
});
