// Films the Edit form of a setup (04-first-launch, shot 4.2): the whole form
// in a tall window, so its three sections (Folder, Access, Codex) are on
// screen together. The window is 1280 x 1320 px, scaled to fit 1080 tall.
//
//   FILM_SIGN_IN=<sign-in link> FILM_DIR=<scratch folder> node footage/film-edit.mjs

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { open, record } from "./app.mjs";

const DIR = process.env.FILM_DIR;
mkdirSync(DIR, { recursive: true });
const view = { width: 1280, height: 1320 };
const { browser, page } = await open({ view, scale: 1 });
await page.locator("article.card .card-foot button", { hasText: /^Edit$/ }).first().click();
await page.waitForSelector("fieldset.section");
await page.waitForTimeout(800);
const stop = await record(page, path.join(DIR, "edit.mp4"), { fit: true });
const t0 = Date.now() / 1000;
const k = 1080 / view.height, padx = (1920 - view.width * k) / 2; // CSS px -> video px
const rects = {};
for (let n = 0; n < 40; n++) {
  const at = Date.now() / 1000 - t0;
  for (let i = 0; i < 3; i++) {
    const box = await page.locator("fieldset.section").nth(i).boundingBox({ timeout: 200 }).catch(() => null);
    if (box) (rects[`sec${i + 1}`] ??= []).push({ at: +at.toFixed(2), x: padx + box.x * k, y: box.y * k, width: box.width * k, height: box.height * k });
  }
  await page.waitForTimeout(250);
}
const { seconds } = await stop(0.3);
writeFileSync(path.join(DIR, "edit-rects.json"), JSON.stringify({ rects, seconds }, null, 1));
console.log("done", seconds.toFixed(1), Object.keys(rects).join(","), JSON.stringify(rects.sec1?.[0]), JSON.stringify(rects.sec3?.[0]));
await browser.close();
