// Service worker minimal : rend la page "installable" (icône + plein écran, critère
// requis par les navigateurs) et sert l'app instantanément au relancement. Ne met en
// cache que la coquille statique — jamais les échanges WebSocket, qui ne passent pas
// par fetch() de toute façon.
const CACHE_NAME = 'alyx-mobile-v1';
const FICHIERS_COQUILLE = [
  './',
  './index.html',
  './style.css',
  './app.js',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(FICHIERS_COQUILLE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((noms) =>
      Promise.all(noms.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    caches.match(event.request).then((reponse) => reponse || fetch(event.request))
  );
});
