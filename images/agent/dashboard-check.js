#!/usr/bin/env node
// Exercise real browser rendering and a server-backed interaction offline.
"use strict";
const { chromium } = require("/usr/local/lib/node_modules/@playwright/mcp/node_modules/playwright");
(async () => {
  const browser = await chromium.launch({ headless: true, channel: "chromium" });
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(process.argv[2]);
    await page.getByRole("heading", { name: "Smoke", exact: true }).waitFor();
    await page.getByRole("button", { name: "Run check", exact: true }).click();
    await page.getByText("Interaction passed", { exact: true }).waitFor();
    if (errors.length) throw new Error(errors.join("\n"));
    console.log("rendered dashboard interaction passed");
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
