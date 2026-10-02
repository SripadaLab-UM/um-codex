// Drives the UM-Codex launcher window the footage is filmed on: a demo data
// folder's `um-codex ui --no-browser`, signed in with its one-time link.
//
//   FILM_SIGN_IN=http://127.0.0.1:PORT/sign-in?token=... node footage/<script>
//
// The page is shown at 1280x720 and drawn at 1.5x, so each frame is 1920x1080
// and rects (CSS pixels) are scaled by SCALE to match.

import { mkdirSync, appendFileSync, writeFileSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { chromium } from "playwright-core";

export const HERE = path.dirname(fileURLToPath(import.meta.url));
export const VIEW = { width: 1280, height: 720 };
export const SCALE = 1.5;

export async function open({ signIn = process.env.FILM_SIGN_IN, view = VIEW, scale = SCALE } = {}) {
  if (!signIn) throw new Error("FILM_SIGN_IN (the launcher's sign-in link) is needed.");
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({ viewport: view, deviceScaleFactor: scale, colorScheme: "light" });
  const page = await context.newPage();
  await page.goto(signIn);
  await page.waitForSelector("#main");
  return { browser, context, page, base: new URL(signIn).origin };
}

/** Films the page until stop() is called, keeping real time (Chrome sends a
    frame only when something moves, so each is held until the next). */
export async function record(page, outFile, { fit = false } = {}) {
  const dir = outFile.replace(/\.mp4$/, "-frames");
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const cdp = await page.context().newCDPSession(page);
  const frames = [];
  cdp.on("Page.screencastFrame", ({ data, metadata, sessionId }) => {
    const file = path.join(dir, `${String(frames.length).padStart(5, "0")}.jpg`);
    writeFileSync(file, Buffer.from(data, "base64"));
    frames.push({ file, at: metadata.timestamp });
    cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
  });
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: fit ? 4000 : 1920, maxHeight: fit ? 4000 : 1080 });
  const began = Date.now() / 1000;
  return async function stop(tail = 0.4) {
    await page.waitForTimeout(tail * 1000);
    await cdp.send("Page.stopScreencast");
    const ended = Date.now() / 1000;
    if (!frames.length) throw new Error("No frames");
    const lines = frames.map((f, i) => {
      const next = i + 1 < frames.length ? frames[i + 1].at : ended;
      return `file '${f.file}'\nduration ${Math.max(0.001, next - (i === 0 ? began : f.at)).toFixed(4)}`;
    });
    lines.push(`file '${frames.at(-1).file}'`);
    writeFileSync(path.join(dir, "list.txt"), lines.join("\n") + "\n");
    const run = spawnSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", path.join(dir, "list.txt"),
      "-vf", fit ? "fps=30,scale=-2:1080:flags=lanczos,pad=1920:1080:(ow-iw)/2:0:white" : "fps=30,scale=1920:1080:flags=lanczos", "-c:v", "libx264", "-crf", "16", "-g", "10", "-pix_fmt", "yuv420p", outFile]);
    if (run.status) throw new Error(run.stderr.toString());
    rmSync(dir, { recursive: true, force: true });
    return { began, ended, seconds: ended - began };
  };
}
