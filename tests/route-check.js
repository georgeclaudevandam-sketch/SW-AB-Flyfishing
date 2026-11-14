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
  await d.uncheck('#inView'); await d.fill('#q', 'Bear Pond'); await d.waitForTimeout(500);
  await d.click('#siteRows tr[data-id] >> nth=0'); await d.waitForTimeout(1500);
  await d.click('#dHere');
  const t0 = Date.now(); let last = '';
  for (let i = 0; i < 120; i++) {
    await d.waitForTimeout(1000);
    const st = await d.$eval('#rStats', e => e.innerText.replace(/\n/g, ' | '));
    if (st !== last) { console.log(`t+${Math.round((Date.now() - t0) / 1000)}s stats: ${st}`); last = st; }
    if (!/Finding|Checking/.test(st) && i > 3) break;
  }
  console.log('toast:', await d.$eval('#toast', e => e.innerText));
  console.log('route labels:', await d.$$eval('.rt-lbl', e => e.map(x => x.innerText.replace(/\n/g, ' / '))));
  await d.screenshot({ path: 'route-check.png' });
  console.log('--- log ---\n' + log.join('\n'));
  await b.close();
})();
