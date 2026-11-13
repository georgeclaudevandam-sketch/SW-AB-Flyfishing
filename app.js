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
  const chunkLoading = {};
  const sort = store.get('sort2', { key: 'name', desc: false });
  const spName = c => (SP[c] ? SP[c].name : c);
  const spColor = c => (SP[c] ? SP[c].color : '#666');

  /* ---------------- Map and layers ---------------- */
  const map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([51.3, -115.6], 7);
  const canvas = L.canvas({ padding: 0.3, tolerance: 6 });
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
    'Hillshade': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}', { maxZoom: 16, opacity: 0.35, attribution: 'Esri' })
  };
  let baseName = store.get('base', 'Topo (OpenTopoMap)');
  if (!bases[baseName]) baseName = 'Topo (OpenTopoMap)';
  bases[baseName].addTo(map);
  store.get('overlays', []).forEach(n => overlays[n] && overlays[n].addTo(map));
  L.control.layers(bases, overlays, { position: 'topright', collapsed: true }).addTo(map);
  L.control.scale({ imperial: false }).addTo(map);
  map.on('baselayerchange', e => { baseName = e.name; store.set('base', e.name); });
  map.on('overlayadd overlayremove', () => store.set('overlays', Object.keys(overlays).filter(n => map.hasLayer(overlays[n]))));
  const waterLayer = L.layerGroup().addTo(map);
  const labelLayer = L.layerGroup().addTo(map);
  let hiLayer = null;

  /* ---------------- Filters ---------------- */
  const F = Object.assign({ species: null, match: 'any', lakes: true, streams: true, minOrder: 1, noRecord: false, onlyStocked: false, labels: true }, store.get('filters2', {}));
  function readFilters() {
    F.species = $$('#speciesList input:checked').map(i => i.value);
    F.match = $('input[name=match]:checked').value;
    F.lakes = $('#showLakes').checked; F.streams = $('#showStreams').checked;
    F.minOrder = +$('#minOrder').value;
    F.noRecord = $('#showNoRecord').checked; F.onlyStocked = $('#onlyStocked').checked;
    F.labels = $('#labels').checked;
    store.set('filters2', F);
  }
  function writeFilters() {
    $$('#speciesList input').forEach(i => { i.checked = !F.species || F.species.includes(i.value); });
    $$('input[name=match]').forEach(i => { i.checked = i.value === F.match; });
    $('#showLakes').checked = F.lakes; $('#showStreams').checked = F.streams;
    $('#minOrder').value = F.minOrder; $('#showNoRecord').checked = F.noRecord; $('#onlyStocked').checked = F.onlyStocked;
    $('#labels').checked = F.labels;
  }
  const allSp = it => it.st ? [...new Set(it.sp.concat(Object.keys(it.st)))] : it.sp;
  function passes(it) {
    if (it.k === 'l' ? !F.lakes : !F.streams) return false;
    if (it.k === 's' && (it.o || 1) < F.minOrder) return false;
    if (F.onlyStocked && !it.st) return false;
    const sp = allSp(it);
    if (!sp.length) return F.noRecord;
    const sel = F.species || [];
    if (!sel.length) return false;
    return F.match === 'all' ? sel.every(c => sp.includes(c)) : sp.some(c => sel.includes(c));
  }
  const topSpecies = it => { const sp = allSp(it); return RARITY.find(c => sp.includes(c)) || sp[0]; };
  const colorOf = it => { const t = topSpecies(it); return t ? spColor(t) : NO_REC; };

  /* ---------------- Chunk loading ---------------- */
  function chunksInView() {
    const b = map.getBounds().pad(0.1), d = META.chunkDeg;
    const keys = new Set();
    // Any item whose bbox intersects the view pulls in its chunk (rivers can be long).
    for (const it of ITEMS) {
      if (!passing.has(it.id)) continue;
      const bb = it.b;
      if (bb[2] < b.getWest() || bb[0] > b.getEast() || bb[3] < b.getSouth() || bb[1] > b.getNorth()) continue;
      keys.add(it.ch);
    }
    return [...keys].filter(k => META.chunks.includes(k));
  }
  function loadChunk(k) {
    if (chunkData[k]) return Promise.resolve();
    if (chunkLoading[k]) return chunkLoading[k];
    return (chunkLoading[k] = fetch(`data/water/c_${k}.json`).then(r => r.json()).then(arr => {
      const m = {}; arr.forEach(f => m[f.id] = f.g); chunkData[k] = m;
    }).catch(() => { delete chunkLoading[k]; }));
  }

  /* ---------------- Drawing ---------------- */
  let drawToken = 0;
  async function draw() {
    if (!META) return;
    const token = ++drawToken;
    const keys = chunksInView();
    const z = map.getZoom();
    if (keys.length > 40 && z < 9) {
      // Too far out to draw full geometry: show centroids instead.
      waterLayer.clearLayers(); labelLayer.clearLayers();
      const b = map.getBounds();
      ITEMS.forEach(it => {
        if (!passing.has(it.id) || !b.contains([it.c[1], it.c[0]])) return;
        if (it.k === 's' && (it.o || 1) < Math.max(F.minOrder, 4)) return;
        L.circleMarker([it.c[1], it.c[0]], { renderer: canvas, radius: it.k === 'l' ? 4 : 3, weight: 1, color: '#fff', fillColor: colorOf(it), fillOpacity: 1 })
          .on('click', () => select(it.id, false)).addTo(waterLayer);
      });
      $('#listInfo').textContent = 'Zoom in to see full lake and stream outlines.';
      return renderList();
    }
    await Promise.all(keys.map(loadChunk));
    if (token !== drawToken) return;
    waterLayer.clearLayers();
    const b = map.getBounds().pad(0.1);
    const lakes = [], streams = [];
    for (const it of ITEMS) {
      if (!passing.has(it.id)) continue;
      const bb = it.b;
      if (bb[2] < b.getWest() || bb[0] > b.getEast() || bb[3] < b.getSouth() || bb[1] > b.getNorth()) continue;
      const g = (chunkData[it.ch] || {})[it.id];
      if (!g) continue;
      (it.k === 'l' ? lakes : streams).push([it, g]);
    }
    const swap = g => g.map(part => part.map(c => [c[1], c[0]]));
    streams.sort((a, b2) => (a[0].o || 1) - (b2[0].o || 1));
    for (const [it, g] of lakes) {
      const col = colorOf(it);
      L.polygon(swap(g), { renderer: canvas, color: col, weight: 2, fillColor: col, fillOpacity: 0.35 }).on('click', () => select(it.id, false)).addTo(waterLayer);
    }
    for (const [it, g] of streams) {
      const o = it.o || 1;
      L.polyline(swap(g), { renderer: canvas, color: colorOf(it), weight: Math.min(1 + o * 0.8, 6), opacity: it.sp.length ? 0.95 : 0.6 }).on('click', () => select(it.id, false)).addTo(waterLayer);
    }
    drawLabels();
    renderList();
  }
  function drawLabels() {
    labelLayer.clearLayers();
    if (!F.labels || map.getZoom() < LABEL_ZOOM) return;
    const b = map.getBounds();
    let n = 0;
    const cand = ITEMS.filter(it => passing.has(it.id) && allSp(it).length && b.contains([it.c[1], it.c[0]]))
      .sort((a, c) => (c.k === 'l') - (a.k === 'l') || (c.o || 0) - (a.o || 0));
    for (const it of cand) {
      if (n++ >= MAX_LABELS) break;
      const sp = allSp(it);
      L.tooltip({ permanent: true, direction: 'right', className: 'codes-lbl', offset: [4, 0], interactive: false })
        .setLatLng([it.c[1], it.c[0]]).setContent(sp.join(' ')).addTo(labelLayer);
    }
  }
  map.on('moveend', () => { draw(); });

  function applyFilters() {
    passing = new Set(ITEMS.filter(passes).map(it => it.id));
    $('#count').textContent = `${passing.size.toLocaleString()} of ${ITEMS.length.toLocaleString()} waters`;
    $('#ordOut').textContent = F.minOrder <= 1 ? 'all' : `order ${F.minOrder}+`;
    draw();
  }

  /* ---------------- List ---------------- */
  function renderList() {
    if (!META) return;
    const q = $('#q').value.trim().toLowerCase();
    const inView = $('#inView').checked, b = map.getBounds();
    let rows = ITEMS.filter(it => passing.has(it.id) &&
      (!inView || b.contains([it.c[1], it.c[0]])) &&
      (!q || ((it.n || '') + ' ' + (it.a || '') + ' ' + allSp(it).join(' ')).toLowerCase().includes(q)));
    const total = rows.length;
    if (sort.key === 'codes') rows.sort((a, c) => (RARITY.indexOf(topSpecies(a)) + 1 || 99) - (RARITY.indexOf(topSpecies(c)) + 1 || 99));
    else rows.sort((a, c) => (a.n || '~').localeCompare(c.n || '~'));
    if (sort.desc) rows.reverse();
    rows = rows.slice(0, 300);
    $$('.sites th').forEach(th => { th.classList.toggle('sorted', th.dataset.sort === sort.key); th.classList.toggle('desc', th.dataset.sort === sort.key && sort.desc); });
    if (map.getZoom() >= 9 || !inView) $('#listInfo').textContent = `${total.toLocaleString()} waters${total > 300 ? ' (showing first 300)' : ''}`;
    $('#siteRows').innerHTML = rows.map(it => `
      <tr data-id="${it.id}" class="${it.id === selectedId ? 'sel' : ''}">
        <td>${esc(it.n || 'Unnamed ' + (it.k === 'l' ? 'lake' : 'stream'))}${it.st ? '<span class="badge pc">stocked</span>' : ''}
          <div class="sub">${it.k === 'l' ? 'Lake' : 'Stream' + (it.o ? ', order ' + it.o : '')}${it.a ? ' · ' + esc(it.a) : ''}</div></td>
        <td class="codes">${allSp(it).map(c => `<span style="color:${spColor(c)}">${c}</span>`).join(' ') || '<span class="hint">no records</span>'}</td>
      </tr>`).join('') || '<tr><td colspan="2" class="hint">Nothing matches. Select more species, widen the filters or pan the map.</td></tr>';
  }

  /* ---------------- Details ---------------- */
  async function select(id, pan = true) {
    selectedId = id;
    const it = BYID[id];
    await loadChunk(it.ch);
    if (hiLayer) map.removeLayer(hiLayer);
    const g = (chunkData[it.ch] || {})[id];
    if (g) {
      const ll = g.map(p => p.map(c => [c[1], c[0]]));
      hiLayer = (it.k === 'l' ? L.polygon(ll, { color: '#ffeb3b', weight: 5, fill: false }) : L.polyline(ll, { color: '#ffeb3b', weight: 8, opacity: 0.7 })).addTo(map);
      hiLayer.bringToBack && hiLayer.bringToBack();
      if (pan) map.fitBounds(hiLayer.getBounds(), { maxZoom: 13, padding: [30, 30] });
    } else if (pan) map.setView([it.c[1], it.c[0]], 12);
    const name = it.n || 'Unnamed ' + (it.k === 'l' ? 'lake' : 'stream');
    const stocked = it.st ? Object.entries(it.st).map(([c, yrs]) => `<li><b class="code">${c}</b> ${esc(spName(c))}${yrs.length ? `: ${yrs.length > 6 ? yrs[0] + '–' + yrs[yrs.length - 1] + ` (${yrs.length} years)` : yrs.join(', ')}` : ''}</li>`).join('') : '';
    const other = it.sp.filter(c => !SP[c]);
    $('#tab-detail').innerHTML = `<div class="detail">
      <h2>${esc(name)}</h2>
      <div class="sub hint">${it.k === 'l' ? 'Lake / pond / reservoir' : 'River / stream' + (it.o ? `, Strahler order ${it.o}` : '')}${it.a ? ' · also called ' + esc(it.a) : ''}</div>
      <h3 class="dh">Species recorded (FWMIS)</h3>
      <div>${it.sp.length ? it.sp.filter(c => SP[c]).map(c => `<span class="chip"><span class="dot" style="background:${spColor(c)}"></span><b class="code">${c}</b> ${esc(spName(c))}</span>`).join('') : '<span class="hint">No fish records in FWMIS.</span>'}</div>
      ${other.length ? `<p class="hint">Other species codes: <span class="code">${other.join(' ')}</span></p>` : ''}
      ${stocked ? `<h3 class="dh">Stocking records</h3><ul class="stock">${stocked}</ul>` : ''}
      <dl>
        <dt>Waterbody ID</dt><dd class="code">${id.slice(1)}</dd>
        ${it.h ? `<dt>Watershed</dt><dd class="code">HUC ${esc(it.h)}</dd>` : ''}
        <dt>Location</dt><dd class="code">${it.c[1].toFixed(4)}, ${it.c[0].toFixed(4)}</dd>
      </dl>
      <div class="route-btns">
        <button id="dRoute" class="primary">Add to route</button>
        <a href="https://www.google.com/maps/dir/?api=1&destination=${it.c[1]},${it.c[0]}" target="_blank" rel="noopener"><button>Directions</button></a>
        <button id="dCopy">Copy coordinates</button>
      </div>
      <p class="hint">A species is listed if FWMIS has ever recorded it anywhere in this waterbody, not necessarily at this spot or today.
      Check seasons, limits and closures in the <a href="https://albertaregulations.ca/fishingregs/" target="_blank" rel="noopener">Alberta sportfishing regulations</a>.</p>
    </div>`;
    $('#dRoute').onclick = () => { route.add(L.latLng(it.c[1], it.c[0])); showTab('route'); toast('Added to route'); };
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
  const route = {
    drawing: false, pts: [], markers: [], line: L.polyline([], { color: '#ff5722', weight: 4, opacity: .9 }).addTo(map), path: [],
    add(ll) { this.pts.push(ll); this.redraw(); },
    redraw() {
      this.markers.forEach(m => map.removeLayer(m));
      this.markers = this.pts.map((p, i) => {
        const m = L.marker(p, { draggable: true, icon: L.divIcon({ className: '', html: '<div class="rt-pt"></div>', iconSize: [14, 14], iconAnchor: [7, 7] }), title: 'Point ' + (i + 1) }).addTo(map);
        m.on('dragend', () => { this.pts[i] = m.getLatLng(); this.compute(); });
        m.on('click', () => { this.pts.splice(i, 1); this.redraw(); });
        return m;
      });
      this.compute();
    },
    async compute() {
      let path = this.pts.slice();
      if ($('#rSnap').checked && this.pts.length > 1) {
        try {
          const coords = this.pts.map(p => `${p.lng.toFixed(5)},${p.lat.toFixed(5)}`).join(';');
          const r = await fetch(`https://routing.openstreetmap.de/routed-foot/route/v1/foot/${coords}?overview=full&geometries=geojson`);
          const j = await r.json();
          if (j.routes && j.routes[0]) path = j.routes[0].geometry.coordinates.map(c => L.latLng(c[1], c[0]));
        } catch (e) { toast('Could not snap to trails (offline?). Using straight lines.'); }
      }
      this.path = path;
      this.line.setLatLngs(path);
      let d = 0; for (let i = 1; i < path.length; i++) d += path[i - 1].distanceTo(path[i]);
      const km = d / 1000, rt = $('#rReturn').checked ? km * 2 : km;
      $('#rStats').innerHTML = this.pts.length < 2 ? (this.pts.length ? '1 point. Add another.' : 'No route yet.') :
        `<b>${km.toFixed(1)} km</b> one way · <b>${rt.toFixed(1)} km</b> ${$('#rReturn').checked ? 'round trip' : 'total'}${rt > 40 ? '<br><b>Over 40 km: plan an overnight.</b>' : ''}`;
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
  $('#rReturn').onchange = () => route.compute();
  $('#rGpx').onclick = () => {
    if (route.path.length < 2) return toast('Draw a route first');
    const name = $('#rName').value || 'Route';
    const trk = route.path.map(p => `<trkpt lat="${p.lat.toFixed(6)}" lon="${p.lng.toFixed(6)}"></trkpt>`).join('\n');
    download(name.replace(/\W+/g, '_') + '.gpx', gpxWrap(`<trk><name>${esc(name)}</name><trkseg>\n${trk}\n</trkseg></trk>`), 'application/gpx+xml');
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
  const label = it => `${it.n || 'Unnamed ' + (it.k === 'l' ? 'lake' : 'stream')} [${allSp(it).join(' ')}]`;
  $('#xGpx').onclick = () => download('eastern-slopes-waters.gpx', gpxWrap(exportRows().map(it =>
    `<wpt lat="${it.c[1]}" lon="${it.c[0]}"><name>${esc(label(it))}</name><desc>FWMIS waterbody ${it.id.slice(1)}</desc><sym>Fishing Area</sym></wpt>`).join('\n')), 'application/gpx+xml');
  $('#xKml').onclick = () => download('eastern-slopes-waters.kml', `<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Eastern Slopes waters</name>\n` +
    exportRows().map(it => `<Placemark><name>${esc(label(it))}</name><description>FWMIS waterbody ${it.id.slice(1)}</description><Point><coordinates>${it.c[0]},${it.c[1]},0</coordinates></Point></Placemark>`).join('\n') +
    '\n</Document></kml>', 'application/vnd.google-earth.kml+xml');
  $('#xJson').onclick = () => download('eastern-slopes-waters.geojson', JSON.stringify({ type: 'FeatureCollection', features: exportRows().map(it => ({ type: 'Feature', geometry: { type: 'Point', coordinates: it.c }, properties: { name: it.n, kind: it.k === 'l' ? 'lake' : 'stream', species: allSp(it), fwmis_id: it.id.slice(1) } })) }), 'application/geo+json');
  $('#btnTools').onclick = () => $('#tools').showModal();

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
  Promise.all([fetch('data/species.json').then(r => r.json()), fetch('data/water/index.json').then(r => { if (!r.ok) throw new Error('nodata'); return r.json(); })])
    .then(([sp, idx]) => {
      SPECIES = sp; SPECIES.forEach(s => SP[s.code] = s); RARITY = SPECIES.map(s => s.code);
      META = idx.meta; ITEMS = idx.items; ITEMS.forEach(it => BYID[it.id] = it);
      const counts = {}; ITEMS.forEach(it => allSp(it).forEach(c => counts[c] = (counts[c] || 0) + 1));
      // Known species first (in our order), then any other code present in the data.
      const extra = Object.keys(counts).filter(c => !SP[c]).sort();
      const groups = [...new Set(SPECIES.map(s => s.group))];
      $('#speciesList').innerHTML = groups.map(g => `<div class="sp-group"><h3>${esc(g)}</h3>` + SPECIES.filter(s => s.group === g && counts[s.code]).map(s =>
        `<label class="sp"><input type="checkbox" value="${s.code}"><span class="dot" style="background:${s.color}"></span><span class="code">${s.code}</span><span class="n">${esc(s.name)}<span class="c">${counts[s.code]}</span></span></label>`).join('') + '</div>').join('') +
        (extra.length ? `<details class="sp-group"><summary>Other species codes (${extra.length})</summary>` + extra.map(c =>
          `<label class="sp"><input type="checkbox" value="${c}"><span class="dot" style="background:#666"></span><span class="code">${c}</span><span class="n"><span class="c">${counts[c]}</span></span></label>`).join('') + '</details>' : '');
      $('#legend').innerHTML = SPECIES.filter(s => counts[s.code]).map(s => `<div class="row"><span class="dot" style="background:${s.color}"></span><span class="code">${s.code}</span> ${esc(s.name)}</div>`).join('') +
        `<div class="row"><span class="dot" style="background:${NO_REC}"></span> No fish records</div>`;
      $('#dataInfo').textContent = `Data downloaded ${META.built}.`;
      if (F.species === null) F.species = SPECIES.filter(s => s.group.startsWith('Trout')).map(s => s.code).concat(['MNWH']);
      writeFilters(); readFilters();
      $('#filters').addEventListener('change', () => { readFilters(); applyFilters(); });
      $('#minOrder').addEventListener('input', () => { readFilters(); applyFilters(); });
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
