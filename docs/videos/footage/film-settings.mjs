// Films the Edit page of a setup for 05-launcher-settings: ONE continuous take
// whose clock is the narration's (it starts with the narration at 0), so each
// click lands when the narrator says it. The page is 1280 x 720 px drawn at
// 1.5x (1920 x 1080), scrolled to each section as the narration reaches it.
// Nothing is saved: the take ends with Cancel.
//
//   FILM_SIGN_IN=<sign-in link of a demo `um-codex ui --no-browser`> \
//   FILM_DIR=<scratch folder> FILM_FOLDER="$HOME/Demo/Reference notes" \
//   node footage/film-settings.mjs
//
// Writes $FILM_DIR/settings.mp4 and settings.json (where each part of the page
// sat, sampled throughout). cut-settings.py cuts the shots from them.

import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { open, record, VIEW, SCALE } from "./app.mjs";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const DIR = process.env.FILM_DIR;
mkdirSync(DIR, { recursive: true });
const NAME = "05-launcher-settings";
const build = path.resolve(HERE, "../build", NAME);

// ---- when each phrase is spoken (global narration seconds) ----
const timing = JSON.parse(readFileSync(path.join(build, "timing.json"), "utf8"));
const captions = readFileSync(path.join(build, "captions.srt"), "utf8").trim().split(/\n\s*\n/).map((block) => {
  const [, times, ...lines] = block.split("\n");
  const [a, b] = times.split(" --> ").map((s) => s.split(/[:,]/).map(Number)).map(([h, m, sec, ms]) => h * 3600 + m * 60 + sec + ms / 1000);
  return { a, b, text: lines.join(" ") };
});
function spoken(shot, phrase) {
  const { start, end } = timing.shots.find((s) => s.shot === shot);
  for (const c of captions) {
    if (c.a < start - 0.01 || c.b > end + 0.01) continue;
    const i = c.text.indexOf(phrase);
    if (i >= 0) return c.a + (i / c.text.length) * (c.b - c.a);
  }
  throw new Error(`"${phrase}" isn't spoken in shot ${shot}`);
}
const endOf = (shot) => timing.shots.find((s) => s.shot === shot).end;

const { browser, page } = await open();
// "Add a folder…" answers with a second demo folder at once (no Mac dialog:
// the picker was shown in "Your first launch"); the page's own handler is unchanged.
const folder = process.env.FILM_FOLDER;
await page.evaluate(({ path: p, shown }) => {
  pickFolder = async () => ({ path: p, shown, warnings: [] });
}, { path: folder, shown: folder.replace(process.env.HOME, "~") });

const stop = await record(page, path.join(DIR, "settings.mp4"));
const t0 = Date.now() / 1000;
const now = () => Date.now() / 1000 - t0;

const sw = (key) => page.locator("label.switch", { has: page.locator(`input[data-key="${key}"]`) });
const targets = {
  editbtn: () => page.locator("article.card .card-foot button", { hasText: /^Edit$/ }).first(),
  newbtn: () => page.locator("section.block .block-head button.primary").first(),
  sections: () => page.locator("form.setup"),
  working: () => page.locator(".field", { has: page.locator("#label-working") }),
  more: () => page.locator(".field", { has: page.locator("#help-more") }),
  chip: () => page.locator(".field .chip").first(),
  internet: () => sw("internet"),
  browser: () => sw("browser"),
  asks: () => sw("browser-asks"),
  model: () => page.locator(".field.inline"),
  openin: () => page.locator(".field", { has: page.locator(".radios") }),
  moreopts: () => page.locator("details.more-options"),
  ask: () => sw("ask"),
  where: () => page.locator(".field", { has: page.locator("#label-runs-on") }),
  name: () => page.locator(".field", { has: page.locator("#setup-name") }),
  summary: () => page.locator("#form-summary"),
  save: () => page.locator('button[data-key="save-start"]'),
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
    await page.waitForTimeout(200);
  }
})();
// Smooth scroll so a section's top sits near the top of the window (or the page's end).
const scrollTo = (n) => page.evaluate((n) => {
  const top = n === "end" ? document.documentElement.scrollHeight : n === 0 ? 0 : document.querySelectorAll("fieldset.section")[n - 1].getBoundingClientRect().top + scrollY - 34;
  scrollTo({ top, behavior: "smooth" });
}, n);
const until = async (t) => { const w = t - now(); if (w > 0) await page.waitForTimeout(w * 1000); };
const log = (what) => console.log(now().toFixed(1).padStart(6), what);

// ---- the script of clicks, in narration time ----
await until(spoken("2.1", "It's all on one page") + 0.5);
log("Edit"); await targets.editbtn().click();
await page.waitForSelector("fieldset.section");
await until(spoken("3.1", "the working folder") - 0.6);
log("top"); await scrollTo(0);

await until(spoken("3.2", "More folders") + 0.4);
log("Add a folder"); await page.locator('button[data-key="pick-more"]').click();
await page.waitForSelector(".field .chip");
await until(spoken("3.2", "Read and write means") - 0.6);
log("Read & write"); await page.locator('button[data-key="access-0-true"]').click();
await until(endOf("3.2") - 1.2);
log("Read only again"); await page.locator('button[data-key="access-0-false"]').click();

await until(timing.shots.find((x) => x.shot === "4.1").start - 0.3);
log("to Access"); await scrollTo(2);
await until(spoken("4.1", "Off means") - 0.2);
log("Internet off"); await sw("internet").click();
await until(endOf("4.1") - 1.8);
log("Internet on"); await sw("internet").click();

await until(spoken("4.2", "Approve each browser action is on") - 2.2);
log("Browser tool on"); await sw("browser").click();
await until(spoken("4.2", "Turn the internet off") + 0.4);
log("Internet off"); await sw("internet").click();
await until(endOf("4.2") - 0.4);
log("Internet on"); await sw("internet").click();

await until(timing.shots.find((x) => x.shot === "5.1").start - 0.3);
log("to Codex"); await scrollTo(3);
await until(spoken("5.2", "Under More options") + 0.3);
log("More options"); await page.locator("details.more-options summary").click();
await until(spoken("5.2", "Turn it on") + 0.2);
log("Ask on"); await sw("ask").click();
await until(spoken("5.2", "Name is") + 0.9);
log("Ask off"); await sw("ask").click();
await until(spoken("5.2", "Where Codex runs is") - 0.6);
log("to Where Codex runs"); await page.evaluate(() => scrollBy({ top: 150, behavior: "smooth" }));

await until(timing.shots.find((x) => x.shot === "6.1").start - 0.3);
log("to the end"); await scrollTo("end");
await until(endOf("6.1") - 0.6);
log("Cancel (nothing saved)"); await page.locator('button[data-key="cancel"]').click();
await page.waitForTimeout(1500);
sampling = false;
const { seconds } = await stop(0.3);
writeFileSync(path.join(DIR, "settings.json"), JSON.stringify({ rects, seconds }, null, 1));
console.log("done", seconds.toFixed(1), "s;", Object.keys(rects).join(","));
await browser.close();
