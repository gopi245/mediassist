/* Browser bridge: boots the MediAssist Python server in Pyodide, routes /api/ fetches to it,
   and saves the database and uploads in this browser (IndexedDB). */
"use strict";
(function () {
  const PY = ["server.py", "app/__init__.py", "app/core.py", "app/schema.py", "app/refdata.py", "app/safety.py", "app/notify.py", "app/m_admin.py",
    "app/m_clinical.py", "app/m_pharmacy.py", "app/m_lab.py", "app/m_appointments.py", "app/m_ipd.py", "app/m_billing.py", "app/m_accounts.py",
    "app/m_docs.py", "app/m_pdf.py", "app/m_portal.py", "app/m_reports.py", "app/m_weekly.py", "app/m_upload.py", "app/m_watch.py", "app/m_tracker.py", "app/m_alerts.py", "app/m_assistant.py", "app/m_care.py", "app/lab_explain.py", "app/m_suppliers.py", "app/rx_words.py", "app/setup.py", "bridge.py"];
  window.MA_DEMO = window.MA_DEMO || {};
  const origFetch = window.fetch.bind(window);
  let token = null; try { token = localStorage.getItem("ma-sid"); } catch (e) {}

  /* ---------- loading screen ---------- */
  const box = document.createElement("div");
  box.id = "bootScreen";
  box.innerHTML = `<div class="boot-card"><div class="mark"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M8 2h4v6h6v4h-6v6H8v-6H2V8h6z"/></svg></div>
    <h2>MediAssist</h2><p id="bootMsg">Starting the hospital server in your browser…</p><div class="boot-bar"><i id="bootBar"></i></div>
    <p class="small muted">The full system runs on this device. The first visit downloads about 14 MB.</p></div>`;
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(box));
  const msg = (t, pct) => { const m = document.getElementById("bootMsg"), b = document.getElementById("bootBar"); if (m) m.textContent = t; if (b && pct != null) b.style.width = pct + "%"; };

  /* ---------- IndexedDB ---------- */
  const idb = () => new Promise((res, rej) => { const r = indexedDB.open("mediassist-demo", 1); r.onupgradeneeded = () => r.result.createObjectStore("kv"); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
  async function idbGet(k) { try { const d = await idb(); return await new Promise(res => { const q = d.transaction("kv").objectStore("kv").get(k); q.onsuccess = () => res(q.result); q.onerror = () => res(null); }); } catch (e) { return null; } }
  async function idbSet(k, v) { try { const d = await idb(); await new Promise(res => { const t = d.transaction("kv", "readwrite"); t.objectStore("kv").put(v, k); t.oncomplete = res; t.onerror = res; }); } catch (e) {} }
  async function idbClear() { try { const d = await idb(); await new Promise(res => { const t = d.transaction("kv", "readwrite"); t.objectStore("kv").clear(); t.oncomplete = res; t.onerror = res; }); } catch (e) {} }

  let py = null;
  const loadScript = src => new Promise((res, rej) => { const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = () => rej(new Error("Could not load " + src)); document.head.appendChild(s); });
  function walk(dir, out) {
    let names = []; try { names = py.FS.readdir(dir); } catch (e) { return out; }
    for (const n of names) { if (n === "." || n === "..") continue; const p = dir + "/" + n, st = py.FS.stat(p); if (py.FS.isDir(st.mode)) walk(p, out); else out[p] = py.FS.readFile(p); }
    return out;
  }
  /* Pyodide fetches its .zip archives; they are published as base64 text (.zip.txt). */
  const pyFetch = window.fetch;
  window.fetch = async (input, init) => {
    const u = input instanceof Request ? input.url : String(input);
    if (/\/pyodide\/[^/]+\.zip$/.test(new URL(u, location.href).pathname)) {
      const r = await origFetch(u + ".txt"); if (!r.ok) return r;
      const bin = atob(await r.text()), buf = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
      return new Response(buf, { status: 200, headers: { "Content-Type": "application/zip" } });
    }
    return pyFetch(input, init);
  };
  const ready = (async () => {
    msg("Downloading the Python runtime…", 10);
    await loadScript("pyodide/pyodide.js");
    py = await loadPyodide({ indexURL: new URL("pyodide/", location.href).href });
    msg("Loading the database engine…", 45);
    await py.loadPackage("sqlite3");
    py.FS.mkdirTree("/ma/app"); py.FS.mkdirTree("/data/uploads");
    msg("Loading the hospital server…", 60);
    for (const f of PY) { const r = await origFetch("py/" + f); if (!r.ok) throw new Error("Missing " + f); py.FS.writeFile("/ma/" + f, await r.text()); }
    const saved = await idbGet("db"), uploads = (await idbGet("uploads")) || {};
    if (saved) { py.FS.writeFile("/data/mediassist.db", saved); for (const [p, data] of Object.entries(uploads)) { py.FS.mkdirTree(p.slice(0, p.lastIndexOf("/"))); py.FS.writeFile(p, data); } }
    msg(saved ? "Opening your saved data…" : "Creating demo hospitals, staff, patients and 30 days of history…", 75);
    await new Promise(r => setTimeout(r, 30));
    py.runPython(await (await origFetch("py/bridge.py")).text());
    py.globals.get("boot")(!saved);
    if (!token) signIn("owner");
    if (!saved) await persistNow();
    msg("Ready", 100);
    setTimeout(() => box.remove(), 250);
  })();
  ready.catch(e => { msg("This browser couldn't start the in-browser server: " + e.message + ". Use the installed version instead.", 100); console.error(e); });

  let saveT = null;
  async function persistNow() {
    const snap = py.globals.get("snapshot")(); const bytes = snap.toJs(); snap.destroy();
    await idbSet("db", new Uint8Array(bytes)); await idbSet("uploads", walk("/data/uploads", {}));
  }
  const persistSoon = () => { clearTimeout(saveT); saveT = setTimeout(() => persistNow().catch(() => {}), 1200); };

  /* ---------- no sign-in screen: the demo opens straight in as the owner ---------- */
  function call(method, path, headers, body) {
    if (token) headers.Cookie = "sid=" + token;
    const b64 = body ? btoa(String.fromCharCode(...new TextEncoder().encode(body))) : "";
    const out = JSON.parse(py.globals.get("handle")(method, path, JSON.stringify(headers), b64));
    if (out.cookie) { const m = out.cookie.match(/^sid=([^;]*)/); token = m && m[1] ? m[1] : null; try { token ? localStorage.setItem("ma-sid", token) : localStorage.removeItem("ma-sid"); } catch (e) {} }
    return out;
  }
  function signIn(user) { token = null; return call("POST", "/api/login", { "Content-Type": "application/json" }, JSON.stringify({ username: user, password: "demo1234" })).status === 200; }

  /* ---------- fetch bridge ---------- */
  const zipAware = window.fetch;
  window.fetch = async (input, init = {}) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href);
    if (!url.pathname.startsWith("/api/")) return zipAware(input, init);
    await ready;
    const method = (init.method || "GET").toUpperCase(), headers = { ...(init.headers || {}) };
    let b64 = "";
    if (init.body) { const bytes = new TextEncoder().encode(init.body); let s = ""; for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000)); b64 = btoa(s); }
    const send = () => { const h = { ...headers }; if (token) h.Cookie = "sid=" + token; const o = JSON.parse(py.globals.get("handle")(method, url.pathname + url.search, JSON.stringify(h), b64));
      if (o.cookie) { const m = o.cookie.match(/^sid=([^;]*)/); token = m && m[1] ? m[1] : null; try { token ? localStorage.setItem("ma-sid", token) : localStorage.removeItem("ma-sid"); } catch (e) {} }
      return o; };
    const t0 = performance.now();
    let out = send();
    const ms = performance.now() - t0;
    (window.MA_DEMO.timings = window.MA_DEMO.timings || []).push({ path: url.pathname, ms: Math.round(ms), status: out.status });
    if (ms > 1500) console.warn(`[MediAssist demo] ${method} ${url.pathname} took ${(ms / 1000).toFixed(1)}s in the browser server`);
    if (ms > 4000 && typeof toast === "function") toast(`${url.pathname.replace("/api/", "")} took ${(ms / 1000).toFixed(0)}s: the whole server runs inside this tab, so the first call after a reload can be slow.`);
    if (out.status === 500) console.error(`[MediAssist demo] ${method} ${url.pathname} failed on the server; see Admin > Error log`);
    // session gone (expired or signed out): sign back in as the owner instead of showing a sign-in screen
    if (out.status === 401 && !url.pathname.startsWith("/api/login") && !url.pathname.startsWith("/api/logout") && signIn("owner")) out = send();
    if (method === "POST") persistSoon();
    const bin = atob(out.body), buf = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return new Response(buf, { status: out.status, headers: { "Content-Type": out.ctype, ...out.headers } });
  };

  /* images that point at /api/ (document thumbnails) go through the bridge too */
  const fixImg = async img => { const src = img.getAttribute("src"); if (!src || !src.startsWith("/api/")) return; img.removeAttribute("src"); try { const r = await window.fetch(src); img.src = URL.createObjectURL(await r.blob()); } catch (e) {} };
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => { if (n.nodeType !== 1) return; if (n.tagName === "IMG") fixImg(n); n.querySelectorAll && n.querySelectorAll('img[src^="/api/"]').forEach(fixImg); })))
    .observe(document.documentElement, { childList: true, subtree: true });

  window.MA_DEMO = Object.assign(window.MA_DEMO || {}, { switchUser: async u => { await ready; signIn(u); await persistNow(); location.reload(); }, reset: async () => { await idbClear(); try { localStorage.removeItem("ma-sid"); } catch (e) {} location.reload(); } });
})();
