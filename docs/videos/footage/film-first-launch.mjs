// Films the launcher window for 04-first-launch (and its first screen for
// 02-installing-on-a-mac) in ONE continuous recording (alpha.7 flow: the Get
// started list, New setup…, the form, Save and start), with where each part of
// the page sits sampled throughout. The takes are cut from it afterwards
// (cut-first-launch.py). The desktop parts (the folder picker, UM-Codex's own
// Codex window) are screen-recorded separately by whoever drives them.
//
//   FILM_SIGN_IN=<sign-in link of a demo `um-codex ui --no-browser`> \
//   FILM_START=<the demo folder> FILM_DIR=<scratch folder> node footage/film-first-launch.mjs
//
// Phases, logged with times to $FILM_DIR/events.json:
//   idle       the Get started list, untouched
//   new-setup  "New setup…" pressed; form   the form opens
//   pick-click "Choose folder…" pressed (the picker opens on the desktop); picked: it closed
//   save       "Save and start" pressed; card: the card appeared; connected: its line says Connected
//   facts-open "What Codex can do here" opened
//   (waits for the file $FILM_DIR/stop-now, made once the Codex window part is done)
//   stop       Stop pressed, the question shown, confirmed; then stopped, the card's Start back.

import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { open, record, VIEW, SCALE } from "./app.mjs";

const DIR = process.env.FILM_DIR;
mkdirSync(DIR, { recursive: true });
const { browser, page } = await open();
// The picker opens inside the demo folder (whose parent holds nothing else),
// not wherever it was last used: the page's own handler is unchanged, only the
// starting place it passes on.
if (process.env.FILM_START) {
  await page.evaluate((start) => { const pick = pickFolder; pickFolder = (s) => pick(s ?? start); }, process.env.FILM_START);
}
const stop = await record(page, path.join(DIR, "launcher.mp4"));
const t0 = Date.now() / 1000;
const now = () => Date.now() / 1000 - t0;
const events = [];
const log = (name) => { events.push({ name, t: +now().toFixed(2) }); console.log(name, now().toFixed(1)); };

const steps = (n) => page.locator("section.intro ol.steps li").nth(n);
const sections = (...ns) => ({ boundingBox: async (o) => {
  const boxes = (await Promise.all(ns.map((n) => page.locator("fieldset.section").nth(n).boundingBox(o).catch(() => null)))).filter(Boolean);
  if (!boxes.length) return null;
  const x = Math.min(...boxes.map((b) => b.x)), y = Math.min(...boxes.map((b) => b.y));
  return { x, y, width: Math.max(...boxes.map((b) => b.x + b.width)) - x, height: Math.max(...boxes.map((b) => b.y + b.height)) - y };
} });
const targets = {
  getstarted: () => page.locator("section.intro"),
  step1: () => steps(0),
  step2: () => steps(1),
  step3: () => steps(2),
  newsetup: () => page.locator('section.intro button[data-key="new"]'),
  pickbtn: () => page.locator('button[data-key="pick-working"]'),
  defaults: () => sections(1, 2),
  summary: () => page.locator("#form-summary"),
  save: () => page.locator('button[data-key="save-start"]'),
  card: () => page.locator("article.card").first(),
  line: () => page.locator("article.card .status-line").first(),
  sum: () => page.locator("article.card .card-sum").first(),
  facts: () => page.locator("article.card details.card-facts").first(),
  stop: () => page.locator("article.card .card-start button").first(),
  dialog: () => page.locator("#confirm-dialog"),
  links: () => page.locator("article.card .card-foot").first(),
};
const rects = {};
let sampling = true;
(async () => {
  while (sampling) {
    const at = now();
    for (const [id, loc] of Object.entries(targets)) {
      const box = await loc().boundingBox({ timeout: 120 }).catch(() => null);
      if (!box) continue;
      // Clipped to what is on screen (a section can be taller than the window).
      const x0 = Math.max(0, box.x), y0 = Math.max(0, box.y);
      const x1 = Math.min(VIEW.width, box.x + box.width), y1 = Math.min(VIEW.height, box.y + box.height);
      if (x1 - x0 < 4 || y1 - y0 < 4) continue;
      (rects[id] ??= []).push({ at: +at.toFixed(2), x: +(x0 * SCALE).toFixed(1), y: +(y0 * SCALE).toFixed(1), width: +((x1 - x0) * SCALE).toFixed(1), height: +((y1 - y0) * SCALE).toFixed(1) });
    }
    await page.waitForTimeout(220);
  }
})();
const pause = (s) => page.waitForTimeout(s * 1000);
const wait = async (fn, seconds, what) => {
  const end = now() + seconds;
  while (now() < end) { if (await fn()) return true; await pause(0.5); }
  console.log("timed out waiting for", what);
  return false;
};
// Smooth scroll so a section's top sits near the top of the window (or the page's end).
const scrollTo = (n) => page.evaluate((n) => {
  const top = n === "end" ? document.documentElement.scrollHeight : n === 0 ? 0 : document.querySelectorAll("fieldset.section")[n - 1].getBoundingClientRect().top + scrollY - 34;
  scrollTo({ top, behavior: "smooth" });
}, n);
const save = () => writeFileSync(path.join(DIR, "events.json"), JSON.stringify({ events, rects, seconds: now() }, null, 1));

await page.mouse.move(1270, 710);
log("idle");
await pause(18);
await targets.newsetup().hover();
await pause(1);
log("new-setup");
await targets.newsetup().click();
await page.waitForSelector("form.setup");
log("form");
await pause(5);
log("scroll-summary"); await scrollTo("end"); await pause(5);
log("scroll-top"); await scrollTo(0); await pause(1.5);
await targets.pickbtn().hover();
await pause(1);
log("pick-click");
await targets.pickbtn().click();
await wait(() => page.locator(".folder-line").count().then((n) => n > 0), 900, "the folder");
log("picked");
await pause(2);
log("to-access"); await scrollTo(2); await pause(5);
log("to-codex"); await scrollTo(3); await pause(4);
log("to-end"); await scrollTo("end"); await pause(3);
await targets.save().hover();
await pause(1);
log("save");
await targets.save().click();
await wait(() => page.locator("article.card").count().then((n) => n > 0), 300, "the card");
log("card");
await wait(() => page.locator("article.card .status-line").first().innerText().then((t) => /Connected/.test(t)).catch(() => false), 300, "Connected");
log("connected");
await pause(3);
await page.locator("article.card details.card-facts summary").first().hover();
await pause(0.8);
await page.locator("article.card details.card-facts summary").first().click();
log("facts-open");
await pause(11);
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
await wait(() => page.locator("article.card .card-start button", { hasText: /^Start$/ }).count().then((n) => n > 0), 60, "the card's Start");
await pause(1);
log("stopped");
await pause(9);
log("end");
sampling = false;
const { seconds } = await stop(0.5);
save();
console.log("done", seconds.toFixed(1), "s");
await browser.close();
