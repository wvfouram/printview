// Minimal service worker: makes PrintWatch installable. No caching - the
// app is only useful live, so every request goes straight to the Pi.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
