/* Service worker minimale: rende installabile la PWA e serve l'interfaccia
 * anche in caso di micro-interruzioni di rete. NON mette in cache il video
 * live ne' gli eventi (devono essere sempre in tempo reale). */

const CACHE = "baby-monitor-v3";
const SHELL = [
  ".",
  "index.html",
  "style.css",
  "app.js",
  "wizard.js",
  "manifest.json",
  "icon-192.png",
  "icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Non intercettare stream live, eventi e API: sempre dalla rete.
  if (url.pathname.endsWith("/stream.mjpg") ||
      url.pathname.endsWith("/events") ||
      url.pathname.includes("/api/") ||
      url.pathname.includes("/lullabies/")) {
    return;
  }
  // Per la "shell" della PWA: rete se possibile, altrimenti cache.
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request).then((r) => r || caches.match("index.html")))
  );
});
