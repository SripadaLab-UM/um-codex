// The launcher window. Plain JavaScript: everything shown is built with
// textContent (never innerHTML), and every request is a same-origin JSON
// fetch (the server refuses anything else; see ui/protection.py).
"use strict";

const BROWSER_PLAIN =
  "Codex can open websites in a fresh browser inside the sandbox; it has none of your logins.";
const START_WAIT_MS = 90000; // how long a card says "Starting…" before giving up

let state = null; // the last /api/state
let view = { name: "list" }; // "list" | "form" | "summary"
let models = null;
let polling = true;
const starting = new Map(); // setup id -> when Start was pressed (until its launch shows as running)

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

const approvalsWords = (s) =>
  s.approvals === "never" ? "Runs commands without asking" : "Asks before commands";

function internetWords(s) {
  if (!s.internet) return ["Internet off"];
  const words = ["Internet on"];
  if (s.browser) words.push(s.browser_asks ? "Browser tool on (asks before each action)" : "Browser tool on");
  else words.push("Browser tool off");
  return words;
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
    parent ? el("span", { class: "parent", text: middle(parent, 34) }) : null,
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
    extra || el("span", { class: "access", text: folder.write ? "READ & WRITE" : "READ" }),
  );
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
  if (state.installed) {
    box.append(
      el(
        "span",
        { class: "item stale" },
        el("span", { class: "dot attn" }),
        el("span", { text: `UM-Codex ${state.installed} is installed; this window is still ${state.version}.` }),
        el("button", { class: "link", onclick: reopenNewer, text: "Reopen" }),
      ),
    );
  } else if (state.update) {
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

async function reopenNewer() {
  try {
    await api("POST", "/api/reopen");
    polling = false;
    notice("Reopening as the installed version: a new window opens in your browser. You can close this one.");
  } catch (error) {
    notice(error.message, true);
  }
}

// ---------------------------------------------------------------- the key

function keyInput() {
  return document.getElementById("key-input");
}

function openKeyDialog() {
  const dialog = document.getElementById("key-dialog");
  keyInput().value = "";
  document.getElementById("key-message").hidden = true;
  dialog.showModal();
  keyInput().focus();
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
    document.getElementById("key-dialog").close();
    models = null;
    notice(result.words);
    refresh();
  } catch (error) {
    message.className = "message";
    message.textContent = error.message;
    keyInput().focus();
  } finally {
    button.disabled = false;
  }
}

// ---------------------------------------------------------------- the list

function runningOf(setupId) {
  return state.running.find((run) => run.setup_id === setupId);
}

function renderList() {
  const parts = [];
  if (state.running.length) {
    parts.push(
      el(
        "section",
        { class: "block", "aria-label": "Running" },
        el("div", { class: "block-head" }, el("h2", { class: "label", text: "Running now" })),
        state.running.map((run) =>
          el(
            "div",
            { class: "running-row" },
            el("span", { class: "pulse", "aria-hidden": "true" }),
            el("span", { class: "name", text: run.setup_name }),
            el("span", { class: "since", text: `Running since ${run.since}` }),
            el("span", { class: "grow" }),
            el("button", { key: `stop-${run.launch_id}`, onclick: () => stopLaunch(run), text: "Stop" }),
          ),
        ),
      ),
    );
  }
  if (!state.setups.length) {
    parts.push(firstRun());
  } else {
    const head = el(
      "div",
      { class: "block-head" },
      el("h2", { class: "label", text: "Your setups" }),
      el("button", { class: "primary", key: "new", onclick: () => showForm(null), text: "New setup" }),
    );
    parts.push(el("section", { class: "block", "aria-label": "Setups" }, head, el("div", { class: "cards" }, state.setups.map(card))));
  }
  render(...parts);
}

// The first time: what's needed, in order.
function firstRun() {
  const docker = state.docker;
  const step = (done, title, detail, action) =>
    el(
      "li",
      { class: done ? "done" : "" },
      el("span", { class: "tick", "aria-hidden": "true", text: done ? "✓" : "" }),
      el("span", { class: "step" }, el("strong", { text: title }), el("span", { class: "help", text: done ? "Done." : detail })),
      done ? null : action,
    );
  return el(
    "section",
    { class: "block", "aria-label": "Getting started" },
    el("h2", { text: "Getting started" }),
    el("p", { class: "muted", text: "Three things, then Codex opens in a terminal window whenever you start a setup." }),
    el(
      "ol",
      { class: "checklist" },
      step(
        state.key.saved,
        "Add your Toolkit key",
        "It's kept in this computer's keychain and never goes into the sandbox.",
        el("button", { key: "first-key", onclick: openKeyDialog, text: "Add key…" }),
      ),
      step(
        docker.state === "ready",
        "Docker Desktop running",
        docker.words,
        docker.can_open
          ? el("button", { key: "first-docker", onclick: openDocker, text: "Open Docker Desktop" })
          : docker.can_fix
            ? el("button", { key: "first-fix", onclick: fixDocker, text: "Fix it…" })
            : null,
      ),
      step(
        false,
        "Make your first setup",
        "Which folders Codex can use, and whether it can reach the internet.",
        el("button", { class: "primary", key: "new", onclick: () => showForm(null), text: "New setup" }),
      ),
    ),
  );
}

function card(s) {
  const run = runningOf(s.id);
  if (run) starting.delete(s.id);
  const since = starting.get(s.id);
  if (since && Date.now() - since > START_WAIT_MS) {
    starting.delete(s.id);
    notice(`“${s.name}” didn't start. Its terminal window says why.`, true);
  }
  let start;
  if (run) {
    start = el(
      "span",
      { class: "running-tag" },
      el("span", { class: "pulse", "aria-hidden": "true" }),
      "Running · ",
      el("button", { class: "link", key: `stop-card-${s.id}`, onclick: () => stopLaunch(run), text: "Stop" }),
    );
  } else if (starting.has(s.id)) {
    start = el("button", { class: "primary", disabled: true, text: "Starting…" });
  } else {
    start = el("button", {
      class: "primary",
      key: `start-${s.id}`,
      disabled: Boolean(s.problem),
      onclick: (e) => showSummary(s, e.currentTarget),
      text: "Start",
    });
  }
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
      pathView(s.working, { key: `copy-${s.id}` }),
    ),
    s.folders.length
      ? el("div", {}, el("span", { class: "label", text: "More folders" }), el("div", { class: "chips" }, s.folders.map((f) => chip(f))))
      : null,
    el("p", { class: "facts" }, [...internetWords(s), approvalsWords(s), s.model].map((w) => el("span", { text: w }))),
    s.problem ? el("p", { class: "problem", text: `Can't start as it is: ${s.problem}` }) : null,
    el(
      "div",
      { class: "actions" },
      start,
      el("button", { key: `edit-${s.id}`, onclick: () => showForm(s), text: "Edit" }),
      el("button", { class: "quiet", key: `dup-${s.id}`, onclick: () => duplicate(s), text: "Duplicate" }),
      el("button", { class: "quiet danger", key: `del-${s.id}`, onclick: () => remove(s), text: "Delete" }),
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

// Each field's control, for focusing the first problem (in the form's order).
const FIELD_CONTROLS = {
  working: "pick-working",
  name: "name",
  folders: "pick-more",
  approvals: "ask",
  model: "model",
  open_in: "open-terminal",
};

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
  document.querySelector('#main [data-key="pick-working"]')?.focus();
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
  const errorId = (field) => (errors[field] ? `err-${field}` : null);
  const describe = (...ids) => ids.filter(Boolean).join(" ") || null;
  const error = (field) => (errors[field] ? el("p", { class: "message", id: `err-${field}`, text: errors[field] }) : null);
  const switchRow = (key, label, help, checked, onchange, extraClass) =>
    el(
      "label",
      { class: `switch ${extraClass || ""}` },
      el("input", { type: "checkbox", role: "switch", key, checked, onchange, "aria-describedby": help ? `help-${key}` : null }),
      el(
        "span",
        { class: "text" },
        el("strong", { text: label }),
        help ? el("span", { class: "help", id: `help-${key}`, text: help }) : null,
      ),
    );

  const chooseWorking = async () => {
    const chosen = await pickFolder(draft.working?.path);
    if (!chosen) return;
    if (chosen.error) errors.working = chosen.error;
    else {
      delete errors.working;
      draft.working = chosen;
      if (!view.nameTouched || !draft.name) draft.name = splitPath(chosen.shown).name;
    }
    renderForm();
  };

  const working = el(
    "fieldset",
    { class: "field" },
    el("legend", { class: "label", text: "Working folder" }),
    draft.working
      ? el(
          "div",
          { class: "folder-line" },
          pathView(draft.working, { key: "copy-working" }),
          el("button", {
            type: "button",
            key: "pick-working",
            text: "Change…",
            "aria-describedby": describe("help-working", errorId("working")),
            onclick: chooseWorking,
          }),
        )
      : el("button", {
          type: "button",
          class: "primary big",
          key: "pick-working",
          text: "Choose working folder…",
          "aria-describedby": describe("help-working", errorId("working")),
          "aria-invalid": errors.working ? "true" : null,
          onclick: chooseWorking,
        }),
    el("span", { class: "help", id: "help-working", text: "Codex starts here, and can read, change and delete files in it." }),
    (draft.working?.warnings || []).map((w) => el("p", { class: "note", text: w })),
    error("working"),
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
      "aria-invalid": errors.name ? "true" : null,
      "aria-describedby": errorId("name"),
      oninput: (e) => {
        draft.name = e.target.value;
        view.nameTouched = true;
      },
    }),
    error("name"),
  );

  const more = el(
    "fieldset",
    { class: "field" },
    el("legend", { class: "label", text: "More folders" }),
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
            el(
              "span",
              { class: "segmented", role: "group", "aria-label": `Access to ${name}` },
              access(false, "Read only"),
              access(true, "Read & write"),
            ),
            el("button", {
              type: "button",
              class: "remove",
              key: `remove-${index}`,
              "aria-label": `Remove ${name}`,
              text: "×",
              onclick: () => {
                draft.folders.splice(index, 1);
                renderForm();
                document.querySelector('#main [data-key="pick-more"]')?.focus();
              },
            }),
          ),
        );
      }),
    ),
    el("button", {
      type: "button",
      key: "pick-more",
      text: "Choose folder…",
      "aria-describedby": describe("help-more", errorId("folders")),
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
      id: "help-more",
      text: "Optional. Read only: Codex can look but not change. Read & write: Codex can change and delete files there too.",
    }),
    draft.folders.flatMap((f) => f.warnings || []).map((w) => el("p", { class: "note", text: w })),
    error("folders"),
  );

  const modelList = models ? [...models.models] : [];
  const currentModel = draft.model || models?.default || "gpt-5.6-terra";
  if (!modelList.includes(currentModel)) modelList.unshift(currentModel);
  draft.model = currentModel;
  const modelField = el(
    "div",
    { class: "field" },
    el("label", { class: "label", for: "setup-model", text: "Model" }),
    el(
      "select",
      { id: "setup-model", key: "model", "aria-describedby": errorId("model"), onchange: (e) => (draft.model = e.target.value) },
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
        onchange: () => (draft.open_in = o.key),
      }),
      o.available ? o.label : `${o.label} (coming soon)`,
    ),
  );

  const form = el(
    "form",
    { class: "setup", onsubmit: saveForm, novalidate: true },
    el("h2", { text: draft.id ? `Edit “${draft.name}”` : "New setup" }),
    el("p", { class: "muted", text: "What Codex can see and do when it starts. You can change this later." }),
    working,
    nameField,
    more,
    el(
      "fieldset",
      { class: "field" },
      el("legend", { class: "label", text: "Internet and approvals" }),
      switchRow("internet", "Internet", "Off: Codex can reach only the model. On: the whole internet.", draft.internet, (e) => {
        draft.internet = e.target.checked;
        if (!draft.internet) draft.browser = false;
        renderForm();
      }),
      draft.internet
        ? switchRow("browser", "Browser tool", BROWSER_PLAIN, draft.browser, (e) => {
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
            (e) => (draft.browser_asks = e.target.checked),
            "indent",
          )
        : null,
      switchRow(
        "ask",
        "Ask me before commands",
        "Off (recommended): Codex runs commands without asking; the sandbox is what keeps it in.",
        draft.approvals === "on-request",
        (e) => (draft.approvals = e.target.checked ? "on-request" : "never"),
      ),
      error("approvals"),
    ),
    modelField,
    el("fieldset", { class: "field" }, el("legend", { class: "label", text: "Open in" }), el("div", { class: "radios" }, openers), error("open_in")),
    errors.general ? el("p", { class: "message", role: "alert", text: errors.general }) : null,
    el(
      "div",
      { class: "actions" },
      el("button", { type: "submit", class: "primary", key: "save", text: "Save" }),
      el("button", { type: "button", key: "cancel", onclick: backToList, text: "Cancel" }),
    ),
  );
  render(form);
}

async function saveForm(event) {
  event.preventDefault();
  const { draft } = view;
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
    // Every problem at once, in the form's order; the first one gets the focus.
    view.errors = Object.keys(error.errors).length ? { ...error.errors } : { general: error.message };
    renderForm();
    const first = Object.keys(view.errors).find((field) => FIELD_CONTROLS[field]);
    if (first) document.querySelector(`#main [data-key="${FIELD_CONTROLS[first]}"]`)?.focus();
  }
}

function backToList() {
  view = { name: "list" };
  refresh();
}

// ---------------------------------------------------------------- before a start

async function showSummary(s, button) {
  notice("");
  if (button) button.disabled = true;
  try {
    const prepared = await api("POST", `/api/setups/${encodeURIComponent(s.id)}/prepare`);
    view = { name: "summary", setup: s, prepared, confirmed: false, busy: false };
    renderSummary();
    document.querySelector('#main [data-key="go"]:not([disabled]), #main [data-key="back"]')?.focus();
  } catch (error) {
    notice(error.message, true);
    if (button) button.disabled = false;
  }
}

function shortHome(path) {
  const home = state?.home;
  if (!home) return path;
  return path === home || path.startsWith(home + "/") || path.startsWith(home + "\\") ? "~" + path.slice(home.length) : path;
}

// A summary folder line, "  <folder>   (<where in the sandbox>)", as
// "/work ← <short path>".
function folderLine(line) {
  const at = line.lastIndexOf("   (");
  const path = line.slice(0, at).trim();
  const where = line.slice(at + 4, -1).split(", ").pop();
  return el(
    "div",
    { class: "path-line" },
    el("code", { class: "target", text: where }),
    el("span", { class: "arrow", "aria-label": "is", text: " ← " }),
    pathView({ path, shown: shortHome(path) }),
  );
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
    else if (line.startsWith("  ") && line.includes("   (") && line.endsWith(")")) {
      flush();
      block.append(folderLine(line));
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
  const docker = state.docker;
  const dockerReady = docker.state === "ready";
  const needsConfirm = prepared.moved.length > 0;
  const start = el("button", {
    class: "primary",
    key: "go",
    onclick: startSetup,
    text: view.busy ? "Starting…" : `Start in ${openerLabel(setup.open_in)}`,
  });
  start.disabled = view.busy || !dockerReady || (needsConfirm && !view.confirmed);
  const dockerBox = dockerReady
    ? null
    : el(
        "div",
        { class: "warning", role: "status" },
        el("p", { class: "strong", text: docker.state === "stopped" ? "Docker Desktop isn't running. Open it first." : docker.words }),
        docker.can_open ? el("button", { key: "open-docker", onclick: openDocker, text: "Open Docker Desktop" }) : null,
        docker.can_fix ? el("button", { key: "fix-docker", onclick: fixDocker, text: "Fix it…" }) : null,
      );
  const warning = needsConfirm
    ? el(
        "div",
        { class: "warning", role: "alert" },
        el("p", { class: "strong", text: "A saved folder now leads somewhere else (a link was put in its path):" }),
        prepared.moved.map((m) =>
          el("p", {}, el("span", { class: "path", text: m.saved }), el("span", { class: "path", text: `now goes to ${m.now}` })),
        ),
        el("p", {
          text:
            "This can happen when something (an earlier launch, a sync, an unpacked archive) replaced part of the path " +
            "with a link. Check that this is what you want, or go back and edit the setup.",
        }),
        el(
          "label",
          {},
          el("input", {
            type: "checkbox",
            key: "confirm-moved",
            checked: view.confirmed,
            onchange: (e) => {
              view.confirmed = e.target.checked;
              renderSummary();
            },
          }),
          "Use them where they go now",
        ),
      )
    : null;
  render(
    el(
      "section",
      { class: "block" },
      el("h2", { text: `Start “${setup.name}”?` }),
      el("p", { class: "muted", text: "Here's what Codex will be able to see and do." }),
      dockerBox,
      warning,
      summaryBlock(prepared.summary),
      el("div", { class: "actions" }, start, el("button", { key: "back", onclick: backToList, text: "Back" })),
    ),
  );
}

async function startSetup() {
  const { setup } = view;
  view.busy = true;
  renderSummary();
  try {
    const result = await api("POST", `/api/setups/${encodeURIComponent(setup.id)}/start`, {
      confirm_moved: Boolean(view.confirmed),
    });
    starting.set(setup.id, Date.now());
    notice(`Opened in ${result.opened}: Codex is starting there. Quit Codex there (or Stop here) to end it.`);
    backToList();
  } catch (error) {
    notice(error.message, true);
    view.busy = false;
    if (view.name === "summary") {
      await refresh();
      renderSummary();
    }
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
  // A poll that finds nothing new changes nothing on screen.
  const seen = JSON.stringify(fresh);
  if (!force && seen === lastSeen && !starting.size) return;
  lastSeen = seen;
  state = fresh;
  renderStatus();
  if (view.name === "list") renderList();
  else if (view.name === "summary" && !view.busy) renderSummary();
}

// The key field: shown as dots, but not a password field, so browsers don't
// offer to save it in their password managers (and the managers' extensions
// are asked to leave it alone). Where the dots aren't supported, it's a
// password field that asks for no saving.
const keyField = keyInput();
if (!CSS.supports("-webkit-text-security", "disc")) keyField.type = "password";
document.getElementById("key-form").addEventListener("submit", saveKey);
document.getElementById("key-cancel").addEventListener("click", () => document.getElementById("key-dialog").close());
// Escape, Cancel or saving: the field is emptied whenever the box closes.
document.getElementById("key-dialog").addEventListener("close", () => (keyField.value = ""));
refresh();
// Polling goes on while a dialog is open, so an open box never makes the
// server think the page has gone.
setInterval(() => {
  if (polling) refresh(false);
}, 4000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && polling) refresh(false);
});
