// The launcher window. Plain JavaScript: everything shown is built with
// textContent (never innerHTML), and every request is a same-origin JSON
// fetch (the server refuses anything else; see ui/protection.py).
//
// The first time, a short list: what's ready, and New setup… (the form, with
// the Codex app and the other defaults chosen). After that, one list of
// setups, each with its own Start. No summary page and no pop-ups on the way:
// a card says what its setup gives Codex (in full under "What Codex can do
// here"), problems and questions show on the card, and a pop-up question is
// kept only before Stop and Delete (and Windows' administrator prompt).
"use strict";

const START_WAIT_MS = 90000; // how long a card says "Starting…" before giving up
const DOCKER_WAIT_MS = 180000; // how long Start waits for Docker Desktop it opened

let state = null; // the last /api/state
let view = { name: "home" }; // "home" | "form"
let models = null;
let polling = true;
// Per setup, what this page is doing for it now (until its launch shows as running):
// { phase: "starting" | "docker" | "key" | "include" | "failed", since, text }
const cards = new Map();
let pending = null; // a Start waiting for the key or Docker: { id, extra }
const renaming = new Map(); // setup id -> the name being typed on its card (kept across redraws)
const warned = new Map(); // setup id -> the folder notes from choosing it (a network drive, ...)
const said = new Map(); // setup id -> its status line as last announced
const openFacts = new Set(); // setup ids whose "What Codex can do here" is open (kept across redraws)
const shownSteps = new Set(); // launch ids whose Codex app steps were opened by hand

// ---------------------------------------------------------------- helpers

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "key") node.dataset.key = value; // keeps focus across re-renders
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

// Replace main's content, keeping keyboard focus on the same control.
function render(...children) {
  const main = document.getElementById("main");
  const focused = document.activeElement;
  const key = focused && main.contains(focused) ? focused.dataset.key : null;
  main.replaceChildren(...children);
  if (key) main.querySelector(`[data-key="${CSS.escape(key)}"]`)?.focus();
}

function focusKey(key) {
  document.querySelector(`#main [data-key="${CSS.escape(key)}"]`)?.focus();
}

class ApiError extends Error {
  constructor(status, data) {
    super(data.error || "That didn't work.");
    this.status = status;
    this.field = data.field;
    this.errors = data.errors || (data.field ? { [data.field]: this.message } : {});
  }
}

async function api(method, path, body) {
  const options = { method, headers: { "Content-Type": "application/json" }, credentials: "same-origin" };
  if (method !== "GET") options.body = JSON.stringify(body === undefined ? {} : body);
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError(0, { error: "UM-Codex isn't answering. Open it again from its app." });
  }
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) location.reload();
  if (!response.ok) throw new ApiError(response.status, data);
  return data;
}

// One line under the status strip, for what belongs to no card (a copied
// path, a saved key, a request that failed).
// One polite announcement (a status line that changed), for screen readers.
function announce(text) {
  const box = document.getElementById("announce");
  if (box) box.textContent = text;
}

function notice(text, bad = false) {
  const box = document.getElementById("notice");
  box.textContent = text;
  box.className = bad ? "notice bad" : "notice";
  box.hidden = !text;
}

// A question before something that can't be undone: Cancel has the focus,
// so Enter or Escape leaves things as they are.
function confirmBox(title, text, yes) {
  const dialog = document.getElementById("confirm-dialog");
  document.getElementById("confirm-title").textContent = title;
  document.getElementById("confirm-text").textContent = text;
  document.getElementById("confirm-yes").textContent = yes;
  dialog.returnValue = "";
  dialog.showModal();
  document.getElementById("confirm-no").focus();
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "yes"), { once: true });
  });
}

function openerLabel(key) {
  const found = (state?.openers || []).find((o) => o.key === key);
  return found ? found.label : key;
}

// ---------------------------------------------------------------- paths

// "~/Documents/projects/thesis" -> parent "~/Documents/projects/", name "thesis".
function splitPath(shown) {
  const sep = shown.includes("\\") && !shown.includes("/") ? "\\" : "/";
  const trimmed = shown.length > 1 ? shown.replace(/[\\/]+$/, "") : shown;
  const at = trimmed.lastIndexOf(sep);
  if (at < 0) return { parent: "", name: trimmed };
  return { parent: trimmed.slice(0, at + 1), name: trimmed.slice(at + 1) || trimmed };
}

function middle(text, max) {
  if (text.length <= max) return text;
  const head = Math.ceil((max - 1) * 0.4);
  return text.slice(0, head) + "…" + text.slice(text.length - (max - 1 - head));
}

function shortHome(path) {
  const home = state?.home;
  if (!home) return path;
  return path === home || path.startsWith(home + "/") || path.startsWith(home + "\\") ? "~" + path.slice(home.length) : path;
}

async function copyPath(path, name) {
  try {
    await navigator.clipboard.writeText(path);
    notice(`Copied the full path of “${name}”.`);
  } catch {
    notice("The path couldn't be copied here.", true);
  }
}

// The folder's name in bold, its parent shortened; the whole path in the
// tooltip and a Copy button.
function pathView(folder, { copy = true, key } = {}) {
  const { parent, name } = splitPath(folder.shown);
  return el(
    "span",
    { class: "pathview", title: folder.path },
    parent ? el("span", { class: "parent", text: middle(parent, 30) }) : null,
    el("b", { class: "name", text: name }),
    copy
      ? el("button", {
          type: "button",
          class: "copy",
          key,
          "aria-label": `Copy the full path of ${name}`,
          text: "Copy",
          onclick: () => copyPath(folder.path, name),
        })
      : null,
  );
}

function chip(folder, extra) {
  return el(
    "span",
    { class: folder.write ? "chip write" : "chip" },
    pathView(folder, { copy: !extra }),
    extra || el("span", { class: "access", text: folder.write ? "READ & WRITE" : "READ ONLY" }),
  );
}

// ---------------------------------------------------------------- what a setup gives Codex

// The safety facts, short, always on the card and under the form (they used
// to be a summary page before every start). Same facts as the terminal's
// summary (setups.summary).
const WORDS = {
  writes: "Codex can change and delete files there: your real files, no undo.",
  internetOn:
    "Internet on: Codex can reach the whole internet, so it could send what it can read anywhere " +
    "(also programs on this computer and your local network or VPN).",
  internetOff: "Internet off: Codex can reach only the model.",
  browserOn: "Browser tool on: a fresh browser in the sandbox, with none of your logins",
  key: "Your Toolkit key stays on this computer; the sandbox never sees it.",
  // M4, "On this computer".
  local: "On this computer: Codex runs on your Mac, not in the sandbox. It can do anything you can do here.",
  localFull: "Codex can change and delete any of your files, not only these: no undo.",
  localFolder: "Codex's commands can change only these folders (its own sandbox). Computer and browser control aren't limited by that.",
  localControlOn: "Computer and browser control on: Computer Use and the app's own browser (macOS asks once for Screen Recording and Accessibility). Your own Chrome: not supported yet.",
  localControlOff: "Computer and browser control off.",
  localKey: "Your Toolkit key stays in the keychain, but Codex runs as you here, so it may be able to reach it.",
  localNetFull: "Internet: everything this Mac can reach (full access doesn't limit it).",
  localNetOn: "Internet for Codex's commands: on.",
  localNetOff: "Internet for Codex's commands: off (computer and browser control still use your apps' own).",
};

function onThisComputer(s) {
  return s.runs_on === "this-computer";
}

function accessLines(s) {
  if (onThisComputer(s)) {
    const net = s.local_access === "folder" ? (s.internet ? WORDS.localNetOn : WORDS.localNetOff) : WORDS.localNetFull;
    return [WORDS.local, net, s.computer_use === false ? WORDS.localControlOff : WORDS.localControlOn];
  }
  const lines = [s.internet ? WORDS.internetOn : WORDS.internetOff];
  if (s.internet && s.browser) lines.push(WORDS.browserOn + (s.browser_asks ? " (asks before each action)." : "."));
  return lines;
}

function codexLine(s) {
  const asks = s.approvals === "never" ? "runs commands without asking" : "asks before commands";
  if (onThisComputer(s)) return ["UM-Codex's local Codex window", s.model, asks].join(" · ");
  return [openerLabel(s.open_in), s.model, asks].join(" · ");
}

// The facts block: folders (working + more), access, Codex.
function facts(s, { key = "" } = {}) {
  const more = s.folders || [];
  return el(
    "div",
    { class: "facts" },
    el(
      "div",
      { class: "fact" },
      el("span", { class: "label", text: "Folder" }),
      el(
        "div",
        { class: "chips" },
        s.working ? chip({ ...s.working, write: true }, el("span", { class: "access", text: "READ & WRITE" })) : el("span", { class: "faint", text: "No folder yet" }),
        more.map((f) => chip(f)),
        s.working ? el("button", { type: "button", class: "copy", key: `copy-${key}`, text: "Copy path", onclick: () => copyPath(s.working.path, splitPath(s.working.shown).name) }) : null,
      ),
      el("p", { class: "line", text: onThisComputer(s) ? (s.local_access === "folder" ? WORDS.localFolder : WORDS.localFull) : WORDS.writes }),
    ),
    el("div", { class: "fact" }, el("span", { class: "label", text: "Access" }), accessLines(s).map((t) => el("p", { class: "line", text: t }))),
    el("div", { class: "fact" }, el("span", { class: "label", text: "Codex" }), el("p", { class: "line", text: codexLine(s) })),
  );
}

// ---------------------------------------------------------------- the status strip

function renderStatus() {
  const box = document.getElementById("status");
  box.replaceChildren();
  if (!state) return;
  const d = state.docker;
  const quiet = [];
  const loud = [];
  if (d.state === "ready") quiet.push(el("span", { class: "item" }, el("span", { class: "dot ok" }), "Docker running"));
  else {
    const item = el("div", { class: "item loud" }, el("span", { class: `dot ${d.state === "starting" ? "attn" : "bad"}` }), el("span", { text: d.words }));
    if (d.can_open) item.append(el("button", { class: "link", onclick: openDocker, text: "Open Docker Desktop" }));
    if (d.can_fix) item.append(el("button", { class: "link", onclick: fixDocker, text: "Fix it…" }));
    loud.push(item);
    if (d.fix_explained) loud.push(el("p", { class: "explain", text: d.fix_explained }));
  }
  if (state.key.saved) {
    quiet.push(
      el(
        "span",
        { class: "item" },
        el("span", { class: "dot ok" }),
        "Toolkit key saved",
        el("button", { class: "link", onclick: () => showKeyPanel(), text: "Replace" }),
      ),
    );
  } else {
    loud.push(el("div", { class: "item loud" }, el("span", { class: "dot bad" }), el("span", { text: "Add your Toolkit key to start (below)." })));
  }
  loud.push(...updateItems());
  quiet.push(
    el(
      "span",
      { class: "item faint" },
      `version ${state.version}`,
      el("button", { class: "link", key: "check-updates", onclick: checkUpdates, text: "Check for updates" }),
    ),
  );
  box.append(el("div", { class: "quiet" }, quiet), ...loud);
  // No key: its field is shown, without a Cancel.
  if (!state.key.saved) showKeyPanel({ required: true, focus: false });
}

// Updates (M7): "X is available · Update", its progress, then "Updated to X · Reopen".
let updateSaid = null; // { text, bad }: what Update or Check for updates said last

function updateItems() {
  const u = state.update;
  const item = (dot, text, ...rest) => el("div", { class: "item loud" }, el("span", { class: `dot ${dot}` }), el("span", { text }), ...rest);
  if (u.words && u.words !== said.get("update")) announce(u.words);
  said.set("update", u.words);
  if (u.phase === "running") return [item("attn", `Updating… ${u.words || ""}`)];
  if (u.phase === "updated")
    return [item("ok", `${u.words} Reopen to use it.`, el("button", { class: "link", key: "reopen", onclick: reopenNewer, text: "Reopen" }))];
  if (u.phase === "failed") return [item("bad", u.words)];
  const found = [];
  if (u.phase === "newest") found.push(item("ok", u.words));
  if (state.installed)
    found.push(
      item("attn", `UM-Codex ${state.installed} is installed; this window is still ${state.version}.`, el("button", { class: "link", key: "reopen", onclick: reopenNewer, text: "Reopen" })),
    );
  else if (u.available)
    found.push(item("attn", `UM-Codex ${u.available} is available.`, el("button", { class: "link", key: "update", onclick: startUpdate, text: "Update" })));
  if (updateSaid) found.push(el("p", { class: updateSaid.bad ? "explain message" : "explain", role: "status", text: updateSaid.text }));
  return found;
}

async function startUpdate() {
  updateSaid = null;
  try {
    await api("POST", "/api/update");
  } catch (error) {
    updateSaid = { text: error.message, bad: true };
  }
  refresh();
}

async function checkUpdates() {
  updateSaid = { text: "Checking for a newer version…" };
  renderStatus();
  try {
    updateSaid = { text: (await api("POST", "/api/update/check")).words };
  } catch (error) {
    updateSaid = { text: error.message, bad: true };
  }
  refresh();
}

async function openDocker() {
  try {
    notice((await api("POST", "/api/docker/open")).words);
  } catch (error) {
    notice(error.message, true);
  }
}

async function fixDocker() {
  const ok = await confirmBox(
    "Fix Docker's virtual machine?",
    state.docker.fix_explained + " Windows will now ask for an administrator's permission.",
    "Fix it now",
  );
  if (!ok) return;
  notice("Waiting for the administrator prompt, then restarting Docker Desktop…");
  try {
    notice((await api("POST", "/api/docker/fix")).words);
  } catch (error) {
    notice(error.message, true);
  }
  refresh();
}

async function reopenNewer() {
  try {
    await api("POST", "/api/reopen");
    polling = false;
    notice("Reopening as the installed version: a new window opens in your browser. You can close this one.");
  } catch (error) {
    notice(error.message, true);
  }
}

// ---------------------------------------------------------------- the key (inline)

function keyInput() {
  return document.getElementById("key-input");
}

function showKeyPanel({ required = false, focus = true } = {}) {
  const panel = document.getElementById("key-panel");
  const wasHidden = panel.hidden;
  panel.hidden = false;
  document.getElementById("key-cancel").hidden = required;
  if (wasHidden) document.getElementById("key-message").hidden = true;
  if (focus) keyInput().focus();
}

// Cancel, Escape or saving: the field is emptied whenever it's put away.
function hideKeyPanel() {
  keyField.value = "";
  document.getElementById("key-panel").hidden = true;
}

async function saveKey(event) {
  event.preventDefault();
  const message = document.getElementById("key-message");
  const button = document.getElementById("key-save");
  button.disabled = true;
  message.hidden = false;
  message.className = "message ok";
  message.textContent = "Checking the key with the Toolkit…";
  try {
    const result = await api("POST", "/api/key", { key: keyInput().value });
    hideKeyPanel();
    models = null;
    notice(result.words);
    await refresh();
    if (pending && cards.get(pending.id)?.phase === "key") startSetup(pending.id, pending.extra);
  } catch (error) {
    message.className = "message";
    message.textContent = error.message;
    keyInput().focus();
  } finally {
    button.disabled = false;
  }
}

// ---------------------------------------------------------------- starting

function setupOf(id) {
  return state?.setups.find((s) => s.id === id);
}

function runningOf(setupId) {
  return state.running.find((run) => run.setup_id === setupId);
}

// Start a setup now: no summary, no question. What stops it shows on its card.
async function startSetup(id, extra = {}) {
  notice("");
  cards.set(id, { phase: "starting", since: Date.now() });
  pending = null;
  redraw();
  try {
    await api("POST", `/api/setups/${encodeURIComponent(id)}/start`, extra);
    cards.set(id, { phase: "starting", since: Date.now() });
  } catch (error) {
    if (error.field === "key") {
      pending = { id, extra };
      cards.set(id, { phase: "key" });
      redraw();
      showKeyPanel({ required: !state?.key.saved });
      return;
    }
    if (error.field === "docker" && state?.docker.can_open) {
      // Docker Desktop is closed: open it, and start once it's running.
      pending = { id, extra };
      cards.set(id, { phase: "docker", since: Date.now() });
      api("POST", "/api/docker/open").catch((e) => cards.set(id, { phase: "failed", text: e.message }));
    } else if (error.field === "ssh_include") {
      cards.set(id, { phase: "include" });
    } else if (error.field === "moved") {
      cards.delete(id); // the card shows the moved folders and its own Start
    } else {
      cards.set(id, { phase: "failed", text: error.message });
    }
  }
  await refresh();
}

// What a card's one status line says now: Starting → Opening Codex → Connected.
function statusOf(s, run) {
  const mine = cards.get(s.id);
  if (run) {
    const app = run.app;
    if (app?.local) {
      if (app.copy === "failed") return { text: "UM-Codex's local Codex window couldn't be opened. Stop, then Start again.", bad: true, live: true };
      if (app.copy === "already-open")
        return { text: "Running on this computer. UM-Codex's local Codex window was already open: switch to it (another ChatGPT icon in the Dock).", live: true };
      if (!app.pid) return { text: "Opening UM-Codex's local Codex window…", live: true };
      return { text: "Running on this computer, in UM-Codex's local Codex window. Quit that window, or Stop here.", ok: true, live: true };
    }
    if (!app && onThisComputer(s)) return { text: "Opening UM-Codex's local Codex window…", live: true };
    if (!app && s.open_in === "codex-app") return { text: "Opening Codex… preparing the sandbox for the Codex app.", live: true };
    if (!app) return { text: `Running in Terminal since ${run.since}. Quit Codex there, or Stop here.`, live: true };
    if (app.fallback_message) return { text: app.fallback_message, bad: true, terminal: true };
    if (app.copy === "reopening") return { text: "Reopening the Codex window… so it knows this setup.", live: true };
    if (app.copy === "failed") return { text: "UM-Codex's Codex window couldn't be opened. Stop, then Start again.", bad: true, live: true };
    if (app.copy === "refused")
      return { text: "UM-Codex didn't open its Codex window: its folders would have been your own app's. Use Terminal.", bad: true, terminal: true };
    if (app.connected) return { text: `Connected ✓ The Codex app is working in the sandbox (${app.alias}).`, ok: true, live: true };
    if (app.copy === "already-open")
      return { text: `Opening Codex… UM-Codex's Codex window was already open: switch to it (${app.icon || "a second ChatGPT icon in the Dock"}).`, live: true };
    return { text: app.seeded || !app.first_time ? "Opening Codex… waiting for the Codex app to connect." : "Opening Codex… the first time needs a few steps (below).", live: true };
  }
  // The last launch in the Codex app fell back (Windows): why, until the next Start.
  if (!mine && s.app_fallback && s.open_in === "codex-app") return { text: s.app_fallback, bad: true, terminal: true };
  if (!mine) return null;
  if (mine.phase === "starting") return { text: "Starting…", busy: true };
  if (mine.phase === "docker") return { text: "Opening Docker Desktop… Codex starts as soon as it's running.", busy: true };
  if (mine.phase === "key") return { text: "Add your Toolkit key (above); then it starts.", bad: true };
  if (mine.phase === "failed") return { text: mine.text, bad: true };
  return null;
}

// Starts that waited too long, and Starts waiting for Docker that's ready now.
function checkPending() {
  for (const [id, mine] of cards) {
    const run = runningOf(id);
    if (run && mine.phase === "starting") cards.delete(id);
    else if (mine.phase === "starting" && Date.now() - mine.since > START_WAIT_MS) {
      const s = setupOf(id);
      cards.set(id, {
        phase: "failed",
        text:
          s?.open_in === "codex-app"
            ? "It didn't start. Why is in UM-Codex's data folder, ui/app-launch.log."
            : "It didn't start. Its terminal window says why.",
      });
    } else if (mine.phase === "docker") {
      if (state.docker.state === "ready" && pending?.id === id) startSetup(id, pending.extra);
      else if (Date.now() - mine.since > DOCKER_WAIT_MS)
        cards.set(id, { phase: "failed", text: "Docker Desktop didn't start. Open it yourself, then Start again." });
    }
  }
}

async function stopLaunch(run) {
  if (run.app?.local) {
    const yes = await confirmBox(`Stop “${run.setup_name}”?`, "UM-Codex's Codex window on this computer closes. Chats are kept.", "Stop");
    if (!yes) return;
    try {
      await api("POST", `/api/launches/${encodeURIComponent(run.launch_id)}/stop`);
    } catch (error) {
      notice(error.message, true);
    }
    return refresh();
  }
  const inApp = run.app
    ? ` The Codex app then says it can't reconnect to ${run.app.alias}; that's expected. Start the setup again to go on.`
    : "";
  const ok = await confirmBox(
    `Stop “${run.setup_name}”?`,
    "Codex stops and its sandbox is removed. Files it already changed in your folders stay as they are; " +
      "its history is kept." +
      inApp,
    "Stop",
  );
  if (!ok) return;
  try {
    await api("POST", `/api/launches/${encodeURIComponent(run.launch_id)}/stop`);
  } catch (error) {
    notice(error.message, true);
  }
  refresh();
}

// ---------------------------------------------------------------- home

function redraw() {
  if (!state) return;
  if (view.name === "home") renderHome();
}

function renderHome() {
  const parts = [];
  if (!state.setups.length) parts.push(getStarted());
  else {
    parts.push(
      el(
        "section",
        { class: "block", "aria-labelledby": "setups-title" },
        el(
          "div",
          { class: "block-head" },
          el("div", {}, el("h2", { id: "setups-title", text: "Your setups" }), el("p", { class: "help", text: "Each setup is a folder for Codex to work in. Start one to open Codex there." })),
          el("button", { class: "primary", key: "new", onclick: () => showForm(null), text: "New setup…" }),
        ),
        el("div", { class: "cards" }, state.setups.map(card)),
      ),
    );
  }
  const loose = state.running.filter((run) => !setupOf(run.setup_id));
  if (loose.length) {
    parts.push(
      el(
        "section",
        { class: "block", "aria-label": "Also running" },
        el("h2", { class: "label", text: "Also running" }),
        loose.map((run) =>
          el(
            "p",
            { class: "running-row" },
            el("span", { class: "pulse", "aria-hidden": "true" }),
            `${run.setup_name} · since ${run.since} `,
            el("button", { class: "link", key: `stop-${run.launch_id}`, onclick: () => stopLaunch(run), text: "Stop" }),
          ),
        ),
      ),
    );
  }
  render(...parts);
}

// The first time: what's ready, and the one thing to do next (a setup).
function getStarted() {
  const keyReady = state.key.saved;
  const dockerReady = state.docker.state === "ready";
  const where = state.default_open_in === "codex-app" ? "the Codex app (a separate copy set up for UM-Codex)" : "a Terminal window";
  const step = (done, title, detail, action) =>
    el(
      "li",
      { class: `step${done ? " done" : ""}` },
      el("span", { class: "tick", "aria-hidden": "true", text: done ? "✓" : "" }),
      el("div", {}, el("strong", { text: title }), detail ? el("p", { class: "help", text: detail }) : null, action || null),
    );
  return el(
    "section",
    { class: "intro", "aria-labelledby": "intro-title" },
    el("h2", { id: "intro-title", text: "Get started" }),
    el("p", { class: "lead", text: "UM-Codex runs Codex on the U-M GPT Toolkit in a sandbox: Codex sees only the folders you give it." }),
    el(
      "ol",
      { class: "steps" },
      step(keyReady, keyReady ? "Toolkit key saved" : "Add your Toolkit key", keyReady ? null : "Paste it in the box above. It stays in this computer's keychain."),
      step(dockerReady, dockerReady ? "Docker is running" : "Docker Desktop", dockerReady ? null : state.docker.words),
      step(
        false,
        "Make your first setup",
        `Choose a folder for Codex to work in, and what it may reach. Then start it: Codex opens in ${where}.`,
        el("button", { class: "primary big", key: "new", disabled: !keyReady, onclick: () => showForm(null), text: "New setup…" }),
      ),
    ),
  );
}

const INCLUDE_REASON =
  "The Codex app reaches the sandbox through your ssh settings: this adds one line at the top of " +
  "~/.ssh/config (Include ~/.ssh/um-codex/config), backed up first; uninstalling takes it out.";

function needsInclude(s) {
  return !onThisComputer(s) && s.open_in === "codex-app" && !state.ssh_include;
}

// The card's own Start: the ssh line, when it's missing, is part of it (the
// explanation is right there on the card).
function startOrAsk(s) {
  if (needsInclude(s)) {
    cards.set(s.id, { phase: "include" });
    redraw();
    focusKey(`allow-${s.id}`);
    return;
  }
  startSetup(s.id);
}

function card(s) {
  const run = runningOf(s.id);
  const status = statusOf(s, run);
  // Screen readers hear a card's line when it changes, not every redraw.
  if (status && said.get(s.id) !== status.text) announce(`${s.name}: ${status.text}`);
  said.set(s.id, status?.text);
  const last = state.setups.length > 1 && s.id === (state.last_used || state.setups[0].id);
  const title = renaming.has(s.id)
    ? renameField(s)
    : el(
        "div",
        { class: "card-title" },
        el("h3", { text: s.name }),
        last ? el("span", { class: "tag", text: "Last used" }) : null,
        onThisComputer(s) ? el("span", { class: "badge local", title: WORDS.local, text: "On this computer · experimental" }) : null,
      );
  let start;
  if (run) {
    start = el("button", { key: `stop-card-${s.id}`, onclick: () => stopLaunch(run), text: "Stop" });
  } else if (s.moved.length) {
    start = el("button", {
      class: "primary",
      key: `start-moved-${s.id}`,
      // The places shown on the card: if a folder moved again since, the server refuses.
      onclick: () => startSetup(s.id, { confirm_moved: s.moved.map((m) => m.now) }),
      text: "Use them where they go now, and start",
    });
  } else if (needsInclude(s)) {
    start = el("button", {
      class: "primary",
      key: `allow-${s.id}`,
      disabled: Boolean(s.problem) || Boolean(status?.busy),
      onclick: () => startSetup(s.id, { allow_ssh_include: true }),
      text: "Add the line and start",
    });
  } else {
    start = el("button", {
      class: "primary",
      key: `start-${s.id}`,
      disabled: Boolean(s.problem) || Boolean(status?.busy),
      onclick: () => startSetup(s.id),
      text: status?.busy ? "Starting…" : "Start",
    });
  }
  return el(
    "article",
    { class: `card${run ? " live" : ""}${onThisComputer(s) ? " local" : ""}`, "aria-label": onThisComputer(s) ? `${s.name} (on this computer)` : s.name },
    el("div", { class: "card-head" }, title, el("div", { class: "card-start" }, start)),
    summaryLine(s),
    status
      ? el(
          "p",
          { class: `status-line${status.bad ? " bad" : ""}${status.ok ? " ok" : ""}` },
          status.live ? el("span", { class: "pulse", "aria-hidden": "true" }) : null,
          status.text,
          status.terminal && s.open_in === "codex-app"
            ? el("button", { class: "link small", key: `fallback-terminal-${s.id}`, onclick: () => useTerminal(s), text: "Open in Terminal instead" })
            : null,
        )
      : null,
    run?.app && !run.app.local ? appDetails(run) : null,
    run?.app?.local ? localDetails(run) : null,
    s.problem ? el("p", { class: "problem", text: `Can't start as it is: ${s.problem} Edit it to change that.` }) : null,
    (warned.get(s.id) || []).map((w) => el("p", { class: "note", text: w })),
    s.moved.length ? movedBlock(s) : null,
    !run && needsInclude(s) ? includeBlock(s) : null,
    el(
      "details",
      { class: "card-facts", key: `facts-${s.id}`, open: openFacts.has(s.id), ontoggle: (e) => (e.target.open ? openFacts.add(s.id) : openFacts.delete(s.id)) },
      el("summary", { text: "What Codex can do here" }),
      facts(s, { key: s.id }),
    ),
    el(
      "div",
      { class: "card-foot" },
      el("button", { class: "link", key: `edit-${s.id}`, onclick: () => showForm(s), "aria-label": `Edit ${s.name}`, text: "Edit" }),
      el("button", { class: "link", key: `rename-${s.id}`, "aria-label": `Rename ${s.name}`, text: "Rename", onclick: () => startRename(s) }),
      el("button", { class: "link", key: `dup-${s.id}`, "aria-label": `Duplicate ${s.name}`, onclick: () => duplicate(s), text: "Duplicate" }),
      el("button", { class: "link danger", key: `del-${s.id}`, "aria-label": `Delete ${s.name}`, onclick: () => remove(s), text: "Delete" }),
    ),
  );
}

// A card's one line: the folder, where Codex opens, the internet, the model.
function summaryLine(s) {
  const bits = [
    onThisComputer(s) ? "UM-Codex's local Codex window" : openerLabel(s.open_in),
    onThisComputer(s) ? null : s.internet ? (s.browser ? "Internet on + browser" : "Internet on") : "Internet off",
    s.model,
    s.approvals === "never" ? null : "asks before commands",
  ].filter(Boolean);
  return el(
    "p",
    { class: "card-sum" },
    s.working ? pathView(s.working, { copy: false }) : el("span", { class: "faint", text: "No folder" }),
    (s.folders || []).length ? el("span", { class: "faint", text: ` + ${s.folders.length} more` }) : null,
    el("span", { class: "sep", "aria-hidden": "true", text: "·" }),
    el("span", { text: bits.join(" · ") }),
  );
}

// A saved folder that now leads somewhere else: a real risk, so Start needs
// a deliberate click on the card (no pop-up).
function movedBlock(s) {
  return el(
    "div",
    { class: "warning", role: "alert" },
    el("p", { class: "strong", text: "A saved folder now leads somewhere else (a link was put in its path):" }),
    s.moved.map((m) => el("p", { class: "path" }, `${shortHome(m.saved)} → now ${shortHome(m.now)}`)),
    el("p", {
      class: "help",
      text: "Something (an earlier launch, a sync, an unpacked archive) replaced part of the path with a link. Check that's what you want, or Edit the setup.",
    }),
  );
}

// The Codex app's one line in ~/.ssh/config, when the installer didn't add it.
function includeBlock(s) {
  const asked = cards.get(s.id)?.phase === "include";
  return el(
    "div",
    { class: asked ? "warning" : "inline-note" },
    el("p", {
      text:
        "The Codex app reaches the sandbox through your ssh settings: Start adds one line at the top of " +
        "~/.ssh/config (Include ~/.ssh/um-codex/config). Your file is backed up first, nothing else in it " +
        "changes, and uninstalling UM-Codex takes it out.",
    }),
    el("button", { class: "link", key: `terminal-${s.id}`, onclick: () => useTerminal(s), text: "Open in Terminal instead" }),
  );
}

async function useTerminal(s) {
  try {
    await api("PUT", `/api/setups/${encodeURIComponent(s.id)}`, { ...bodyOf(s), open_in: "terminal" });
    cards.delete(s.id);
  } catch (error) {
    cards.set(s.id, { phase: "failed", text: error.message });
  }
  refresh();
}

// A launch in the Codex app: the first-time steps when UM-Codex couldn't
// set the copy up itself, and the plain lines about where chats run.
function appDetails(run) {
  const app = run.app;
  const showSteps = !app.connected && ((app.first_time && !app.seeded) || shownSteps.has(run.launch_id));
  return el(
    "div",
    { class: "app-panel" },
    showSteps ? el("ol", { class: "steps" }, app.steps.map((step) => el("li", { text: step }))) : null,
    !app.connected && !showSteps
      ? el("button", {
          class: "link small",
          key: `steps-${run.launch_id}`,
          text: "It doesn't connect: show the steps",
          onclick: () => {
            shownSteps.add(run.launch_id);
            redraw();
          },
        })
      : null,
    el(
      "details",
      { class: "app-notes-block" },
      el("summary", { text: `Use chats that show Remote · ${app.alias}; local chats are blocked.` }),
      el("ul", { class: "app-notes" }, app.notes.map((line) => el("li", { text: line }))),
    ),
  );
}

// A launch on this computer: what that window is, in plain lines.
function localDetails(run) {
  return el(
    "details",
    { class: "app-notes-block" },
    el("summary", { text: "About UM-Codex's local Codex window" }),
    el("ul", { class: "app-notes" }, (run.app.notes || []).map((line) => el("li", { text: line }))),
  );
}

function startRename(s) {
  renaming.set(s.id, s.name);
  redraw();
  const field = document.querySelector(`#main [data-key="name-${CSS.escape(s.id)}"]`);
  field?.focus();
  field?.select();
}

function endRename(s) {
  renaming.delete(s.id);
  redraw();
  focusKey(`rename-${s.id}`);
}

function renameField(s) {
  const message = el("span", { class: "message", role: "alert", hidden: true });
  const save = async (event) => {
    event.preventDefault();
    try {
      await api("POST", `/api/setups/${encodeURIComponent(s.id)}/rename`, { name: renaming.get(s.id) });
      renaming.delete(s.id);
      await refresh();
      focusKey(`rename-${s.id}`);
    } catch (error) {
      message.textContent = error.message;
      message.hidden = false;
    }
  };
  return el(
    "form",
    { class: "card-title rename", onsubmit: save },
    el("input", {
      type: "text",
      name: "name",
      key: `name-${s.id}`,
      value: renaming.get(s.id),
      maxlength: "80",
      "aria-label": "Setup name",
      oninput: (e) => renaming.set(s.id, e.target.value),
      onkeydown: (e) => {
        if (e.key === "Escape") endRename(s);
      },
    }),
    el("button", { type: "submit", class: "primary", text: "Save" }),
    el("button", { type: "button", text: "Cancel", onclick: () => endRename(s) }),
    message,
  );
}

async function duplicate(s) {
  try {
    await api("POST", `/api/setups/${encodeURIComponent(s.id)}/duplicate`);
  } catch (error) {
    notice(error.message, true);
  }
  refresh();
}

async function remove(s) {
  const ok = await confirmBox(
    `Delete “${s.name}”?`,
    "The setup and its Codex history are deleted. Your folders themselves aren't touched.",
    "Delete",
  );
  if (!ok) return;
  try {
    await api("DELETE", `/api/setups/${encodeURIComponent(s.id)}`);
  } catch (error) {
    notice(error.message, true);
  }
  refresh();
}

async function pickFolder(start) {
  try {
    const chosen = await api("POST", "/api/folders/pick", start ? { start } : {});
    return chosen.cancelled ? null : chosen;
  } catch (error) {
    return { error: error.message };
  }
}

// ---------------------------------------------------------------- the form

// Each field's control, for focusing the first problem (in the form's order).
const FIELD_CONTROLS = {
  moved: "confirm-moved",
  working: "pick-working",
  folders: "pick-more",
  model: "model",
  open_in: "open-terminal",
  name: "name",
  approvals: "ask",
  runs_on: "runs-on-sandbox",
  local_access: "local-full",
};

// A saved setup as the API takes it back (an edit sends every field).
function bodyOf(s) {
  return {
    name: s.name,
    working: s.working?.path || "",
    folders: (s.folders || []).map((f) => ({ path: f.path, write: Boolean(f.write) })),
    internet: Boolean(s.internet),
    browser: Boolean(s.internet && s.browser),
    browser_asks: s.browser_asks !== false,
    approvals: s.approvals,
    model: s.model,
    open_in: s.open_in,
    runs_on: s.runs_on || "sandbox",
    local_access: s.local_access || "full",
    computer_use: s.computer_use !== false,
  };
}

function showForm(existing) {
  notice("");
  const draft = existing
    ? JSON.parse(JSON.stringify(existing))
    : {
        id: null,
        name: "",
        working: null,
        folders: [],
        internet: true,
        browser: false,
        browser_asks: true,
        approvals: "never",
        model: null,
        open_in: state?.default_open_in || "terminal",
        runs_on: "sandbox",
        local_access: "full",
        computer_use: true,
      };
  view = { name: "form", draft, errors: {}, more: Boolean(existing && (existing.approvals !== "never" || onThisComputer(existing))) };
  renderForm();
  focusKey(existing ? "pick-working" : "pick-working");
  loadModels();
}

async function loadModels() {
  if (models) return;
  try {
    models = await api("GET", "/api/models");
  } catch {
    models = { models: [], default: "gpt-5.6-terra" };
  }
  if (view.name === "form") renderForm();
}

function renderForm() {
  const { draft, errors } = view;
  const local = onThisComputer(draft);
  // On this computer, full access or computer and browser control need "Ask before commands".
  const mustAsk = local && (draft.local_access !== "folder" || draft.computer_use !== false);
  if (mustAsk) draft.approvals = "on-request";
  const running = Boolean(draft.id && state?.running.some((run) => run.setup_id === draft.id));
  const errorId = (field) => (errors[field] ? `err-${field}` : null);
  const describe = (...ids) => ids.filter(Boolean).join(" ") || null;
  const error = (field) => (errors[field] ? el("p", { class: "message", id: `err-${field}`, text: errors[field] }) : null);
  const switchRow = (key, label, help, checked, onchange, extraClass, disabled = false) =>
    el(
      "label",
      { class: `switch ${extraClass || ""}${disabled ? " off" : ""}` },
      el("input", { type: "checkbox", role: "switch", key, checked, disabled, onchange, "aria-describedby": help ? `help-${key}` : null }),
      el("span", { class: "text" }, el("strong", { text: label }), help ? el("span", { class: "help", id: `help-${key}`, text: help }) : null),
    );
  const section = (title, ...children) => el("fieldset", { class: "section" }, el("legend", { text: title }), ...children);

  const chooseWorking = async () => {
    const chosen = await pickFolder(draft.working?.path);
    if (!chosen) return;
    if (chosen.error) errors.working = chosen.error;
    else {
      delete errors.working;
      draft.working = chosen;
    }
    renderForm();
  };

  const working = el(
    "div",
    { class: "field" },
    el("span", { class: "label", id: "label-working", text: "Working folder" }),
    draft.working
      ? el(
          "div",
          { class: "folder-line" },
          pathView(draft.working, { key: "copy-working" }),
          el("button", { type: "button", key: "pick-working", text: "Change…", "aria-describedby": describe("help-working", errorId("working")), onclick: chooseWorking }),
        )
      : el("button", {
          type: "button",
          class: "primary",
          key: "pick-working",
          text: "Choose folder…",
          "aria-describedby": describe("help-working", errorId("working")),
          "aria-invalid": errors.working ? "true" : null,
          onclick: chooseWorking,
        }),
    el("span", { class: "help", id: "help-working", text: "Codex starts here, and can read, change and delete files in it." }),
    (draft.working?.warnings || []).map((w) => el("p", { class: "note", text: w })),
    error("working"),
  );

  const more = el(
    "div",
    { class: "field" },
    el("span", { class: "label", text: "More folders" }),
    el(
      "div",
      { class: "chips" },
      draft.folders.map((folder, index) => {
        const { name } = splitPath(folder.shown);
        const access = (write, text) =>
          el("button", {
            type: "button",
            key: `access-${index}-${write}`,
            "aria-pressed": String(folder.write === write),
            text,
            onclick: () => {
              folder.write = write;
              renderForm();
            },
          });
        return chip(
          folder,
          el(
            "span",
            { class: "controls" },
            local
              ? el("span", { class: "access", text: "READ & WRITE" })
              : el("span", { class: "segmented", role: "group", "aria-label": `Access to ${name}` }, access(false, "Read only"), access(true, "Read & write")),
            el("button", {
              type: "button",
              class: "remove",
              key: `remove-${index}`,
              "aria-label": `Remove ${name}`,
              text: "×",
              onclick: () => {
                draft.folders.splice(index, 1);
                renderForm();
                focusKey("pick-more");
              },
            }),
          ),
        );
      }),
    ),
    el("button", {
      type: "button",
      key: "pick-more",
      text: "Add a folder…",
      "aria-describedby": describe("help-more", errorId("folders")),
      onclick: async () => {
        const chosen = await pickFolder();
        if (!chosen) return;
        if (chosen.error) errors.folders = chosen.error;
        else {
          delete errors.folders;
          draft.folders.push({ path: chosen.path, shown: chosen.shown, write: local, warnings: chosen.warnings });
        }
        renderForm();
      },
    }),
    el("span", {
      class: "help",
      id: "help-more",
      text: local
        ? "Optional. On this computer they're part of Codex's project, Read & write (read-only isn't offered: Codex can read all your files here)."
        : "Optional. Read only: Codex can look but not change. Read & write: it can change and delete there too.",
    }),
    draft.folders.flatMap((f) => f.warnings || []).map((w) => el("p", { class: "note", text: w })),
    error("folders"),
  );

  // Newest release first (the server sorts); the setup's own model stays selected.
  const modelList = models ? [...models.models] : [];
  const currentModel = draft.model || models?.default || "gpt-5.6-terra";
  if (!modelList.includes(currentModel)) modelList.unshift(currentModel);
  draft.model = currentModel;
  const modelField = el(
    "div",
    { class: "field inline" },
    el("label", { class: "label", for: "setup-model", text: "Model" }),
    el(
      "select",
      { id: "setup-model", key: "model", "aria-describedby": errorId("model"), onchange: (e) => ((draft.model = e.target.value), renderSummary()) },
      modelList.map((m) => el("option", { value: m, selected: m === currentModel, text: m })),
    ),
    error("model"),
  );

  const openers = (state?.openers || []).map((o) =>
    el(
      "label",
      { class: o.available ? "" : "off" },
      el("input", {
        type: "radio",
        name: "open_in",
        key: `open-${o.key}`,
        value: o.key,
        checked: draft.open_in === o.key,
        disabled: !o.available,
        onchange: () => {
          draft.open_in = o.key;
          renderForm();
        },
      }),
      o.label,
      !o.available && o.reason ? el("span", { class: "help", text: o.reason }) : null,
    ),
  );

  const nameField = el(
    "div",
    { class: "field" },
    el("label", { class: "label", for: "setup-name", text: "Name" }),
    el("input", {
      type: "text",
      id: "setup-name",
      key: "name",
      value: draft.name,
      maxlength: "80",
      placeholder: draft.working ? splitPath(draft.working.shown).name : "The working folder's name",
      "aria-invalid": errors.name ? "true" : null,
      "aria-describedby": describe("help-name", errorId("name")),
      oninput: (e) => (draft.name = e.target.value),
    }),
    el("span", { class: "help", id: "help-name", text: "Shown on its card and as its project in the Codex app. Empty: the working folder's name." }),
    error("name"),
  );

  const moreOptions = el(
    "details",
    { class: "more-options", open: view.more || errors.name || errors.approvals ? true : null, ontoggle: (e) => (view.more = e.target.open) },
    el("summary", { text: "More options" }),
    switchRow(
      "ask",
      "Ask before commands",
      local
        ? mustAsk
          ? "On: Codex asks before commands in this setup's chats (new chats; the Codex app's own permission choice in a chat can change this). It stays on with full access or with computer and browser control (without it, the apps' own permission questions are turned down)."
          : "On (recommended here): Codex asks before commands in this setup's chats (new chats; the Codex app's own permission choice in a chat can change this). There's no sandbox around it on this computer."
        : "Off (recommended): Codex runs commands without asking; the sandbox is what keeps it in.",
      draft.approvals === "on-request",
      (e) => ((draft.approvals = e.target.checked ? "on-request" : "never"), renderSummary()),
      "",
      local && mustAsk,
    ),
    error("approvals"),
    nameField,
    whereField(draft, errors, error),
  );

  const form = el(
    "form",
    { class: "setup", onsubmit: (e) => saveForm(e, !running), novalidate: true },
    el("h2", { text: draft.id ? `Edit “${draft.name}”` : "New setup" }),
    section("Folder", working, more),
    local
      ? section(
          "Access",
          el("p", { class: "warning-line", text: WORDS.local }),
          el(
            "div",
            { class: "field" },
            el("span", { class: "label", id: "label-local-access", text: "What Codex can change" }),
            el(
              "div",
              { class: "radios", role: "radiogroup", "aria-labelledby": "label-local-access" },
              [
                ["full", "Anything I can (full access)"],
                ["folder", "Only this setup's folders"],
              ].map(([value, label]) =>
                el(
                  "label",
                  {},
                  el("input", {
                    type: "radio",
                    name: "local_access",
                    key: `local-${value}`,
                    value,
                    checked: (draft.local_access || "full") === value,
                    onchange: () => ((draft.local_access = value), renderForm()),
                  }),
                  label,
                ),
              ),
            ),
            el("span", {
              class: "help",
              text:
                "“Only this setup's folders” uses Codex's own macOS sandbox for its commands and file edits. It doesn't limit computer and browser control: those act through your apps, which can change anything you can.",
            }),
            error("local_access"),
          ),
          draft.local_access === "folder"
            ? switchRow(
                "internet",
                "Internet for Codex's commands",
                "On: commands can reach the internet. Off: they can't (Codex's own sandbox). Computer and browser control aren't limited by this.",
                draft.internet,
                (e) => ((draft.internet = e.target.checked), renderSummary()),
                "indent",
              )
            : el("p", { class: "help", text: WORDS.localNetFull }),
          switchRow(
            "computer-use",
            "Computer and browser control",
            "Computer Use (your Mac's apps) and the app's own browser. macOS asks once for Screen Recording and Accessibility. Control of your own Chrome isn't supported yet.",
            draft.computer_use !== false,
            (e) => ((draft.computer_use = e.target.checked), renderForm()),
          ),
        )
      : section(
      "Access",
      switchRow("internet", "Internet", "On: the whole internet. Off: Codex can reach only the model.", draft.internet, (e) => {
        draft.internet = e.target.checked;
        if (!draft.internet) draft.browser = false;
        renderForm();
      }),
      draft.internet
        ? switchRow("browser", "Browser tool", "A fresh browser inside the sandbox; it has none of your logins.", draft.browser, (e) => {
            draft.browser = e.target.checked;
            renderForm();
          }, "indent")
        : null,
      draft.internet && draft.browser
        ? switchRow(
            "browser-asks",
            "Approve each browser action",
            "Opening pages, clicking, typing. Reading a page doesn't ask.",
            draft.browser_asks,
            (e) => ((draft.browser_asks = e.target.checked), renderSummary()),
            "indent",
          )
        : null,
    ),
    section(
      "Codex",
      modelField,
      local
        ? el("div", { class: "field" }, el("span", { class: "label", text: "Open in" }), el("p", { class: "line", text: "UM-Codex's local Codex window (a separate copy of the Codex app, apart from the sandbox's)." }))
        : el(
        "div",
        { class: "field" },
        el("span", { class: "label", text: "Open in" }),
        el("div", { class: "radios" }, openers),
        draft.open_in === "codex-app"
          ? el("span", { class: "help", text: "Codex's desktop app, in a separate copy with UM-Codex's own settings; the work happens in the sandbox." })
          : null,
        error("open_in"),
      ),
      moreOptions,
    ),
    el("div", { class: "form-summary", id: "form-summary" }),
    errors.moved ? movedInForm(draft, errors.moved) : null,
    errors.general ? el("p", { class: "message", role: "alert", text: errors.general }) : null,
    running ? el("p", { class: "note", text: "It's running now: changes apply the next time it starts." }) : null,
    el(
      "div",
      { class: "actions" },
      running
        ? el("button", { type: "button", class: "primary", key: "save", onclick: (e) => saveForm(e, false), text: "Save" })
        : [
            el("button", { type: "submit", class: "primary", key: "save-start", text: "Save and start" }),
            el("button", { type: "button", key: "save", onclick: (e) => saveForm(e, false), text: "Save" }),
          ],
      el("button", { type: "button", key: "cancel", onclick: backHome, text: "Cancel" }),
    ),
  );
  render(form);
  renderSummary();
}

// "Where Codex runs" (M4), in More options: the sandbox is the default. Choosing
// "On this computer" asks first, the one deliberate pop-up (Cancel has the focus);
// Start never asks again.
function whereField(draft, errors, error) {
  const info = state?.this_computer || { available: false, reason: null, warning: "" };
  const current = draft.runs_on || "sandbox";
  const choose = async (value) => {
    if (value === current) return;
    if (value === "this-computer") {
      renderForm(); // the radio stays on the sandbox until the answer is yes
      const yes = await confirmBox("Run Codex on this computer?", info.warning, "Run on this computer");
      if (!yes) {
        focusKey("runs-on-this-computer");
        return;
      }
      draft.runs_on = "this-computer";
      draft.approvals = "on-request";
      draft.browser = false;
      if (draft.folders.some((f) => !f.write)) {
        draft.folders.forEach((f) => (f.write = true));
        view.notes = ["Read-only isn't offered on this computer, so the other folders are now Read & write (part of Codex's project). Remove any you don't want."];
      }
    } else {
      draft.runs_on = "sandbox";
      view.notes = [];
    }
    renderForm();
    focusKey(`runs-on-${draft.runs_on}`);
  };
  const option = (value, label) =>
    el(
      "label",
      { class: value === "this-computer" && !info.available ? "off" : "" },
      el("input", {
        type: "radio",
        name: "runs_on",
        key: `runs-on-${value}`,
        value,
        checked: current === value,
        disabled: value === "this-computer" && !info.available && current !== "this-computer",
        onchange: () => choose(value),
      }),
      label,
    );
  return el(
    "div",
    { class: "field" },
    el("span", { class: "label", id: "label-runs-on", text: "Where Codex runs" }),
    el(
      "div",
      { class: "radios", role: "radiogroup", "aria-labelledby": "label-runs-on" },
      option("sandbox", "In the sandbox (recommended)"),
      option("this-computer", "On this computer (experimental)"),
    ),
    el("span", {
      class: "help",
      text: info.available
        ? "On this computer (experimental): Codex works directly on your Mac, with computer and browser control. Only when you need that."
        : info.reason || "",
    }),
    (view.notes || []).map((n) => el("p", { class: "note", text: n })),
    error("runs_on"),
  );
}

// Under the form: what Codex gets with it, as the card will show it.
function renderSummary() {
  const box = document.getElementById("form-summary");
  if (!box) return;
  box.replaceChildren(el("h3", { class: "label", text: "What Codex gets" }), facts(view.draft, { key: "form" }), el("p", { class: "help", text: WORDS.key }));
}

// Saving a setup whose saved folder now leads somewhere else needs the same
// confirmation as Start: both places, and a deliberate click.
function movedInForm(draft, message) {
  return el(
    "div",
    { class: "warning", role: "alert" },
    el("p", { class: "strong", text: message }),
    (draft.moved || []).map((m) => el("p", { class: "path" }, `${shortHome(m.saved)} → now ${shortHome(m.now)}`)),
    el("button", {
      type: "button",
      key: "confirm-moved",
      onclick: (e) => saveForm(e, false, { confirm_moved: (draft.moved || []).map((m) => m.now) }),
      text: "Use them where they go now, and save",
    }),
  );
}

async function saveForm(event, andStart, extra = {}) {
  event.preventDefault();
  const { draft } = view;
  const body = { ...bodyOf(draft), name: draft.name, ...extra };
  try {
    const saved = draft.id
      ? await api("PUT", `/api/setups/${encodeURIComponent(draft.id)}`, body)
      : await api("POST", "/api/setups", body);
    view = { name: "home" };
    await refresh();
    if (andStart) startOrAsk(saved);
  } catch (error) {
    if (error.field === "moved" && draft.id) {
      await refresh(); // where the folders lead now, to show (and confirm) exactly that
      draft.moved = setupOf(draft.id)?.moved || [];
    }
    // Every problem at once, in the form's order; the first one gets the focus.
    view.errors = Object.keys(error.errors).length ? { ...error.errors } : { general: error.message };
    if (view.errors.name || view.errors.approvals || view.errors.runs_on) view.more = true;
    renderForm();
    const first = Object.keys(view.errors).find((field) => FIELD_CONTROLS[field]);
    if (first) focusKey(FIELD_CONTROLS[first]);
  }
}

function backHome() {
  view = { name: "home" };
  refresh();
}

// ---------------------------------------------------------------- refresh

let lastSeen = "";

async function refresh(force = true) {
  let fresh;
  try {
    fresh = await api("GET", "/api/state");
  } catch (error) {
    notice(error.message, true);
    return;
  }
  // A poll that finds nothing new changes nothing on screen.
  const seen = JSON.stringify(fresh);
  if (!force && seen === lastSeen && !cards.size) return;
  lastSeen = seen;
  state = fresh;
  checkPending();
  renderStatus();
  redraw();
}

// The key field: shown as dots, but not a password field, so browsers don't
// offer to save it in their password managers (and the managers' extensions
// are asked to leave it alone). Where the dots aren't supported, it's a
// password field that asks for no saving.
const keyField = keyInput();
if (!CSS.supports("-webkit-text-security", "disc")) keyField.type = "password";
document.getElementById("key-form").addEventListener("submit", saveKey);
document.getElementById("key-cancel").addEventListener("click", hideKeyPanel);
keyField.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    keyField.value = "";
    if (state?.key.saved) hideKeyPanel();
  }
});
refresh();
// Polling goes on while a question is open, so an open question never makes
// the server think the page has gone.
setInterval(() => {
  if (polling) refresh(false);
}, 4000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && polling) refresh(false);
});
