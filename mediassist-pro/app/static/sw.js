/* Offline shell: the app's own files are cached so screens open without a connection.
   API data is never cached here; bills made offline are queued by the page and synced later. */
const CACHE = "mediassist-v2-8";
const SHELL = ["/", "/app.css", "/icon.svg", "/manifest.json", "/js/core.js", "/js/shell.js", "/js/v_clinical.js", "/js/v_tracker.js", "/js/v_lab.js", "/js/v_ipd.js",
  "/js/v_pharmacy.js", "/js/v_stockedit.js", "/js/portal.js", "/js/v_portal.js", "/js/vendor/qrcode.js", "/js/v_weekly.js", "/js/v_watch.js", "/js/v_alerts.js", "/js/v_assistant.js", "/js/v_billing.js", "/js/v_docs.js", "/js/v_accounts.js", "/js/v_reports.js", "/js/v_admin.js", "/js/boot.js"];
self.addEventListener("install", e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/")) return;
  e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); return r; }).catch(() => caches.match(e.request).then(m => m || caches.match("/"))));
});
