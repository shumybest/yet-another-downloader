// Run after build:extension. Install Playwright and its Chromium browser first.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';

const { chromium } = await import(process.env.M3U8_BRIDGE_PLAYWRIGHT_MODULE || 'playwright');
const content = await readFile(new URL('../apps/chrome-extension/dist/content.js', import.meta.url));
const server = createServer((request, response) => {
  if (request.url === '/content.js') {
    response.setHeader('Content-Type', 'text/javascript; charset=utf-8');
    response.end(content);
  } else {
    response.setHeader('Content-Type', 'text/html; charset=utf-8');
    response.end('<style>body{margin:0}video{display:block;width:640px;height:360px;background:#123;margin:40px 16px}</style><video id="one" src="/one.mp4"></video><video id="two" src="/two.mp4"></video>');
  }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.M3U8_BRIDGE_CHROME_PATH ? { executablePath: process.env.M3U8_BRIDGE_CHROME_PATH } : {}) });
  const page = await browser.newPage({ viewport: { width: 1000, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    window.submissions = [];
    window.chrome = { runtime: {
      onMessage: { addListener: listener => { window.captureMessage = listener; } },
      sendMessage: async message => {
        if (message.type === 'download-capture') window.submissions.push(message.captureId);
        return { ok: true, captures: [] };
      },
    } };
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.addScriptTag({ url: '/content.js' });
  const send = (id, video = 'one', update = false) => page.evaluate(({ id, video, update }) => {
    window.captureMessage({ type: update ? 'media-capture-updated' : 'media-capture', capture: {
      id, kind: 'direct', url: `${location.origin}/${video}.mp4?${id}`, contentLength: 2000000,
      mediaInfo: { width: 1920, height: 1080, renditions: Array.from({ length: 4 }, (_, i) => ({
        id: `quality-${i}`, width: 1920, height: 1080, bitrate: 3200000, videoCodec: 'x'.repeat(300),
      })) },
    } });
  }, { id, video, update });
  const panel = page.locator('#__m3u8_bridge_overlay__ .panel');
  await send('first');
  await panel.waitFor();
  const toggle = page.getByRole('button', { name: '收起媒体列表', exact: true });
  await toggle.waitFor({ timeout: 3000 });
  await toggle.click();
  await page.getByRole('button', { name: '展开媒体列表', exact: true }).waitFor();
  const compactHeight = (await panel.boundingBox()).height;
  for (let index = 0; index < 12; index++) await send(`new-${index}`);
  await send('first', 'one', true);
  await page.waitForTimeout(100);
  assert.equal(await panel.locator('.row').count(), 0);
  assert.equal((await panel.boundingBox()).height, compactHeight);
  assert.match(await panel.innerText(), /13路/);
  assert.equal(await panel.locator('.toggle').getAttribute('aria-expanded'), 'false');
  await page.screenshot({ path: process.env.M3U8_BRIDGE_OVERLAY_SCREENSHOT || '/tmp/yad-overlay-collapsed.png' });
  await page.getByRole('button', { name: '展开媒体列表', exact: true }).click();
  await panel.locator('.row').first().waitFor();
  assert.equal(await panel.locator('.row').count(), 13);
  assert.ok((await panel.boundingBox()).height <= 230, 'expanded list must not cover the whole video');
  assert.equal(await panel.evaluate(element => element.scrollWidth <= element.clientWidth), true);
  const list = panel.locator('.resources');
  assert.equal(await list.evaluate(element => element.scrollHeight > element.clientHeight), true);
  await page.screenshot({ path: '/tmp/yad-overlay-expanded.png' });
  await panel.locator('.download').first().click();
  await page.waitForFunction(() => window.submissions.length === 1);
  await page.getByRole('button', { name: '收起媒体列表', exact: true }).click();
  await send('other', 'two');
  await page.locator('#two').hover();
  await page.waitForTimeout(100);
  assert.equal(await panel.locator('.row').count(), 0, 'switching videos preserves collapse');
  assert.match(await panel.innerText(), /1路/);
  await page.setViewportSize({ width: 300, height: 600 });
  await page.locator('#one').hover({ position: { x: 10, y: 10 } });
  await page.waitForTimeout(100);
  const box = await panel.boundingBox();
  assert.ok(box.x >= 0 && box.x + box.width <= 300);
  assert.equal(await panel.locator('.row').count(), 0);
  await page.getByRole('button', { name: '关闭此视频的下载提示', exact: true }).click();
  await panel.waitFor({ state: 'detached' });
  assert.deepEqual(errors, []);
  console.log('PASS: sticky collapse, counts, metadata updates, video switching, scroll bounds, download, close and narrow viewport');
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
