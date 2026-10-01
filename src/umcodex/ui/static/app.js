// The launcher window. Plain JavaScript: everything shown is built with
// textContent (never innerHTML), and every request is a same-origin JSON
// fetch (the server refuses anything else; see ui/protection.py).
"use strict";

const BROWSER_PLAIN =
  "Codex can open websites in a fresh browser inside the sandbox; it has none of your logins.";

let state = null; // the last /api/state
let view = { name: "list" }; // "list" | "form" | "summary"
let models = null;

// ---------------------------------------------------------------- helpers

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

class ApiError extends Error {
  constructor(status, message, field) {
    super(message);
    this.status = status;
    this.field = field;
  }
}

async function api(method, path, body) {
  const options = { method, headers: { "Content-Type": "application/json" }, credentials: "same-origin" };
  if (method !== "GET") options.body = JSON.stringify(body === undefined ? {} : body);
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError(0, "UM-Codex isn't answering. Open it again from its app.");
  }
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    location.reload();
  }
  if (!response.ok) throw new ApiError(response.status, data.error || "That didn't work.", data.field);
  return data;
}

function notice(text, bad = false) {
  const box = document.getElementById("notice");
  box.textContent = text;
  box.className = bad ? "notice bad" : "notice";
  box.hidden = !text;
}

function confirmBox(title, text, yes) {
  const dialog = document.getElementById("confirm-dialog");
  document.getElementById("confirm-title").textContent = title;
  document.getElementById("confirm-text").textContent = text;
  document.getElementById("confirm-yes").textContent = yes;
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "yes"), { once: true });
  });
}

const approvalsWords = (s) =>
  s.approvals === "never" ? "Runs commands without asking" : "Asks before commands";

function internetWords(s) {
  if (!s.internet) return ["Internet off"];
  const words = ["Internet on"];
  if (s.browser) words.push(s.browser_asks ? "Browser tool on (asks before each action)" : "Browser tool on");
  else words.push("Browser tool off");
  return words;
}

function chip(folder, extra) {
  return el(
    "span",
    { class: folder.write ? "chip write" : "chip", title: folder.path },
    el("span", { class: "path", text: folder.shown }),
    extra || el("span", { class: "access", text: folder.write ? "READ & WRITE" : "READ" }),
  );
}

function openerLabel(key) {
  const found = (state?.openers || []).find((o) => o.key === key);
  return found ? found.label : key;
}

// ---------------------------------------------------------------- status line

function renderStatus() {
  const box = document.getElementById("status");
  box.replaceChildren();
  if (!state) return;
  document.getElementById("version").textContent = `· version ${state.version}`;
  const d = state.docker;
  const dockerItem = el(
    "span",
    { class: "item" },
    el("span", { class: `dot ${d.state === "ready" ? "ok" : d.state === "starting" ? "attn" : "bad"}` }),
    el("span", { text: d.words }),
  );
  if (d.can_open) dockerItem.append(el("button", { class: "link", onclick: openDocker, text: "Open Docker Desktop" }));
  if (d.can_fix) dockerItem.append(el("button", { class: "link", onclick: fixDocker, text: "Fix it…" }));
  box.append(dockerItem);
  if (d.fix_explained) box.append(el("span", { class: "explain", text: d.fix_explained }));
  box.append(
    el(
      "span",
      { class: "item" },
      el("span", { class: `dot ${state.key.saved ? "ok" : "bad"}` }),
      el("span", { text: state.key.saved ? "Toolkit key saved" : "No Toolkit key saved" }),
      el("button", { class: "link", onclick: openKeyDialog, text: state.key.saved ? "Replace key…" : "Add key…" }),
    ),
  );
  if (state.update) {
    box.append(
      el(
        "span",
        { class: "item" },
        el("span", { class: "dot attn" }),
        el("span", { text: "A new version is available: in a terminal, run " }),
        el("code", { text: "um-codex update" }),
      ),
    );
  }
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

// ---------------------------------------------------------------- the key

function openKeyDialog() {
  const dialog = document.getElementById("key-dialog");
  const input = document.getElementById("key-input");
  input.value = "";
  document.getElementById("key-message").hidden = true;
  dialog.showModal();
  input.focus();
}

async function saveKey(event) {
  event.preventDefault();
  const input = document.getElementById("key-input");
  const message = document.getElementById("key-message");
  const button = document.getElementById("key-save");
  button.disabled = true;
  message.hidden = false;
  message.className = "message ok";
  message.textContent = "Checking the key with the Toolkit…";
  try {
    const result = await api("POST", "/api/key", { key: input.value });
    input.value = "";
    document.getElementById("key-dialog").close();
    models = null;
    notice(result.words);
    refresh();
  } catch (error) {
    message.className = "message";
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

// ---------------------------------------------------------------- the list

function renderList() {
  const main = document.getElementById("main");
  const parts = [];
  if (state.running.length) {
    parts.push(
      el(
        "section",
        { class: "block", "aria-label": "Running" },
        el("div", { class: "block-head" }, el("span", { class: "label", text: "Running now" })),
        state.running.map((run) =>
          el(
            "div",
            { class: "running-row" },
            el("span", { class: "pulse", "aria-hidden": "true" }),
            el("span", { class: "name", text: run.setup_name }),
            el("span", { class: "since", text: `Running since ${run.since}` }),
            el("span", { class: "grow" }),
            el("button", { onclick: () => stopLaunch(run), text: "Stop" }),
          ),
        ),
      ),
    );
  }
  const head = el(
    "div",
    { class: "block-head" },
    el("span", { class: "label", text: "Your setups" }),
    el("button", { class: "primary", onclick: () => showForm(null), text: "New setup" }),
  );
  const cards = state.setups.length
    ? el("div", { class: "cards" }, state.setups.map(card))
    : el(
        "p",
        { class: "empty" },
        "No setups yet. A setup says which folders Codex can use, whether it can reach the internet, " +
          "and how it asks you before acting. Make one with New setup.",
      );
  parts.push(el("section", { class: "block", "aria-label": "Setups" }, head, cards));
  main.replaceChildren(...parts);
}

function card(s) {
  return el(
    "article",
    { class: "card", "aria-label": s.name },
    el(
      "div",
      { class: "card-head" },
      el("h3", { text: s.name }),
      el("span", { class: "opens", text: `Opens in ${openerLabel(s.open_in)}` }),
    ),
    el(
      "div",
      { class: "working" },
      el("span", { class: "label", text: "Working folder (read & write)" }),
      el("span", { class: "path", title: s.working.path, text: s.working.shown }),
    ),
    s.folders.length
      ? el("div", {}, el("span", { class: "label", text: "More folders" }), el("div", { class: "chips" }, s.folders.map((f) => chip(f))))
      : null,
    el(
      "p",
      { class: "facts" },
      [...internetWords(s), approvalsWords(s), s.model].map((w) => el("span", { text: w })),
    ),
    s.problem ? el("p", { class: "problem", text: `Can't start as it is: ${s.problem}` }) : null,
    el(
      "div",
      { class: "actions" },
      el("button", { class: "primary", disabled: Boolean(s.problem), onclick: () => showSummary(s), text: "Start" }),
      el("button", { onclick: () => showForm(s), text: "Edit" }),
      el("button", { class: "quiet", onclick: () => duplicate(s), text: "Duplicate" }),
      el("button", { class: "quiet danger", onclick: () => remove(s), text: "Delete" }),
    ),
  );
}

async function stopLaunch(run) {
  const ok = await confirmBox(
    `Stop “${run.setup_name}”?`,
    "Codex stops and its sandbox is removed. Files it already changed in your folders stay as they are; " +
      "its history is kept.",
    "Stop",
  );
  if (!ok) return;
  try {
    await api("POST", `/api/launches/${encodeURIComponent(run.launch_id)}/stop`);
    notice(`Stopped “${run.setup_name}”.`);
  } catch (error) {
    notice(error.message, true);
  }
  refresh();
}

async function duplicate(s) {
  try {
    const copy = await api("POST", `/api/setups/${encodeURIComponent(s.id)}/duplicate`);
    notice(`Made “${copy.name}”.`);
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
    notice(`Deleted “${s.name}”.`);
  } catch (error) {
    notice(error.message, true);
  }
  refresh();
}

// ---------------------------------------------------------------- the form

function showForm(existing) {
  notice("");
  const draft = existing
    ? JSON.parse(JSON.stringify(existing))
    : {
        id: null,
        name: "",
        working: null,
        folders: [],
        internet: false,
        browser: false,
        browser_asks: true,
        approvals: "never",
        model: null,
        open_in: "terminal",
      };
  view = { name: "form", draft, errors: {}, nameTouched: Boolean(existing) };
  renderForm();
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

async function pickFolder(start) {
  try {
    const chosen = await api("POST", "/api/folders/pick", start ? { start } : {});
    return chosen.cancelled ? null : chosen;
  } catch (error) {
    return { error: error.message };
  }
}

function renderForm() {
  const { draft, errors } = view;
  const main = document.getElementById("main");
  const error = (field) => (errors[field] ? el("p", { class: "message", role: "alert", text: errors[field] }) : null);
  const switchRow = (label, help, checked, onchange, extraClass) =>
    el(
      "label",
      { class: `switch ${extraClass || ""}` },
      el("input", { type: "checkbox", role: "switch", checked, onchange }),
      el("span", { class: "text" }, el("strong", { text: label }), help ? el("span", { class: "help", text: help }) : null),
    );

  const nameInput = el("input", {
    type: "text",
    value: draft.name,
    maxlength: "80",
    oninput: (e) => {
      draft.name = e.target.value;
      view.nameTouched = true;
    },
  });

  const working = el(
    "div",
    { class: "field" },
    el("span", { class: "label", text: "Working folder" }),
    el(
      "div",
      { class: "folder-line" },
      draft.working
        ? el("span", { class: "path", title: draft.working.path, text: draft.working.shown })
        : el("span", { class: "muted", text: "None chosen yet" }),
      el("button", {
        type: "button",
        text: "Choose folder…",
        onclick: async () => {
          const chosen = await pickFolder(draft.working?.path);
          if (!chosen) return;
          if (chosen.error) errors.working = chosen.error;
          else {
            delete errors.working;
            draft.working = chosen;
            if (!view.nameTouched || !draft.name) draft.name = chosen.path.split(/[\\/]/).filter(Boolean).pop() || "";
          }
          renderForm();
        },
      }),
    ),
    el("span", { class: "help", text: "Codex starts here, and can read, change and delete files in it." }),
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
      draft.folders.map((folder, index) =>
        chip(
          folder,
          el(
            "span",
            { class: "controls" },
            el(
              "span",
              { class: "segmented", role: "group", "aria-label": `Access to ${folder.shown}` },
              el("button", {
                type: "button",
                "aria-pressed": String(!folder.write),
                text: "Read only",
                onclick: () => {
                  folder.write = false;
                  renderForm();
                },
              }),
              el("button", {
                type: "button",
                "aria-pressed": String(folder.write),
                text: "Read & write",
                onclick: () => {
                  folder.write = true;
                  renderForm();
                },
              }),
            ),
            el("button", {
              type: "button",
              class: "remove",
              "aria-label": `Remove ${folder.shown}`,
              text: "×",
              onclick: () => {
                draft.folders.splice(index, 1);
                renderForm();
              },
            }),
          ),
        ),
      ),
    ),
    el("button", {
      type: "button",
      text: "Choose folder…",
      onclick: async () => {
        const chosen = await pickFolder();
        if (!chosen) return;
        if (chosen.error) errors.folders = chosen.error;
        else {
          delete errors.folders;
          draft.folders.push({ path: chosen.path, shown: chosen.shown, write: false, warnings: chosen.warnings });
        }
        renderForm();
      },
    }),
    el("span", {
      class: "help",
      text: "Optional. Read only: Codex can look but not change. Read & write: Codex can change and delete files there too.",
    }),
    draft.folders.flatMap((f) => f.warnings || []).map((w) => el("p", { class: "note", text: w })),
    error("folders"),
  );

  const modelList = models ? [...models.models] : [];
  const currentModel = draft.model || models?.default || "gpt-5.6-terra";
  if (!modelList.includes(currentModel)) modelList.unshift(currentModel);
  const modelSelect = el(
    "select",
    { onchange: (e) => (draft.model = e.target.value) },
    modelList.map((m) => el("option", { value: m, selected: m === currentModel, text: m })),
  );
  draft.model = currentModel;

  const openers = (state?.openers || []).map((o) =>
    el(
      "label",
      { class: o.available ? "" : "off" },
      el("input", {
        type: "radio",
        name: "open_in",
        value: o.key,
        checked: draft.open_in === o.key,
        disabled: !o.available,
        onchange: () => (draft.open_in = o.key),
      }),
      o.available ? `${o.label}` : `${o.label} (coming soon)`,
    ),
  );

  const form = el(
    "form",
    { class: "setup", onsubmit: saveForm, novalidate: true },
    el("h2", { text: draft.id ? `Edit “${draft.name}”` : "New setup" }),
    el("p", { class: "muted", text: "What Codex can see and do when it starts. You can change this later." }),
    working,
    el("label", { class: "field" }, el("span", { class: "label", text: "Name" }), nameInput, error("name")),
    more,
    el("span", { class: "label", text: "Internet and approvals" }),
    switchRow("Internet", "Off: Codex can reach only the model. On: the whole internet.", draft.internet, (e) => {
      draft.internet = e.target.checked;
      if (!draft.internet) draft.browser = false;
      renderForm();
    }),
    draft.internet
      ? switchRow("Browser tool", BROWSER_PLAIN, draft.browser, (e) => {
          draft.browser = e.target.checked;
          renderForm();
        }, "indent")
      : null,
    draft.internet && draft.browser
      ? switchRow(
          "Approve each browser action",
          "Opening pages, clicking, typing. Reading a page doesn't ask.",
          draft.browser_asks,
          (e) => (draft.browser_asks = e.target.checked),
          "indent",
        )
      : null,
    switchRow(
      "Ask me before commands",
      "Off (recommended): Codex runs commands without asking; the sandbox is what keeps it in.",
      draft.approvals === "on-request",
      (e) => (draft.approvals = e.target.checked ? "on-request" : "never"),
    ),
    error("approvals"),
    el("label", { class: "field" }, el("span", { class: "label", text: "Model" }), modelSelect, error("model")),
    el("fieldset", {}, el("legend", { class: "label", text: "Open in" }), el("div", { class: "radios" }, openers), error("open_in")),
    error("general"),
    el(
      "div",
      { class: "actions" },
      el("button", { type: "submit", class: "primary", text: "Save" }),
      el("button", { type: "button", onclick: backToList, text: "Cancel" }),
    ),
  );
  main.replaceChildren(form);
}

async function saveForm(event) {
  event.preventDefault();
  const { draft } = view;
  view.errors = {};
  const body = {
    name: draft.name,
    working: draft.working?.path || "",
    folders: draft.folders.map((f) => ({ path: f.path, write: Boolean(f.write) })),
    internet: draft.internet,
    browser: draft.internet && draft.browser,
    browser_asks: draft.browser_asks,
    approvals: draft.approvals,
    model: draft.model,
    open_in: draft.open_in,
  };
  try {
    const saved = draft.id
      ? await api("PUT", `/api/setups/${encodeURIComponent(draft.id)}`, body)
      : await api("POST", "/api/setups", body);
    notice(`Saved “${saved.name}”.`);
    backToList();
  } catch (error) {
    view.errors[error.field || "general"] = error.message;
    renderForm();
  }
}

function backToList() {
  view = { name: "list" };
  refresh();
}

// ---------------------------------------------------------------- before a start

async function showSummary(s) {
  notice("");
  try {
    const prepared = await api("POST", `/api/setups/${encodeURIComponent(s.id)}/prepare`);
    view = { name: "summary", setup: s, prepared, confirmed: false };
    renderSummary();
  } catch (error) {
    notice(error.message, true);
  }
}

function summaryBlock(lines) {
  // The terminal's summary lines (setups.summary): a folder line is
  // "  <folder>   (<where in the sandbox>)"; other indented lines are notes;
  // a plain line ending in "." or ":" ends its paragraph (the terminal wraps
  // longer ones over several lines).
  const block = el("div", { class: "summary" });
  let paragraph = [];
  const flush = () => {
    if (paragraph.length) block.append(el("p", { text: paragraph.join(" ") }));
    paragraph = [];
  };
  for (const line of lines) {
    const text = line.trim();
    if (!text || line.startsWith("Setup: ")) flush();
    else if (line.startsWith("  ") && line.includes("   (")) {
      flush();
      block.append(el("div", { class: "path-line", text }));
    } else if (line.startsWith("  ")) {
      flush();
      block.append(el("p", { class: text.startsWith("Note:") ? "note" : "muted", text }));
    } else {
      if (/^[A-Z][A-Za-z ]*: /.test(text)) flush(); // "Model: …", "Approvals: …" start their own
      paragraph.push(text);
      if (/[.:]$/.test(text)) flush();
    }
  }
  flush();
  return block;
}

function renderSummary() {
  const { setup, prepared } = view;
  const main = document.getElementById("main");
  const start = el("button", { class: "primary", onclick: startSetup, text: `Start in ${openerLabel(setup.open_in)}` });
  const needsConfirm = prepared.moved.length > 0;
  start.disabled = needsConfirm && !view.confirmed;
  const warning = needsConfirm
    ? el(
        "div",
        { class: "warning", role: "alert" },
        el("p", { class: "strong", text: "A saved folder now leads somewhere else (a link was put in its path):" }),
        prepared.moved.map((m) =>
          el("p", {}, el("span", { class: "path", text: m.saved }), el("span", { class: "path", text: `now goes to ${m.now}` })),
        ),
        el(
          "p",
          { text: "This can happen when something (an earlier launch, a sync, an unpacked archive) replaced part of the path with a link. Check that this is what you want, or go back and edit the setup." },
        ),
        el(
          "label",
          {},
          el("input", {
            type: "checkbox",
            onchange: (e) => {
              view.confirmed = e.target.checked;
              start.disabled = !view.confirmed;
            },
          }),
          "Use them where they go now",
        ),
      )
    : null;
  main.replaceChildren(
    el(
      "section",
      { class: "block" },
      el("h2", { text: `Start “${setup.name}”?` }),
      el("p", { class: "muted", text: "Here's what Codex will be able to see and do." }),
      warning,
      summaryBlock(prepared.summary),
      el("div", { class: "actions" }, start, el("button", { onclick: backToList, text: "Back" })),
    ),
  );
}

async function startSetup() {
  const { setup } = view;
  try {
    const result = await api("POST", `/api/setups/${encodeURIComponent(setup.id)}/start`, {
      confirm_moved: Boolean(view.confirmed),
    });
    notice(`Opened in ${result.opened}: Codex is starting there. Quit Codex there (or Stop here) to end it.`);
    backToList();
  } catch (error) {
    notice(error.message, true);
  }
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
  // A poll that finds nothing new changes nothing on screen (keeps focus).
  const seen = JSON.stringify(fresh);
  if (!force && seen === lastSeen) return;
  lastSeen = seen;
  state = fresh;
  renderStatus();
  if (view.name === "list") renderList();
}

document.getElementById("key-form").addEventListener("submit", saveKey);
document.getElementById("key-cancel").addEventListener("click", () => {
  document.getElementById("key-input").value = "";
  document.getElementById("key-dialog").close();
});
refresh();
setInterval(() => {
  if (!document.querySelector("dialog[open]")) refresh(false);
}, 4000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh(false);
});
