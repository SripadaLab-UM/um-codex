// Films the launcher window for 04-first-launch (and its first screen for
// 02-installing-on-a-mac) in ONE continuous recording, with where each part
// of the page sits sampled throughout. The takes are cut from it afterwards
// (cut-first-launch.py). The desktop parts (the folder picker, UM-Codex's own
// Codex window) are screen-recorded separately by whoever drives them.
//
//   FILM_SIGN_IN=<sign-in link of a demo `um-codex ui --no-browser`> \
//   FILM_DIR=<scratch folder> node footage/film-first-launch.mjs
//
// Phases, logged with times to $FILM_DIR/events.json:
//   idle      the first-run screen, untouched
//   click     "Choose a folder and start…" pressed (the picker opens on the desktop)
//   card      the setup's card appeared; connected: its line says Connected
//   (waits for the file $FILM_DIR/stop-now, made once the Codex window part is done)
//   stop      Stop pressed, the question shown, confirmed; then Start; then Edit.

import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { open, record, SCALE } from "./app.mjs";

const DIR = process.env.FILM_DIR;
mkdirSync(DIR, { recursive: true });
const { browser, page } = await open();
// The picker should open inside the demo folder (whose parent holds nothing
// else), not wherever it was last used: the page's own handler is unchanged,
// only the starting place it passes on.
if (process.env.FILM_START) {
  await page.evaluate((start) => { const pick = pickFolder; pickFolder = (s) => pick(s ?? start); }, process.env.FILM_START);
}
const stop = await record(page, path.join(DIR, "launcher.mp4"));
const t0 = Date.now() / 1000;
const now = () => Date.now() / 1000 - t0;
const events = [];
const log = (name) => { events.push({ name, t: +now().toFixed(2) }); console.log(name, now().toFixed(1)); };

// Where parts of the page sit, sampled while we work (CSS px x SCALE = video px).
const targets = {
  status: () => page.locator("#status"),
  start: () => page.getByRole("button", { name: /Choose a folder and start/ }),
  help: () => page.locator("#quick-help"),
  card: () => page.locator("article.card").first(),
  line: () => page.locator("article.card .status-line").first(),
  facts: () => page.locator("article.card .facts").first(),
  stop: () => page.locator("article.card .actions button", { hasText: /^Stop$/ }).first(),
  dialog: () => page.locator("#confirm-dialog"),
  startlast: () => page.locator(".hero button.primary.big").first(),
  edit: () => page.locator("article.card .actions button", { hasText: /^Edit$/ }).first(),
  sections: () => page.locator("fieldset.section").first(),
};
const rects = {};
let sampling = true;
(async () => {
  while (sampling) {
    const at = now();
    for (const [id, loc] of Object.entries(targets)) {
      const box = await loc().boundingBox({ timeout: 150 }).catch(() => null);
      if (box) (rects[id] ??= []).push({ at: +at.toFixed(2), x: box.x * SCALE, y: box.y * SCALE, width: box.width * SCALE, height: box.height * SCALE });
    }
    await page.waitForTimeout(250);
  }
})();
const pause = (s) => page.waitForTimeout(s * 1000);
const wait = async (fn, seconds, what) => {
  const end = now() + seconds;
  while (now() < end) { if (await fn()) return true; await pause(0.5); }
  console.log("timed out waiting for", what);
  return false;
};
const save = () => writeFileSync(path.join(DIR, "events.json"), JSON.stringify({ events, rects, seconds: now() }, null, 1));

await page.mouse.move(1270, 710);
log("idle");
await pause(27);
await targets.start().hover();
await pause(1.2);
log("click");
await targets.start().click();
await wait(() => page.locator("article.card").count().then((n) => n > 0), 900, "the card");
log("card");
await wait(() => page.locator("article.card .status-line").first().innerText().then((t) => /Connected|Running in Terminal/.test(t)).catch(() => false), 300, "Connected");
log("connected");
save();
await wait(async () => existsSync(path.join(DIR, "stop-now")), 3600, "stop-now");
await pause(1);
log("stop");
await targets.stop().hover();
await pause(1.5);
await targets.stop().click();
await pause(8); // the question is on screen
log("question");
await page.locator("#confirm-yes").click();
await wait(() => page.locator("article.card .actions button", { hasText: /^Start$/ }).count().then((n) => n > 0), 60, "the card's Start");
await pause(1);
log("stopped");
await pause(7);
log("edit");
await targets.edit().hover();
await pause(1);
await targets.edit().click();
await pause(10);
log("end");
sampling = false;
const { seconds } = await stop(0.5);
save();
console.log("done", seconds.toFixed(1), "s");
await browser.close();
