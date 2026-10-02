# Spike: M4, "On this computer" (Codex app on the Mac, with computer use)

Date: 2026-10-02. Branch `m4-this-computer` (from v0.1.0-alpha.3). Question:
can Codex's desktop app run directly on the person's Mac (not in the
container), with Computer Use and control of their own Chrome, on the U-M GPT
Toolkit through UM-Codex's relay, with the key still never in a file?

How it was checked:
- **Bundle:** the installed app, ChatGPT.app 26.928.40906 (bundle id
  `com.openai.codex`, bundled Codex CLI 0.159.2), read only: `app.asar`
  (main process `.vite/build/main-*.js`, the webview's `app-initial-*.js` and
  `app-shared-*.js`) extracted to a scratch folder, the bundled plugins in
  `Contents/Resources/plugins/openai-bundled/`, the Computer Use service in
  `Contents/Resources/cua_node/`. Nothing in the app was changed.
- **Docs:** learn.chatgpt.com (Computer Use, Browser extension, Built-in
  browser, Pricing / feature table, Sandboxing, Commands and deep links).
- **Source:** openai/codex (`codex-rs/config/src/guardian.rs`,
  `codex-rs/protocol/src/openai_models/guardian.rs`, turn metadata).
- **The bundled Codex:** `codex features list` and `codex debug models
  --bundled`, with a scratch `CODEX_HOME`.
- **One real Toolkit call through the relay** (the key read by the relay
  from the keychain, never printed): the model list and one Responses
  request with an image in a tool's output.
- **Not done:** the live run of a local-mode copy of the app (see "The
  proof"), no macOS permission granted, nothing clicked, the person's own app
  and `~/.codex` untouched.

Labels: **VERIFIED (docs)**, **VERIFIED (bundle)** (read in the code of
26.928.40906: how it's written to behave, not run; internals that can change
in any update), **VERIFIED (live)**, **UNSURE** (needs the GUI test).

## 1. How Computer Use, the in-app browser and Chrome control are switched on

All three are **bundled plugins** plus **desktop feature flags**. Each must
pass every one of these:

| | Computer Use | In-app browser (agent control) | Chrome (your own browser) |
|---|---|---|---|
| Plugin (`openai-bundled` marketplace) | `computer-use` (skill only) | `browser` | `chrome` |
| Remote flag (Statsig gate, evaluated in the app's window) | `1506311413` | `410262010`, plus the browser pane being available | `410065390` |
| Codex feature (`experimentalFeature/list` from the app-server) | `computer_use` | `browser_use` | `browser_use_external` |
| Requirements (`configRequirements/read`) | `allowBrowserAndComputerUse` not false | same | same |
| Platform | macOS (Windows needs an account beta setting) | any desktop | any desktop, not WSL |

- **VERIFIED (bundle):** the webview computes `computerUse`,
  `inAppBrowserUse` and `externalBrowserUse` from exactly these inputs
  (`app-shared`: the availability hooks return `available` only when the
  requirements allow it, the gate is on, the platform fits and the Codex
  feature is on; their failure reasons are `config-requirement-disabled`,
  `statsig-disabled`, `unsupported-platform`, `browser-pane-disabled`) and
  sends them to the main process (`electron-desktop-features-changed`). The
  main process uses them to install the bundled plugins and to add the
  `node_repl` MCP server to the app-server's config.
- **VERIFIED (bundle):** there's no local switch for the gates in a release
  build. `CODEX_ELECTRON_DESKTOP_FEATURE_OVERRIDES` exists but is read only
  in the Dev build flavor.
- **VERIFIED (bundle):** the Statsig client (`client-…` SDK key in the
  webview) is initialised with a stable ID even with no ChatGPT account. So a
  copy with a custom provider still evaluates the gates, as an anonymous user.
  **UNSURE: whether the three gates pass for an anonymous user.** This is the
  main question for the GUI test.
- **The Codex features** (`computer_use`, `browser_use`,
  `browser_use_external`, `in_app_browser`) are "stable" and on in the
  bundled 0.159.2 (VERIFIED, `codex features list`). An administrator turns
  them off in `requirements.toml` (`[features] computer_use = false`,
  VERIFIED docs). There is no per-copy requirements file on a Mac
  (`/etc/codex/requirements.toml` would also apply to the person's own
  Codex), so UM-Codex can't *enforce* them off for one copy.
- **Plugins are per CODEX_HOME.** Turning one off is
  `plugins.<id>.enabled = false` in that copy's `config.toml` (VERIFIED
  bundle: the app writes `keyPath: plugins.${pluginId}.enabled`). The app also
  reconciles the bundled plugins at start (installs missing ones; Computer Use
  only if the `computerUseAutoInstall` gate `741821319` is on and it isn't
  installed). **UNSURE:** the exact plugin ids (expected
  `computer-use@openai-bundled`, `chrome@openai-bundled`,
  `browser@openai-bundled`) and whether the reconcile turns a disabled one
  back on.
- **Plan, region, API key** (VERIFIED docs, feature table): for the
  "API Key" column, "Built-in browser previews and comments" is available;
  "Computer Use", "Computer Use in the browser" and "Use ChatGPT with Chrome"
  are "Limited*" in every column ("limited to only specific regions"); plugins
  are "Limited†" for API key ("Some first party plugins are not available").
  The Computer Use page says it's for "ChatGPT Work and Codex" in supported
  regions: Codex is what this copy runs. A custom provider (no sign-in at all)
  isn't mentioned anywhere. **UNSURE** in practice.

### What runs, and the tools the model sees

- **One MCP server for all three: `node_repl`** (VERIFIED bundle). The app
  adds `[mcp_servers.node_repl]` to the app-server's config: the bundled
  `cua_node/bin/node_repl` (a Rust binary running a Node kernel), with
  environment telling it which backends to load: `iab` (in-app browser),
  `chrome`, and for Computer Use `sky: "@oai/sky/service"`. The model gets a
  `js` tool (run JavaScript in a persistent REPL, `await
  nodeRepl.emitImage(...)` for images) plus `js_reset`; the plugins' skills
  teach it the APIs (`@oai/sky`: `list_apps`, `get_app_state` with a
  screenshot and the accessibility tree, `click`, `type_text`, `press_key`,
  `scroll`, `drag`, `set_value`, ...). A `cua_repl` server
  (`unified-computer-use` plugin) is shipped disabled.
- **Computer Use's service** is a separate signed app, **Codex Computer
  Use.app** (bundle id `com.openai.sky.CUAService`, executable
  `SkyComputerUseService`, Team ID `2DC432GLL2`, with helpers
  `SkyComputerUseClient.app` and `CUALockScreenGuardian.app`). The app copies
  it to **`$CODEX_HOME/computer-use/Codex Computer Use.app`** and runs it from
  there (VERIFIED bundle: `computer-use/Codex Computer Use.app`, and
  `SKY_CUA_SERVICE_PATH` passed to node_repl).
- **Chrome control** uses the ChatGPT extension (Chrome Web Store id
  `hehggadaopoacecdllhhajmbjkdcmajg`; Edge, Brave, Opera, Vivaldi too) and a
  native messaging host, `com.openai.codexextension`, whose binary ("ChatGPT
  for Chrome") is in the installed `chrome` plugin. The plugin's install
  script **writes the host manifest for the whole macOS user**, in
  `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/` (and
  Chromium's and Chrome for Testing's), pointing at *that copy's* plugin
  folder (VERIFIED bundle, `chrome/scripts/installManifest.mjs`). So the
  person's own app and a UM-Codex copy that both install the Chrome plugin
  overwrite each other's manifest. **UNSURE** what that breaks (the
  extension host finds app instances through sockets, by extension instance
  id), and uninstalling UM-Codex would leave the manifest pointing at a
  removed folder until the person's own app reinstalls it.
- **Approvals of their own** (VERIFIED docs): Computer Use asks before each
  new app ("Allow Codex to use Calculator? Always allow / Cancel / Allow");
  Chrome asks before each new website (once, this site, all sites, decline);
  sensitive actions ask again. These are separate from Codex's approval
  policy. node_repl asks for each `js` run through an MCP elicitation ("Run
  JavaScript"). **UNSURE:** with `approval_policy = "never"` Codex declines
  MCP elicitations without asking (M2b found this for MCP tools), which may
  break or bypass these prompts. Test both policies.
- **"Approve for me" (auto-review)** sends the reviews to a reviewer model
  (VERIFIED source, `guardian.rs`; models with
  `node_repl_auto_review_required`, which are the gpt-6-* entries in the
  bundled catalog, require it for Computer Use under that mode). The Toolkit
  has no `codex-auto-review` model (VERIFIED live, the model list), so the
  local copy should keep the person as the reviewer.

### The model side

- **Image inputs through the relay work.** VERIFIED (live, 2026-10-02): one
  Responses request to `gpt-5.6-terra` through the relay to the Toolkit, with
  a 64×64 red PNG inside a `function_call_output` (the shape Codex sends a
  tool's screenshot in), answered "Red" (HTTP 200). The Toolkit lists 46
  models, among them `gpt-5.5`, `gpt-5.6-luna/terra/sol`, `gpt-6-luna`,
  `gpt-6-sol`, `gpt-6.1-sol` and `gpt-6-astra` (the docs' choice for visual
  Computer Use tasks).
- Every model in the bundled catalog has `input_modalities = ["text",
  "image"]` and `node_repl_disabled = false` (VERIFIED, `debug models
  --bundled`); Codex sends `node_repl_disabled` and
  `node_repl_auto_review_required` to node_repl in each turn's metadata.
  UM-Codex's catalog copies these entries, so they're kept. A Toolkit model
  with no catalog entry gets Codex's fallback metadata: **UNSURE** whether
  node_repl then runs.
- `NODE_REPL_ENFORCE_MODEL_CHECK` (gate `337408568`) makes node_repl check
  the turn's model metadata; with the catalog entries above it should pass.

## 2. macOS permissions

- **Computer Use: Screen Recording and Accessibility, for "Codex Computer
  Use"** (VERIFIED docs: "check Screen Recording and Accessibility for Codex
  Computer Use"; the service app above is the process that needs them). Not
  ChatGPT.app itself.
- **Automation (Apple Events):** the service declares
  `NSAppleEventsUsageDescription` (for the Messages plugin). Not needed for
  Computer Use itself, as far as the docs say.
- **Chrome control:** no macOS permission. The extension's own permissions
  in Chrome (it asks to "Access the page debugger"), and the per-site prompts.
- **In-app browser:** none.
- **A second copy:** each CODEX_HOME gets its own copy of the service app at
  a different path, with the same bundle id and signature. macOS keys
  privacy grants for a signed app by bundle id and its code requirement, so
  **probably shared** with the person's own copy (granted once for both).
  **UNSURE:** macOS sometimes lists such copies separately, or asks again
  for a new path. The GUI test checks it. Either way, these grants are the
  person's own decision in System Settings; UM-Codex never grants or edits
  them.

## 3. Design (the spike's, before the build)

Maintainer's requirement (2026-10-02): **"On this computer" is the secondary
option.** The sandbox stays the default and the prominent choice.

### The setup

- **Where Codex runs:** "In the sandbox" (default, prominent) or, under
  "More options" (or as a less prominent choice), "On this computer".
- **Choosing "On this computer" opens a caution dialog**, the one deliberate
  exception to the fewer-pop-ups rule:

  > Codex will run on your Mac, not in the sandbox. It can read, change and
  > delete any of your files, use your apps and browser, and act with your
  > accounts. Use it only when you need computer or browser control.

  Two buttons: **Cancel** (default focus; Return or Esc keeps the sandbox)
  and **Run on this computer**. Choosing it saves `runs_on = "this-computer"`
  with the setup.
- **The setup's card carries a clear "On this computer" marker** (a label or
  badge on the card and in the running list, not colour alone).
- **Starting it doesn't ask again.** The dialog appears only when the choice
  is made (or changed back to it), never at each Start.
- For an "On this computer" setup the form asks:
  - **Folders:** the working folder (and more write folders) become the
    copy's project (`local-projects`, one project with several root paths
    when there are several) and are trusted in its `config.toml`. Read-only
    folders don't exist here; the form says so instead of offering them.
  - **What Codex can change:** "Anything I can (full access)" (default) or
    "Only this folder" (Codex's own macOS sandbox, Seatbelt:
    `sandbox_mode = "workspace-write"`, with network on or off from the
    setup's internet choice). The form says plainly that "only this folder"
    covers Codex's commands and file edits, **not** Computer Use or Chrome:
    those act through your apps, which can change anything you can.
  - **Approvals:** "Ask me before commands" by default here (not "never" as in
    the sandbox), so the app's own app and website prompts aren't turned
    down (the open question above). "Approve for me" isn't offered (no
    reviewer model on the Toolkit).
  - **Computer and browser control:** on or off (default on, since it's the
    reason to pick this mode). Off writes `plugins.<id>.enabled = false` for
    `computer-use`, `chrome` and `browser` in the copy's config at each
    start (a default the person could change in the app, not enforced).
  - **Model:** the setup's; the summary suggests `gpt-6-astra` for visual
    tasks (docs) and avoids models with no catalog entry.
- **The summary** repeats the warning in one line ("Runs on this computer:
  Codex can do anything you can do on this Mac.") and lists the macOS
  permissions Computer Use will ask for, and that they're granted to "Codex
  Computer Use".

### The app copy

- **A separate copy from the sandbox copy:** `<data>/codex-app-local/`
  (`codex-home/`, `user-data/`, `relay-port`, `relay-token`, `models.json`),
  opened as M6 opens its copy (`open -n --env CODEX_HOME=… --env
  CODEX_ELECTRON_USER_DATA_PATH=… <app> --args --user-data-dir=…`). The
  sandbox copy (`<data>/codex-app/`) keeps blocking local chats; the local
  copy has no ssh hosts. Local and sandbox chats never share a window, a
  history or a state file. Two app icons in the Dock, besides the person's
  own app: the launcher says which is which ("UM-Codex · this computer").
- **Its config.toml** (`this_computer.local_config`): provider `toolkit` at
  `http://127.0.0.1:<port>/relay/v1` with `auth = { command = "/bin/cat",
  args = [<relay-token>], refresh_interval_ms = 300000 }` and no
  `requires_openai_auth` (so no sign-in, as M6 found), `forced_login_method =
  "api"`, analytics, feedback and update checks off, the setup's model, the
  bundled catalog (`model_catalog_json`, no upgrade offers), the access and
  approval defaults, the folders trusted. The app's other settings are kept.
- **Seeded before it opens** (`this_computer.seed_copy`), as M6: a local
  project for the folder, selected and first in the sidebar; the welcome flow
  and the model announcements marked seen. Shapes from the app's schema
  (`local-projects` entries `{id, name, rootPaths, createdAt, updatedAt}`,
  `selected-project = {type: "local", projectId}`). **UNSURE** (GUI): the
  app also has an "app-server projects" migration
  (`app-server-projects-migration-by-host`) that may move local projects.
- **The relay** — recommendation: **the launch process, held while the copy
  runs** (as M6's `AppHold`). The launcher's Start runs `um-codex launch
  --setup <id>` in the background (its own session, no window); it starts
  `LocalRelay` on the port fixed per data folder, writes the token file
  (0600), writes the config, seeds, opens the copy, then waits for the
  copy's main process to end (`wait_while_running`), and then stops the
  relay and deletes the token. Stop in the launcher quits the copy (by PID)
  and so ends the launch. Why this one:
  - no always-on helper (no launchd agent, nothing running and holding the
    key when the copy is closed);
  - the launcher server (`um-codex ui`) isn't always running: the person
    closes its tab, and its process is a page server, not something a chat
    should depend on;
  - it's the M6 pattern, with its lock, log and running list.

  If the launch process dies while the copy is open, chats show
  "Reconnecting…"; Start again finds the copy open, brings it forward and
  starts the relay again with the same token (`keep_token=True`), so the
  open chats carry on. Opening ChatGPT from the Dock opens the person's own
  app, never this copy, so the copy can't run without UM-Codex.
- **The key:** still only in the keychain and read only by the relay; never
  in the copy's files, `auth.json` or an environment variable. The token
  works only through this relay, only while it runs. Two plain limits to
  write down:
  - any program running as the person can read the token file and use the
    Toolkit through the relay while the copy is open (as with any app the
    person runs, and their own `~/.codex/auth.json` if they had one);
  - with full access, Codex runs as the person, so it can ask the keychain
    for UM-Codex's item the same way UM-Codex does (the `keyring` item
    trusts the program that saved it). **UNSURE** whether macOS asks first.
    The sandbox mode doesn't have this exposure; this mode can't remove it.
- **Windows:** not in this round (the M6 Windows limits apply, and Computer
  Use on Windows has its own rules).

### The terminal variant

- `um-codex` in a terminal with an "On this computer" setup runs a **native
  `codex` pinned and installed by UM-Codex** in its program folder (the
  release's binary from openai/codex's GitHub release, checked against a
  pinned SHA-256; not the `codex` on PATH), with `CODEX_HOME =
  <data>/codex-local/<setup>` and the same relay hold (held while `codex`
  runs, as a sandbox launch holds it). No Computer Use or in-app browser:
  those are desktop-app gates and plugins (the 2026-10-01 check of the terminal Codex
  in the container found no such tools). Browser control in the terminal is
  DESIGN's plan: Playwright's MCP server connected to the person's Chrome
  through its extension, each action asking. Docker becomes optional for
  people who use only this mode.

## The spike's proof

Added `src/umcodex/this_computer.py` (new module; nothing in `ui/` or the
M6 code changed): the copy's paths and `open -n` command, `local_config`,
`seeded_state`/`seed_copy`, the fixed relay port, `LocalRelay` (a
`RelayServer` on that port, the token file 0600, kept across a relay
restart), and `wait_while_running`. `tests/test_this_computer.py` checks
them with a stand-in key and a mock upstream: the config's provider, auth
command and defaults, the folder-only mode, the seeded project, the port
kept, the relay refusing a missing token, swapping in the key and removing
the token file.

**The live run was not done.** Opening a local-mode copy of the app on this
Mac (scratch data folder, stub upstream, stand-in key) was refused by this
session's permission check as "creating an unsafe agent" (a Codex app copy
with full access to the Mac). That run is the GUI round's (part F below),
with the maintainer present. What *was* checked live: the relay path with
the real key and an image (above).

## 4. Design, as built (2026-10-02)

The spike's design was built on this branch after M7 merged; DESIGN.md M4
is the reference (the choice behind the caution dialog, the card marker,
the separate copy in `<data>/codex-app-local/`, its config and seeded state,
the relay held by the launch, Stop, uninstall). Changes from the spike:

- The caution dialog also says Codex "may also be able to reach UM-Codex's
  own Toolkit key" while it runs (the keychain limit found above).
- `approvals_reviewer = "user"` in the copy's config (no "Approve for me").
- After the review of #22:
  - **the copy never outlives its relay**: however the hold ends (Ctrl-C,
    SIGTERM, SIGHUP, an error, the port taken), the copy is quit (asked,
    then SIGTERM, then SIGKILL);
  - **`auth.command` is `um-codex local-token`**, which gives the token only
    when what listens on the port is this person's relay process (`lsof`:
    PID from `relay-pid`, uid, 127.0.0.1), not `/bin/cat <file>`;
  - `SO_REUSEADDR` on the relay's socket; the folder made 0700 every time;
    a data-folder lock so two Starts can't race;
  - "Only this setup's folders" sets `writable_roots` to every folder of
    the setup and has its own Internet switch;
  - full access with "never" is refused (API and launch);
  - Stop finds the copy by its profile folder, whatever PID was noted;
  - uninstall always removes the copy's programs (`computer-use`,
    `plugins`), its relay files and Chrome's manifest leading into it, but
    keeps its settings and chats with `--keep-data`; it points the person
    at System Settings for the privacy grants (no `tccutil reset`).
- **The terminal variant is left for later:** a native `codex` pinned and
  installed by UM-Codex needs a pinned download (GitHub release asset and
  SHA-256), its update path and tests; not small. On this computer is
  Codex-app only for now.

## Open questions for the GUI round

1. Do the gates pass with no ChatGPT account: does the local copy offer
   Computer Use, the in-app browser and Chrome (Plugins, Settings >
   Computer Use, the `@` menu)? Which reason does it show if not?
2. Does Plugins > Computer Use > Install work with a custom provider and no
   sign-in? Which plugin ids does `config.toml` get (expected
   `computer-use@openai-bundled`, `browser@…`, `chrome@…`), and does the
   control switch (off) hide them?
3. The macOS permission prompts: which app do they name, and are the grants
   shared with the person's own ChatGPT copy?
4. A Computer Use turn on the Toolkit model, with "Ask before commands" on,
   then off ("never"): do the app's own prompts and node_repl's "Run
   JavaScript" prompt appear, or are they declined?
5. Chrome: does the extension pair with this copy with no ChatGPT account?
   Does the person's own app still control Chrome afterwards (the shared
   native host manifest)?
6. Does the seeded local project open selected, with no welcome flow and
   no model announcement?
7. "Only this setup's folders": is a write outside refused, and how does
   the app label the permissions?
8. Does Stop's quit ask the person first (the app's own quit confirmation)?

## The GUI round: M7 and M4 together (for the maintainer's computer-use agent)

**Preconditions.** A Mac with ChatGPT.app 26.928.x and Docker Desktop.
UM-Codex from `main` with this branch merged (or this branch), run from
the worktree: `UMCODEX_DATA_DIR=<scratch> uv run um-codex ui`, so the
installed UM-Codex and its data are untouched. A Toolkit key saved for that
scratch data folder (the real one, in the keychain, entered by the
maintainer). The person's own ChatGPT app may be open; never use it except
where a step says so. Grant macOS permissions only where a step says so,
and record each prompt's exact words. Screenshot each "Expect".

**A. First run (M7).**
1. Open the launcher page. Expect: the first-run page, "Choose a folder and
   start…" with its lines under it (Codex app or Terminal; changes and
   deletes, no undo; the internet on), the quiet strip (Docker running ·
   Toolkit key saved).
2. Click "Choose a folder and start…", pick a scratch folder `demo` in the
   native picker. Expect: no form, no pop-up; a card "demo", Starting… →
   Opening Codex… → Connected ✓; UM-Codex's sandbox copy of the app opens
   on the project "demo", Remote · `umcodex-demo-…`, with no sign-in or
   welcome flow.
3. In that chat: "List the files here and create hello.txt saying hi".
   Expect: `hello.txt` in `demo` in Finder.

**B. Returning (M7).**
4. Stop on the card (its question; Cancel focused, confirm). Expect: the app
   shows it can't reconnect; the card idle.
5. Reload the page. Expect: "Start “demo”" at the top. Click it once.
   Expect: connected again (about 10–30 s), no question.
6. "Choose another folder…" with a second folder: a second card, started
   at once. Stop both.

**C. Update (M7).**
7. Click "Check for updates". Expect "UM-Codex X is the newest version."
   (or, if a newer release exists, the Update line). With a setup running,
   Update is refused with "Stop running setups first: “demo”." Don't
   install an update in this round unless the maintainer says so.

**D. The sandbox Codex app (M6), still right after M4.**
8. Start "demo". In UM-Codex's sandbox copy, start a local (not Remote)
   chat: expect only the reminder to use Remote · `umcodex-demo-…`. Stop.

**E. On this computer (M4): the choice and the caution dialog.**
9. "New setup with options…" (or Edit on a new scratch setup `here` with
   folder `here`). In **More options**, expect "Where Codex runs" with "In
   the sandbox (recommended)" selected and "On this computer" below it.
   Nothing else on the form mentions it.
10. Choose "On this computer". Expect the dialog "Run Codex on this
    computer?" with the text: Codex will run on your Mac, not in the
    sandbox… delete any of your files, use your apps and browser, and act
    with your accounts… may also be able to reach UM-Codex's own Toolkit
    key… Use it only when you need computer or browser control. Buttons
    Cancel (focused) and "Run on this computer".
11. Press Return. Expect: the dialog closes and "In the sandbox" is still
    selected. Choose "On this computer" again; press Esc: same.
12. Choose it again and click "Run on this computer". Expect: the Access
    section shows the red line "On this computer: …", "What Codex can
    change" (Anything I can (full access) selected; Only this setup's
    folders) with the note that it doesn't limit computer and browser
    control, "Computer and browser control" on; no Browser tool switch;
    under full access, the line "Internet: everything this Mac can reach";
    "Ask before commands" on (its help says it's needed with full access);
    Open in shows UM-Codex's
    local Codex window; added folders are Read & write, with no Read only
    button. If a read-only folder was there before, it's now Read & write
    with a note.
13. Save. Expect: the card shows the "On this computer" badge and a red
    edge, and its facts: "On this computer: Codex runs on your Mac…",
    "Codex can change and delete any of your files…", "Computer and
    browser control on…", "UM-Codex's local Codex window · model · asks
    before commands". The "demo" card has no badge.
14. Edit "here", switch to "In the sandbox" (no dialog), Save, then back to
    "On this computer" (the dialog again), Save.
14a. Edit "here": turn "Ask before commands" off and Save. Expect it
    refused under the switch ("On this computer with full access, Codex
    must ask before commands…"). Turn it back on.

**F. On this computer: starting, the window, Stop.**
15. Start "here". Expect: no dialog, no Docker needed (it works with Docker
    Desktop quit, too: try it once); the card says "Running on this
    computer, in UM-Codex's local Codex window…"; a ChatGPT window opens
    that is neither the person's own nor the sandbox copy (`ps` shows
    `--user-data-dir=<scratch>/codex-app-local/user-data`), with no
    sign-in, the project "here" selected, no welcome flow, no model
    announcement (question 6).
16. In a new chat: "Say hello and run pwd". Expect an answer from the
    Toolkit model and the folder `here`; no "Remote ·" strip. Ask it to
    create `hi.txt`: with "Ask before commands" on, the app asks first.
17. Check `<scratch>/codex-app-local` is 0700, `relay-token` is 0600 and
    contains no `sk-` key, `relay-pid` names the background `um-codex
    launch` process; `codex-home/config.toml` has the `toolkit` provider at
    127.0.0.1 with `auth.command` = UM-Codex's `local-token`, and no key.
    In a terminal, `UMCODEX_DATA_DIR=<scratch> uv run um-codex local-token`
    prints a token (don't paste it anywhere).
18. Start "demo" (sandbox) at the same time: both run; the sandbox copy and
    the local copy are separate windows; the local copy has no `umcodex-*`
    hosts; the sandbox copy has no "here" project.
19. Stop "here" in the launcher. Expect: the local window quits (note if
    the app asks to confirm, question 8), the card goes idle, `relay-token`
    is gone. Start it again: the window reopens on "here".
20. Quit the local window yourself (Cmd-Q). Expect: the card goes idle
    within a few seconds.
20a. Start "here"; then end its background launch process (`kill <pid>`
    of the `um-codex launch --setup … --open local` process, SIGTERM).
    Expect: the local window quits within ~10 s, `relay-token` and
    `relay-pid` are gone, the card goes idle. The copy is never left open
    without its relay.

**G. On this computer: computer and browser control.**
21. With "here" running: open Plugins, Settings > Computer Use, and type
    `@` in a new chat. Record what's offered (Computer Use, Browser,
    Chrome) and any reason shown (questions 1–2). Save `codex-home/config.toml`'s
    `[plugins]` part and the lists of `codex-home/computer-use/` and
    `codex-home/plugins/`.
22. Only if offered, and with the maintainer's OK: "Use Computer Use to
    open Calculator and compute 12×12". Record each prompt in order: the
    app's "Allow Codex to use Calculator?", node_repl's "Run JavaScript",
    macOS's Screen Recording and Accessibility prompts (which app they
    name). Grant for this test only. Expect 144, and screenshots in the
    chat. Then System Settings > Privacy & Security > Screen Recording and
    Accessibility: list the "Codex Computer Use" entries (question 3).
23. (Changed after the round: with computer and browser control on,
    "Ask before commands" can't be turned off; see R4.)
24. "@Browser open https://example.com and tell me the heading": the
    app's own browser pane and the answer.
25. (Changed after the round: Chrome control is off in the local copy and
    not offered; see R1.)
26. Edit "here": "Computer and browser control" off, Stop and Start.
    Expect: Computer Use, Browser and Chrome not offered (or disabled) in
    the local window; `config.toml` has them `enabled = false`.
27. Edit "here": add a second folder `here2` (Read & write), "Only this
    setup's folders", "Internet for Codex's commands" off, "Ask before
    commands" on; Start. Expect `writable_roots` with both folders in
    `config.toml`. Ask Codex to write `here/inside.txt` and
    `here2/inside.txt` (both work), and `~/Desktop/um-codex-outside.txt`
    (refused or asks), and to run `curl -sI https://example.com` (fails or
    asks). Record the permission label in the chat (question 7). The card
    and summary say "Internet for Codex's commands: off".

**H. Cleanup.**
28. Stop everything. With the local window open, `um-codex uninstall`
    (against the scratch data folder) refuses ("Quit it first"). Quit it;
    run `UMCODEX_DATA_DIR=<scratch> uv run um-codex uninstall --keep-data`
    only if the maintainer wants the uninstall checked (it removes the
    Toolkit key from the keychain too: answer accordingly). Expect:
    "Removing the programs in UM-Codex's local Codex window…" and the line
    about removing "Codex Computer Use" in System Settings yourself;
    `codex-home/computer-use`, `codex-home/plugins`, `relay-token` gone;
    the copy's `config.toml` and chats kept; a Chrome manifest leading into
    the copy removed, one of the person's own app left; no privacy grant
    changed. With `--delete-data` instead, all of `codex-app-local` goes.
29. List any macOS permissions granted during the round for the maintainer
    to remove if wanted.


## The GUI round's results (at b61b17f) and the re-test

Passed: the first run and returning flows; the caution dialog (Cancel
default; Return and Esc keep the sandbox); the local copy with no sign-in;
the token and relay checks; the two copies kept apart; Stop, Cmd-Q and
SIGTERM closing the copy; folders-only mode with `writable_roots`;
**Computer Use through the Toolkit with no account** (Calculator 12×12 =
144 after "Allow this conversation"); **the in-app browser** (after "Allow
once").

Fixed since (see DESIGN M4 and M6):
1. Chrome, in both copies (the sandbox copy took it too: the maintainer's
   manifest led into the video agent's `UM-Codex-demo/codex-app`): the
   `chrome` plugin is off in config.toml (not enough by itself: the app's
   reconcile writes the manifest for an installed plugin even when it's
   disabled); the person's manifest is remembered before a copy opens, put
   back at each poll of the launch and when it ends (and at uninstall,
   from either copy's backup); the copies' entries leave the shared
   registry. Windows: the manifest there always points at the app package,
   so only the registry entries are cleaned.
2. Stop on this computer has its own question.
3. "Ask before commands" really asks: Codex's untrusted behaviour, through
   the projects' trust level (config's `approval_policy = "untrusted"` is
   refused since 0.157.1).
4. "Never" isn't allowed with computer and browser control (or full
   access): the switch stays on with the reason; API and launch refuse it.
5. Control off also turns off `unified-computer-use`, `record-and-replay`
   and `computer-history`.
6. Every Codex-app setup is seeded into the sandbox copy; a copy that's open
   but doesn't know a new setup is reopened when no other launch uses it.
7. "here 2": the page's quick start now ignores a second click while one
   runs (the server's picker already allowed one at a time); the duplicate
   was most likely the automation (Duplicate, then Delete).

**The re-test** (R1–R6, with the safe step to give the person's Chrome link
back first) is in `docs/spikes/2026-10-02-retest.md`, ready to hand to the
tester. Since its first version: "ours" is the whole data folder in the
Chrome restore (so the two copies never take each other's link for the
person's), stale and failed backups are handled, "Ask before commands" is
worded honestly (the app's own permission choice in a chat wins; R3 checks
that), and the reopen never force-quits the window.

## Sources

- Docs: [Computer Use](https://learn.chatgpt.com/docs/computer-use),
  [Browser extension](https://learn.chatgpt.com/docs/chrome-extension),
  [Built-in browser](https://learn.chatgpt.com/docs/browser),
  [Pricing / feature availability](https://learn.chatgpt.com/docs/pricing),
  [Sandboxing](https://learn.chatgpt.com/docs/sandboxing),
  [Commands and deep links](https://learn.chatgpt.com/docs/reference/commands).
- Source: openai/codex `codex-rs/config/src/guardian.rs`,
  `codex-rs/protocol/src/openai_models/guardian.rs`,
  `codex-rs/core/src/turn_metadata.rs`.
- Bundle: ChatGPT.app 26.928.40906, read only.
- Earlier: `2026-10-01-codex-desktop-app.md` §5, DESIGN.md M4 and M6.
