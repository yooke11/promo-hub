// 찜 알림 받기(2026-11-26): 서버가 보낸 알림을 띄우고, 누르면 상품(또는 찜 목록)을 연다. 캐시는 하지 않는다.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = {title: "찜한 상품 소식", body: e.data ? e.data.text() : ""}; }
  const host = self.location.hostname;
  const icon = host.startsWith("jangbopick") ? "/icon-food-192.png" : host.startsWith("fashionsalepick") ? "/icon-fashion-192.png"
             : host.startsWith("beautysalepick") ? "/icon-beauty-192.png" : "/icon-192.png";
  e.waitUntil(self.registration.showNotification(d.title || "찜한 상품 소식", {
    body: d.body || "", icon, badge: icon, image: d.image || undefined, data: {url: d.url || "/?view=fav"}, tag: d.tag || undefined
  }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/?view=fav";
  e.waitUntil(self.clients.openWindow(url));
});
