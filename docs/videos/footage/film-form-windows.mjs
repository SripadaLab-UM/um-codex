// Films the New setup form of the alpha.7 launcher for 04-first-launch-windows (shots 3.1 to 3.8),
// section by section with a long hold on each, so a spotlight can name each part as it is
// spoken. The page only (headless): no desktop is touched.
//
//   FILM_SIGN_IN=<sign-in link of a demo `um-codex ui --no-browser`> FILM_DIR=<scratch folder> \
//   node footage/film-form-windows.mjs
//
// Writes $FILM_DIR/form.mp4 and $FILM_DIR/form-events.json: {events, rects}, the rects sampled
// throughout (CSS px x SCALE = video px), like film-first-launch-windows.mjs.

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { open, record, SCALE } from "./app.mjs";

const DIR = process.env.FILM_DIR;
mkdirSync(DIR, { recursive: true });
const { browser, page } = await open();
const stop = await record(page, path.join(DIR, "form.mp4"));
const t0 = Date.now() / 1000;
const now = () => Date.now() / 1000 - t0;
const events = [];
const log = (name) => { events.push({ name, t: +now().toFixed(2) }); console.log(name, now().toFixed(1)); };
const btn = (name) => page.getByRole("button", { name });
const field = (text) => page.locator("div.field, fieldset, section", { hasText: text }).last();

const targets = {
  status: () => page.locator("#status"),
  steps: () => page.locator("section", { has: page.locator("#intro-title") }).first(),
  newsetup: () => btn(/^New setup/).first(),
  folderfield: () => page.locator(".field", { has: page.locator("#label-working") }).first(),
  moreFolders: () => page.getByText("MORE FOLDERS", { exact: false }).first().locator("xpath=..").first(),
  accessbox: () => page.getByText("Internet", { exact: true }).first().locator("xpath=ancestor::*[self::fieldset or self::section][1]"),
  internet: () => page.locator("label.switch", { hasText: /^Internet/ }).first(),
  browser: () => page.locator("label.switch", { hasText: /^Browser tool/ }).first(),
  model: () => page.locator("#setup-model"),
  openin: () => page.getByText("Open in", { exact: false }).first().locator("xpath=ancestor::div[contains(@class,'field')][1]"),
  more: () => page.locator("details", { hasText: "More options" }).first(),
  askcmd: () => page.locator("label.switch", { hasText: "Ask before commands" }).first(),
  runson: () => page.locator(".field", { has: page.locator("#label-runs-on") }).first(),
  sandboxopt: () => page.locator("label", { hasText: "In the sandbox" }).first(),
  localopt: () => page.locator("label", { hasText: "On this computer" }).first(),
  localhelp: () => page.locator(".field", { has: page.locator("#label-runs-on") }).first().locator(".help").first(),
  gets: () => page.locator("#form-summary"),
  buttons: () => page.getByRole("button", { name: /^Save and start$/ }).locator("xpath=..").first(),
};
const rects = {};
let sampling = true;
(async () => {
  while (sampling) {
    const at = now();
    for (const [id, loc] of Object.entries(targets)) {
      const box = await loc().boundingBox({ timeout: 120 }).catch(() => null);
      if (box) (rects[id] ??= []).push({ at: +at.toFixed(2), x: box.x * SCALE, y: box.y * SCALE, width: box.width * SCALE, height: box.height * SCALE });
    }
    await page.waitForTimeout(250);
  }
})();
const pause = (s) => page.waitForTimeout(s * 1000);
const show = async (id, seconds, what) => {
  await targets[id]().scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => console.log("no", id));
  log(what);
  await pause(seconds);
};

await page.mouse.move(1270, 710);
log("home");
await pause(2);
await targets.newsetup().hover();
await pause(1);
await targets.newsetup().click();
log("form");
await pause(16);                       // 3.1 Folder
await show("internet", 15, "access");  // 3.2 Access
await show("model", 14, "codex");      // 3.3 model, open in
await targets.more().locator("summary").scrollIntoViewIfNeeded();
await targets.more().locator("summary").hover();
await pause(1);
await targets.more().locator("summary").click();
await show("askcmd", 14, "askcmd");    // 3.4 More options, Ask before commands
await show("runson", 18, "runson");    // 3.5 Where Codex runs, in the sandbox
await targets.localopt().hover();
log("local");
await pause(24);                       // 3.6 On this computer
log("greyed");
await pause(12);                       // 3.7 greyed out, and its line
await show("gets", 20, "gets");        // 3.8 What Codex gets, and the buttons
sampling = false;
const { seconds } = await stop(0.5);
writeFileSync(path.join(DIR, "form-events.json"), JSON.stringify({ events, rects, seconds }, null, 1));
console.log("done", seconds.toFixed(1), "s", Object.keys(rects).join(","));
await browser.close();
