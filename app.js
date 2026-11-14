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
  const cap = t => t.toLowerCase().replace(/(^|[ (-])([a-z])/g, (m, p, l) => p + l.toUpperCase());
  const spName = c => (SP[c] ? SP[c].name : NAMES[c] ? cap(NAMES[c]) : c);
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
  let fade = store.get('fade', 45);
  const applyFade = () => { Object.values(bases).forEach(l => l.setOpacity(1 - fade / 100)); const o = document.getElementById('fadeOut'); if (o) o.textContent = fade + '%'; };
  applyFade();
  store.get('overlays', []).forEach(n => overlays[n] && overlays[n].addTo(map));
  L.control.layers(bases, overlays, { position: 'topright', collapsed: true }).addTo(map);
  L.control.scale({ imperial: false }).addTo(map);
  map.on('baselayerchange', e => { baseName = e.name; store.set('base', e.name); applyFade(); });
  document.getElementById('fade').value = fade;
  document.getElementById('fade').addEventListener('input', e => { fade = +e.target.value; store.set('fade', fade); applyFade(); });
  map.on('overlayadd overlayremove', () => store.set('overlays', Object.keys(overlays).filter(n => map.hasLayer(overlays[n]))));
  const waterLayer = L.layerGroup().addTo(map);
  const siteHi = L.layerGroup().addTo(map);
  const labelLayer = L.layerGroup().addTo(map);
  let hiLayer = null;

  /* ---------------- Filters ---------------- */
  const F = Object.assign({ species: null, match: 'any', lakes: true, streams: true, minOrder: 1, noRecord: false, onlyStocked: false, labels: true, since: 0, sites: true }, store.get('filters3', {}));
  function readFilters() {
    F.species = $$('#speciesList input:checked').map(i => i.value);
    F.match = $('input[name=match]:checked').value;
    F.lakes = $('#showLakes').checked; F.streams = $('#showStreams').checked;
    F.minOrder = +$('#minOrder').value;
    F.noRecord = $('#showNoRecord').checked; F.onlyStocked = $('#onlyStocked').checked;
    F.labels = $('#labels').checked; F.since = +$('#since').value; F.sites = $('#showSites').checked;
    store.set('filters3', F);
  }
  function writeFilters() {
    $$('#speciesList input').forEach(i => { i.checked = !F.species || F.species.includes(i.value); });
    $$('input[name=match]').forEach(i => { i.checked = i.value === F.match; });
    $('#showLakes').checked = F.lakes; $('#showStreams').checked = F.streams;
    $('#minOrder').value = F.minOrder; $('#showNoRecord').checked = F.noRecord; $('#onlyStocked').checked = F.onlyStocked;
    $('#labels').checked = F.labels; $('#since').value = F.since; $('#showSites').checked = F.sites;
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
        L.polygon(swap(f.g), { renderer: canvas, color: colorOfSp(selOnly(allSp(it))), weight: 3, fillColor: colorOfSp(selOnly(allSp(it))), fillOpacity: 0.5 }).on('click', () => select(it.id, false)).addTo(waterLayer);
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
        lyr.on('click', () => select(it.id, false, r)).addTo(waterLayer);
        if (selOnly(sp).length) { const m = mid(r.g); labels.push([m[1], m[0], selOnly(sp), r.o || 1]); }
      }
    }
    if (F.sites && z >= 11) drawSites(keys, items);
    drawLabels(labels);
    renderList();
  }
  function siteLayer(s, name) {
    const sp = spIn(s[2]);
    if (!sp.length) return;
    const src = s[4] && s[4].startsWith('pc:') ? `Parks Canada (${s[4].slice(3)})` : 'FWMIS survey';
    const tip = `<b>${esc(name || 'Survey site')}</b><br>${sp.map(c => `<span class="code">${c}</span> ${esc(spName(c))}${s[2][c] ? ' (' + s[2][c] + ')' : ''}`).join('<br>')}<br><span class="hint">${src}${s[5] && s[5].length ? ' · ' + esc(s[5].join(', ')) : ''} · ${s[3]} record${s[3] > 1 ? 's' : ''}</span>`;
    const hit = selMatch(sp), z = map.getZoom(), r = hit ? Math.min(9, 4 + (z - 11)) : 3;
    if (hit) {  // white halo + dark ring so the selected fish stand out on any basemap
      L.circleMarker([s[1], s[0]], { renderer: canvas, radius: r + 3, weight: 0, fillColor: '#fff', fillOpacity: 0.9, interactive: false }).addTo(siteHi);
      L.circleMarker([s[1], s[0]], { renderer: canvas, radius: r, weight: 2, color: '#111', fillColor: colorOfSp(sp), fillOpacity: 1 })
        .bindTooltip(tip, { direction: 'top' }).addTo(siteHi);
      if (F.labels && z >= 15) L.tooltip({ permanent: true, direction: 'right', className: 'codes-lbl', offset: [r + 2, 0], interactive: false })
        .setLatLng([s[1], s[0]]).setContent(sp.map(c => `<span style="color:${spColor(c)}">${c}</span>`).join(' ')).addTo(labelLayer);
    } else {
      L.circleMarker([s[1], s[0]], { renderer: canvas, radius: r, weight: 1, color: '#fff', fillColor: '#888', fillOpacity: 0.7 })
        .bindTooltip(tip, { direction: 'top' }).addTo(waterLayer);
    }
  }
  function drawSites(keys, items) {
    const b = map.getBounds();
    for (const it of items) { const f = (chunkData[it.ch] || {})[it.id]; (f && f.s || []).forEach(s => { if (b.contains([s[1], s[0]])) siteLayer(s, dispName(it)); }); }
    for (const k of keys) (chunkPts[k] || []).forEach(s => { if (b.contains([s[1], s[0]])) siteLayer(s, s[6] ? s[6] + ' (not on a mapped water)' : 'Survey site not on a mapped water'); });
  }
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
      return this.compute();
    },
    async fromMe(dest) {
      if (!navigator.geolocation) return toast('Location not available');
      toast('Finding your location…');
      navigator.geolocation.getCurrentPosition(p => {
        this.pts = [L.latLng(p.coords.latitude, p.coords.longitude), dest];
        $('#rSnap').checked = true; showTab('route'); openPanel('side');
        this.redraw().then(() => this.path.length > 1 && map.fitBounds(L.latLngBounds(this.path).pad(0.15)));
      }, () => toast('Could not get your location'), { enableHighAccuracy: true, timeout: 15000 });
    },
    async compute() {
      let path = this.pts.slice(); this.dur = null;
      if ($('#rSnap').checked && this.pts.length > 1) {
        try {
          const coords = this.pts.map(p => `${p.lng.toFixed(5)},${p.lat.toFixed(5)}`).join(';');
          const mode = $('#rMode').value;
          const r = await fetch(`https://routing.openstreetmap.de/routed-${mode}/route/v1/driving/${coords}?overview=full&geometries=geojson`);
          const j = await r.json();
          if (j.routes && j.routes[0]) { path = j.routes[0].geometry.coordinates.map(c => L.latLng(c[1], c[0])); this.dur = j.routes[0].duration; }
          else toast('No route found along roads or trails. Using straight lines.');
        } catch (e) { toast('Auto-routing needs signal. Using straight lines.'); }
      }
      this.path = path;
      this.line.setLatLngs(path);
      let d = 0; for (let i = 1; i < path.length; i++) d += path[i - 1].distanceTo(path[i]);
      const km = d / 1000, rt = $('#rReturn').checked ? km * 2 : km;
      $('#rStats').innerHTML = this.pts.length < 2 ? (this.pts.length ? '1 point. Add another.' : 'No route yet.') :
        `<b>${km.toFixed(1)} km</b> one way · <b>${rt.toFixed(1)} km</b> ${$('#rReturn').checked ? 'round trip' : 'total'}${this.dur ? `<br>About ${Math.round(this.dur / 60) >= 60 ? (this.dur / 3600).toFixed(1) + ' h' : Math.round(this.dur / 60) + ' min'} one way by ${$('#rMode').value} (routing estimate)` : ''}${rt > 40 ? '<br><b>Over 40 km: plan an overnight.</b>' : ''}`;
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
        (extra.length ? `<details class="sp-group"><summary>Other species codes (${extra.length})</summary>` + extra.map(c =>
          `<label class="sp"><input type="checkbox" value="${c}"><span class="dot" style="background:#666"></span><span class="code">${c}</span><span class="n">${esc(spName(c) !== c ? spName(c) : '')}<span class="c">${counts[c]}</span></span></label>`).join('') + '</details>' : '');
      $('#legend').innerHTML = SPECIES.filter(s => counts[s.code]).map(s => `<div class="row"><span class="dot" style="background:${s.color}"></span><span class="code">${s.code}</span> ${esc(s.name)}</div>`).join('') +
        `<div class="row"><span class="dot" style="background:${NO_REC}"></span> No fish records</div>`;
      $('#dataInfo').textContent = `Data downloaded ${META.built}: ${(META.total || ITEMS.length).toLocaleString()} waters.`;
      if (F.species === null || !F.species.some(c => counts[c])) F.species = SPECIES.filter(s => s.group.startsWith('Trout')).map(s => s.code).concat(['MNWH']);
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
