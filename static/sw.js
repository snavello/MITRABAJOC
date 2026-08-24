// Service worker minimo, solo para cumplir el requisito de instalabilidad
// de Chrome/Android. A PROPOSITO no cachea nada: la app se despliega
// seguido (cada push a main redeploya en Render) y un service worker que
// sirviera HTML/JS viejo desde cache dejaria a un trabajador "pegado" en
// una version anterior sin que se note. Cada pedido va siempre a la red.
self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
