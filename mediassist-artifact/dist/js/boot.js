/* Boot: register the offline service worker and start. */
"use strict";
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
start().catch(() => showLogin(false));
