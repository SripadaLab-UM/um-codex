// Films the launcher window for 04-first-launch-windows (the flow of alpha.7 and
// later: Get started, New setup..., Choose folder..., Save and start, the card)
// in ONE continuous recording, with where each part of the page sits sampled
// throughout. The takes are cut from it afterwards (cut-windows.py). The desktop
// parts (Windows' folder dialog, UM-Codex's own copy of the Codex app) are
// screen-recorded separately by record-windows-launch.ps1.
//
//   FILM_SIGN_IN=<sign-in link of a demo `um-codex ui --no-browser`> \
//   FILM_START=<demo folder> FILM_DIR=<scratch folder> node footage/film-first-launch-windows.mjs
//
// Phases, logged with times to $FILM_DIR/events.json:
//   idle        the Get started screen, untouched
//   newsetup    "New setup..." pressed; the form shown
//   choose      "Choose folder..." pressed (the folder dialog opens on the desktop)
//   chosen      the working folder shows on the form
//   start       "Save and start" pressed
//   line        the card's line changes (each new text, with its time)
//   connected   the card's line says Connected (or Running in Terminal)
//   (waits for the file $FILM_DIR/stop-now, made once the Codex part is done)
//   stop, question, stopped   Stop pressed, the question, confirmed.

import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { open, record, SCALE } from "./app.mjs";

const DIR = process.env.FILM_DIR;
mkdirSync(path.join(DIR, "dbg"), { recursive: true });
const { browser, page } = await open();
// The dialog should open in the demo folder (whose parent holds nothing else),
// not wherever it was last used: the page's own handler is unchanged, only the
// starting place it passes on.
if (process.env.FILM_START) {
  await page.evaluate((start) => { const pick = pickFolder; pickFolder = (s) => pick(s ?? start); }, process.env.FILM_START);
}
const stop = await record(page, path.join(DIR, "launcher.mp4"));
const t0 = Date.now() / 1000;
const now = () => Date.now() / 1000 - t0;
const events = [];
const lines = [];
const log = (name) => { events.push({ name, t: +now().toFixed(2) }); console.log(name, now().toFixed(1)); };
const btn = (name) => page.getByRole("button", { name });

// Where parts of the page sit, sampled while we work (CSS px x SCALE = video px).
const targets = {
  status: () => page.locator("#status"),
  steps: () => page.locator("section", { has: page.locator("#intro-title") }).first(),
  newsetup: () => btn(/^New setup/).first(),
  folderbtn: () => btn(/^Choose folder/).first(),
  save: () => btn(/^Save and start$/),
  card: () => page.locator("article.card").first(),
  line: () => page.locator("article.card .status-line").first(),
  startbtn: () => page.locator("article.card .card-start button").first(),
  summary: () => page.locator("article.card").first().locator("p").first(),
  facts: () => page.locator("article.card details.card-facts").first(),
  dialog: () => page.locator("#confirm-dialog"),
  // The New setup form.
  folderfield: () => page.locator(".field", { has: page.locator("#label-working") }).first(),
  internet: () => page.getByText("Internet", { exact: true }).first(),
  model: () => page.locator("#setup-model"),
  openin: () => page.locator(".field", { hasText: "Open in" }).first(),
  more: () => page.locator("details", { hasText: "More options" }).first(),
  runson: () => page.locator(".field", { has: page.locator("#label-runs-on") }).first(),
  sandboxopt: () => page.locator("label", { hasText: "In the sandbox" }).first(),
  localopt: () => page.locator("label", { hasText: "On this computer" }).first(),
  askcmd: () => page.locator(".field", { hasText: "Ask before commands" }).first(),
  gets: () => page.locator("#form-summary"),
};
const rects = {};
let sampling = true;
(async () => {
  let shot = 0, lastLine = "";
  while (sampling) {
    const at = now();
    for (const [id, loc] of Object.entries(targets)) {
      const box = await loc().boundingBox({ timeout: 150 }).catch(() => null);
      if (box) (rects[id] ??= []).push({ at: +at.toFixed(2), x: box.x * SCALE, y: box.y * SCALE, width: box.width * SCALE, height: box.height * SCALE });
    }
    const text = await page.locator("article.card .status-line").first().innerText({ timeout: 150 }).catch(() => "");
    if (text && text !== lastLine) { lastLine = text; lines.push({ t: +at.toFixed(2), text }); console.log("line", at.toFixed(1), text); }
    if (shot++ % 24 === 0) await page.screenshot({ path: path.join(DIR, "dbg", `p${String(Math.round(at)).padStart(4, "0")}.png`) }).catch(() => {});
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
const save = () => writeFileSync(path.join(DIR, "events.json"), JSON.stringify({ events, lines, rects, seconds: now() }, null, 1));

await page.mouse.move(1270, 710);
log("idle");
await pause(16);
await targets.newsetup().hover();
await pause(1.2);
await targets.newsetup().click();
log("newsetup");
await pause(9);
// The form, section by section, then More options and where Codex runs.
await targets.internet().scrollIntoViewIfNeeded();
await pause(5);
log("access");
await targets.more().locator("summary").scrollIntoViewIfNeeded();
await targets.more().locator("summary").hover();
await pause(1);
await targets.more().locator("summary").click();
log("more");
await pause(5);
await targets.runson().scrollIntoViewIfNeeded();
await pause(2);
log("runson");
await targets.localopt().hover();
await pause(16);
await targets.gets().scrollIntoViewIfNeeded();
log("gets");
await pause(9);
await page.evaluate(() => window.scrollTo(0, 0));
await pause(1.5);
await targets.folderbtn().hover();
await pause(1.2);
log("choose");
await targets.folderbtn().click();
// The dialog is answered on the desktop; the form then shows the folder.
await wait(() => page.getByText(/UM-Codex demo/).count().then((n) => n > 0), 120, "the folder on the form");
log("chosen");
await pause(5);
await targets.save().hover();
await pause(1.2);
log("start");
await targets.save().click();
await wait(() => page.locator("article.card").count().then((n) => n > 0), 120, "the card");
log("card");
save();
// A first start in the Codex app may ask to add the ssh line first.
const allow = page.getByRole("button", { name: /^Add the line and start$/ });
if (await allow.count()) { log("allow-ssh"); await allow.first().click(); }
await wait(() => page.locator("article.card .status-line").first().innerText().then((t) => /Connected|Running in Terminal/.test(t)).catch(() => false), 420, "Connected");
log("connected");
save();
await wait(async () => existsSync(path.join(DIR, "stop-now")), 3600, "stop-now");
await pause(1);
log("stop");
const stopBtn = page.locator("article.card .card-start button", { hasText: /^Stop$/ }).first();
await stopBtn.hover();
await pause(1.5);
await stopBtn.click();
await pause(8); // the question is on screen
log("question");
await page.locator("#confirm-yes").click();
await wait(() => page.locator("article.card .card-start button", { hasText: /^Start$/ }).count().then((n) => n > 0), 90, "the card's Start");
await pause(1);
log("stopped");
await pause(7);
log("end");
sampling = false;
const { seconds } = await stop(0.5);
save();
console.log("done", seconds.toFixed(1), "s");
await browser.close();
