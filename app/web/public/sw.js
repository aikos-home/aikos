// aikos app service worker: keeps the app shell available offline (the API is never cached: it is personal data) and
// shows the push for a new door message (A24: time, length, speaker, recognised text; never sound, G5).
const CACHE = "aikos-shell-v2";
const SHELL = ["/", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/.well-known/")) return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match("/"))),
  );
});

function doorTitle(d) {
  const t = new Date(d.time);
  const hm = Number.isNaN(t.getTime()) ? "" : t.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  const secs = typeof d.seconds === "number" ? `${Math.round(d.seconds)} s` : "";
  return [d.recipient ? `Nachricht für ${d.recipient}` : "Nachricht an der Tür", hm, secs].filter(Boolean).join(" · ");
}

function doorBody(d) {
  const said = d.text ? `${d.speaker ? `${d.speaker}: ` : ""}„${d.text}“` : "Kein Text erkannt.";
  const where = d.here === true ? " Steht noch vor der Tür." : d.here === false ? " Nicht mehr vor der Tür." : "";
  return said + where;
}

self.addEventListener("push", (event) => {
  let d = {};
  try {
    d = event.data ? event.data.json() : {};
  } catch {
    d = {};
  }
  const base = { icon: "/icon-192.png", badge: "/icon-192.png", data: { url: "/#nachrichten" } };
  const shown = d.kind === "door_message"
    ? self.registration.showNotification(doorTitle(d), { ...base, body: doorBody(d), tag: `door-${d.id}` })
    : d.kind === "test"
      ? self.registration.showNotification("aikos", { ...base, body: "Test: Benachrichtigungen kommen an.", tag: "aikos-test" })
      : self.registration.showNotification("aikos", { ...base, body: "Neues in der App.", tag: "aikos" });
  event.waitUntil(shown);
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const mine = open.find((c) => new URL(c.url).origin === self.location.origin);
    if (mine) {
      await mine.focus();
      mine.postMessage({ type: "open", url });
      return;
    }
    await self.clients.openWindow(url);
  })());
});
