/* Eastern Slopes Trout Map.
   Waters and species come from data/water/ (built from Alberta FWMIS by scripts/build_fwmis.py). */
(function () {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const toast = (msg, ms = 2500) => { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('show'), ms); };
  const isMobile = () => matchMedia('(max-width: 820px)').matches;
  const NO_REC = '#9aa3a0';
  const LABEL_ZOOM = 11, MAX_LABELS = 300;

  let SPECIES = [], SP = {}, META = null, ITEMS = [], BYID = {}, RARITY = [];
  let passing = new Set(), selectedId = null;
  const chunkData = {};      // chunk key -> {id: geometry}
  const chunkExtra = {};     // chunk key -> waters with no fish records (geometry + name only)
  const chunkPts = {};       // chunk key -> survey sites not on a mapped water
  const chunkLoading = {};
  const sort = store.get('sort2', { key: 'name', desc: false });
  const dispName = it => it.n || it.a || 'Unnamed ' + (it.k === 'l' ? 'lake' : 'stream');
  let NAMES = {};
  // Codes outside data/species.json that are game fish in Alberta Fishery Regulations, 1998 (SOR/98-246), Schedule 1 Part 1.
  const GAME_EXTRA = new Set(['AGMN', 'GOLD', 'LKST', 'MOON', 'SAUG', 'CISC']);
  // FWMIS codes that are not fish (amphibians, molluscs, crustaceans) or only identified to family / unknown.
  const NOT_FISH = new Set(['ANOG', 'BOTO', 'CICH', 'FAM1', 'GEN1', 'NOCY', 'TISA', 'WOFR', 'TESTFISH', 'UNKN', 'TEMP355', 'SLMN', 'FAMCATO', 'FAMCYPR']);
  const syncGroups = () => document.querySelectorAll('#speciesList .grp').forEach(g => {
    const subs = [...document.querySelectorAll(`#speciesList .sub[data-grp="${g.dataset.grp}"] input`)], on = subs.filter(i => i.checked).length;
    g.checked = on > 0 && on === subs.length; g.indeterminate = on > 0 && on < subs.length;
  });
  const cap = t => t.toLowerCase().replace(/(^|[ (-])([a-z])/g, (m, p, l) => p + l.toUpperCase());
  const spName = c => (SP[c] ? SP[c].name : NAMES[c] ? cap(NAMES[c]) : c);
  const spColor = c => (SP[c] ? SP[c].color : '#666');

  /* ---------------- Map and layers ---------------- */
  // One shared canvas for every vector layer: a second canvas on top would swallow hover and taps for the one below.
  const canvas = L.canvas({ padding: 0.3, tolerance: 6 });
  const map = L.map('map', { zoomControl: true, preferCanvas: true, renderer: canvas }).setView([51.3, -115.6], 7);
  const osmAttr = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  const bases = {
    'Topo (OpenTopoMap)': L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', { maxZoom: 17, subdomains: 'abc', attribution: osmAttr + ', SRTM | &copy; <a href="https://opentopomap.org">OpenTopoMap</a>' }),
    'Canada Topo (NRCan Toporama)': L.tileLayer.wms('https://maps.geogratis.gc.ca/wms/toporama_en', { layers: 'WMS-Toporama', format: 'image/png', maxZoom: 17, attribution: 'Toporama &copy; Natural Resources Canada' }),
    'Tracks & cutlines (CyclOSM)': L.tileLayer('https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png', { maxZoom: 18, subdomains: 'abc', attribution: osmAttr + ' | <a href="https://www.cyclosm.org">CyclOSM</a>' }),
    'Roads (OpenStreetMap)': L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: osmAttr }),
    'Esri World Topo': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', { maxZoom: 18, attribution: 'Tiles &copy; Esri' }),
    'Satellite (Esri)': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 18, attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics' })
  };
  const overlays = {
    'Hiking trails (Waymarked)': L.tileLayer('https://tile.waymarkedtrails.org/hiking/{z}/{x}/{y}.png', { maxZoom: 18, opacity: 0.85, attribution: '<a href="https://hiking.waymarkedtrails.org">Waymarked Trails</a>' }),
    'Roads & place names': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}', { maxZoom: 18, attribution: 'Esri' }),
    'Place names (Esri)': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', { maxZoom: 18, attribution: 'Esri' }),
    'Hillshade': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}', { maxZoom: 16, opacity: 0.35, attribution: 'Esri' })
  };
  let baseName = store.get('base', 'Topo (OpenTopoMap)');
  if (!bases[baseName]) baseName = 'Topo (OpenTopoMap)';
  bases[baseName].addTo(map);
  let fade = store.get('fade', 45);
  const applyFade = () => { Object.values(bases).forEach(l => l.setOpacity(1 - fade / 100)); const o = document.getElementById('fadeOut'); if (o) o.textContent = fade + '%'; };
  applyFade();
  if (store.get('overlaysV', 0) < 2) { store.set('overlays', [...new Set([...store.get('overlays', []), 'Place names (Esri)'])]); store.set('overlaysV', 2); }
  store.get('overlays', []).forEach(n => overlays[n] && overlays[n].addTo(map));
  L.control.layers(bases, overlays, { position: 'topright', collapsed: true }).addTo(map);
  L.control.scale({ imperial: false }).addTo(map);
  const MaxZoom = L.Control.extend({ options: { position: 'topleft' }, onAdd() {
    const d = L.DomUtil.create('div', 'leaflet-bar'), a = L.DomUtil.create('a', 'max-zoom', d);
    a.href = '#'; a.title = 'Zoom all the way in'; a.setAttribute('role', 'button'); a.textContent = 'MAX';
    L.DomEvent.disableClickPropagation(d);
    L.DomEvent.on(a, 'click', e => { L.DomEvent.preventDefault(e); const lyr = bases[baseName]; map.setZoom(Math.min((lyr && lyr.options.maxZoom) || 18, map.getMaxZoom() || 18)); });
    return d; } });
  new MaxZoom().addTo(map);
  map.on('baselayerchange', e => { baseName = e.name; store.set('base', e.name); applyFade(); });
  document.getElementById('fade').value = fade;
  document.getElementById('fade').addEventListener('input', e => { fade = +e.target.value; store.set('fade', fade); applyFade(); });
  map.on('overlayadd overlayremove', () => store.set('overlays', Object.keys(overlays).filter(n => map.hasLayer(overlays[n]))));
  const waterLayer = L.layerGroup().addTo(map);
  const siteHi = L.layerGroup().addTo(map);
  const labelLayer = L.layerGroup().addTo(map);

  /* ---------------- Trail and place names (OpenStreetMap via Overpass) ---------------- */
  map.createPane('trails').style.zIndex = 390;
  const trailCanvas = L.canvas({ pane: 'trails', padding: 0.3, tolerance: 6 });
  const trailLayer = L.layerGroup().addTo(map), nameLayer = L.layerGroup().addTo(map);
  const TRAIL_ZOOM = 13, PLACE_ZOOM = 10, TOWN_ZOOM = 8, ROAD_ZOOM = 12, OVERPASS = ['https://overpass-api.de/api/interpreter'];
  const osm = { trails: [], places: [], roads: [], boxes: [], busy: false };  // boxes: [kind, south, west, north, east]
  const covered = (kind, v) => osm.boxes.some(x => x[0] === kind && x[1] <= v.getSouth() && x[2] <= v.getWest() && x[3] >= v.getNorth() && x[4] >= v.getEast());
  const withTimeout = ms => (typeof AbortSignal !== 'undefined' && AbortSignal.timeout ? AbortSignal.timeout(ms) : undefined);
  // Overpass allows only a couple of requests at once per user, so requests queue and run one at a time.
  // Route lookups (priority) jump ahead of background name loading. A busy answer (429) waits and retries.
  const ovq = []; let ovBusy = false;
  function overpass(q, ms = 25000, priority = false) {
    return new Promise((resolve, reject) => { (priority ? ovq.unshift.bind(ovq) : ovq.push.bind(ovq))({ q, ms, resolve, reject }); pumpOverpass(); });
  }
  async function pumpOverpass() {
    if (ovBusy || !ovq.length) return;
    ovBusy = true;
    const job = ovq.shift();
    try { job.resolve(await overpassFetch(job.q, job.ms)); } catch (e) { job.reject(e); }
    ovBusy = false; pumpOverpass();
  }
  async function overpassFetch(q, ms) {
    let last;
    for (let attempt = 0; attempt < 3; attempt++) {
      for (const url of OVERPASS) {
        try {
          const r = await fetch(url, { method: 'POST', body: 'data=' + encodeURIComponent(q), headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, signal: withTimeout(ms) });
          if (r.ok) return await r.json();
          last = new Error('Overpass ' + r.status);
          if (r.status !== 429 && r.status < 500) throw last;
        } catch (e) { last = e; if (e.name === 'TimeoutError' || e.name === 'AbortError') throw e; }
      }
      await new Promise(r => setTimeout(r, 1500 * (attempt + 1)));
    }
    throw last;
  }
  async function loadOsm() {
    const z = map.getZoom(), v = map.getBounds();
    if (!osmReady || osm.busy || (!F.trailNames && !F.placeNames && !F.roadNames)) return;
    const want = [];
    if (F.trailNames && z >= TRAIL_ZOOM && !covered('t', v)) want.push('t');
    if (F.roadNames && z >= ROAD_ZOOM && !covered('r', v)) want.push('r');
    if (F.placeNames && z >= TOWN_ZOOM && !covered('P', v)) want.push('P');
    if (F.placeNames && z >= PLACE_ZOOM && !covered('p', v)) want.push('p');
    if (!want.length) return drawOsm();
    osm.busy = true;
    try {
      for (const kind of want) {
        const p = v.pad(kind === 't' ? 0.5 : kind === 'P' ? 0.6 : 0.3), bb = `${p.getSouth().toFixed(4)},${p.getWest().toFixed(4)},${p.getNorth().toFixed(4)},${p.getEast().toFixed(4)}`;
        if (kind === 'r') {
          // Roads with a name or number in OSM (highways, range and township roads, local names such as Coal Camp Road).
          const j = await overpass(`[out:json][timeout:25];way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|track|service|road)$"]["name"](${bb});way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|track|road)$"]["ref"][!"name"](${bb});out tags geom;`);
          const seen = new Set(osm.roads.map(t => t.id));
          for (const e of j.elements || []) {
            if (e.type !== 'way' || !e.geometry || seen.has(e.id)) continue;
            const t = e.tags || {}, ref = (t.ref || '').split(';')[0];
            const name = t.name ? (ref && /^\d/.test(ref) && !t.name.includes(ref) ? `${t.name} (${ref})` : t.name) : (/^\d+[A-Z]?$/.test(ref) ? 'Hwy ' + ref : ref);
            if (name) osm.roads.push({ id: e.id, name, g: e.geometry.map(q => [q.lat, q.lon]), hw: t.highway, surface: t.surface || '' });
          }
        } else if (kind === 't') {
          // Named or officially operated trails, plus every way in a hiking route relation (takes the route's name).
          const j = await overpass(`[out:json][timeout:25];relation["route"~"^(hiking|foot)$"](${bb})->.r;.r out tags;(way(r.r)(${bb});way["highway"~"^(path|footway|track|bridleway|steps)$"]["name"](${bb});way["highway"~"^(path|footway|track|bridleway)$"]["operator"](${bb}););out tags geom;`);
          const rels = {}; (j.elements || []).filter(e => e.type === 'relation' && e.tags).forEach(e => { rels[e.id] = e.tags; });
          // way -> route relation membership needs a second lookup; ask for it compactly
          const wayIds = (j.elements || []).filter(e => e.type === 'way').map(e => e.id);
          const memb = {};
          if (Object.keys(rels).length && wayIds.length) {
            const m = await overpass(`[out:json][timeout:25];relation(id:${Object.keys(rels).join(',')});out body;`);
            (m.elements || []).forEach(rl => (rl.members || []).forEach(mm => { if (mm.type === 'way') (memb[mm.ref] = memb[mm.ref] || []).push(rl.id); }));
          }
          const seen = new Set(osm.trails.map(t => t.id));
          for (const e of j.elements || []) {
            if (e.type !== 'way' || !e.geometry || seen.has(e.id)) continue;
            const t = e.tags || {}, routes = (memb[e.id] || []).map(id => rels[id]).filter(Boolean);
            const route = routes.find(r => r.name) || routes[0];
            const name = t.name || (route && route.name) || t.ref || (t.operator ? t.operator + ' trail' : '');
            if (!name) continue;
            osm.trails.push({ id: e.id, name, g: e.geometry.map(q => [q.lat, q.lon]), hw: t.highway, op: t.operator || (route && route.operator) || '',
              official: !!(t.operator || route || t.ref), route: route && route.name || '', sac: t.sac_scale || '' });
          }
        } else {
          const j = await overpass(kind === 'P'
            ? `[out:json][timeout:25];node["place"~"^(city|town|village|hamlet)$"]["name"](${bb});out body;`
            : `[out:json][timeout:25];(node["place"~"^(locality|isolated_dwelling|neighbourhood)$"]["name"](${bb});node["natural"~"^(peak|hill|volcano|saddle|ridge|waterfall|glacier|spring|cave_entrance|arete)$"]["name"](${bb});node["waterway"="waterfall"]["name"](${bb});node["mountain_pass"="yes"]["name"](${bb});node["tourism"~"^(camp_site|alpine_hut|wilderness_hut|viewpoint)$"]["name"](${bb});node["highway"="trailhead"]["name"](${bb});node["historic"]["name"](${bb});node["man_made"~"^(tower|dam)$"]["name"](${bb});node["leisure"="slipway"]["name"](${bb}););out body;`);
          const seen = new Set(osm.places.map(t => t.id));
          for (const e of j.elements || []) if (!seen.has(e.id) && e.tags && e.tags.name) osm.places.push({ id: e.id, name: e.tags.name, lat: e.lat, lon: e.lon, kind: e.tags.place || (e.tags.waterway === 'waterfall' ? 'waterfall' : '') || e.tags.natural || e.tags.tourism || (e.tags.highway === 'trailhead' ? 'trailhead' : '') || (e.tags.mountain_pass ? 'pass' : '') || (e.tags.historic ? 'historic' : '') || e.tags.man_made || (e.tags.leisure === 'slipway' ? 'boat_launch' : 'landmark'), ele: e.tags.ele || '' });
        }
        osm.boxes.push([kind, p.getSouth(), p.getWest(), p.getNorth(), p.getEast()]);
      }
    } catch (err) { console.warn('Trail/place names unavailable:', err.message); }
    osm.busy = false;
    drawOsm();
  }
  const PLACE_MIN_Z = { city: 7, town: 8, village: 9, hamlet: 10, locality: 11, neighbourhood: 13, isolated_dwelling: 13, peak: 10, volcano: 10, hill: 11, ridge: 11, arete: 12, saddle: 12, pass: 10, glacier: 11,
    waterfall: 12, spring: 13, cave_entrance: 13, camp_site: 12, alpine_hut: 11, wilderness_hut: 11, viewpoint: 13, trailhead: 12, historic: 13, tower: 13, dam: 12, boat_launch: 13, landmark: 13 };
  const PLACE_ICON = { peak: '▲ ', volcano: '▲ ', hill: '△ ', saddle: '⌒ ', ridge: '⌒ ', arete: '⌒ ', pass: '⌒ ', glacier: '❄ ', waterfall: '≋ ', spring: '◌ ', cave_entrance: '◖ ', camp_site: '⛺ ', alpine_hut: '⌂ ', wilderness_hut: '⌂ ',
    viewpoint: '◉ ', trailhead: '⬤ ', historic: '✦ ', tower: '♜ ', dam: '▬ ', boat_launch: '⚓ ' };
  // When labels compete, settlements first, then higher summits.
  const PLACE_RANK = { city: 0, town: 1, village: 2, hamlet: 3, peak: 4, volcano: 4, pass: 5, hill: 6, locality: 7 };
  const eleOf = p => parseFloat(String(p.ele).replace(',', '.')) || 0;
  let osmReady = false;
  function drawOsm() {
    if (!osmReady) return;
    trailLayer.clearLayers(); nameLayer.clearLayers();
    const z = map.getZoom(), v = map.getBounds();
    if (F.roadNames && z >= ROAD_ZOOM) {
      // One label per road name per map cell (~2 km at zoom 13), on a visible vertex near the middle of that piece.
      const cell = 0.25 / Math.pow(2, z - 10), used = new Set(); let n = 0;
      const minor = /^(residential|service)$/;
      for (const r of osm.roads) {
        if (minor.test(r.hw) && z < 14) continue;
        const vis = r.g.filter(q => v.contains(q)); if (!vis.length) continue;
        const at = vis[Math.floor(vis.length / 2)], key = r.name + '|' + Math.round(at[0] / cell) + '|' + Math.round(at[1] / (cell * 1.6));
        if (used.has(key) || n > 220) continue; used.add(key); n++;
        L.tooltip({ permanent: true, direction: 'center', className: 'road-lbl' + (/^(motorway|trunk|primary|secondary)$/.test(r.hw) ? ' major' : ''), interactive: false }).setLatLng(at).setContent(esc(r.name)).addTo(nameLayer);
      }
    }
    if (F.trailNames && z >= TRAIL_ZOOM) {
      const labelled = new Map();
      for (const t of osm.trails) {
        if (!t.g.some(q => v.contains(q))) continue;
        const tip = `<b>${esc(t.name)}</b>${t.route && t.route !== t.name ? '<br>Part of ' + esc(t.route) : ''}${t.op ? '<br>Operator: ' + esc(t.op) : ''}${t.sac ? '<br>Difficulty (SAC): ' + esc(t.sac.replace(/_/g, ' ')) : ''}<br><span class="hint">OpenStreetMap ${esc(t.hw || '')}</span>`;
        L.polyline(t.g, { renderer: trailCanvas, color: t.official ? '#8b2f00' : '#6b4a2b', weight: t.official ? 3 : 2, opacity: 0.85, dashArray: t.hw === 'track' ? '8 4' : '5 4' }).bindTooltip(tip, { sticky: true }).addTo(trailLayer);
        // one label per trail name per ~1.5 km, placed on the longest visible piece
        const vis = t.g.filter(q => v.contains(q));
        const key = t.name + '|' + Math.round(vis[0][0] * 70) + '|' + Math.round(vis[0][1] * 50);
        if (!labelled.has(key) || labelled.get(key).n < vis.length) labelled.set(key, { n: vis.length, at: vis[Math.floor(vis.length / 2)], t });
      }
      const used = new Set();
      [...labelled.values()].sort((a, c) => c.n - a.n).slice(0, 120).forEach(({ at, t }) => {
        const cell = Math.round(at[0] * 120) + ':' + Math.round(at[1] * 80) + ':' + t.name;
        if (used.has(cell)) return; used.add(cell);
        L.tooltip({ permanent: true, direction: 'center', className: 'trail-lbl' + (t.official ? ' off' : ''), interactive: false }).setLatLng(at).setContent(esc(t.name)).addTo(nameLayer);
      });
    }
    if (F.placeNames && z >= TOWN_ZOOM) {
      osm.places.filter(p => z >= (PLACE_MIN_Z[p.kind] || 13) && v.contains([p.lat, p.lon]))
        .sort((a, c) => (PLACE_RANK[a.kind] ?? 9) - (PLACE_RANK[c.kind] ?? 9) || eleOf(c) - eleOf(a)).slice(0, 300).forEach(p =>
        L.tooltip({ permanent: true, direction: 'top', className: 'place-lbl k-' + p.kind, interactive: false }).setLatLng([p.lat, p.lon])
          .setContent((PLACE_ICON[p.kind] || '') + esc(p.name) + (p.ele && /peak|volcano|hill|pass|saddle/.test(p.kind) ? ` <small>${esc(String(p.ele).replace(/\s*m$/, ''))} m</small>` : '')).addTo(nameLayer));
    }
  }
  let osmTimer = 0;
  map.on('moveend', () => { clearTimeout(osmTimer); drawOsm(); osmTimer = setTimeout(loadOsm, 700); });
  let hiLayer = null;

  /* ---------------- Filters ---------------- */
  const F = Object.assign({ species: null, match: 'any', lakes: true, streams: true, minOrder: 1, noRecord: false, onlyStocked: false, labels: false, since: 0, sites: true, trailNames: true, placeNames: true, roadNames: true }, store.get('filters3', {}));
  if (!store.get('labelsHover', false)) { F.labels = false; store.set('labelsHover', true); }
  function readFilters() {
    F.species = $$('#speciesList input:checked:not(.grp)').map(i => i.value); syncGroups();
    F.match = $('input[name=match]:checked').value;
    F.lakes = $('#showLakes').checked; F.streams = $('#showStreams').checked;
    F.minOrder = +$('#minOrder').value;
    F.noRecord = $('#showNoRecord').checked; F.onlyStocked = $('#onlyStocked').checked;
    F.labels = $('#labels').checked; F.trailNames = $('#trailNames').checked; F.roadNames = $('#roadNames').checked; F.placeNames = $('#placeNames').checked; F.since = +$('#since').value; F.sites = $('#showSites').checked;
    store.set('filters3', F);
  }
  function writeFilters() {
    $$('#speciesList input:not(.grp)').forEach(i => { i.checked = !F.species || F.species.includes(i.value); }); syncGroups();
    $$('input[name=match]').forEach(i => { i.checked = i.value === F.match; });
    $('#showLakes').checked = F.lakes; $('#showStreams').checked = F.streams;
    $('#minOrder').value = F.minOrder; $('#showNoRecord').checked = F.noRecord; $('#onlyStocked').checked = F.onlyStocked;
    $('#labels').checked = F.labels; $('#trailNames').checked = F.trailNames; $('#roadNames').checked = F.roadNames; $('#placeNames').checked = F.placeNames; $('#since').value = F.since; $('#showSites').checked = F.sites;
  }
  // Species in a {code: lastYear} map that pass the "records since" filter (year 0 = undated list).
  const spIn = y => Object.keys(y || {}).filter(c => !F.since || y[c] === 0 || y[c] >= F.since).sort();
  function allSp(it) {
    const sp = new Set(spIn(it.y));
    if (it.st) Object.entries(it.st).forEach(([c, yrs]) => { if (!F.since || !yrs.length || yrs[yrs.length - 1] >= F.since) sp.add(c); });
    return [...sp].sort();
  }
  const selOnly = sp => { const sel = F.species || []; return sp.filter(c => sel.includes(c)); };
  const selMatch = sp => { const sel = F.species || []; if (!sel.length || !sp.length) return false; return F.match === 'all' ? sel.every(c => sp.includes(c)) : sp.some(c => sel.includes(c)); };
  function passes(it) {
    if (it.k === 'l' ? !F.lakes : !F.streams) return false;
    if (it.k === 's' && (it.o || 1) < F.minOrder) return false;
    if (F.onlyStocked && !it.st) return false;
    return selMatch(allSp(it));
  }
  const rarest = sp => RARITY.find(c => sp.includes(c)) || sp[0];
  const colorOfSp = sp => { const t = rarest(sp); return t ? spColor(t) : NO_REC; };
  const topSpecies = it => rarest(allSp(it));
  const colorOf = it => colorOfSp(selOnly(allSp(it)).length ? selOnly(allSp(it)) : allSp(it));
  const yrs = (it, c) => { const r = (it.yr || {})[c]; return r && r[1] ? (r[0] && r[0] !== r[1] ? `${r[0]}–${r[1]}` : `${r[1]}`) : ''; };

  /* ---------------- Chunk loading ---------------- */
  const inBox = (bb, b) => !(bb[2] < b.getWest() || bb[0] > b.getEast() || bb[3] < b.getSouth() || bb[1] > b.getNorth());
  function chunksInView() {
    const b = map.getBounds().pad(0.1), d = META.chunkDeg;
    const keys = new Set();
    for (const it of ITEMS) if (passing.has(it.id) && inBox(it.b, b)) keys.add(it.ch);
    if ((F.noRecord || F.sites) && map.getZoom() >= 10) {
      for (let x = Math.floor(b.getWest() / d); x <= Math.floor(b.getEast() / d); x++)
        for (let y = Math.floor(b.getSouth() / d); y <= Math.floor(b.getNorth() / d); y++) keys.add(`${x}_${y}`);
    }
    return [...keys].filter(k => META.chunks.includes(k));
  }
  function loadChunk(k) {
    if (chunkData[k]) return Promise.resolve();
    if (chunkLoading[k]) return chunkLoading[k];
    return (chunkLoading[k] = fetch(`data/water/c_${k}.json`).then(r => r.json()).then(arr => {
      const m = {}, extra = [], pts = [];
      arr.forEach(f => { if (f.pts) pts.push(...f.pts); else { m[f.id] = f; if (f.k) extra.push(f); } });
      chunkData[k] = m; chunkExtra[k] = extra; chunkPts[k] = pts;
    }).catch(() => { delete chunkLoading[k]; }));
  }

  /* ---------------- Drawing ---------------- */
  let drawToken = 0;
  const swap = g => g.map(part => part.map(c => [c[1], c[0]]));
  const mid = g => { const p = g.reduce((a, b) => (b.length > a.length ? b : a)); return p[Math.floor(p.length / 2)]; };
  async function draw() {
    if (!META) return;
    const token = ++drawToken;
    const z = map.getZoom();
    const keys = chunksInView();
    if (keys.length > 40 && z < 9) {
      waterLayer.clearLayers(); siteHi.clearLayers(); labelLayer.clearLayers();
      const b = map.getBounds();
      ITEMS.forEach(it => {
        if (!passing.has(it.id) || !b.contains([it.c[1], it.c[0]])) return;
        if (it.k === 's' && (it.o || 1) < Math.max(F.minOrder, 4)) return;
        L.circleMarker([it.c[1], it.c[0]], { renderer: canvas, radius: it.k === 'l' ? 4 : 3, weight: 1, color: '#fff', fillColor: colorOf(it), fillOpacity: 1 })
          .on('click', () => select(it.id, false)).addTo(waterLayer);
      });
      $('#listInfo').textContent = 'Zoom in to see lake outlines and each stretch of stream.';
      return renderList();
    }
    await Promise.all(keys.map(loadChunk));
    if (token !== drawToken) return;
    waterLayer.clearLayers(); siteHi.clearLayers(); labelLayer.clearLayers();
    const b = map.getBounds().pad(0.1);
    const labels = [];
    if (F.noRecord && z >= 10) {
      for (const k of keys) for (const f of (chunkExtra[k] || [])) {
        if (f.k === 'l' ? !F.lakes : (!F.streams || (f.o || 1) < F.minOrder)) continue;
        const g = f.g || (f.r || []).flatMap(r => r.g);
        const lyr = f.k === 'l' ? L.polygon(swap(g), { renderer: canvas, color: NO_REC, weight: 1, fillColor: NO_REC, fillOpacity: 0.2 }) : L.polyline(swap(g), { renderer: canvas, color: NO_REC, weight: Math.min(1 + (f.o || 1) * 0.5, 3), opacity: 0.5 });
        lyr.bindTooltip((f.n || 'Unnamed') + ' · no fish records', { sticky: true }).addTo(waterLayer);
      }
    }
    const items = ITEMS.filter(it => passing.has(it.id) && inBox(it.b, b));
    items.sort((a, c) => (a.k === 'l') - (c.k === 'l') || (a.o || 1) - (c.o || 1));
    for (const it of items) {
      const f = (chunkData[it.ch] || {})[it.id];
      if (!f) continue;
      if (it.k === 'l') {
        const col = colorOf(it);
        L.polygon(swap(f.g), { renderer: canvas, color: '#ffffff', weight: 6, fill: false, opacity: 0.9, interactive: false }).addTo(waterLayer);
        L.polygon(swap(f.g), { renderer: canvas, color: colorOfSp(selOnly(allSp(it))), weight: 3, fillColor: colorOfSp(selOnly(allSp(it))), fillOpacity: 0.5 })
          .bindTooltip(hoverCodes(dispName(it), selOnly(allSp(it))), { sticky: true, className: 'codes-lbl hover' }).on('click', () => select(it.id, false)).addTo(waterLayer);
        labels.push([it.c[1], it.c[0], selOnly(allSp(it)), 1000]);
        continue;
      }
      // Streams: each stretch (reach) shows only the species caught on that stretch.
      for (const r of f.r || []) {
        const sp = spIn(r.y);
        const w = Math.min(1 + (r.o || it.o || 1) * 0.7, 6);
        if (selMatch(sp)) L.polyline(swap(r.g), { renderer: canvas, color: '#ffffff', weight: w + 4, opacity: 0.9, interactive: false }).addTo(waterLayer);
        const lyr = selMatch(sp)
          ? L.polyline(swap(r.g), { renderer: canvas, color: colorOfSp(selOnly(sp)), weight: w + 1, opacity: 1 })
          : L.polyline(swap(r.g), { renderer: canvas, color: '#6f8f9a', weight: Math.max(1, w - 2), opacity: 0.55, dashArray: '4 5' });
        lyr.bindTooltip(selMatch(sp) ? hoverCodes(dispName(it), selOnly(sp)) : `${esc(dispName(it))}<br><span class="hint">No survey record of the selected fish on this stretch</span>`, { sticky: true, className: 'codes-lbl hover' })
          .on('click', () => select(it.id, false, r)).addTo(waterLayer);
        if (selOnly(sp).length) { const m = mid(r.g); labels.push([m[1], m[0], selOnly(sp), r.o || 1]); }
      }
    }
    if (F.sites && z >= 11) drawSites(keys, items);
    drawLabels(labels);
    renderList();
  }
  // Nearest point on a set of [lon, lat] lines; returns [lat, lon, metres] or null.
  function snapTo(lines, lon, lat) {
    const kx = 111320 * Math.cos(lat * Math.PI / 180), ky = 110540; let best = null;
    for (const g of lines) for (let i = 1; i < g.length; i++) {
      const ax = (g[i - 1][0] - lon) * kx, ay = (g[i - 1][1] - lat) * ky, bx = (g[i][0] - lon) * kx, by = (g[i][1] - lat) * ky;
      const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy, t = L2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / L2)) : 0;
      const px = ax + t * dx, py = ay + t * dy, d = Math.hypot(px, py);
      if (!best || d < best[2]) best = [lat + py / ky, lon + px / kx, d];
    }
    return best;
  }
  function siteLayer(s, name, lines) {
    const sp = spIn(s[2]);
    if (!sp.length) return;
    // Draw the dot on the stream line (sites were matched to the stream within 500 m); the popup keeps the recorded position.
    const snap = lines && lines.length ? snapTo(lines, s[0], s[1]) : null;
    const ll = snap && snap[2] <= 600 ? [snap[0], snap[1]] : [s[1], s[0]];
    const where = snap && snap[2] <= 600 && snap[2] >= 15 ? `<br><span class="hint">Shown on the stream line; recorded at ${s[1].toFixed(5)}, ${s[0].toFixed(5)} (${Math.round(snap[2])} m away)</span>` : '';
    const src = s[4] && s[4].startsWith('pc:') ? `Parks Canada (${s[4].slice(3)})` : 'FWMIS survey';
    const tip = `<b>${esc(name || 'Survey site')}</b><br>${sp.map(c => `<span class="code">${c}</span> ${esc(spName(c))}${s[2][c] ? ' (' + s[2][c] + ')' : ''}`).join('<br>')}<br><span class="hint">${src}${s[5] && s[5].length ? ' · ' + esc(s[5].join(', ')) : ''} · ${s[3]} record${s[3] > 1 ? 's' : ''}</span>${where}`;
    const hit = selMatch(sp), z = map.getZoom(), r = hit ? Math.min(9, 4 + (z - 11)) : 3;
    if (hit) {  // white halo + dark ring so the selected fish stand out on any basemap
      L.circleMarker(ll, { renderer: canvas, radius: r + 3, weight: 0, fillColor: '#fff', fillOpacity: 0.9, interactive: false }).addTo(siteHi);
      L.circleMarker(ll, { renderer: canvas, radius: r, weight: 2, color: '#111', fillColor: colorOfSp(sp), fillOpacity: 1 })
        .bindTooltip(tip, { direction: 'top' }).addTo(siteHi);
      if (F.labels && z >= 15) L.tooltip({ permanent: true, direction: 'right', className: 'codes-lbl', offset: [r + 2, 0], interactive: false })
        .setLatLng(ll).setContent(sp.map(c => `<span style="color:${spColor(c)}">${c}</span>`).join(' ')).addTo(labelLayer);
    } else {
      L.circleMarker(ll, { renderer: canvas, radius: r, weight: 1, color: '#fff', fillColor: '#888', fillOpacity: 0.7 })
        .bindTooltip(tip, { direction: 'top' }).addTo(waterLayer);
    }
  }
  function drawSites(keys, items) {
    const b = map.getBounds();
    for (const it of items) { const f = (chunkData[it.ch] || {})[it.id]; const lines = it.k === 's' && f && f.r ? f.r.map(r => r.g) : null; (f && f.s || []).forEach(s => { if (b.contains([s[1], s[0]])) siteLayer(s, dispName(it), lines); }); }
    for (const k of keys) (chunkPts[k] || []).forEach(s => { if (b.contains([s[1], s[0]])) siteLayer(s, s[6] ? s[6] + ' (not on a mapped water)' : 'Survey site not on a mapped water'); });
  }
  const hoverCodes = (name, codes) => `<b class="hn">${esc(name)}</b><br>` + codes.map(c => `<span style="color:${spColor(c)}">${c}</span>`).join(' ');
  function drawLabels(labels) {
    if (!F.labels || map.getZoom() < LABEL_ZOOM) return;
    const b = map.getBounds();
    labels.filter(l => l[2].length && b.contains([l[0], l[1]])).sort((a, c) => c[3] - a[3]).slice(0, MAX_LABELS).forEach(l =>
      L.tooltip({ permanent: true, direction: 'right', className: 'codes-lbl', offset: [4, 0], interactive: false })
        .setLatLng([l[0], l[1]]).setContent(l[2].map(c => `<span style="color:${spColor(c)}">${c}</span>`).join(' ')).addTo(labelLayer));
  }
  map.on('moveend', () => { draw(); });

  function applyFilters() {
    passing = new Set(ITEMS.filter(passes).map(it => it.id));
    $('#count').textContent = `${passing.size.toLocaleString()} waters with selected fish · ${(META.total || ITEMS.length).toLocaleString()} lakes & streams mapped`;
    $('#ordOut').textContent = F.minOrder <= 1 ? 'all' : `order ${F.minOrder}+`;
    draw();
  }

  /* ---------------- List ---------------- */
  function renderList() {
    if (!META) return;
    const q = $('#q').value.trim().toLowerCase();
    const inView = $('#inView').checked, b = map.getBounds();
    let rows = ITEMS.filter(it => passing.has(it.id) &&
      (!inView || inBox(it.b, b)) &&
      (!q || ((it.n || '') + ' ' + (it.a || '') + ' ' + allSp(it).join(' ')).toLowerCase().includes(q)));
    const total = rows.length;
    if (sort.key === 'codes') rows.sort((a, c) => (RARITY.indexOf(topSpecies(a)) + 1 || 99) - (RARITY.indexOf(topSpecies(c)) + 1 || 99));
    else rows.sort((a, c) => dispName(a).localeCompare(dispName(c)));
    if (sort.desc) rows.reverse();
    rows = rows.slice(0, 300);
    $$('.sites th').forEach(th => { th.classList.toggle('sorted', th.dataset.sort === sort.key); th.classList.toggle('desc', th.dataset.sort === sort.key && sort.desc); });
    if (map.getZoom() >= 9 || !inView) $('#listInfo').textContent = `${total.toLocaleString()} waters${total > 300 ? ' (showing first 300)' : ''}`;
    $('#siteRows').innerHTML = rows.map(it => `
      <tr data-id="${it.id}" class="${it.id === selectedId ? 'sel' : ''}">
        <td>${esc(dispName(it))}${it.st ? '<span class="badge pc">stocked</span>' : ''}
          <div class="sub">${it.k === 'l' ? 'Lake' : 'Stream' + (it.o ? ', order ' + it.o : '')}${it.pk ? ' · ' + esc(Object.keys(it.pk).join(', ')) + ' NP' : ''}${it.a && it.n ? ' · ' + esc(it.a) : ''}</div></td>
        <td class="codes">${selOnly(allSp(it)).map(c => `<span style="color:${spColor(c)}">${c}</span>`).join(' ')}</td>
      </tr>`).join('') || '<tr><td colspan="2" class="hint">Nothing matches. Select more species, widen the filters or pan the map.</td></tr>';
  }

  /* ---------------- Details ---------------- */
  const chips = (list, it) => list.map(c => `<span class="chip"><span class="dot" style="background:${spColor(c)}"></span><b class="code">${c}</b> ${esc(spName(c))}${it && yrs(it, c) ? ` <span class="hint">${yrs(it, c)}</span>` : ''}</span>`).join('');
  async function select(id, pan = true, reach = null) {
    selectedId = id;
    const it = BYID[id];
    await loadChunk(it.ch);
    if (hiLayer) map.removeLayer(hiLayer);
    const f = (chunkData[it.ch] || {})[id];
    const g = f ? (f.g || (f.r || []).flatMap(r => r.g)) : null;
    if (g) {
      hiLayer = (it.k === 'l' ? L.polygon(swap(g), { color: '#ffeb3b', weight: 5, fill: false }) : L.polyline(swap(g), { color: '#ffeb3b', weight: 9, opacity: 0.6 })).addTo(map);
      hiLayer.bringToBack();
      if (pan) map.fitBounds(hiLayer.getBounds(), { maxZoom: 13, padding: [30, 30] });
    } else if (pan) map.setView([it.c[1], it.c[0]], 12);
    const sp = allSp(it);
    const sites = (f && f.s || []).slice().sort((a, c) => Math.max(0, ...Object.values(c[2])) - Math.max(0, ...Object.values(a[2])));
    const stocked = it.st ? Object.entries(it.st).map(([c, ys]) => `<li><b class="code">${c}</b> ${esc(spName(c))}${ys.length ? `: ${ys.length > 6 ? ys[0] + '–' + ys[ys.length - 1] + ` (${ys.length} years)` : ys.join(', ')}` : ''}</li>`).join('') : '';
    $('#tab-detail').innerHTML = `<div class="detail">
      <h2>${esc(dispName(it))}</h2>
      <div class="sub hint">${it.k === 'l' ? 'Lake / pond / reservoir' : 'River / stream' + (it.o ? `, Strahler order ${it.o}` : '')}${it.a && it.n ? ' · also called ' + esc(it.a) : ''}${it.pk ? ' · ' + esc(Object.keys(it.pk).join(', ')) + ' National Park' : ''}</div>
      ${reach ? `<h3 class="dh">This stretch${F.since ? ` (since ${F.since})` : ''}</h3>
      <div>${spIn(reach.y).length ? chips(selOnly(spIn(reach.y)).concat(spIn(reach.y).filter(c => !selOnly([c]).length))) : '<span class="hint">No survey records on this stretch.</span>'}</div>` : ''}
      <h3 class="dh">${it.k === 's' ? (reach ? 'Whole stream, all stretches' : 'Caught at survey sites along this stream') : 'Recorded in this lake'}${F.since ? ` (since ${F.since})` : ''}</h3>
      <div>${selOnly(sp).length ? chips(selOnly(sp), it) : '<span class="hint">None of the selected species.</span>'}</div>
      ${sp.filter(c => !selOnly([c]).length).length ? `<details><summary class="hint">Other fish recorded (${sp.filter(c => !selOnly([c]).length).length})</summary>${chips(sp.filter(c => !selOnly([c]).length), it)}</details>` : ''}
      ${it.k === 's' ? '<p class="hint">Tap a stretch on the map to see what was caught on that stretch. Dashed stretches have no survey record of the selected species.</p>' : ''}
      ${stocked ? `<h3 class="dh">Stocking records</h3><ul class="stock">${stocked}</ul>` : ''}
      ${sites.length ? `<h3 class="dh">Survey sites (${sites.length})</h3><ul class="stock">${sites.slice(0, 40).map(s => `<li><span class="code">${Object.keys(s[2]).sort().join(' ')}</span> · ${Math.max(0, ...Object.values(s[2])) || 'undated'}${s[4].startsWith('pc:') ? ' · Parks Canada' : ''}${s[5] && s[5].length ? ' · ' + esc(s[5].join(', ')) : ''}</li>`).join('')}${sites.length > 40 ? '<li class="hint">…</li>' : ''}</ul>` : ''}
      ${it.pres && it.pres.length ? `<details><summary class="hint">FWMIS list for the whole river system, not location-specific (${it.pres.length})</summary><p class="code">${it.pres.join(' ')}</p></details>` : ''}
      <dl>
        <dt>FWMIS ID</dt><dd class="code">${id.slice(1)}</dd>
        ${it.h ? `<dt>Watershed</dt><dd class="code">HUC ${esc(it.h)}</dd>` : ''}
        <dt>Location</dt><dd class="code">${it.c[1].toFixed(4)}, ${it.c[0].toFixed(4)}</dd>
      </dl>
      <div class="route-btns">
        <button id="dRoute" class="primary">Add to route</button>
        <button id="dHere">Route here from me</button>
        <button id="dCopy">Copy coordinates</button>
      </div>
      <p class="hint">Sources: Alberta FWMIS fish survey records${it.pk ? ' and Parks Canada open data (' + Object.entries(it.pk).map(([p, u]) => `<a href="${u}" target="_blank" rel="noopener">${esc(p)}</a>`).join(', ') + ')' : ''}. A record means the species was caught there in that year, not that it is there today.
      ${it.pk ? 'National parks need a Parks Canada fishing permit. ' : ''}Check seasons, limits and closures in the <a href="https://albertaregulations.ca/fishingregs/" target="_blank" rel="noopener">Alberta sportfishing regulations</a>.</p>
    </div>`;
    $('#dRoute').onclick = () => { route.add(L.latLng(it.c[1], it.c[0])); showTab('route'); toast('Added to route'); };
    $('#dHere').onclick = () => route.fromMe(L.latLng(it.c[1], it.c[0]));
    $('#dCopy').onclick = () => { navigator.clipboard && navigator.clipboard.writeText(`${it.c[1]}, ${it.c[0]}`).then(() => toast('Copied')); };
    showTab('detail'); openPanel('side'); renderList();
  }

  /* ---------------- Panels and tabs ---------------- */
  function showTab(name) {
    $$('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    $$('.tab').forEach(t => { t.hidden = t.id !== 'tab-' + name; });
    $('#sideTitle').textContent = { list: 'Waters', detail: 'Details', route: 'Route' }[name];
  }
  function openPanel(id) { if (!isMobile()) return; $$('.panel').forEach(p => p.classList.toggle('open', p.id === id)); }
  function closePanels() { $$('.panel').forEach(p => p.classList.remove('open')); }
  $$('.tabs button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
  $$('[data-close]').forEach(b => b.onclick = closePanels);
  $('#btnFilters').onclick = () => $('#filters').classList.contains('open') ? closePanels() : openPanel('filters');
  $('#btnList').onclick = () => { if ($('#side').classList.contains('open')) closePanels(); else { showTab('list'); openPanel('side'); } };
  map.on('click', () => { if (isMobile() && !route.drawing) closePanels(); });
  window.addEventListener('resize', () => { if (!isMobile()) closePanels(); map.invalidateSize(); });

  /* ---------------- Route planner ---------------- */

  /* ---------------- Routing helpers: OSRM routes, OSM surfaces, parking ---------------- */
  const routeLayer = L.layerGroup().addTo(map);
  // Line type per surface. Surface comes only from OpenStreetMap tags on the ways the route uses.
  const RT_STYLE = {
    paved: { label: 'Paved road', line: { color: '#d84315', weight: 6, opacity: 1 }, casing: true },
    gravel: { label: 'Gravel or dirt road', line: { color: '#d84315', weight: 5, dashArray: '12 7', opacity: 1 }, casing: true },
    unknown: { label: 'Road, surface not mapped', line: { color: '#d84315', weight: 4, dashArray: '2 6 10 6', opacity: 0.85 }, casing: true },
    foot: { label: 'On foot (trail or path)', line: { color: '#1b5e20', weight: 5, dashArray: '1 9', lineCap: 'round', opacity: 1 }, casing: true },
    dryweather: { label: 'Dry-weather road (unpaved, impassable when wet)', line: { color: '#6d4c41', weight: 5, dashArray: '6 5', opacity: 1 }, casing: true },
    winter: { label: 'Winter road', line: { color: '#5c6bc0', weight: 5, dashArray: '6 5', opacity: 1 }, casing: true },
    ford: { label: 'Ford or winter crossing', line: { color: '#0277bd', weight: 6, opacity: 1 }, casing: true },
    unchecked: { label: 'Road (surface not checked)', line: { color: '#d84315', weight: 5, opacity: 0.75 }, casing: true },
    straight: { label: 'Straight line (not routed)', line: { color: '#ff5722', weight: 3, dashArray: '4 4', opacity: 0.9 } },
  };
  const rtSwatch = c => { const l = RT_STYLE[c].line; return `<svg width="38" height="10" class="rt-sw"><line x1="3" y1="5" x2="35" y2="5" stroke="#fff" stroke-width="${l.weight + 3}" stroke-linecap="round"/><line x1="3" y1="5" x2="35" y2="5" stroke="${l.color}" stroke-width="${l.weight}" stroke-dasharray="${l.dashArray || ''}" stroke-linecap="${l.lineCap || 'butt'}"/></svg>`; };
  const PAVED = /^(paved|asphalt|concrete|concrete:plates|concrete:lanes|paving_stones|sett|chipseal|metal|wood)$/;
  const UNPAVED = /^(unpaved|gravel|fine_gravel|compacted|dirt|earth|ground|mud|sand|grass|pebblestone|rock|gravel;ground|woodchips|clay|stone)$/;
  const FOOTWAY = /^(path|footway|bridleway|steps|pedestrian|cycleway|via_ferrata|corridor)$/;
  function surfaceClass(t, legMode) {
    if (!t) return legMode === 'foot' ? 'foot' : 'unknown';
    if (FOOTWAY.test(t.highway || '')) return 'foot';
    const sf = (t.surface || '').toLowerCase();
    if (PAVED.test(sf)) return 'paved';
    if (UNPAVED.test(sf)) return 'gravel';
    if (t.highway === 'track' && /^grade[2-5]$/.test(t.tracktype || '')) return 'gravel';
    if (t.highway === 'track' && t.tracktype === 'grade1') return 'paved';
    return 'unknown';
  }
  async function osrm(mode, pts) {
    const prof = mode === 'drivehike' ? 'car' : mode;
    const coords = pts.map(p => `${p.lng.toFixed(5)},${p.lat.toFixed(5)}`).join(';');
    const r = await fetch(`https://routing.openstreetmap.de/routed-${prof}/route/v1/driving/${coords}?overview=full&geometries=geojson&annotations=nodes`, { signal: withTimeout(20000) });
    const j = await r.json();
    if (!j.routes || !j.routes[0]) throw new Error('No route found along roads or trails.');
    const rt = j.routes[0], nodes = [];
    (rt.legs || []).forEach(l => ((l.annotation || {}).nodes || []).forEach(n => { if (nodes[nodes.length - 1] !== n) nodes.push(n); }));
    return { path: rt.geometry.coordinates.map(c => L.latLng(c[1], c[0])), nodes, dur: rt.duration, dist: rt.distance };
  }
  // Split each leg into runs of the same surface class, using the OSM ways that hold each pair of route nodes.
  // Vehicles allowed on this way by its OSM tags (no access=no/private and no motor_vehicle/vehicle ban).
  const NO_CAR = /^(no|private|agricultural|forestry|delivery|permit|military)$/;
  const carOk = t => !!t && !FOOTWAY.test(t.highway || '') && !/^(construction|proposed|abandoned|raceway|bus_guideway)$/.test(t.highway || '') &&
    !NO_CAR.test(t.access || '') && !NO_CAR.test(t.motor_vehicle || '') && !NO_CAR.test(t.vehicle || '') && !NO_CAR.test(t.motorcar || '');
  // Split each leg into runs of the same surface class, using the OSM ways that hold each pair of route nodes.
  // Surfaces are looked up for the walk and the last part of the drive (about the last 30 km); the rest of a long
  // drive is shown as "surface not checked" to keep the lookup small enough to answer.
  async function classifyLegs(legs) {
    const all = [...new Set(legs.flatMap(l => l.r.nodes))];
    const sub = [...new Set(legs.flatMap(l => l.mode === 'foot' ? l.r.nodes : l.r.nodes.slice(-700)))];
    let pos = {}, pair = {};
    if (all.length) {
      try {
        const j = await overpass(`[out:json][timeout:60];node(id:${all.join(',')});out skel qt;node(id:${sub.join(',')});way(bn)["highway"];out body qt;`, 60000, true);
        for (const e of j.elements || []) {
          if (e.type === 'node') pos[e.id] = L.latLng(e.lat, e.lon);
          else if (e.type === 'way') for (let k = 1; k < e.nodes.length; k++) pair[Math.min(e.nodes[k - 1], e.nodes[k]) + ':' + Math.max(e.nodes[k - 1], e.nodes[k])] = e.tags;
        }
      } catch (e) { console.warn('surface lookup', e); pos = {}; }
    }
    const inSub = new Set(sub), runs = [];
    const push = (cls, a, b, leg, drv) => { const last = runs[runs.length - 1]; if (last && last.cls === cls && last.leg === leg && last.drv === drv) last.pts.push(b); else runs.push({ cls, pts: [a, b], leg, drv }); };
    legs.forEach((l, li) => {
      const n = l.r.nodes;
      if (n.length < 2 || n.some(id => !pos[id])) {  // no node data: keep OSRM geometry, class from leg mode only
        const g = l.r.path; for (let k = 1; k < g.length; k++) push(l.mode === 'foot' ? 'foot' : 'unchecked', g[k - 1], g[k], li, l.mode !== 'foot');
        return;
      }
      const seg = (a, b) => {
        if (!inSub.has(a) || !inSub.has(b)) return ['unchecked', true];
        const t = pair[Math.min(a, b) + ':' + Math.max(a, b)];
        return [surfaceClass(t, l.mode), l.mode === 'foot' ? carOk(t) : true];
      };
      let [c0, d0] = seg(n[0], n[1]);
      push(c0, l.r.path[0], pos[n[0]], li, d0);
      for (let k = 1; k < n.length; k++) { const [c, d] = seg(n[k - 1], n[k]); push(c, pos[n[k - 1]], pos[n[k]], li, d); }
      const lr = runs[runs.length - 1]; push(lr.cls, pos[n[n.length - 1]], l.r.path[l.r.path.length - 1], li, lr.drv);
    });
    return runs.length ? runs : [{ cls: 'unchecked', pts: legs[0].r.path, leg: 0, drv: true }];
  }
  // The car router skips some roads that OSM marks as open to vehicles (often gravel tracks to trailheads).
  // If the walk starts on such a road, keep driving to where the road ends or becomes restricted.
  function extendDrive(runs, marks) {
    const footStart = runs.findIndex(r => r.leg === 1);
    if (footStart < 0) return null;
    let k = footStart, d = 0;
    const len = pts => { let x = 0; for (let m = 1; m < pts.length; m++) x += pts[m - 1].distanceTo(pts[m]); return x; };
    const drivable = r => r && r.leg === 1 && r.cls !== 'foot' && r.drv;
    // Short gaps under 40 m (a junction, a snapped route end) do not stop the drive if a drivable road follows.
    while (k < runs.length && (drivable(runs[k]) || (runs[k].leg === 1 && len(runs[k].pts) < 40 && drivable(runs[k + 1])))) {
      if (!drivable(runs[k])) runs[k].cls = runs[k + 1].cls;
      runs[k].leg = 0; d += len(runs[k].pts); k++;
    }
    if (!d || k >= runs.length) return null;
    const end = runs[k].pts[0], main = marks.find(m => m.kind === 'roadend' || m.kind === 'park');
    if (main && main.kind === 'roadend') main.at = end;
    return d;
  }
  // Where the route leaves a road for a trail (ignoring short footpath bits under 300 m).
  function transitions(runs) {
    const out = [], len = pts => { let d = 0; for (let k = 1; k < pts.length; k++) d += pts[k - 1].distanceTo(pts[k]); return d; };
    let onFoot = runs.length && runs[0].cls === 'foot';
    for (let k = 1; k < runs.length; k++) {
      const foot = runs[k].cls === 'foot';
      if (foot === onFoot) continue;
      if (foot) { let d = 0; for (let m = k; m < runs.length && runs[m].cls === 'foot'; m++) d += len(runs[m].pts); if (d < 300) continue; }
      else { let d = 0; for (let m = k; m < runs.length && runs[m].cls !== 'foot'; m++) d += len(runs[m].pts); if (d < 300) continue; }
      out.push({ kind: foot ? 'tofoot' : 'toroad', at: runs[k].pts[0] });
      onFoot = foot;
    }
    return out;
  }
  async function findParking(at, radius) {
    const j = await overpass(`[out:json][timeout:15];nwr["amenity"="parking"](around:${radius},${at.lat.toFixed(5)},${at.lng.toFixed(5)});out center tags;`, 10000, true);
    return (j.elements || []).filter(e => !/^(private|no|customers)$/.test((e.tags || {}).access || '') && (e.lat || e.center)).map(e => ({ at: L.latLng(e.lat || e.center.lat, e.lon || e.center.lon), tags: e.tags || {}, id: e.type + e.id }));
  }
  async function parkingNear(points, have) {
    const seen = new Set(have.filter(m => m.pid).map(m => m.pid)), out = [];
    try {
      const pts = points.slice(0, 8);
      const j = await overpass(`[out:json][timeout:15];(${pts.map(p => `nwr["amenity"="parking"](around:400,${p.lat.toFixed(5)},${p.lng.toFixed(5)});`).join('')});out center tags;`, 15000, true);
      const found = (j.elements || []).filter(e => !/^(private|no|customers)$/.test((e.tags || {}).access || '') && (e.lat || e.center)).map(e => ({ at: L.latLng(e.lat || e.center.lat, e.lon || e.center.lon), tags: e.tags || {}, id: e.type + e.id }));
      for (const f of found) if (!seen.has(f.id)) { seen.add(f.id); out.push({ kind: 'parking', at: f.at, tags: f.tags, pid: f.id }); }
    } catch (e) { console.warn('parking lookup', e); }
    return out;
  }
  // Roads near a point from the Alberta road data: the nearest vertex of each distinct road (by name, else by feature).
  async function abNearRoads(at, radius) {
    const body = new URLSearchParams({
      geometry: JSON.stringify({ x: +at.lng.toFixed(5), y: +at.lat.toFixed(5), spatialReference: { wkid: 4326 } }), geometryType: 'esriGeometryPoint', inSR: '4326',
      spatialRel: 'esriSpatialRelIntersects', distance: String(radius), units: 'esriSRUnit_Meter', where: 'FEATURE_TYPE IN (3,4,5,6,7,8,9,14)',
      outFields: 'OBJECTID,FEATURE_TYPE,NAME', returnGeometry: 'true', outSR: '4326', f: 'geojson', resultRecordCount: '1500' });
    const r = await fetch(AB_ROADS, { method: 'POST', body, signal: withTimeout(20000) });
    const j = await r.json();
    if (j.error) throw new Error(j.error.message || 'Alberta roads error');
    const best = new Map();
    for (const f of j.features || []) {
      const g = f.geometry; if (!g) continue;
      const lines = g.type === 'LineString' ? [g.coordinates] : g.type === 'MultiLineString' ? g.coordinates : [];
      const key = (f.properties.NAME || '').trim() || 'id' + f.properties.OBJECTID;
      for (const ln of lines) for (const c of ln) {
        const ll = L.latLng(c[1], c[0]), d = ll.distanceTo(at);
        if (!best.has(key) || d < best.get(key).d) best.set(key, { at: ll, d, name: f.properties.NAME || '', ft: f.properties.FEATURE_TYPE });
      }
    }
    return [...best.values()].sort((a, b) => a.d - b.d);
  }
  // OSRM table: distances from sources to destinations in one request (also returns where each point snaps to).
  async function osrmTable(prof, pts, sources, dests) {
    const coords = pts.map(p => `${p.lng.toFixed(5)},${p.lat.toFixed(5)}`).join(';');
    const r = await fetch(`https://routing.openstreetmap.de/routed-${prof}/table/v1/driving/${coords}?sources=${sources.join(';')}&destinations=${dests.join(';')}&annotations=distance`, { signal: withTimeout(20000) });
    const j = await r.json();
    if (j.code !== 'Ok') throw new Error('No route table: ' + (j.message || j.code));
    return j;
  }
  // Drive, then walk the shortest way. Instead of only driving to the road point nearest the water (which may have
  // no trail), trail access points all around the destination are compared and the one with the shortest walk wins:
  //  - the road point nearest the destination,
  //  - the nearest road to points 4, 9 and 15 km out in 8 directions (any road the car router knows, BC included),
  //  - the nearest point of each road within 15 km in the Government of Alberta road data,
  //  - mapped public parking within 10 km (OpenStreetMap, if it answers in time),
  //  - then any road the best walk still crosses or follows (drive there instead of walking to it).
  // Two table requests compare them all (car: reachable from the start? foot: walking distance to the water).
  async function driveThenHike(pts) {
    const start = pts[0], walkPts = pts.slice(1), dest = pts[pts.length - 1];
    const lotsP = findParking(dest, 10000).then(l => l.sort((a, b) => a.at.distanceTo(dest) - b.at.distanceTo(dest)).slice(0, 4)).catch(e => { console.warn('parking', e); return []; });
    const roadsP = abNearRoads(dest, 15000).catch(e => { console.warn('Alberta near roads', e); return []; });
    const offs = (km, deg) => { const r = deg * Math.PI / 180; return L.latLng(dest.lat + km / 110.54 * Math.cos(r), dest.lng + km / (111.32 * Math.cos(dest.lat * Math.PI / 180)) * Math.sin(r)); };
    const probes = [{ at: dest, kind: 'roadend' }];
    for (const km of [4, 9, 15]) for (let deg = 0; deg < 360; deg += 45) probes.push({ at: offs(km, deg + (km === 9 ? 22.5 : 0)), kind: 'roadend' });
    for (const r of (await roadsP).slice(0, 6)) probes.push({ at: r.at, kind: 'roadend', road: r.name });
    const lots = await Promise.race([lotsP, new Promise(r => setTimeout(() => r(null), 3000))]);
    for (const c of lots || []) probes.push({ at: c.at, kind: 'park', tags: c.tags, pid: c.id });
    // 1. Car: which probes can be driven to from the start, and where does each one meet the road network?
    const ct = await osrmTable('car', [start, ...probes.map(p => p.at)], [0], probes.map((_, k) => k + 1));
    let cands = [];
    probes.forEach((p, k) => {
      const d = ct.distances[0][k], w = ct.destinations[k];
      if (d == null || !w) return;
      const at = L.latLng(w.location[1], w.location[0]);
      if (cands.some(c => c.at.distanceTo(at) < 300 && (c.kind === p.kind || p.kind !== 'park'))) return;
      cands.push({ ...p, at: p.kind === 'park' ? p.at : at, carDist: d });
    });
    if (!cands.length) {
      const walk = await osrm('foot', pts).catch(() => null);
      if (walk) return { legs: [{ mode: 'foot', r: walk }], marks: [], note: 'No driving route found from the start, so this is a walking route.' };
      throw new Error('No route found along roads or trails.');
    }
    // 2. Foot: walking distance from each access point to the destination.
    const ft = await osrmTable('foot', [...cands.map(c => c.at), dest], cands.map((_, k) => k), [cands.length]);
    cands.forEach((c, k) => { c.footDist = ft.distances[k][0]; });
    cands = cands.filter(c => c.footDist != null).sort((a, b) => a.footDist - b.footDist || a.carDist - b.carDist);
    if (!cands.length) throw new Error('No walking route found to the destination.');
    const best = cands.find(c => c.kind === 'park' && c.footDist <= cands[0].footDist + 300) || cands[0];
    // 3. Full routes for the winner.
    let car = await osrm('car', [start, best.at]);
    let end = best.kind === 'park' ? best.at : car.path[car.path.length - 1];
    let foot = await osrm('foot', [end, ...walkPts]);
    // 4. If the walk still crosses or follows a drivable road, drive to the last such point instead.
    try {
      const ab = await abRoads(foot.path), fp = foot.path; let cut = -1;
      for (let k = fp.length - 1; k > 0; k--) { const sg = abAt(ab, fp[k].lat, fp[k].lng); if (sg && /^(paved|gravel|dryweather)$/.test(AB_CLASS[sg.ft])) { cut = k; break; } }
      if (cut > 0 && fp[cut].distanceTo(fp[0]) > 300) {
        const car2 = await osrm('car', [start, fp[cut]]), end2 = car2.path[car2.path.length - 1], foot2 = await osrm('foot', [end2, ...walkPts]);
        if (foot2.dist < foot.dist - 200) { car = car2; end = end2; foot = foot2; best.kind = 'roadend'; best.road = ''; }
      }
    } catch (e) { console.warn('walk road check', e); }
    return { legs: [{ mode: 'road', r: car }, { mode: 'foot', r: foot }],
      marks: [{ kind: best.kind, at: end, tags: best.tags || {}, pid: best.pid }],
      note: (best.kind === 'park' ? 'Drive to the mapped parking area with the shortest walk.' : `Drive to the trail access point with the shortest walk${best.road ? ' (' + esc(cap(best.road)) + ')' : ''}.`) +
        ` Compared ${cands.length} access points around the destination.` + (lots === null ? ' The OpenStreetMap parking lookup did not answer in time.' : '') };
  }
  function drawRoute(runs, marks) {
    routeLayer.eachLayer(l => l.unbindTooltip && l.unbindTooltip());
    routeLayer.clearLayers();
    for (const r of runs) { const st = RT_STYLE[r.cls]; if (st.casing) L.polyline(r.pts, { color: '#fff', weight: st.line.weight + 4, opacity: 0.95, interactive: false }).addTo(routeLayer); }
    for (const r of runs) L.polyline(r.pts, RT_STYLE[r.cls].line).bindTooltip(RT_STYLE[r.cls].label, { sticky: true }).addTo(routeLayer);
    for (const m of marks) {
      const t = m.tags || {}, nm = t.name || '';
      if (m.kind === 'park' || m.kind === 'parking') {
        const info = [nm || 'Parking', t.fee === 'yes' ? 'fee' : t.fee === 'no' ? 'free' : '', t.capacity ? t.capacity + ' spaces' : '', t.surface ? t.surface : ''].filter(Boolean).join(' · ');
        L.marker(m.at, { icon: L.divIcon({ className: '', html: `<div class="rt-p${m.kind === 'park' ? ' main' : ''}">P</div>`, iconSize: [22, 22], iconAnchor: [11, 11] }), zIndexOffset: 500 })
          .bindTooltip((m.kind === 'park' ? '<b>Park here</b><br>' : '') + esc(info) + '<br><span class="hint">OpenStreetMap</span>', { permanent: m.kind === 'park' || !!nm, direction: 'right', offset: [10, 0], className: 'rt-lbl' }).addTo(routeLayer);
      } else if (m.kind === 'roadend') {
        L.marker(m.at, { icon: L.divIcon({ className: '', html: '<div class="rt-foot">🥾</div>', iconSize: [24, 24], iconAnchor: [12, 12] }), zIndexOffset: 500 })
          .bindTooltip('<b>Drive ends here</b><br>Walk from here', { permanent: true, direction: 'right', offset: [12, 0], className: 'rt-lbl' }).addTo(routeLayer);
      } else {
        L.marker(m.at, { icon: L.divIcon({ className: '', html: `<div class="rt-foot">${m.kind === 'tofoot' ? '🥾' : '🚗'}</div>`, iconSize: [24, 24], iconAnchor: [12, 12] }), zIndexOffset: 400 })
          .bindTooltip(m.kind === 'tofoot' ? '<b>On foot from here</b><br>Road ends, trail begins' : '<b>Back on a road</b>', { permanent: m.kind === 'tofoot', direction: 'right', offset: [12, 0], className: 'rt-lbl' }).addTo(routeLayer);
      }
    }
  }

  /* Road surface from the Government of Alberta Access Road layer (authoritative provincial road data). */
  const AB_ROADS = 'https://geospatial.alberta.ca/titan/rest/services/transportation/access_facility_roads/MapServer/0/query';
  const AB_CLASS = { 3: 'paved', 6: 'paved', 7: 'paved', 8: 'paved', 9: 'paved', 4: 'gravel', 5: 'gravel', 14: 'dryweather', 12: 'winter', 2: 'ford', 10: 'gravel' };
  const AB_TYPE = { 1: 'Ferry crossing', 2: 'Ford/winter crossing', 3: 'Interchange ramp', 4: 'One-lane gravel road', 5: 'Two-lane gravel road', 6: 'Divided paved road', 7: 'One-lane paved road', 8: 'Two-lane paved road', 9: 'Four-lane paved road', 10: 'Driveway', 12: 'Winter road', 14: 'Dry-weather road' };
  async function abRoads(path) {
    // Query in ~15 km pieces (each answer is capped at 2000 roads; city streets crossing the route add up fast).
    const pieces = [[path[0]]]; let acc = 0;
    for (let k = 1; k < path.length; k++) { acc += path[k - 1].distanceTo(path[k]); pieces[pieces.length - 1].push(path[k]); if (acc > 15000 && k < path.length - 1) { pieces.push([path[k]]); acc = 0; } }
    const cells = new Map(), C = 0.005; let n = 0, failed = 0;
    for (let k = 0; k < pieces.length; k += 3) {
      const res = await Promise.all(pieces.slice(k, k + 3).map(pc => abQuery(pc).catch(e => { console.warn('Alberta roads', e); failed++; return []; })));
      for (const feats of res) { n += feats.length; indexAB(feats, cells, C); }
    }
    if (!n && failed) throw new Error('Alberta road data did not answer');
    return { cells, C, n };
  }
  async function abQuery(path) {
    const v = [path[0]]; let acc = 0;  // a vertex every ~150 m stays within the 40 m search buffer
    for (let k = 1; k < path.length; k++) { acc += path[k - 1].distanceTo(path[k]); if (acc >= 150 || k === path.length - 1) { v.push(path[k]); acc = 0; } }
    const body = new URLSearchParams({
      geometry: JSON.stringify({ paths: [v.map(p => [+p.lng.toFixed(5), +p.lat.toFixed(5)])], spatialReference: { wkid: 4326 } }),
      geometryType: 'esriGeometryPolyline', inSR: '4326', spatialRel: 'esriSpatialRelIntersects', distance: '40', units: 'esriSRUnit_Meter',
      outFields: 'FEATURE_TYPE,NAME,HWY_NUMBER', returnGeometry: 'true', outSR: '4326', f: 'geojson', resultRecordCount: '2000' });
    const r = await fetch(AB_ROADS, { method: 'POST', body, signal: withTimeout(25000) });
    if (!r.ok) throw new Error('Alberta roads ' + r.status);
    const j = await r.json();
    if (j.error) throw new Error('Alberta roads: ' + (j.error.message || 'error'));
    return j.features || [];
  }
  function indexAB(features, cells, C) {
    for (const f of features) {
      const ft = (f.properties || {}).FEATURE_TYPE, g = f.geometry; if (!g || AB_CLASS[ft] === undefined) continue;
      const lines = g.type === 'LineString' ? [g.coordinates] : g.type === 'MultiLineString' ? g.coordinates : [];
      for (const ln of lines) for (let k = 1; k < ln.length; k++) {
        const sg = { a: ln[k - 1], b: ln[k], ft, name: f.properties.NAME || '' };
        const x0 = Math.floor(Math.min(sg.a[0], sg.b[0]) / C), x1 = Math.floor(Math.max(sg.a[0], sg.b[0]) / C), y0 = Math.floor(Math.min(sg.a[1], sg.b[1]) / C), y1 = Math.floor(Math.max(sg.a[1], sg.b[1]) / C);
        for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) { const key = x + ':' + y; (cells.get(key) || cells.set(key, []).get(key)).push(sg); }
      }
    }
  }
  // Nearest Alberta road segment to a point (within 25 m), or null.
  function abAt(ab, lat, lon) {
    const kx = 111320 * Math.cos(lat * Math.PI / 180), ky = 110540; let best = null, bd = 25;
    const cx = Math.floor(lon / ab.C), cy = Math.floor(lat / ab.C);
    for (let x = cx - 1; x <= cx + 1; x++) for (let y = cy - 1; y <= cy + 1; y++) for (const sg of ab.cells.get(x + ':' + y) || []) {
      const ax = (sg.a[0] - lon) * kx, ay = (sg.a[1] - lat) * ky, bx = (sg.b[0] - lon) * kx, by = (sg.b[1] - lat) * ky;
      const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy, t = L2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / L2)) : 0;
      const d = Math.hypot(ax + t * dx, ay + t * dy); if (d < bd) { bd = d; best = sg; }
    }
    return best;
  }
  // Re-class every road (non-foot) stretch from the Alberta data where a provincial road lies under it.
  function applyAB(runs, ab) {
    if (!ab) return runs;
    const out = [];
    const push = (r, cls, a, b, src) => { const l = out[out.length - 1]; if (l && l.cls === cls && l.leg === r.leg && l.drv === r.drv && l.src === src) l.pts.push(b); else out.push({ cls, pts: [a, b], leg: r.leg, drv: r.drv, src }); };
    for (const r of runs) {
      for (let k = 1; k < r.pts.length; k++) {
        const a = r.pts[k - 1], b = r.pts[k];
        let cls = r.cls, src = r.src;
        let drv = r.drv;
        // Road stretches take Alberta's surface. The walk is checked too: where it follows an Alberta road
        // (paved, gravel or dry-weather) that road is drivable, so the drive can be extended along it.
        if (r.cls !== 'foot' || r.drv || r.leg === 1) {
          const sg = abAt(ab, (a.lat + b.lat) / 2, (a.lng + b.lng) / 2);
          if (sg) { cls = AB_CLASS[sg.ft]; src = 'ab'; if (r.leg === 1) drv = /^(paved|gravel|dryweather)$/.test(cls); }
        }
        push({ ...r, drv }, cls, a, b, src);
      }
    }
    return out;
  }
  const route = {
    drawing: false, pts: [], markers: [], path: [], runs: [], marks: [],
    add(ll) { this.pts.push(ll); this.redraw(); },
    redraw() {
      this.markers.forEach(m => map.removeLayer(m));
      this.markers = this.pts.map((p, i) => {
        const m = L.marker(p, { draggable: true, icon: L.divIcon({ className: '', html: '<div class="rt-pt"></div>', iconSize: [14, 14], iconAnchor: [7, 7] }), title: 'Point ' + (i + 1) }).addTo(map);
        m.on('dragend', () => { this.pts[i] = m.getLatLng(); this.compute(); });
        m.on('click', () => { this.pts.splice(i, 1); this.redraw(); });
        return m;
      });
      return this.compute();
    },
    async fromMe(dest) {
      if (!navigator.geolocation) return toast('Location not available');
      toast('Finding your location…');
      navigator.geolocation.getCurrentPosition(p => {
        this.pts = [L.latLng(p.coords.latitude, p.coords.longitude), dest];
        $('#rSnap').checked = true; $('#rMode').value = 'drivehike'; showTab('route'); openPanel('side');
        this.fitNext = true; this.redraw();
      }, () => toast('Could not get your location'), { enableHighAccuracy: true, timeout: 15000 });
    },
    async compute() {
      const token = (this.token = (this.token || 0) + 1);
      const mode = $('#rMode').value, live = () => token === this.token;
      if (!$('#rSnap').checked || this.pts.length < 2) return this.show(this.pts.length > 1 ? [{ cls: 'straight', pts: this.pts.slice() }] : [], [], null, '');
      $('#rStats').innerHTML = '<span class="hint">Finding a route…</span>';
      let legs, marks = [], note = '';
      try {
        if (mode === 'drivehike') ({ legs, marks, note } = await driveThenHike(this.pts));
        else legs = [{ mode: mode === 'foot' ? 'foot' : 'road', r: await osrm(mode, this.pts) }];
      } catch (e) {
        console.warn('route', e);
        if (!live()) return;
        toast(e.message && e.message.startsWith('No ') ? e.message + ' Using straight lines.' : navigator.onLine === false ? 'Auto-routing needs signal. Using straight lines.' : 'Routing service did not answer (' + (e.message || 'error') + '). Using straight lines.');
        return this.show([{ cls: 'straight', pts: this.pts.slice() }], [], null, '');
      }
      if (!live()) return;
      const dur = legs.reduce((a, l) => a + (l.r.dur || 0), 0);
      // 1. Show the routed line straight away (road vs foot from the routing profile).
      const quick = legs.map(l => ({ cls: l.mode === 'foot' ? 'foot' : 'unchecked', pts: l.r.path }));
      this.show(quick, marks, dur, note + ' <span class="hint">Checking road surfaces and parking…</span>');
      // 2. Then add surfaces, on-foot points and nearby parking from OpenStreetMap (skipped if that is slow or offline).
      const abP = abRoads(legs.flatMap(l => l.r.path)).catch(e => { console.warn('Alberta road surfaces', e); return null; });
      const extNote = d => ` The drive continues ${(d / 1000).toFixed(1)} km past where the car router stops, on a road that Alberta's road data or OpenStreetMap shows as drivable (check conditions; may need high clearance).`;
      abP.then(ab => {
        if (!ab || !live() || this.runs.some(r => r.src)) return;
        const q = applyAB(quick.map((r, k) => ({ ...r, leg: k, drv: r.cls !== 'foot' })), ab);
        const qm = marks.map(m => ({ ...m }));
        const ext = mode === 'drivehike' ? extendDrive(q, qm) : null;
        this.show(q, qm, dur, note + (ext ? extNote(ext) : '') + ' <span class="hint">Checking parking and trails…</span>');
      });
      try {
        let runs = await classifyLegs(legs);
        if (!live()) return;
        runs = applyAB(runs, await abP);
        if (!live()) return;
        if (mode === 'drivehike') {
          const ext = extendDrive(runs, marks);
          if (ext) note += extNote(ext);
        }
        marks = marks.concat(transitions(runs).filter(t => !marks.some(m => m.at.distanceTo(t.at) < 300)));
        this.show(runs, marks, dur, note);
        const more = await parkingNear(marks.map(m => m.at).concat([runs[0].pts[0], runs[runs.length - 1].pts.slice(-1)[0]]), marks);
        if (!live() || !more.length) return;
        this.show(runs, marks.concat(more), dur, note);
      } catch (e) { console.warn('route details', e); if (live()) this.show(quick, marks, dur, note); }
    },
    show(runs, marks, dur, note) {
      this.runs = runs; this.marks = marks; this.dur = dur;
      this.path = runs.flatMap((r, k) => k ? r.pts.slice(1) : r.pts);
      drawRoute(runs, marks);
      if (this.fitNext && this.path.length > 1) { this.fitNext = false; map.fitBounds(L.latLngBounds(this.path).pad(0.15)); }
      const len = pts => { let d = 0; for (let k = 1; k < pts.length; k++) d += pts[k - 1].distanceTo(pts[k]); return d; };
      const by = {}; runs.forEach(r => { by[r.cls] = (by[r.cls] || 0) + len(r.pts); });
      const km = Object.values(by).reduce((a, b) => a + b, 0) / 1000, rt = $('#rReturn').checked ? km * 2 : km;
      const hrs = d => Math.round(d / 60) >= 60 ? (d / 3600).toFixed(1) + ' h' : Math.round(d / 60) + ' min';
      const footKm = (by.foot || 0) / 1000 * ($('#rReturn').checked ? 2 : 1);
      $('#rStats').innerHTML = this.pts.length < 2 ? (this.pts.length ? '1 point. Add another.' : 'No route yet.') :
        `<b>${km.toFixed(1)} km</b> one way · <b>${rt.toFixed(1)} km</b> ${$('#rReturn').checked ? 'round trip' : 'total'}` +
        (dur ? `<br>About ${hrs(dur)} one way (routing estimate)` : '') +
        (footKm > 30 ? `<br><b>${footKm.toFixed(1)} km on foot${$('#rReturn').checked ? ' round trip' : ''}: plan an overnight.</b>` : '') +
        `<div class="rt-legend">${Object.keys(RT_STYLE).filter(c => by[c] >= 50).map(c => `<div>${rtSwatch(c)} ${RT_STYLE[c].label} <b>${(by[c] / 1000).toFixed(1)} km</b></div>`).join('')}` +
        (runs.some(r => r.src === 'ab') ? `<div class="hint">Road surface: Government of Alberta Access Road data, then OpenStreetMap where Alberta has no road.</div>` : '') +
        (marks.some(m => m.kind === 'parking' || m.kind === 'park') ? `<div><span class="rt-p">P</span> Parking (OpenStreetMap)</div>` : '') +
        (marks.some(m => m.kind === 'tofoot') ? `<div><span class="rt-foot">🥾</span> Road ends, continue on foot</div>` : '') + '</div>' +
        (note ? `<p class="hint">${note}</p>` : '');
      store.set('routeDraft', this.pts.map(p => [p.lat, p.lng]));
    },
    setDrawing(on) {
      this.drawing = on; document.body.classList.toggle('drawing', on);
      $('#rDraw').textContent = on ? 'Stop drawing' : 'Start drawing';
      $('#btnRoute').classList.toggle('on', on);
      if (on) { toast('Tap the map to add points'); if (isMobile()) closePanels(); }
    }
  };
  map.on('click', e => { if (route.drawing) route.add(e.latlng); });
  $('#rDraw').onclick = () => route.setDrawing(!route.drawing);
  $('#btnRoute').onclick = () => { showTab('route'); if (isMobile()) { if (route.drawing) { route.setDrawing(false); openPanel('side'); } else route.setDrawing(true); } else route.setDrawing(!route.drawing); };
  $('#rUndo').onclick = () => { route.pts.pop(); route.redraw(); };
  $('#rClear').onclick = () => { route.pts = []; route.redraw(); };
  $('#rSnap').onchange = () => route.compute();
  $('#rMode').onchange = () => route.compute();
  $('#rReturn').onchange = () => route.compute();
  $('#rGpx').onclick = () => {
    if (route.path.length < 2) return toast('Draw a route first');
    const name = $('#rName').value || 'Route';
    const trk = route.path.map(p => `<trkpt lat="${p.lat.toFixed(6)}" lon="${p.lng.toFixed(6)}"></trkpt>`).join('\n');
    const wpts = (route.marks || []).map(m => {
      const nm = m.kind === 'park' ? 'Park here' + (m.tags.name ? ': ' + m.tags.name : '') : m.kind === 'parking' ? 'Parking' + (m.tags.name ? ': ' + m.tags.name : '') : m.kind === 'tofoot' ? 'On foot from here' : m.kind === 'roadend' ? 'Drive ends here' : 'Back on road';
      return `<wpt lat="${m.at.lat.toFixed(6)}" lon="${m.at.lng.toFixed(6)}"><name>${esc(nm)}</name><sym>${/park/i.test(m.kind) ? 'Parking Area' : 'Trail Head'}</sym></wpt>`;
    }).join('\n');
    download(name.replace(/\W+/g, '_') + '.gpx', gpxWrap(`${wpts}\n<trk><name>${esc(name)}</name><trkseg>\n${trk}\n</trkseg></trk>`), 'application/gpx+xml');
  };
  function renderSaved() {
    const saved = store.get('routes', []);
    $('#rSaved').innerHTML = saved.length ? '<h3 style="font-size:13px">Saved routes</h3>' + saved.map((r, i) =>
      `<div class="saved-route"><span>${esc(r.name)}</span><span><button class="link" data-load="${i}">Load</button> <button class="link" data-del="${i}">Delete</button></span></div>`).join('') : '';
    $$('[data-load]').forEach(b => b.onclick = () => { const r = saved[+b.dataset.load]; route.pts = r.pts.map(p => L.latLng(p[0], p[1])); $('#rName').value = r.name; route.redraw(); map.fitBounds(L.latLngBounds(route.pts).pad(.2)); });
    $$('[data-del]').forEach(b => b.onclick = () => { saved.splice(+b.dataset.del, 1); store.set('routes', saved); renderSaved(); });
  }
  $('#rSave').onclick = () => {
    if (route.pts.length < 2) return toast('Draw a route first');
    const saved = store.get('routes', []);
    saved.push({ name: $('#rName').value || 'Route', pts: route.pts.map(p => [p.lat, p.lng]) });
    store.set('routes', saved); renderSaved(); toast('Saved on this device');
  };

  /* ---------------- Locate ---------------- */
  let meMarker = null;
  $('#btnLocate').onclick = () => {
    if (!navigator.geolocation) return toast('Location not available');
    navigator.geolocation.getCurrentPosition(p => {
      const ll = [p.coords.latitude, p.coords.longitude];
      if (meMarker) map.removeLayer(meMarker);
      meMarker = L.circleMarker(ll, { radius: 8, color: '#fff', weight: 3, fillColor: '#1e88e5', fillOpacity: 1 }).addTo(map).bindPopup(`You are here (±${Math.round(p.coords.accuracy)} m)`);
      map.setView(ll, Math.max(map.getZoom(), 12));
    }, () => toast('Could not get your location'), { enableHighAccuracy: true, timeout: 15000 });
  };

  /* ---------------- Exports ---------------- */
  function download(name, text, type) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name; document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }
  const gpxWrap = body => `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="Eastern Slopes Trout Map" xmlns="http://www.topografix.com/GPX/1/1">\n${body}\n</gpx>`;
  const exportRows = () => { const b = map.getBounds(); return ITEMS.filter(it => passing.has(it.id) && b.contains([it.c[1], it.c[0]])); };
  const label = it => `${dispName(it)} [${allSp(it).join(' ')}]`;
  $('#xGpx').onclick = () => download('eastern-slopes-waters.gpx', gpxWrap(exportRows().map(it =>
    `<wpt lat="${it.c[1]}" lon="${it.c[0]}"><name>${esc(label(it))}</name><desc>FWMIS waterbody ${it.id.slice(1)}</desc><sym>Fishing Area</sym></wpt>`).join('\n')), 'application/gpx+xml');
  $('#xKml').onclick = () => download('eastern-slopes-waters.kml', `<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Eastern Slopes waters</name>\n` +
    exportRows().map(it => `<Placemark><name>${esc(label(it))}</name><description>FWMIS waterbody ${it.id.slice(1)}</description><Point><coordinates>${it.c[0]},${it.c[1]},0</coordinates></Point></Placemark>`).join('\n') +
    '\n</Document></kml>', 'application/vnd.google-earth.kml+xml');
  $('#xJson').onclick = () => download('eastern-slopes-waters.geojson', JSON.stringify({ type: 'FeatureCollection', features: exportRows().map(it => ({ type: 'Feature', geometry: { type: 'Point', coordinates: it.c }, properties: { name: dispName(it), kind: it.k === 'l' ? 'lake' : 'stream', species: allSp(it), fwmis_id: it.id.slice(1) } })) }), 'application/geo+json');
  $('#btnTools').onclick = () => $('#tools').showModal();

  /* ---------------- Sources and references ---------------- */
  let REFS = null;
  const csvCell = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
  function refsHtml(full) {
    const R = {}; REFS.references.forEach(r => R[r.id] = r);
    const built = META ? `Water data downloaded ${META.built}. ` : '';
    return `${full ? `<h1>Eastern Slopes Trout Map: sources and references</h1><p>${built}Reference list updated ${REFS.updated}. Map: ${esc(location.href.split('#')[0])}</p>` : `<p class="hint">${built}</p>`}
      <h3>Which features come from which source</h3>
      <table class="reftable"><thead><tr><th>Feature</th><th>Source</th><th>How it is used</th></tr></thead><tbody>
      ${REFS.features.map(f => `<tr><td>${esc(f.feature)}</td><td>${f.refs.length ? f.refs.map(id => `${id} ${esc(R[id].title)}`).join('<br>') : '<i>Not from a data source</i>'}</td><td>${esc(f.how)}</td></tr>`).join('')}
      </tbody></table>
      <h3>References</h3>
      <table class="reftable"><thead><tr><th>ID</th><th>Reference</th><th>Type</th><th>Licence</th><th>Notes</th></tr></thead><tbody>
      ${REFS.references.map(r => `<tr><td>${r.id}</td><td>${esc(r.author)}. <b>${esc(r.title)}</b>. <a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a></td><td>${esc(r.type)}</td><td>${esc(r.licence)}</td><td>${esc(r.note)}</td></tr>`).join('')}
      </tbody></table>`;
  }
  async function openSources() {
    if (!REFS) { try { REFS = await (await fetch('data/references.json')).json(); } catch (e) { return toast('Could not load the reference list.'); } }
    $('#sourcesBody').innerHTML = refsHtml(false);
    $('#sources').showModal();
  }
  $('#btnSources').onclick = openSources;
  $('#sCsvR').onclick = () => download('eastern-slopes-references.csv', '\ufeff' + [['ID', 'Type', 'Author', 'Title', 'URL', 'Licence', 'Notes']].concat(REFS.references.map(r => [r.id, r.type, r.author, r.title, r.url, r.licence, r.note])).map(row => row.map(csvCell).join(',')).join('\r\n'), 'text/csv');
  $('#sCsvF').onclick = () => { const R = {}; REFS.references.forEach(r => R[r.id] = r);
    download('eastern-slopes-features-by-source.csv', '\ufeff' + [['Feature', 'Reference IDs', 'Reference titles', 'How it is used']].concat(REFS.features.map(f => [f.feature, f.refs.join('; '), f.refs.map(id => R[id].title).join('; '), f.how])).map(row => row.map(csvCell).join(',')).join('\r\n'), 'text/csv'); };
  $('#sDocx').onclick = () => download('eastern-slopes-sources-and-references.html', `<!doctype html><html><head><meta charset="utf-8"><title>Eastern Slopes Trout Map - sources and references</title><style>body{font:14px/1.45 system-ui,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#1e2a22}table{width:100%;border-collapse:collapse;font-size:13px;margin:8px 0 20px}th,td{text-align:left;vertical-align:top;padding:6px;border-bottom:1px solid #ddd}th{color:#555}a{word-break:break-all}</style></head><body>${refsHtml(true)}</body></html>`, 'text/html');
  $('#sPrint').onclick = () => window.print();

  /* ---------------- Offline ---------------- */
  $('#oData').onclick = async () => {
    if (!META) return;
    let n = 0;
    for (const k of META.chunks) { await loadChunk(k); n++; $('#oDataStatus').textContent = `Downloaded ${n} / ${META.chunks.length} areas…`; }
    $('#oDataStatus').textContent = `All ${ITEMS.length.toLocaleString()} waters saved for offline use.`;
  };
  function tileUrls() {
    const layer = bases[baseName];
    const z0 = map.getZoom(), z1 = Math.min(z0 + 3, layer.options.maxZoom || 17);
    const urls = [];
    for (let z = z0; z <= z1; z++) {
      const b = map.getPixelBounds(map.getCenter(), z), ts = 256;
      const min = b.min.divideBy(ts).floor(), max = b.max.divideBy(ts).floor();
      for (let x = min.x; x <= max.x; x++) for (let y = min.y; y <= max.y; y++) {
        const c = L.point(x, y);
        if (layer.wmsParams) {
          const nw = map.unproject(c.multiplyBy(ts), z), se = map.unproject(c.add([1, 1]).multiplyBy(ts), z);
          const p1 = L.CRS.EPSG3857.project(nw), p2 = L.CRS.EPSG3857.project(se);
          const params = Object.assign({}, layer.wmsParams, { width: ts, height: ts, srs: 'EPSG:3857', bbox: [p1.x, p2.y, p2.x, p1.y].join(',') });
          urls.push(layer._url + L.Util.getParamString(params, layer._url, true));
        } else {
          const subs = layer.options.subdomains || 'a';
          urls.push(L.Util.template(layer._url, { s: subs[Math.abs(x + y) % subs.length], x, y, z }));
        }
      }
    }
    return urls;
  }
  $('#oSave').onclick = async () => {
    if (!('caches' in window)) return ($('#oStatus').textContent = 'This browser cannot store tiles.');
    const urls = tileUrls();
    if (urls.length > 1500) return ($('#oStatus').textContent = `That's ${urls.length} tiles. Zoom in closer (limit 1500) and try again.`);
    const cache = await caches.open('tiles-v1');
    let done = 0, failed = 0, i = 0;
    const worker = async () => { while (i < urls.length) { const u = urls[i++]; try { const r = await fetch(u, { mode: 'cors' }); if (r.ok) await cache.put(u, r); else failed++; } catch (e) { failed++; } done++; $('#oStatus').textContent = `Saving ${done} / ${urls.length} tiles…`; } };
    await Promise.all([worker(), worker(), worker(), worker()]);
    $('#oStatus').textContent = `Saved ${done - failed} tiles of "${baseName}"${failed ? ` (${failed} failed)` : ''}.`;
  };
  $('#oClear').onclick = async () => { if ('caches' in window) { await caches.delete('tiles-v1'); $('#oStatus').textContent = 'Saved tiles deleted.'; } };

  /* ---------------- Boot ---------------- */
  Promise.all([fetch('data/species_names.json').then(r => r.json()).then(n => { NAMES = n; }).catch(() => {}), fetch('data/species.json').then(r => r.json()), fetch('data/water/index.json').then(r => { if (!r.ok) throw new Error('nodata'); return r.json(); })])
    .then(([, sp, idx]) => {
      SPECIES = sp; SPECIES.forEach(s => SP[s.code] = s); RARITY = SPECIES.map(s => s.code);
      META = idx.meta; ITEMS = idx.items;
      const pk = (META.parks || {});
      ITEMS.forEach(it => BYID[it.id] = it);
      const noLoc = pk.unmatched || [];
      const bw = pk.banffWatersheds || {};
      $('#parksInfo').innerHTML = (Object.keys(bw).length ? `<p class="hint"><b>Banff stream survey (2015–17)</b>, reported by watershed only: ` +
        Object.entries(bw).map(([w, spp]) => `${esc(w)}: ` + Object.entries(spp).filter(([, v]) => parseFloat(v[0]) > 0 || parseFloat(v[1]) > 0).map(([c]) => `<span class="code">${esc(c)}</span>`).join(' ')).join('; ') +
        ` · <a href="${(pk.datasets || {}).banff_streams}" target="_blank" rel="noopener">dataset</a></p>` : '') +
        (noLoc.length ? `<details><summary class="hint">Park records with no map location (${noLoc.length})</summary><ul class="stock">` +
        noLoc.map(u => `<li>${esc(u.park)}: ${esc(u.name)} <span class="code">${u.species.join(' ')}</span></li>`).join('') + '</ul></details>' : '');
      const counts = {}; ITEMS.forEach(it => Object.keys(it.y || {}).concat(Object.keys(it.st || {})).forEach(c => counts[c] = (counts[c] || 0) + 1));
      // Known species first (in our order), then any other code present in the data.
      const extra = Object.keys(counts).filter(c => !SP[c]).sort();
      const groups = [...new Set(SPECIES.map(s => s.group))];
      $('#speciesList').innerHTML = groups.map(g => `<div class="sp-group"><h3>${esc(g)}</h3>` + SPECIES.filter(s => s.group === g && counts[s.code]).map(s =>
        `<label class="sp"><input type="checkbox" value="${s.code}"><span class="dot" style="background:${s.color}"></span><span class="code">${s.code}</span><span class="n">${esc(s.name)}<span class="c">${counts[s.code]}</span></span></label>`).join('') + '</div>').join('') +
        (() => {
          // Game fish per Alberta Fishery Regulations, 1998, Schedule 1 Part 1 (R25); everything else is grouped as non-game.
          const otherGame = extra.filter(c => GAME_EXTRA.has(c)), nonGame = extra.filter(c => !GAME_EXTRA.has(c));
          const row = c => `<label class="sp"><input type="checkbox" value="${c}"><span class="dot" style="background:#666"></span><span class="code">${c}</span><span class="n">${esc(spName(c) !== c ? spName(c) : '')}<span class="c">${counts[c]}</span></span></label>`;
          const fish = nonGame.filter(c => !NOT_FISH.has(c)), notFish = nonGame.filter(c => NOT_FISH.has(c));
          return (otherGame.length ? `<div class="sp-group"><h3>More game fish</h3>${otherGame.map(row).join('')}</div>` : '') +
            (nonGame.length ? `<div class="sp-group ng"><label class="sp grp-row"><input type="checkbox" class="grp" data-grp="ng"><span></span><span class="code">ALL</span><span class="n"><b>Non-game species</b><span class="c">${nonGame.length} kinds</span></span></label>` +
              `<details><summary>Show each non-game species</summary><div class="sub" data-grp="ng">${fish.map(row).join('')}` +
              (notFish.length ? `<h3>Not fish, or not identified to species</h3>${notFish.map(row).join('')}` : '') + '</div></details></div>' : '');
        })();
      $('#legend').innerHTML = SPECIES.filter(s => counts[s.code]).map(s => `<div class="row"><span class="dot" style="background:${s.color}"></span><span class="code">${s.code}</span> ${esc(s.name)}</div>`).join('') +
        `<div class="row"><span class="dot" style="background:${NO_REC}"></span> No fish records</div>`;
      $('#dataInfo').textContent = `Data downloaded ${META.built}: ${(META.total || ITEMS.length).toLocaleString()} waters.`;
      if (F.species === null || !F.species.some(c => counts[c])) F.species = SPECIES.filter(s => s.group.startsWith('Trout')).map(s => s.code).concat(['MNWH']);
      writeFilters(); readFilters();
      osmReady = true; setTimeout(loadOsm, 500);
      $('#filters').addEventListener('change', () => { readFilters(); applyFilters(); drawOsm(); loadOsm(); });
      $('#minOrder').addEventListener('input', () => { readFilters(); applyFilters(); });
      $('#speciesList').addEventListener('change', e => { if (e.target.classList.contains('grp')) $$(`#speciesList .sub[data-grp="${e.target.dataset.grp}"] input`).forEach(i => { i.checked = e.target.checked; }); }, true);
      $('#spAll').onclick = () => { $$('#speciesList input').forEach(i => i.checked = true); readFilters(); applyFilters(); };
      $('#spNone').onclick = () => { $$('#speciesList input').forEach(i => i.checked = false); readFilters(); applyFilters(); };
      $('#q').addEventListener('input', renderList);
      $('#inView').addEventListener('change', renderList);
      $$('.sites th').forEach(th => th.onclick = () => { sort.desc = sort.key === th.dataset.sort ? !sort.desc : false; sort.key = th.dataset.sort; store.set('sort2', sort); renderList(); });
      $('#siteRows').addEventListener('click', e => { const tr = e.target.closest('tr[data-id]'); if (tr) select(tr.dataset.id); });
      passing = new Set(ITEMS.filter(passes).map(it => it.id));
      const xs = ITEMS.map(i => i.c[0]), ys = ITEMS.map(i => i.c[1]);
      map.fitBounds([[Math.min(...ys), Math.min(...xs)], [Math.max(...ys), Math.max(...xs)]]);
      applyFilters();
      const draft = store.get('routeDraft', []); if (draft.length) { route.pts = draft.map(p => L.latLng(p[0], p[1])); route.redraw(); }
      renderSaved();
    }).catch(e => {
      console.error(e);
      $('#listInfo').textContent = 'The lake and stream data has not been downloaded yet. It is built from Alberta FWMIS by scripts/build_fwmis.py.';
      toast('Water data not available yet.', 6000);
    });

  if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('sw.js').catch(() => {});
})();
