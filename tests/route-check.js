// Live check of drive-then-hike routing against the real routing and OpenStreetMap servers.
// Usage: node tests/route-check.js http://localhost:8000/  (geolocation is set to downtown Calgary)
const { chromium } = require('playwright');
(async () => {
  const url = process.argv[2] || 'http://localhost:8000/';
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, geolocation: { latitude: 51.0447, longitude: -114.0719 }, permissions: ['geolocation'] });
  const d = await ctx.newPage(); const log = [];
  d.on('console', m => log.push(m.type() + ': ' + m.text()));
  d.on('pageerror', e => log.push('pageerror: ' + e.message));
  d.on('response', r => { if (/routing\.openstreetmap|overpass|geospatial\.alberta/.test(r.url())) log.push(`${r.status()} ${r.request().method()} ${r.url().slice(0, 110)}`); });
  d.on('requestfailed', r => log.push(`FAILED ${r.url().slice(0, 110)} ${r.failure() && r.failure().errorText}`));
  await d.goto(url); await d.waitForTimeout(4000);
  console.log('fish zones:', await d.$$eval('.fmz-lbl', e => e.map(x => x.textContent).join(' ')));
  console.log('game group:', await d.$$eval('#speciesList .sp-group:not(.ng) .code', e => e.map(x => x.textContent).filter(c => /ARCH|BLBK|CISC/.test(c)).join(' ')));
  await d.screenshot({ path: 'route-check-zones.png' });
  await d.uncheck('#inView');
  for (const water of (process.argv[3] || 'Bear Pond').split(',')) {
    console.log(`=== Calgary to ${water} ===`);
    await d.fill('#q', water); await d.waitForTimeout(500);
    await d.click('#siteRows tr[data-id] >> nth=0'); await d.waitForTimeout(1500);
    await d.click('#dHere');
    const t0 = Date.now(); let last = '';
    for (let i = 0; i < 120; i++) {
      await d.waitForTimeout(1000);
      const st = await d.$eval('#rStats', e => e.innerText.replace(/\n/g, ' | '));
      if (st !== last) { console.log(`t+${Math.round((Date.now() - t0) / 1000)}s stats: ${st}`); last = st; }
      if (!/Finding|Checking/.test(st) && i > 3) break;
    }
    console.log('route labels:', await d.$$eval('.rt-lbl', e => e.map(x => x.innerText.replace(/\n/g, ' / '))));
    console.log('end marker at:', await d.evaluate(() => { const m = [...document.querySelectorAll('.leaflet-marker-icon .rt-foot, .leaflet-marker-icon .rt-p')]; return m.length; }));
    console.log('drive end:', await d.evaluate(() => { const m = [...document.querySelectorAll('.rt-lbl')].find(x => /Drive ends|Park here/.test(x.innerText)); return m ? m.style.transform : ''; }));
    await d.screenshot({ path: `route-check-${water.replace(/\W+/g, '_')}.png` });
    await d.click('button[data-tab=list]');
  }
  await d.click('.max-zoom >> text=MIN'); await d.waitForTimeout(1500);
  for (let i = 0; i < 4; i++) { await d.click('.leaflet-control-zoom-in'); await d.waitForTimeout(800); }
  await d.waitForTimeout(12000);
  console.log('trail tiles:', await d.$$eval('img.leaflet-tile', e => e.filter(x => /alberta_designated/.test(x.src)).map(x => (x.complete ? 'c' : 'n') + x.naturalWidth + (x.classList.contains('leaflet-tile-loaded') ? 'L' : '')).join(',')));
  await d.screenshot({ path: 'route-check-trails.png' });
  console.log('fish zones (end):', await d.$$eval('.fmz-lbl', e => e.map(x => x.textContent).join(' ')), await d.evaluate(() => document.querySelectorAll('path.leaflet-interactive, svg path').length));
  console.log('--- log ---\n' + log.join('\n'));
  await b.close();
})();
