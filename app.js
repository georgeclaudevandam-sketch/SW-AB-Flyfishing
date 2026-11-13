/* Eastern Slopes Trout Map. Data lives in data/sites.json and data/species.json. */
(function () {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const MONTHS = ['J','F','M','A','M','J','J','A','S','O','N','D'];
  const MONTH_NAMES = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  const ACCESS = { roadside: 'Roadside / walk-in', day: 'Day hike', multiday: 'Multi-day / remote' };
  // Rarest first: decides marker colour.
  const RARITY = ['GOTR','ATRT','YSCT','ARGR','CTBW','WSCT','BLTR','LKTR','MNWH','BNTR','RNTR','BKTR'];
  const CR = ['WSCT','BLTR','ATRT'];
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const toast = (msg, ms = 2500) => { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('show'), ms); };
  const isMobile = () => matchMedia('(max-width: 820px)').matches;

  let SPECIES = [], SP = {}, SITES = [], visible = [], selectedId = null;
  const markers = {};
  const sort = store.get('sort', { key: 'name', desc: false });

  /* ---------------- Map and layers ---------------- */
  const map = L.map('map', { zoomControl: true, preferCanvas: false }).setView([51.3, -115.6], 7);
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
  const saveOverlays = () => store.set('overlays', Object.keys(overlays).filter(n => map.hasLayer(overlays[n])));
  map.on('overlayadd overlayremove', saveOverlays);
  const siteLayer = L.layerGroup().addTo(map);

  /* ---------------- Filters ---------------- */
  const defaults = { species: null, match: 'any', access: ['roadside','day','multiday'], km: 80, month: 0, region: '', permAB: true, permPC: true, onlyConfirmed: false, labels: true };
  const F = Object.assign({}, defaults, store.get('filters', {}));

  function readFilters() {
    F.species = $$('#speciesList input:checked').map(i => i.value);
    F.match = $('input[name=match]:checked').value;
    F.access = $$('input[name=access]:checked').map(i => i.value);
    F.km = +$('#km').value;
    F.month = +$('#month').value;
    F.region = $('#region').value;
    F.permAB = $('#permAB').checked; F.permPC = $('#permPC').checked;
    F.onlyConfirmed = $('#onlyConfirmed').checked;
    F.labels = $('#labels').checked;
    store.set('filters', F);
  }
  function writeFilters() {
    $$('#speciesList input').forEach(i => { i.checked = !F.species || F.species.includes(i.value); });
    $$('input[name=match]').forEach(i => { i.checked = i.value === F.match; });
    $$('input[name=access]').forEach(i => { i.checked = F.access.includes(i.value); });
    $('#km').value = F.km; $('#month').value = F.month; $('#region').value = F.region;
    $('#permAB').checked = F.permAB; $('#permPC').checked = F.permPC;
    $('#onlyConfirmed').checked = F.onlyConfirmed; $('#labels').checked = F.labels;
  }
  function passes(s) {
    const sel = F.species || [];
    if (!sel.length) return false;
    if (F.match === 'all' ? !sel.every(c => s.species.includes(c)) : !s.species.some(c => sel.includes(c))) return false;
    if (!F.access.includes(s.access)) return false;
    if (F.km < 80 && (s.rtKm || 0) > F.km) return false;
    if (F.month && !(s.openMonths.includes(F.month) && s.iceFreeMonths.includes(F.month))) return false;
    if (F.region && s.region !== F.region) return false;
    const pc = s.permit === 'Parks Canada';
    if (pc ? !F.permPC : !F.permAB) return false;
    if (F.onlyConfirmed && s.verify) return false;
    return true;
  }

  function topSpecies(s) { return RARITY.find(c => s.species.includes(c)) || s.species[0]; }

  function makeMarker(s) {
    const color = (SP[topSpecies(s)] || {}).color || '#555';
    const cls = ['site-mk', s.verify ? 'verify' : '', s.permit === 'Parks Canada' ? 'park' : ''].join(' ');
    const m = L.marker([s.lat, s.lng], {
      icon: L.divIcon({ className: '', html: `<div class="${cls}" style="background:${color}"></div>`, iconSize: [16, 16], iconAnchor: [8, 8] }),
      title: s.name, keyboard: true
    });
    m.bindTooltip(s.species.join(' '), { permanent: true, direction: 'right', offset: [8, 0], className: 'codes-lbl' });
    m.on('click', () => { if (route.drawing) { route.add(L.latLng(s.lat, s.lng)); return; } select(s.id, false); });
    return m;
  }

  function applyLabels() {
    const show = F.labels && map.getZoom() >= 8;
    visible.forEach(s => { const t = markers[s.id].getTooltip(); if (!t) return; show ? markers[s.id].openTooltip() : markers[s.id].closeTooltip(); });
  }
  map.on('zoomend', applyLabels);

  function render() {
    visible = SITES.filter(passes);
    siteLayer.clearLayers();
    visible.forEach(s => siteLayer.addLayer(markers[s.id]));
    applyLabels();
    $('#count').textContent = `${visible.length} of ${SITES.length} sites`;
    $('#kmOut').textContent = F.km >= 80 ? 'Any' : F.km + ' km';
    renderList();
  }

  /* ---------------- Site list ---------------- */
  function renderList() {
    const q = $('#q').value.trim().toLowerCase();
    let rows = visible.filter(s => !q || (s.name + ' ' + s.region + ' ' + s.species.join(' ') + ' ' + s.trailhead).toLowerCase().includes(q));
    const k = sort.key;
    rows.sort((a, b) => {
      let x, y;
      if (k === 'rtKm') { x = a.rtKm || 0; y = b.rtKm || 0; }
      else if (k === 'codes') { x = RARITY.indexOf(topSpecies(a)); y = RARITY.indexOf(topSpecies(b)); }
      else { x = a.name.toLowerCase(); y = b.name.toLowerCase(); }
      return (x < y ? -1 : x > y ? 1 : 0) * (sort.desc ? -1 : 1);
    });
    $$('.sites th').forEach(th => { th.classList.toggle('sorted', th.dataset.sort === k); th.classList.toggle('desc', th.dataset.sort === k && sort.desc); });
    $('#siteRows').innerHTML = rows.map(s => `
      <tr data-id="${s.id}" class="${s.id === selectedId ? 'sel' : ''}">
        <td>${esc(s.name)}${s.permit === 'Parks Canada' ? '<span class="badge pc">NP</span>' : ''}${s.verify ? '<span class="badge">verify</span>' : ''}
          <div class="sub">${esc(s.region)} · ${ACCESS[s.access]}</div></td>
        <td class="codes">${s.species.map(c => `<span style="color:${SP[c].color}">${c}</span>`).join(' ')}</td>
        <td>${s.rtKm ? s.rtKm : '–'}</td>
      </tr>`).join('') || '<tr><td colspan="3" class="hint">No sites match. Try selecting more species or widening the filters.</td></tr>';
  }

  /* ---------------- Details ---------------- */
  function monthsBar(s) {
    return '<div class="months">' + MONTHS.map((m, i) => {
      const o = s.openMonths.includes(i + 1), f = s.iceFreeMonths.includes(i + 1);
      return `<span class="${o && f ? 'both' : o ? 'frozen' : f ? 'open' : ''}" title="${MONTH_NAMES[i]}: ${o ? 'open season' : 'closed'}, ${f ? 'usually ice-free' : 'usually frozen'}">${m}</span>`;
    }).join('') + '</div><div class="mkey">Dark green = open and ice-free · blue = open but usually frozen · light green = ice-free but closed</div>';
  }
  function regsFor(s) {
    const out = [];
    const cr = s.species.filter(c => CR.includes(c));
    if (cr.length) out.push(`${cr.map(c => SP[c].name).join(', ')}: catch-and-release.`);
    if (s.permit === 'Parks Canada') out.push('National park: Parks Canada fishing permit required (Alberta licence not valid). Park-specific seasons and limits.');
    else out.push('Alberta sportfishing licence required. Check the waterbody table for season, bait ban and limits.');
    if (s.regs) out.push(s.regs);
    return out.map(r => `<li>${esc(r)}</li>`).join('');
  }
  function select(id, pan = true) {
    selectedId = id;
    const s = SITES.find(x => x.id === id);
    Object.values(markers).forEach(m => { const el = m.getElement(); el && el.firstChild && el.firstChild.classList.remove('sel'); });
    const el = markers[id].getElement(); el && el.firstChild && el.firstChild.classList.add('sel');
    if (pan) map.setView([s.lat, s.lng], Math.max(map.getZoom(), 11));
    const gmaps = `https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lng}`;
    $('#tab-detail').innerHTML = `<div class="detail">
      <h2>${esc(s.name)}</h2>
      <div class="sub hint">${esc(s.region)} · ${s.type}${s.permit === 'Parks Canada' ? ' <span class="badge pc">National park</span>' : ''}${s.verify ? ' <span class="badge">verify</span>' : ''}</div>
      <div style="margin:8px 0">${s.species.map(c => `<span class="chip"><span class="dot" style="background:${SP[c].color}"></span><b class="code">${c}</b> ${esc(SP[c].name)}</span>`).join('')}</div>
      <dl>
        <dt>Access</dt><dd>${ACCESS[s.access]}${s.rtKm ? ` · about ${s.rtKm} km round trip` : ''}</dd>
        <dt>Trailhead</dt><dd>${esc(s.trailhead)}</dd>
        <dt>Season</dt><dd>${esc(s.season)}${monthsBar(s)}</dd>
        <dt>Regulations</dt><dd><ul style="margin:0;padding-left:18px">${regsFor(s)}</ul></dd>
        <dt>Flies</dt><dd>${s.flies ? esc(s.flies) : '<span class="hint">Not known yet. Add yours in data/sites.json.</span>'}</dd>
        ${s.notes ? `<dt>Notes</dt><dd>${esc(s.notes)}</dd>` : ''}
        <dt>Location</dt><dd><span class="code">${s.lat.toFixed(4)}, ${s.lng.toFixed(4)}</span> (approximate)</dd>
      </dl>
      <div class="route-btns">
        <button id="dRoute" class="primary">Add to route</button>
        <a href="${gmaps}" target="_blank" rel="noopener"><button>Driving directions</button></a>
        <button id="dCopy">Copy coordinates</button>
      </div>
      <p class="hint">${s.verify ? 'This entry is less certain: confirm species and access before you go. ' : ''}Always check the current <a href="https://albertaregulations.ca/fishingregs/" target="_blank" rel="noopener">regulations</a>${s.permit === 'Parks Canada' ? ' and <a href="https://parks.canada.ca/voyage-travel/experience/peche-fishing" target="_blank" rel="noopener">Parks Canada rules</a>' : ''}.</p>
    </div>`;
    $('#dRoute').onclick = () => { route.add(L.latLng(s.lat, s.lng)); showTab('route'); toast('Added to route'); };
    $('#dCopy').onclick = () => { navigator.clipboard && navigator.clipboard.writeText(`${s.lat}, ${s.lng}`).then(() => toast('Copied')); };
    showTab('detail');
    openPanel('side');
    renderList();
  }

  /* ---------------- Panels and tabs ---------------- */
  function showTab(name) {
    $$('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    $$('.tab').forEach(t => { t.hidden = t.id !== 'tab-' + name; });
    $('#sideTitle').textContent = { list: 'Sites', detail: 'Details', route: 'Route' }[name];
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
      const hrs = rt / 3.5; // ~3.5 km/h with packs and climbing
      $('#rStats').innerHTML = this.pts.length < 2 ? (this.pts.length ? '1 point. Add another.' : 'No route yet.') :
        `<b>${km.toFixed(1)} km</b> one way · <b>${rt.toFixed(1)} km</b> ${$('#rReturn').checked ? 'round trip' : 'total'}<br>
         About ${hrs.toFixed(1)} h moving at 3.5 km/h. ${rt > 40 ? '<b>Over 40 km: plan an overnight.</b>' : ''}`;
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
  const desc = s => `${s.species.join(' ')} | ${ACCESS[s.access]}${s.rtKm ? ' ~' + s.rtKm + ' km RT' : ''} | ${s.trailhead} | Season: ${s.season}${s.flies ? ' | Flies: ' + s.flies : ''}${s.verify ? ' | VERIFY' : ''}`;
  $('#xGpx').onclick = () => download('eastern-slopes-trout-sites.gpx', gpxWrap(visible.map(s =>
    `<wpt lat="${s.lat}" lon="${s.lng}"><name>${esc(s.name)} [${s.species.join(' ')}]</name><desc>${esc(desc(s))}</desc><sym>Fishing Area</sym></wpt>`).join('\n')), 'application/gpx+xml');
  $('#xKml').onclick = () => download('eastern-slopes-trout-sites.kml', `<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Eastern Slopes Trout Map</name>\n` +
    visible.map(s => `<Placemark><name>${esc(s.name)} [${s.species.join(' ')}]</name><description>${esc(desc(s))}</description><Point><coordinates>${s.lng},${s.lat},0</coordinates></Point></Placemark>`).join('\n') +
    '\n</Document></kml>', 'application/vnd.google-earth.kml+xml');
  $('#xJson').onclick = () => download('eastern-slopes-trout-sites.geojson', JSON.stringify({ type: 'FeatureCollection', features: visible.map(s => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [s.lng, s.lat] }, properties: Object.assign({}, s) })) }, null, 1), 'application/geo+json');
  $('#btnTools').onclick = () => $('#tools').showModal();

  /* ---------------- Offline tiles ---------------- */
  function tileUrls() {
    const layer = bases[baseName];
    const z0 = map.getZoom(), z1 = Math.min(z0 + 3, layer.options.maxZoom || 17);
    const urls = [];
    for (let z = z0; z <= z1; z++) {
      const b = map.getPixelBounds(map.getCenter(), z), ts = 256;
      const min = b.min.divideBy(ts).floor(), max = b.max.divideBy(ts).floor();
      for (let x = min.x; x <= max.x; x++) for (let y = min.y; y <= max.y; y++) {
        const c = L.point(x, y); c.z = z;
        if (layer.wmsParams) {
          const nw = map.unproject(c.multiplyBy(ts), z), se = map.unproject(c.add([1, 1]).multiplyBy(ts), z);
          const p1 = L.CRS.EPSG3857.project(nw), p2 = L.CRS.EPSG3857.project(se);
          const params = Object.assign({}, layer.wmsParams, { width: ts, height: ts, srs: 'EPSG:3857', bbox: [p1.x, p2.y, p2.x, p1.y].join(',') });
          urls.push(layer._url + L.Util.getParamString(params, layer._url, true));
        } else {
          urls.push(L.Util.template(layer._url, { s: (layer.options.subdomains || 'a')[Math.abs(x + y) % (layer.options.subdomains || 'a').length], x, y, z }));
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
    $('#oStatus').textContent = `Saved ${done - failed} tiles of "${baseName}"${failed ? ` (${failed} failed)` : ''}. They will show without signal.`;
  };
  $('#oClear').onclick = async () => { if ('caches' in window) { await caches.delete('tiles-v1'); $('#oStatus').textContent = 'Saved tiles deleted.'; } };

  /* ---------------- Boot ---------------- */
  Promise.all([fetch('data/species.json').then(r => r.json()), fetch('data/sites.json').then(r => r.json())]).then(([sp, sites]) => {
    SPECIES = sp; SPECIES.forEach(s => SP[s.code] = s); SITES = sites;
    const counts = {}; SITES.forEach(s => s.species.forEach(c => counts[c] = (counts[c] || 0) + 1));
    const groups = [...new Set(SPECIES.map(s => s.group))];
    $('#speciesList').innerHTML = groups.map(g => `<div class="sp-group"><h3>${esc(g)}</h3>` + SPECIES.filter(s => s.group === g).map(s =>
      `<label class="sp" title="${esc(s.note)}"><input type="checkbox" value="${s.code}"><span class="dot" style="background:${s.color}"></span><span class="code">${s.code}</span><span class="n">${esc(s.name)}<span class="c">${counts[s.code] || 0}</span></span></label>`).join('') + '</div>').join('');
    $('#legend').innerHTML = SPECIES.map(s => `<div class="row"><span class="dot" style="background:${s.color}"></span><span class="code">${s.code}</span> ${esc(s.name)}</div>`).join('');
    [...new Set(SITES.map(s => s.region))].forEach(r => { const o = document.createElement('option'); o.value = r; o.textContent = r; $('#region').appendChild(o); });
    SITES.forEach(s => markers[s.id] = makeMarker(s));
    writeFilters(); readFilters();
    $('#filters').addEventListener('change', () => { readFilters(); render(); });
    $('#km').addEventListener('input', () => { readFilters(); render(); });
    $('#spAll').onclick = () => { $$('#speciesList input').forEach(i => i.checked = true); readFilters(); render(); };
    $('#spNone').onclick = () => { $$('#speciesList input').forEach(i => i.checked = false); readFilters(); render(); };
    $('#thisMonth').onclick = () => { $('#month').value = new Date().getMonth() + 1; readFilters(); render(); };
    $('#q').addEventListener('input', renderList);
    $$('.sites th').forEach(th => th.onclick = () => { sort.desc = sort.key === th.dataset.sort ? !sort.desc : false; sort.key = th.dataset.sort; store.set('sort', sort); renderList(); });
    $('#siteRows').addEventListener('click', e => { const tr = e.target.closest('tr[data-id]'); if (tr) select(tr.dataset.id); });
    render();
    map.fitBounds(L.latLngBounds(SITES.map(s => [s.lat, s.lng])).pad(0.05));
    const draft = store.get('routeDraft', []); if (draft.length) { route.pts = draft.map(p => L.latLng(p[0], p[1])); route.redraw(); }
    renderSaved();
  }).catch(e => { console.error(e); toast('Could not load site data.', 6000); });

  if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('sw.js').catch(() => {});
})();
