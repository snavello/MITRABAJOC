// Service worker de Colm3na. Nació mínimo para cumplir el requisito de
// instalabilidad de Chrome/Android; desde 2026-09-02 también recibe las
// notificaciones PUSH de trámites (ver push.py). A PROPÓSITO no cachea
// nada: la app se despliega seguido (cada push a main redeploya en Render)
// y un service worker que sirviera HTML/JS viejo desde cache dejaría a un
// trabajador "pegado" en una versión anterior sin que se note. Cada pedido
// va siempre a la red.
self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});

self.addEventListener("push", (event) => {
  let datos = {};
  try { datos = event.data ? event.data.json() : {}; } catch (e) { /* payload no-JSON */ }
  const titulo = datos.titulo || "Colm3na";
  event.waitUntil(self.registration.showNotification(titulo, {
    body: datos.cuerpo || "Tenés una novedad.",
    icon: "/static/icons/icon-192.png",
    badge: "/static/icons/icon-192.png",
    data: { url: datos.url || "/app/inicio" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/app/inicio";
  event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((lista) => {
    for (const c of lista) {
      // si la app ya está abierta, se reusa esa ventana
      if ("focus" in c) { c.navigate(url); return c.focus(); }
    }
    return clients.openWindow(url);
  }));
});
