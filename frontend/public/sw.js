// Service worker: makes the app installable and its shell load instantly / offline.
// Only the app's own files are cached. Live data (Firestore, Binance, Google sign-in) always goes to the network.
const CACHE = "cia-shell-__BUILD_ID__";   // replaced with the build id on every deploy, so old caches are dropped
const SHELL = ["/index.html"];

self.addEventListener("install", (e) => {
  // fetched with cache: "reload" so the shell kept for offline use is the new deploy, never an HTTP-cached copy
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: "reload" })))).catch(() => {})
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/__/")) return;   // never touch data or auth
  if (req.mode === "navigate" && !/\.[a-z0-9]+$/i.test(url.pathname)) {   // files such as /manual.pdf are left to the browser
    // pages: network first (always the newest deploy), cached shell when offline
    e.respondWith(fetch(req, { cache: "no-store" }).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put("/index.html", copy)); }
      return res;
    }).catch(() => caches.match("/index.html")));
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    // build assets have content hashes in their names: cache first is safe
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }   // never keep an error page
      return res;
    })));
  }
});

self.addEventListener("message", (e) => { if (e.data === "SKIP_WAITING") self.skipWaiting(); });

// ---- alert notifications (web push from the engine via Firebase Cloud Messaging) -----------------------------
self.addEventListener("push", (e) => {
  let d = {};
  try { const j = e.data ? e.data.json() : {}; d = j.data || (j.notification ? { title: j.notification.title, body: j.notification.body } : j); }
  catch { d = { body: e.data ? e.data.text() : "" }; }
  const ios = /iphone|ipad|ipod/i.test(self.navigator.userAgent);
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => {
    // the open, visible app shows the alert itself (iOS requires a notification for every push, so always show there)
    if (!ios && cs.some((c) => c.visibilityState === "visible")) return;
    return self.registration.showNotification(d.title || "Crypto Intelligence AI", {
      body: d.body || "", icon: "/icons/icon-192.png", badge: "/icons/icon-192.png", tag: d.tag || undefined,
      data: { url: d.url || "/alerts" },
    });
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/alerts";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => {
    for (const c of cs) {
      if ("focus" in c) { if ("navigate" in c) c.navigate(url).catch(() => {}); return c.focus(); }
    }
    return self.clients.openWindow(url);
  }));
});
