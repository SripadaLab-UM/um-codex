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

## 3. Design

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

## The proof

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
with full access to the Mac). That run is the GUI agent's, step 1 below,
with the maintainer present. What *was* checked live: the relay path with
the real key and an image (above).

## Open questions for the GUI test

1. Do the gates pass with no ChatGPT account: does the copy offer Computer
   Use, the in-app browser and Chrome (Plugins, Settings > Computer Use,
   `@` menu)? Which reason does it show if not?
2. Does Plugins > Computer Use > Install work with a custom provider and no
   sign-in? Where do the plugin ids show in `config.toml`?
3. The macOS permissions: which app is named in the prompts, and are they
   shared with the person's own ChatGPT copy (granted already there or not)?
4. A Computer Use turn on the Toolkit model (screenshot round trip) under
   "ask me before commands", then under "never": do the app prompts and
   node_repl's "Run JavaScript" prompt appear, or are they declined?
5. Chrome: does the extension pair with this copy without a ChatGPT account?
   Does the person's own app still control Chrome afterwards (the shared
   native host manifest)?
6. Does the seeded local project open selected, with no welcome flow?
7. "Only this folder": is a write outside the folder refused? Does the app
   show the config's defaults ("Custom (config.toml)"), and can the person
   change them per chat?
8. Relay restart: kill the launch process, see "Reconnecting…", Start again,
   and the same chat carries on.

## GUI test steps (for the maintainer's computer-use agent)

Preconditions: a test Mac account or the maintainer's, ChatGPT.app 26.928.x
installed, UM-Codex from this branch (`uv run um-codex ui` from the worktree)
with a **scratch data folder** (`UMCODEX_DATA_DIR=<scratch>`), a Toolkit key
saved, Chrome with the person's normal profile. The person's own ChatGPT app
may be open; don't use it except where a step says so. Grant macOS
permissions only when a step says so, and record exactly what each prompt
says.

Until the launcher form has the field (m7-one-click owns `ui/`), steps 2–5
are run against the new form when it lands; step 1 can run now with a
small script that does what the launch will do (`this_computer`:
`LocalRelay(credentials.api_key, toolkit.BASE_URL).start()`,
`local_config(...)` into `<scratch>/codex-app-local/codex-home/config.toml`
with a scratch folder, `seed_copy(...)`, `open_command(...)`, then
`wait_while_running(pid)` and `stop()`).

1. **Copy opens and a local chat answers.** Start the local copy. Expect: a
   second ChatGPT window, no sign-in screen, the scratch project selected,
   no welcome flow or model announcement. Type "Say hello and run `pwd`",
   Return. Expect an answer from the Toolkit model and the scratch folder's
   path; the chat has no "Remote ·" strip. Screenshot. Check `ps` shows the
   copy's `--user-data-dir` under `<scratch>/codex-app-local/`.
2. **Secondary choice and caution dialog.** In the launcher, new setup:
   "In the sandbox" is the selected, prominent choice; "On this computer" is
   under "More options" (or less prominent). Choose it. Expect the caution
   dialog with the exact text above, Cancel focused. Press Return: the
   setup stays "In the sandbox". Choose it again, click "Run on this
   computer": the form shows the folder, "What Codex can change", approvals
   and computer/browser control fields; read-only folders aren't offered.
3. **Card marker.** Save. The setup's card shows "On this computer"
   clearly; a sandbox setup's card doesn't.
4. **No re-ask.** Start the setup: no caution dialog; the copy opens (step 1
   expectations). Stop: the copy quits, the running list clears, and
   `<scratch>/codex-app-local/relay-token` is gone. Start again: still no
   dialog.
5. **Changing it back and forth.** Edit the setup to "In the sandbox"
   (no dialog), then to "On this computer" (dialog again).
6. **Feature availability** (question 1–2). In the local copy: open
   Plugins; note whether Computer Use, Browser and Chrome are listed,
   installed, or show a reason. Open `codex://settings/computer-use/google-chrome`
   and Settings > Computer Use; note what's there. Type `@` in a new chat and
   note the entries (Computer, Browser, Chrome). Save the copy's
   `config.toml` `[plugins]` section and the list of
   `<scratch>/codex-app-local/codex-home/computer-use/` and
   `.../plugins/` to the results.
7. **Computer Use** (only if offered). With the maintainer's OK: install
   the plugin if needed. Ask "Use Computer Use to open Calculator and
   compute 12×12". Record each prompt: the app's "Allow Codex to use
   Calculator?", node_repl's "Run JavaScript", and macOS's Screen Recording
   and Accessibility prompts (which app they name). Grant only for this test
   and note it. Expect 144 and screenshots in the transcript. Then System
   Settings > Privacy & Security > Screen Recording and Accessibility: list
   the entries for Codex Computer Use (one or two?).
8. **Approval policy** (question 4). Repeat 7 with the setup's approvals on
   "never": do the app and JavaScript prompts still appear, does it run
   without them, or does it fail?
9. **In-app browser.** Ask "@Browser open https://example.com and tell me
   the heading". Expect the in-app browser pane and the answer.
10. **Chrome** (question 5). Settings > Computer Use > Google Chrome >
    Install (the extension store page opens in Chrome). Stop here unless the
    maintainer wants the extension installed; if so, install it, ask
    "@Chrome open example.com and read its heading", record the site prompt.
    Then, in the person's own ChatGPT app, check Chrome control still works
    (or note it now points at UM-Codex's copy). Record the contents of
    `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.openai.codexextension.json`
    (its `path`) before and after.
11. **Only this folder** (question 7). Set "What Codex can change" to
    "Only this folder", Start. Ask Codex to create `hello.txt` in the
    project (works) and `~/Desktop/um-codex-outside.txt` (refused or asks).
    Note the permission picker's label in the chat.
12. **Relay restart** (question 8). With a chat open, kill the background
    `um-codex launch` process (Activity Monitor or `kill <pid>`). Send a
    message: expect "Reconnecting…". Start the setup again in the launcher:
    the copy comes forward, the message goes through in the same chat.
13. **Separation.** With a sandbox setup running in the M6 copy and this
    setup in the local copy: the M6 copy's local chats still answer only
    with the "use a Remote chat" reminder; the local copy has no
    `umcodex-*` hosts; the person's own app shows neither project.
14. **Cleanup.** Quit both copies (Stop), check no `um-codex` process or
    relay port is left, and note any permission grants made for the
    maintainer to remove if wanted.

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
