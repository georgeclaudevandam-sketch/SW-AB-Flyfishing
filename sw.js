/* Offline support: app shell + data are cached; map tiles are cached as you view them. */
const SHELL = 'shell-v10';
const TILES = 'tiles-v1';
const ASSETS = ['./', 'index.html', 'style.css', 'app.js', 'manifest.webmanifest',
  'data/species.json', 'data/species_names.json', 'data/references.json', 'vendor/leaflet/leaflet.js', 'vendor/leaflet/leaflet.css',
  'vendor/leaflet/images/layers.png', 'vendor/leaflet/images/layers-2x.png', 'icons/icon.svg', 'icons/icon-192.png'];
const TILE_HOSTS = /opentopomap\.org|tile\.openstreetmap\.org|cyclosm|arcgisonline\.com|waymarkedtrails\.org|geogratis\.gc\.ca/;

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== SHELL && k !== TILES).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (TILE_HOSTS.test(url.hostname)) {
    // Tiles: cache first, then network (and keep a copy).
    e.respondWith(caches.open(TILES).then(async c => {
      const hit = await c.match(e.request.url);
      if (hit) return hit;
      try { const r = await fetch(e.request); if (r.ok) c.put(e.request.url, r.clone()); return r; }
      catch (err) { return new Response('', { status: 504 }); }
    }));
    return;
  }
  if (url.origin === location.origin) {
    // App files: network first so updates arrive, fall back to cache offline.
    e.respondWith(fetch(e.request).then(r => { if (r.ok) { const copy = r.clone(); caches.open(SHELL).then(c => c.put(e.request, copy)); } return r; })
      .catch(() => caches.match(e.request, { ignoreSearch: true }).then(r => r || caches.match('index.html'))));
  }
});
