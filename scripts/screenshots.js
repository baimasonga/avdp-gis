// Capture portal pages at desktop and mobile widths for visual review.
// Usage: node scripts/screenshots.js <outdir> [baseUrl] [user] [password]
const { chromium } = require('playwright');
const out = process.argv[2] || 'screenshots';
const base = process.argv[3] || 'http://localhost';
const user = process.argv[4];
const pass = process.argv[5];
const pages = (process.env.PAGES || '/,/datasets,/maps,/upload-guide/').split(',');
(async () => {
  const browser = await chromium.launch();
  for (const [label, viewport] of [['desktop', { width: 1366, height: 900 }], ['mobile', { width: 390, height: 844 }]]) {
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    if (user) {
      await page.goto(base + '/account/login/');
      await page.fill('input[name=login]', user);
      await page.fill('input[name=password]', pass);
      await Promise.all([page.waitForNavigation(), page.click('button[type=submit], input[type=submit]')]);
    }
    for (const p of pages) {
      await page.goto(base + p, { waitUntil: 'networkidle', timeout: 60000 });
      await page.waitForTimeout(2500);
      const name = `${out}/${label}${p.replace(/[^a-z0-9]+/gi, '_')}${user ? '_auth' : ''}.png`;
      await page.screenshot({ path: name, fullPage: true });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      console.log(`${label} ${p} -> ${name}${overflow ? ' [HORIZONTAL OVERFLOW]' : ''}`);
    }
    if (errors.length) console.log(`${label} page errors:`, errors.slice(0, 5));
    await ctx.close();
  }
  await browser.close();
})();
