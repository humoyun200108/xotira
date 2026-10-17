// Renders README screenshots from the demo page (sample data only).
//   python -m http.server 8790 -d app      (serves the demo)
//   node tools/screenshots.cjs [http://127.0.0.1:8790]   then   python tools/to_webp.py
const { chromium } = require('playwright');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8790';
const OUT = path.join(__dirname, '..', 'docs', 'screenshots');
const STATIC = '.top,.tabs,.stickybar{position:static!important}.toasts,.selbar{display:none!important}';

async function open(browser, { lang = 'en', theme = 'dark', tab = 'smart', width = 1440, height = 900, mobile = false } = {}) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile });
  await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: theme });
  await page.goto(`${BASE}/?demo=1&lang=${lang}&theme=${theme}&tab=${tab}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1800);
  return page;
}
// page coordinates (not viewport) so tall regions work with fullPage screenshots
async function box(page, sel) {
  return page.locator(sel).first().evaluate(e => { const r = e.getBoundingClientRect(); return { x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height }; });
}
async function clipOf(page, top, bottom, pad = 0) {
  const a = await box(page, top), b = await box(page, bottom);
  return { x: 0, y: Math.max(0, a.y - pad), width: page.viewportSize().width, height: b.y + b.height - a.y + pad * 2 };
}
async function shotPanel(page, file, maxH = 1500) {
  await page.addStyleTag({ content: STATIC });
  await page.waitForTimeout(300);
  const c = await clipOf(page, '#tabs', 'section.panel.on', 8);
  c.height = Math.min(c.height, maxH);
  await page.screenshot({ path: path.join(OUT, file), clip: c, fullPage: true });
}

(async () => {
  const browser = await chromium.launch();
  for (const lang of ['en', 'uz']) {
    // hero
    let p = await open(browser, { lang });
    await p.screenshot({ path: path.join(OUT, `hero-${lang}.png`), clip: await clipOf(p, '.top', '.hero', 0) });
    // diagnosis: headline, disk strip and the first two rows of cards
    await p.addStyleTag({ content: STATIC });
    await p.waitForTimeout(300);
    const d = await clipOf(p, '#diag', '#diag', 16);
    const rows = await p.locator('#diagGrid .bcard').evaluateAll(els => els.slice(0, 6).map(e => e.getBoundingClientRect().bottom + scrollY));
    d.height = Math.max(...rows) - d.y + 16;
    await p.screenshot({ path: path.join(OUT, `diagnosis-${lang}.png`), clip: d, fullPage: true });
    await p.close();

    for (const tab of ['games', 'progress', 'smart']) {
      p = await open(browser, { lang, tab });
      await shotPanel(p, `${tab}-${lang}.png`, tab === 'smart' ? 1250 : 1500);
      await p.close();
    }

    // live cleanup modal, caught mid-way
    p = await open(browser, { lang });
    await p.emulateMedia({ reducedMotion: 'no-preference' });
    await p.evaluate(() => cleanTargets(['ae-disk', 'shader', 'chrome', 'user-temp', 'capcut']));
    await p.click('#modal .m-acts .btn.primary');
    await p.waitForTimeout(3600);
    const m = await p.locator('#modal').boundingBox();   // the modal is fixed, so viewport coordinates are right here
    await p.screenshot({ path: path.join(OUT, `cleaning-${lang}.png`), clip: { x: m.x - 40, y: m.y - 40, width: m.width + 80, height: m.height + 80 } });
    await p.close();
  }
  // light theme + phone
  let p = await open(browser, { lang: 'en', theme: 'light' });
  await p.screenshot({ path: path.join(OUT, 'hero-light-en.png'), clip: await clipOf(p, '.top', '.hero', 0) });
  await p.close();
  p = await open(browser, { lang: 'uz', width: 390, height: 844, mobile: true });
  await p.screenshot({ path: path.join(OUT, 'mobile-uz.png') });
  await p.close();
  p = await open(browser, { lang: 'en', width: 390, height: 844, mobile: true });
  await p.evaluate(() => { document.querySelector('#diag').scrollIntoView(); scrollBy(0, -60); });
  await p.waitForTimeout(400);
  await p.screenshot({ path: path.join(OUT, 'mobile-diagnosis-en.png') });
  await p.close();
  await browser.close();
  console.log('screenshots saved to', OUT);
})();
