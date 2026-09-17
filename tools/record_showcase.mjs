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
import pw from 'playwright';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const { chromium } = pw;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const W = 1920, H = 1080;
const DURATION_MS = 52000;                 // covers the ~46s timeline + settle
const OUT_DIR = path.join(ROOT, 'media');
const PAGE = 'file://' + path.join(ROOT, 'docs', 'showcase', 'showcase.html');
const CHROMIUM = process.env.PW_CHROMIUM ||
  (process.env.PLAYWRIGHT_BROWSERS_PATH
    ? path.join(process.env.PLAYWRIGHT_BROWSERS_PATH, 'chromium', 'chrome-linux', 'chrome')
    : undefined);

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
