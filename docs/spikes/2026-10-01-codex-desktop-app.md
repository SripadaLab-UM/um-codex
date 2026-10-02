# Spike: the Codex desktop app as UM-Codex's front end

Date: 2026-10-01. Not committed. Question: can the Codex desktop app be the
front end, with Codex's work done in UM-Codex's container (and later "On this
computer")?

How it was checked:
- **Docs:** developers.openai.com/codex, which now redirects to
  learn.chatgpt.com/docs.
- **GitHub:** openai/codex issues.
- **This Mac:** the installed app's `Info.plist`, plus a read of its
  `app.asar` JavaScript (main process and webview), extracted to the session
  scratchpad, not to this repo.
- **The bundled CLI:** `codex app-server --help` only.
- **Not done:** no install, no login, nothing launched. `~/.codex/auth.json`
  wasn't read. Only the key names of `config.toml` and
  `.codex-global-state.json` were listed.

Labels:
- **VERIFIED (docs):** read in the official docs today.
- **VERIFIED (bundle):** read in the code of the installed app, version
  26.928.21956. This is how that version is written to behave, and it hasn't
  been run. These are internals, so they can change in any update.
- **REPORTED:** from GitHub issues or third parties.
- **UNSURE:** not settled; needs a hands-on test.

## 1. What the app is now

- **The app is "ChatGPT".** VERIFIED (docs, changelog 2026-07-09, 26.707):
  "Codex is now part of the ChatGPT desktop app on macOS and Windows." The
  docs call it "the ChatGPT desktop app (also called Codex)". Inside, you
  pick ChatGPT (Chat / Work) or Codex. There's no separate Codex app any
  more. The `codex://` URL scheme is kept.
- **`/Applications/ChatGPT.app` here *is* the Codex app.** VERIFIED (bundle):
  - `CFBundleIdentifier = com.openai.codex`, `CFBundleAlternateNames = (Codex)`;
  - `CFBundleShortVersionString = 26.928.21956`, build 12404;
  - `LSMinimumSystemVersion = 13.0`;
  - an arm64 Electron build (`owl` runtime), updated by Sparkle.
- **It bundles its own Codex CLI.** VERIFIED (bundle):
  `Contents/Resources/codex-cli/bin/codex` is 0.159.2. It also bundles the
  Computer Use client, the `cua_node` runtime and the bundled plugins
  (browser, chrome, computer-use, ...).
  - The terminal `codex` on PATH here is a different copy:
    `~/.local/bin/codex`, 0.139.0.
  - The newest CLI is 0.160.0 (changelog, 2026-10-01).
- **Platforms:** VERIFIED (docs): macOS (Apple Silicon; Intel support was
  added in 2026), Windows and Linux.
  - Windows: from the Microsoft Store, or
    `winget install --id 9PLM9XGG6VKS -s msstore`.
  - The Windows app runs agents natively (PowerShell plus the Windows
    sandbox) or in WSL2.
- **Versions are dates:** 26.MDD; 26.928 is 2026-09-28.

## 2. Signing in without a ChatGPT account

- **API key sign-in:** VERIFIED (docs, Authentication). The desktop app
  supports "Sign in another way" with an OpenAI API key, for local work. This
  means an OpenAI Platform key. A Toolkit key isn't one.
- **The app reads `~/.codex/config.toml`:** VERIFIED (docs, "Connect to a
  gateway"):
  - Docs: "The macOS app reads the same ~/.codex/config.toml"; on Windows,
    `%USERPROFILE%\.codex\config.toml`; "restart the app".
  - Custom providers (`model_provider`, `[model_providers.<id>] base_url`,
    `env_key`, or `env_http_headers`) are the documented gateway path.
  - The env var must be in the **app process's** environment. A Dock launch
    doesn't get the shell's variables, so OpenRouter's guide uses
    `launchctl setenv`.
  - Alternative: `[model_providers.<id>.auth] command = ...`, a token helper
    with `timeout_ms` and `refresh_interval_ms`. VERIFIED (docs); the
    `ModelProviderAuthInfo{command,args,timeout_ms,refresh_interval_ms,cwd}`
    struct is in the codex binaries here.
- **The app honors `CODEX_HOME`:** VERIFIED (bundle):
  - Its state file is `$CODEX_HOME/.codex-global-state.json`.
  - `CODEX_ELECTRON_USER_DATA_PATH` gives it a separate Electron profile and
    turns off the single-instance lock.
  - Precedent: the app's own "Codex Demo" launcher runs
    `open -n --env CODEX_HOME=… --env CODEX_ELECTRON_USER_DATA_PATH=… ChatGPT.app --args --user-data-dir=…`,
    a second, isolated instance.
  - These env vars are internal and undocumented.
- **Does a custom provider skip the login screen?** VERIFIED (bundle),
  untested:
  - The webview's router shows the login screen only when
    `authMethod == null && requiresAuth`.
  - `requiresAuth` is the app-server's `requiresOpenaiAuth` (defaulting to
    true when missing).
  - A custom provider without `requires_openai_auth = true` reports `false`.
    The app then treats the host as `apikey` / `execution-storage` and
    routes to the app, not the login screen.
  - So a config whose active provider is the Toolkit should open with no
    ChatGPT or API-key sign-in.
  - REPORTED, against this: OpenRouter's guide still tells people to sign in
    first. Community patches exist mainly to keep ChatGPT login and a custom
    provider together.
  - **Hands-on test needed.**
- **Custom provider rough edges:** REPORTED.
  - [#29156](https://github.com/openai/codex/issues/29156): no
    provider-aware model picker; switching providers or `CODEX_HOME` hides
    old chats.
  - [#33029](https://github.com/openai/codex/issues/33029): the app still
    calls chatgpt.com/backend-api (wham) metadata endpoints, and they can
    slow it down.
  - [#30994](https://github.com/openai/codex/issues/30994):
    `model_catalog_json` replaces the whole catalog.
  - [#24457](https://github.com/openai/codex/issues/24457), closed: local
    and remote provider credentials were mixed in an older version.
  - OpenRouter's guide: provider and model are "only honored in the
    user-level `~/.codex/config.toml`".
- **Hosted features need ChatGPT.** VERIFIED (docs, feature table, API-key
  column): Codex cloud, connectors, mobile remote control, voice, Sites and
  plugin sharing need ChatGPT. Some first-party plugins aren't available
  with an API key.

## 3. Remote connections

### 3a. SSH, which is what we'd use

- **Status:**
  - VERIFIED (docs, changelog): announced at 26.415 as "rolling out SSH
    remote connections in alpha".
  - The docs no longer say alpha. The feature table lists "SSH remote
    connections" as Available for every plan **and for API key**.
  - The docs' earlier note that it needs `[features] remote_control = true`
    isn't in today's page or in the bundle's SSH code path.
- **Discovery:** VERIFIED (docs and bundle).
  - The app parses **`~/.ssh/config`** (fixed path: `homedir/.ssh/config`,
    on Windows too) and follows **`Include`** directives.
  - Globs work, and relative paths are resolved from `~/.ssh`.
  - **Only top-level `Include` lines are followed.** An Include inside a
    `Host`/`Match` block isn't, and in OpenSSH an Include after a `Host` line
    belongs to that block anyway. So our `Include` must go at the top of
    `~/.ssh/config`.
  - Correction (2026-10-02, the bundle of app 26.928): "top-level" is per
    file. The discovery walks each included file the same way, so a
    top-level `Include` inside an included file is followed too (globs
    included; each file once). UM-Codex still writes one plain file.
  - It takes the first concrete alias of each `Host` line and skips pattern
    hosts, `colima`, and anything resolving to `github.com`.
  - Each alias is resolved with `ssh -G -F ~/.ssh/config <alias>` (HostName,
    Port, IdentityFile).
- **Hosts start disabled.** VERIFIED (bundle and docs).
  - Discovered hosts start with `autoConnect: false`. The person turns one on
    in Settings > Connections > SSH, or adds it manually (Host / Port /
    Identity, a "codex-managed" entry).
  - The app saves this in `$CODEX_HOME/.codex-global-state.json`
    (`codex-managed-remote-connections`,
    `remote-connection-auto-connect-by-host-id`). The host ID comes from the
    alias, so a **stable alias keeps the toggle and the history**.
- **A deep link can add and connect a host:**
  - VERIFIED (docs): `codex://settings/connections/ssh/add?name=<alias>`
    adds the alias "and disables automatic connection".
  - VERIFIED (bundle), undocumented: the same link also takes
    `projectPath=<remote folder>` and `enabled=true`. With them, the app adds
    the host, turns auto-connect on, connects, creates (or reuses) a remote
    project for that folder, and opens a new chat on it.
  - That's exactly our "launch → the app opens on /work" step, but it's
    undocumented.
  - Seeding the global-state JSON instead is REPORTED unreliable: the app
    overwrites it ([#21554](https://github.com/openai/codex/issues/21554),
    open, which asks for a supported API).
- **What runs on the remote:** VERIFIED (bundle, the `ssh_websocket_v0`
  transport).
  1. Every command is `ssh -v -o BatchMode=yes -o ConnectTimeout=… -o ServerAliveInterval=15 -o ServerAliveCountMax=12 <alias> 'sh -c …'`.
     The app adds no other options, so everything else (Port, IdentityFile,
     ProxyCommand, known hosts, ForwardAgent) comes from the ssh config.
     `BatchMode=yes` means there's never a password or host-key prompt.
  2. The payload re-executes `$SHELL -l -i -c` (bash, zsh, fish, csh and nu
     handled). It fails if `$SHELL` isn't an executable login shell.
  3. It prepends `${CODEX_INSTALL_DIR:-$HOME/.local/bin}` to PATH and sets
     `CODEX_HOME=${CODEX_HOME:-$HOME/.codex}` after the login shell's
     profile has run.
  4. Probe: `command -v codex`. When it's missing, the app offers to install
     Codex with the official installer script. The local `CODEX_CLI_PATH`
     can rename the command (a bare name only).
  5. Probe: `codex --version`. **Minimum 0.141.0** in this build. Our image
     pins 0.157.1, so that's fine.
  6. Start: `mkdir -p $CODEX_HOME/app-server-control`, `pkill -9` any old
     desktop proxy, link the forwarded agent socket (or `rm -f` it), then
     `nohup codex -c features.code_mode_host=true app-server --listen unix:// &`,
     logging to `$CODEX_HOME/app-server-control/app-server.log`.
     `CODEX_SSH_SKIP_APP_SERVER_BOOT=true` on the remote skips this start.
  7. Connect: `ssh -T … <alias> '… exec codex app-server proxy'`. That's
     stdio to the unix socket, and the app speaks WebSocket JSON-RPC over
     that ssh pipe. It reconnects automatically.
  8. Extras, all over the same alias:
     - `sftp -b -` for file uploads and downloads;
     - `ssh -N -L <free>:127.0.0.1:<port>` to preview the remote's localhost
       ports in the app;
     - `ssh -N -L 1455:127.0.0.1:1455` for a ChatGPT login on the remote.
  9. Several ssh processes run per host: the probes, the proxy and the
     forwards.
- **Model calls happen on the remote.** VERIFIED (bundle and docs).
  - The remote `codex app-server` runs the agent loop with the **remote**
    `$CODEX_HOME/config.toml`. The app passes only
    `-c features.code_mode_host=true`.
  - Docs: "Remote project chats run commands, read files, and write changes
    on the remote host".
  - So our container's provider (gateway → relay, launch token) is the one
    used.
- **Auth on the remote host:** VERIFIED (bundle).
  - After `initialize`, the app reads the remote's auth status. It marks the
    host `login-required` only when `authMethod == null` and
    `requiresOpenaiAuth`.
  - A remote whose active provider is the Toolkit (no
    `requires_openai_auth`) should connect without any login.
  - The docs say "Install and authenticate Codex on the remote host", but
    that's for OpenAI-auth remotes.
- **Windows as the app's computer:** VERIFIED (docs) that it's supported. The
  app uses Windows OpenSSH's `ssh.exe` from PATH, and
  `%USERPROFILE%\.ssh\config`. REPORTED problems:
  - [#42995](https://github.com/openai/codex/issues/42995): Win10 → Ubuntu,
    "codex path probe timed out" while manual ssh works. Open.
  - [#47602](https://github.com/openai/codex/issues/47602): console windows
    flash when an SSH task opens. Open.
  - The community also reports repeated prompts with hardware keys, because
    the app opens several ssh sessions.
  - The POSIX-bootstrap failures (#22757, #22965, #26164) are for Windows
    *remotes*. They don't affect us: our remote is a Linux container.
- **Other REPORTED Linux-remote failures:**
  - [#26757](https://github.com/openai/codex/issues/26757): the login shell
    had no `mkdir` in PATH.
  - [#48914](https://github.com/openai/codex/issues/48914): a bastion that
    filters `rm -f` makes the start look successful when it wasn't.
  - [#22823](https://github.com/openai/codex/issues/22823): a DevPod
    devcontainer gave "app server did not become ready". Closed with no
    explanation.
  - [#29335](https://github.com/openai/codex/issues/29335) and
    [#36242](https://github.com/openai/codex/issues/36242): "Failed to
    discover remote SSH connections" on some ssh configs. Open.
  - [#22567](https://github.com/openai/codex/issues/22567): ForwardAgent
    handling.

### 3b. Other ways to point the app at a container

- **Devcontainer or Docker support:** none, so far. REPORTED as feature
  requests: [#10535](https://github.com/openai/codex/issues/10535),
  [#28205](https://github.com/openai/codex/issues/28205).
- **`codex app-server --listen ws://IP:PORT`:** VERIFIED (docs and CLI help)
  that it exists, as "experimental and unsupported".
  - Non-loopback listeners are unauthenticated by default.
    `--ws-auth capability-token|signed-bearer-token` requires an
    `Authorization: Bearer` header.
  - The documented client is the terminal: `codex --remote ws://…`. That's
    useful for the terminal mode and remote TUI, not for the app.
- **Hidden `CODEX_APP_SERVER_WS_URL`:** VERIFIED (bundle), undocumented.
  - With this env var on the app process, the app's **local** host connects
    to that WebSocket app-server instead of starting its bundled codex.
  - Combined with `CODEX_HOME` and `CODEX_ELECTRON_USER_DATA_PATH` (the
    "Codex Demo" pattern), a separate app instance could show the container
    as "this computer".
  - It sends **no auth header** for non-cloud hosts. The container's listener
    would have to be unauthenticated on a published 127.0.0.1 port. Any
    local process could then drive the agent, and probably a web page too
    (cross-site WebSocket; whether Origin is checked is UNSURE).
  - Not recommended. It's a fallback only, behind an authenticating proxy of
    our own.
- **`CODEX_APP_SERVER_USE_LOCAL_DAEMON=1`** (connect to
  `$CODEX_HOME/app-server-control/app-server-control.sock`): VERIFIED
  (bundle). Docker Desktop can't share a unix socket from a container to the
  host's filesystem on Mac or Windows, so it doesn't apply.
- **Remote control ("Control other devices", the phone):** needs ChatGPT
  sign-in on both ends and the desktop app running on the host, relayed
  through OpenAI. Not usable for a container.
- **WSL connections:** a Windows-only option. Not ours.

## 4. Fit with our design: sshd in the container, app connects over SSH

It's feasible. The app's SSH transport is plain OpenSSH driven entirely by an
alias, so we control everything through the ssh config file we write. Gaps and
risks:

1. **Port publishing doesn't work with internet off.** The agent is only on
   `--internal` networks then, and Docker doesn't publish ports for them.
   Options:
   - (a) Use a **`ProxyCommand` instead of a port** (recommended):
     `ProxyCommand <um-codex> ssh-proxy <setup>`, which runs
     `docker exec -i -u root <agent> /usr/sbin/sshd -i` (inetd mode).
     There's no listener, port or network change, and it works with internet
     on or off.
   - (b) Publish through the gateway's bridge (an nginx `stream` to
     agent:22).
2. **ProxyCommand on PATH:** the app checks whether a ProxyCommand's command
   resolves in its own PATH, and otherwise waits for a login-shell
   environment (VERIFIED, bundle). Use absolute paths. On Windows, quote
   carefully: Windows OpenSSH runs ProxyCommand itself, and
   `C:\Program Files\...` has spaces.
3. **Host keys under `BatchMode=yes`:** an unknown or changed host key is a
   hard failure.
   - With ProxyCommand through `docker exec`, the transport is local and
     trusted. `StrictHostKeyChecking no` plus `UserKnownHostsFile /dev/null`
     (or `HostKeyAlias` and a per-setup pinned key) in *our* Host block is
     fine.
   - With a published port, we'd have to write known_hosts at every launch.
4. **Client key:** a per-launch ed25519 pair. The private key is in
   `~/.ssh/um-codex/` (0600) and the public key in the container's
   `authorized_keys`. The sshd is key-only, `PermitRootLogin no`,
   `AllowAgentForwarding no`. Allow **local** TCP forwarding: the app's
   localhost previews and the 1455 login use `-L`. `ForwardAgent no` and
   `ForwardX11 no` go in our Host block, so the container never gets the
   person's ssh agent. The app still runs its agent-socket `ln`/`rm` lines,
   which do nothing without an agent.
5. **Editing `~/.ssh/config`:** this is the person's own file.
   - We need one top-level `Include ~/.ssh/um-codex/config` line, inserted
     **at the top** (VERIFIED: an Include inside a Host block isn't
     followed; one at the top of an included file is, see 3a), with the
     person's consent and an uninstall step.
   - It's absent on Windows until we create `%USERPROFILE%\.ssh\config`.
   - Our folder rules already refuse `~/.ssh` as a mount, which is good.
   - A malformed ssh config elsewhere can break discovery for all hosts
     (REPORTED, #29335).
6. **Stable alias per setup** (`umcodex-<setup>`), not per launch.
   - The app keys hosts, projects, pins and the auto-connect toggle by alias.
   - Codex's history lives in the setup's volume.
   - A per-launch alias would leave a stale host behind every launch.
   - The included file is rewritten per launch: key, container.
7. **Turning the host on:**
   - Discovered hosts start off. Either the person turns the host on once in
     Settings > Connections > SSH and picks `/work`, or `um-codex` opens
     `codex://settings/connections/ssh/add?name=umcodex-<setup>&projectPath=/work&enabled=true`
     at launch.
   - The deep link's `projectPath`/`enabled` parameters are **undocumented**.
     The documented form disables auto-connect.
8. **`$SHELL` and PATH in the container:**
   - The `agent` user needs an executable login shell in `/etc/passwd`
     (bash).
   - `codex` must be on PATH in a login shell. `/usr/local/bin` is fine.
   - `/etc/profile.d/um-codex.sh` must export `CODEX_HOME=/codex-home`.
     Without it the app-server uses `~/.codex`, and our config is ignored.
   - sshd sessions don't inherit `docker run -e` variables.
9. **The launch token in an sshd session:** `env_key` reads the app-server's
   environment. That's the login shell's, not the container's PID 1. Use
   `[model_providers.toolkit.auth] command = "/usr/local/bin/umcodex-token"`,
   which reads a launch-only file such as `/run/um-codex/token`. That avoids
   relying on profile scripts. Exposure is the same as today: the token is
   already in the container.
10. **Lifetime:** nothing in the app says "quit Codex".
    - The remote app-server is `nohup`-ed and lives until the container
      stops.
    - The current "Codex exits → remove containers" rule must become
      something else: an `um-codex` window with "End session", a timeout, or
      the app disconnecting.
    - The watchdog still covers a killed `um-codex`.
    - While the container is gone, the app shows the host disconnected and
      retries.
11. **ChatGPT login inside the container:** the app can forward port 1455
    and run a ChatGPT login *on the remote*. That would put ChatGPT tokens in
    the setup's volume, readable by anything Codex runs. Mitigations:
    - a custom provider means the app never asks;
    - consider `forced_login_method = "api"` in the container's config;
    - test what the UI offers.
12. **The app itself still needs a usable local host.** Even when the work is
    remote, the app's start screen depends on the **local** host's auth
    state. A person with no ChatGPT account (and no OpenAI API key) needs one
    of:
    - (i) a local `config.toml` whose active provider is a custom one (the
      login screen is then skipped, per §2; untested);
    - (ii) a ChatGPT sign-in;
    - (iii) an OpenAI API key.

    Writing (i) into the person's own `~/.codex` would change *their*
    personal Codex. A separate instance with its own `CODEX_HOME` and
    `CODEX_ELECTRON_USER_DATA_PATH` avoids that, but uses undocumented env
    vars.
13. **Several containers at once:** VERIFIED (bundle). Connections are kept
    per host ID, so several aliases can be connected at once, each its own
    host in the sidebar. Each must be turned on (or added by deep link) once.
    The app starts its own app-server per container.
14. **Model list:** the remote's `model/list` comes from the container's
    Codex. Toolkit model names may need `model_catalog_json` in the container
    config, or the picker shows OpenAI defaults (REPORTED: #32080, #30994).
    Not tested with the Toolkit.
15. **Alpha history and churn:**
    - SSH arrived as alpha in April 2026, and 7 of the issues found are still
      open.
    - The internals we'd rely on (bootstrap commands, the
      `features.code_mode_host` flag, the minimum version 0.141.0, the deep
      link's parameters) change with app updates, and the app auto-updates.
    - The app also rejects a remote Codex below its minimum. Pin the image's
      Codex near the app's bundled version, and re-test when the app updates.
16. **Windows:** OpenSSH Client is a Windows optional feature, usually
    present on Windows 10 1809+ and 11; check for `ssh.exe`. Plus the
    REPORTED path-probe timeout (#42995) and console flashes (#47602). Test
    on a real Windows machine early.
17. **Image additions:**
    - `openssh-server`, plus its `sftp-server` for the app's file transfers;
    - `/run/sshd`;
    - `procps` (`pkill`; already there) and coreutils (already there).

## 5. "On this computer": Computer Use and browser

- **Computer Use:** VERIFIED (docs, feature table).
  - Computer Use, "Computer Use in the browser", "Use ChatGPT with Chrome"
    and Record & Replay are "Limited*" for **every** column, API key
    included.
  - The footnote: "* Feature is currently limited to only specific regions"
    (the EEA, UK and Switzerland are excluded for some features). So it's a
    region limit, not a ChatGPT-plan gate, at least for API-key sign-in.
- **Built-in browser:** VERIFIED (docs). "Built-in browser previews and
  comments" is Available for API key.
- **How Computer Use runs:** VERIFIED (bundle and this Mac's config
  structure). It's a bundled plugin whose MCP server is the app's
  `SkyComputerUseClient mcp`, so its tool calls go through whichever model
  provider the session uses.
- **With a custom provider (Toolkit):** UNSURE.
  - Feature availability in the app is also read from remote flags (Statsig)
    that it evaluates with an unauthenticated ID when there's no ChatGPT
    account.
  - The model behind the gateway must accept screenshots (image inputs in
    tool outputs).
  - The Chrome extension's pairing may need a ChatGPT account.
  - A third party (CodexUse) says "browser remote control" and dictation
    don't work on custom-model accounts.
- **Container mode:** no. Computer Use runs only on macOS and Windows, on the
  host where the app-server runs. The Linux container gets no Computer Use;
  the M2b Playwright tool stays. Localhost previews of container ports work
  through the app's ssh `-L` forwards.

## Recommended architecture

**Keep the terminal mode as the default and supported path.** Add an
**"Open in the Codex app"** front end that uses the app's documented SSH
remote connection, with these specifics:

1. **The container gets an SSH entry point and no listener:**
   - `openssh-server` in the image; key-only, no agent or X11 forwarding,
     local forwarding allowed;
   - the `agent` user's shell is bash;
   - `/etc/profile.d/um-codex.sh` sets `CODEX_HOME=/codex-home`;
   - the provider auth is `command`-based, reading the launch token file.
2. **The host's ssh config:**
   - one top-level line, `Include ~/.ssh/um-codex/config`, added once with
     consent;
   - the included file has one stable `Host umcodex-<setup>` per setup:
     `User agent`, `IdentityFile ~/.ssh/um-codex/<setup>_ed25519`,
     `IdentitiesOnly yes`, `ForwardAgent no`,
     `ProxyCommand "<abs path>/um-codex" ssh-proxy <setup>`,
     `StrictHostKeyChecking no`, `UserKnownHostsFile /dev/null`,
     `LogLevel ERROR`;
   - `um-codex ssh-proxy` finds the running launch's agent container by label
     and execs `docker exec -i -u root <agent> /usr/sbin/sshd -i`. It fails
     cleanly when no launch is running.
3. **Launch:** start the containers as now, write the key, then open
   `codex://settings/connections/ssh/add?name=umcodex-<setup>&projectPath=/work&enabled=true`.
   If that undocumented form stops working, fall back to
   `codex://settings/connections/ssh` with a one-line instruction. Keep an
   `um-codex` window or tray process holding the launch, with "End session".
4. **The local host's sign-in:** decided by test (see below). Prefer a
   **separate app instance** with UM-Codex's own `CODEX_HOME` (custom
   provider, so no ChatGPT login) when that works. Otherwise, say plainly that
   the app needs a ChatGPT or OpenAI API sign-in for its local side, even
   though all model calls go to the Toolkit.
5. **"On this computer" in the app:**
   - the app's local host with a Toolkit provider, using the auth `command`
     helper that talks to a host relay;
   - the relay must then outlive a terminal session (a login agent);
   - Computer Use and browser only if the hands-on test passes.

## Open questions only a hands-on test can answer

The person installs and signs in; we watch.

1. With **no** ChatGPT/API sign-in, and `~/.codex/config.toml` (or a separate
   `CODEX_HOME`) whose active provider is the Toolkit: does the app skip the
   login screen and reach Settings > Connections and a working local chat?
2. Does `open -n --env CODEX_HOME=… --env CODEX_ELECTRON_USER_DATA_PATH=… -a ChatGPT`
   run cleanly beside the person's normal ChatGPT app, and survive app
   updates? What's the Windows equivalent: launching `ChatGPT.exe` with env
   vars from the Store package?
3. Against a container reached by `ProxyCommand … sshd -i`:
   - does discovery list `umcodex-<setup>`;
   - does the bootstrap (the login shell, `codex --version`, `nohup … app-server --listen unix://`,
     `app-server proxy`) connect;
   - do chats run in `/work`;
   - do the model calls reach the gateway with the launch token (relay logs)
     and *not* chatgpt.com;
   - is any ChatGPT login offered for the remote?
4. Does the undocumented deep link
   (`…/ssh/add?name=…&projectPath=/work&enabled=true`) add, connect and open
   a chat on `/work` in one step on 26.928+?
5. Toolkit models in the remote's model picker: is `model_catalog_json`
   needed? Do reasoning effort, compaction and the follow-up turns work
   through the gateway as the app-server drives them?
6. Windows 11 with the Store app:
   - Windows OpenSSH plus ProxyCommand with `docker.exe`/`um-codex.exe`;
   - the path-probe timeout (#42995);
   - console flashes (#47602).
7. Two setups at once: both connected, no cross-talk; reconnect after a
   relaunch with a new key.
8. With a Toolkit provider on this computer: are Computer Use, the in-app
   browser and Chrome control offered, and do they work (screenshots through
   the gateway)? Compare with an OpenAI API-key sign-in.
9. What the app does with a remote whose container has gone: the error, the
   retry loop, and leftover `nohup` processes (none, because the container is
   removed).

## Sources

- Docs:
  - [Remote connections](https://learn.chatgpt.com/docs/remote-connections)
  - [Authentication](https://learn.chatgpt.com/docs/auth)
  - [Connect to a gateway](https://learn.chatgpt.com/docs/enterprise/connect-to-a-gateway)
  - [Pricing / feature availability](https://learn.chatgpt.com/docs/pricing)
  - [Computer Use](https://learn.chatgpt.com/docs/computer-use)
  - [App server](https://learn.chatgpt.com/docs/app-server)
  - [Commands and deep links](https://learn.chatgpt.com/docs/reference/commands)
  - [Windows app](https://learn.chatgpt.com/docs/windows/windows-app)
  - [Changelog](https://learn.chatgpt.com/docs/changelog)
- Issues:
  - [#21554](https://github.com/openai/codex/issues/21554)
  - [#29156](https://github.com/openai/codex/issues/29156)
  - [#33029](https://github.com/openai/codex/issues/33029)
  - [#24457](https://github.com/openai/codex/issues/24457)
  - [#45467](https://github.com/openai/codex/issues/45467)
  - [#42995](https://github.com/openai/codex/issues/42995)
  - [#47602](https://github.com/openai/codex/issues/47602)
  - [#26757](https://github.com/openai/codex/issues/26757)
  - [#48914](https://github.com/openai/codex/issues/48914)
  - [#22823](https://github.com/openai/codex/issues/22823)
  - [#29335](https://github.com/openai/codex/issues/29335)
  - [#22567](https://github.com/openai/codex/issues/22567)
  - [#10535](https://github.com/openai/codex/issues/10535)
  - [#28205](https://github.com/openai/codex/issues/28205)
- Third party:
  - [OpenRouter: Codex desktop](https://openrouter.ai/docs/cookbook/coding-agents/codex-desktop)
  - [CodexUse](https://codexuse.com/blog/codex-app-without-openai-subscription/)
- Bundle: `/Applications/ChatGPT.app` 26.928.21956, `app.asar`, read-only
  (`.vite/build/main-*.js`, `bootstrap-*.js`,
  `application-network-startup-*.js`, `webview/assets/*`).
