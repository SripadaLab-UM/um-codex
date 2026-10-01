#!/usr/bin/env node
// Checks the browser tool the way Codex uses it: starts the MCP server over
// stdio, sends `initialize` and `tools/list`, then `browser_navigate` to a URL
// and `browser_snapshot`, and looks for some text in the page as read.
//
//   um-codex-browser-check <url> <expected text> -- <server command and args>
//
// Prints one line per step; exits 0 when the text was found, 1 otherwise.
// The image's smoke test runs it on a data: URL (no network needed); the M2b
// live check ran it on https://example.com with the internet on and off.
"use strict";

const { spawn } = require("node:child_process");

const split = process.argv.indexOf("--");
const [url, expected] = process.argv.slice(2, split);
const command = split > 0 ? process.argv.slice(split + 1) : [];
if (!url || expected === undefined || command.length === 0) {
  console.error("usage: um-codex-browser-check <url> <expected text> -- <command> [args...]");
  process.exit(2);
}

const server = spawn(command[0], command.slice(1), { stdio: ["pipe", "pipe", "pipe"] });
let stderr = "";
server.stderr.on("data", (chunk) => (stderr += chunk));
server.on("error", (error) => fail(`couldn't start ${command[0]}: ${error.message}`));
let finishing = false;
server.on("exit", (code, signal) => {
  if (!finishing) fail(`the server exited early (${signal || `code ${code}`})`);
});

const waiting = new Map();
let buffered = "";
server.stdout.on("data", (chunk) => {
  buffered += chunk;
  let end;
  while ((end = buffered.indexOf("\n")) >= 0) {
    const line = buffered.slice(0, end).trim();
    buffered = buffered.slice(end + 1);
    if (!line) continue;
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      continue;
    }
    if (message.id !== undefined && waiting.has(message.id)) {
      waiting.get(message.id)(message);
      waiting.delete(message.id);
    }
  }
});

let nextId = 1;
function request(method, params, timeoutMs) {
  const id = nextId++;
  server.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${method}: no answer in ${timeoutMs} ms`)), timeoutMs);
    waiting.set(id, (message) => {
      clearTimeout(timer);
      if (message.error) reject(new Error(`${method}: ${JSON.stringify(message.error)}`));
      else resolve(message.result);
    });
  });
}

function textOf(result) {
  return (result.content || []).filter((part) => part.type === "text").map((part) => part.text).join("\n");
}

function fail(why) {
  console.error(`FAIL  ${why}`);
  if (stderr.trim()) console.error(stderr.trim());
  server.kill("SIGKILL");
  process.exit(1);
}

async function main() {
  const init = await request(
    "initialize",
    { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "um-codex-browser-check", version: "1" } },
    30000,
  );
  console.log(`ok    initialize: ${init.serverInfo.name} ${init.serverInfo.version}`);
  server.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
  const { tools } = await request("tools/list", {}, 30000);
  const names = tools.map((tool) => tool.name);
  if (!names.includes("browser_navigate")) fail(`no browser_navigate tool in ${names.join(", ")}`);
  console.log(`ok    tools/list: ${names.length} tools, including browser_navigate`);
  const navigated = await request("tools/call", { name: "browser_navigate", arguments: { url } }, 90000);
  if (navigated.isError) fail(`browser_navigate ${url}: error\n${textOf(navigated).slice(0, 2000)}`);
  console.log(`ok    browser_navigate ${url}`);
  // The page as the model reads it (navigate's own reply puts it in a file).
  const snapshot = await request("tools/call", { name: "browser_snapshot", arguments: {} }, 60000);
  const text = textOf(snapshot);
  if (snapshot.isError || !text.includes(expected)) {
    fail(`browser_snapshot: ${snapshot.isError ? "error" : `no ${expected}`}\n${text.slice(0, 2000)}`);
  }
  console.log(`ok    browser_snapshot: found ${expected}`);
  await request("tools/call", { name: "browser_close", arguments: {} }, 30000).catch(() => {});
  finishing = true;
  server.stdin.end();
  setTimeout(() => process.exit(0), 2000).unref();
  server.on("exit", () => process.exit(0));
}

main().catch((error) => fail(error.message));
