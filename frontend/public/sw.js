// Springform service worker: Web Push only. Registered from Settings when a user turns push on
// (src/core/records/push.ts). Served at /sw.js by Vite in development and by the backend's SPA
// fallback in production, so its scope is the whole app.
// Payload: {notification_id, title, body, url}. The tag is the notification id, so a push the
// server re-sends after a crash replaces the first one instead of showing twice.

self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {};
  event.waitUntil(self.registration.showNotification(data.title || 'Springform', {
    body: data.body || '',
    tag: data.notification_id ? String(data.notification_id) : undefined,
    data: { url: data.url || '/' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || '/', self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
    const same = windows.find((w) => w.url === url);
    return same ? same.focus() : self.clients.openWindow(url);
  }));
});
