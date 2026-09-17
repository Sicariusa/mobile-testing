// Renders docs/showcase/showcase.html to a 1080p video using Playwright's
// bundled Chromium (deterministic, time-based CSS timeline → identical capture).
//
//   node tools/record_showcase.mjs
//
// Produces media/mobile-qa-showcase.webm (raw VP8 recording). Transcode to a
// broadly-compatible H.264 MP4 with any full ffmpeg build, e.g.:
//   ffmpeg -ss 0.5 -i media/mobile-qa-showcase.webm \
//     -c:v libx264 -profile:v high -pix_fmt yuv420p -crf 19 -preset slow \
//     -movflags +faststart -an media/mobile-qa-showcase.mp4
//
// Chromium path resolves from PLAYWRIGHT_BROWSERS_PATH; override with
// PW_CHROMIUM if your install differs.
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

// Resolve playwright whether it's a local dep or a global install.
const require = createRequire(import.meta.url);
function loadPlaywright() {
  const candidates = [
    'playwright',
    '/opt/node22/lib/node_modules/playwright/index.js',
    process.env.PLAYWRIGHT_MODULE,
  ].filter(Boolean);
  for (const c of candidates) { try { return require(c); } catch {} }
  throw new Error('playwright not found — npm i -g playwright, or set PLAYWRIGHT_MODULE');
}
const { chromium } = loadPlaywright();
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// Configurable via env so one recorder renders any format:
//   SHOW_PAGE=docs/showcase/showcase-vertical.html VID_W=1080 VID_H=1920 \
//   SHOW_MS=42000 node tools/record_showcase.mjs
const W = parseInt(process.env.VID_W || '1920', 10);
const H = parseInt(process.env.VID_H || '1080', 10);
const DURATION_MS = parseInt(process.env.SHOW_MS || '52000', 10);   // timeline + settle
const OUT_DIR = path.join(ROOT, 'media');
const PAGE = 'file://' + path.join(ROOT, process.env.SHOW_PAGE || 'docs/showcase/showcase.html');
function resolveChromium() {
  if (process.env.PW_CHROMIUM) return process.env.PW_CHROMIUM;
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH;
  if (!base) return undefined;                 // let Playwright find its own
  const direct = path.join(base, 'chromium');  // may be a symlink to the binary
  try { if (fs.statSync(direct).isFile()) return direct; } catch {}
  try {
    const dir = fs.readdirSync(base).find(d => /^chromium-\d+$/.test(d));
    if (dir) {
      const bin = path.join(base, dir, 'chrome-linux', 'chrome');
      if (fs.existsSync(bin)) return bin;
    }
  } catch {}
  return undefined;
}
const CHROMIUM = resolveChromium();

fs.mkdirSync(OUT_DIR, { recursive: true });

const browser = await chromium.launch({
  executablePath: CHROMIUM,
  args: ['--no-sandbox', '--force-color-profile=srgb', '--disable-lcd-text',
         '--hide-scrollbars', '--autoplay-policy=no-user-gesture-required'],
});
const context = await browser.newContext({
  viewport: { width: W, height: H },
  deviceScaleFactor: 1,
  recordVideo: { dir: OUT_DIR, size: { width: W, height: H } },
});
const page = await context.newPage();
await page.goto(PAGE, { waitUntil: 'load' });
await page.evaluate(() => document.fonts && document.fonts.ready);
await page.waitForTimeout(300);

console.log('recording…');
await page.waitForTimeout(DURATION_MS);

const video = page.video();
await context.close();          // flush + finalize the .webm
await browser.close();
console.log('raw recording:', await video.path());
