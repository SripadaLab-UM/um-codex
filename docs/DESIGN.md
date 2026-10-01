# UM-Codex: design

Status: v0 design, 2026-10-01. Source of most of the machinery:
[IHS DataLab](https://github.com/SripadaLab-UM/ihs-datalab) at `6b6fdca`
(0.3.0b6). Every copied module says so in its first lines.

## What it is

Full-power OpenAI Codex, on U-M GPT Toolkit, running inside a Docker
container on a Mac or Windows computer. There's no web app and no knowledge
base: **Codex's own terminal interface is the front end**. At each launch the
person decides what the container can see and do, then Codex opens in their
terminal.

It follows ITS's "Codex Setup" articles for the model settings (the
`toolkit` provider, `https://api.toolkit.umgpt.umich.edu/v1`,
`gpt-5.6-terra`). It doesn't follow them for the key: there's no
`auth.json` with the key in it (see "The key" below).

**Goal:** a full-power Codex with decent safety, not a locked-down one.
- Internet on means the whole internet.
- Write folders mean write and delete.
- Inside the container, Codex runs commands without asking unless the person
  chooses otherwise, and it can `sudo`.
- The safety comes from **what the container can reach on the host**: only
  the folders that were chosen, and never the key.

## The person's journey

1. **Install:** one command, from the latest release (or a site later),
   with no arguments (the release writes its own address into its
   installers):
   - Mac: `curl -q -fsSL https://github.com/SripadaLab-UM/um-codex/releases/latest/download/install-macos.sh | sh`
   - Windows: `irm https://github.com/SripadaLab-UM/um-codex/releases/latest/download/install-windows.ps1 | iex`
     (after turning on TLS 1.2; the README has the whole line)

   The installer:
   1. finds or installs Docker Desktop, and fixes the Windows VM logon right
      (all from DataLab);
   2. installs uv, then UM-Codex with its own Python, in the person's account;
   3. pulls the pinned images;
   4. asks for the Toolkit API key (masked) and saves it in the Keychain or
      Credential Manager;
   5. adds a **UM-Codex** app to Applications and the Desktop (Mac), or to
      Start and the Desktop (Windows), with the logo.
2. **Launch:** the app (or its Desktop or Start menu shortcut) opens the
   launcher window in the browser (`um-codex ui`, M5 below): saved setups
   as cards, a form for a new one, the summary, then Start opens a terminal
   with Codex in it. Or the person types `um-codex` in any terminal, which
   asks the questions below in the terminal.
   1. Docker check. If Docker Desktop is closed, it's opened and waited for.
      If Windows refuses its VM (the logon right), it offers DataLab's fix:
      one administrator prompt, then Docker Desktop is restarted.
   2. **Setup.** It lists the saved setups with the last one first ("Use
      *thesis* again? [Y/n]"), or asks for a new one:
      - **Name** (default: the working folder's name).
      - **Working folder** (read, write, delete): Codex starts here. Asked as
        "Drag a folder here, or press Enter for <default>". Default: the
        folder `um-codex` was started in. With `--from-app` (the app and the
        shortcuts pass it) the current folder is ignored, as it's only where
        the terminal opened: the default is the last setup's working folder,
        otherwise `~/Documents/UM-Codex`, which is created when it's chosen.
        With no default, an empty Enter says to drag or type a folder.
      - **More folders to write** (read, write, delete). Optional; any number.
      - **Folders to read only.** Optional; any number.
      - **Internet: on or off.** Off means Codex can reach only the model.
      - **Browser tool** (asked only with the internet on): "Browser tool on?
        (Codex can open websites in a fresh browser inside the sandbox; it has
        none of your logins.) [y/N]". When it's on: "Approve each browser
        action? [Y/n]". See M2b below.
      - **Model:** default `gpt-5.6-terra`; the list comes from the Toolkit.
      - **Approvals:** "Codex runs commands without asking" (default), or
        "ask me before commands".
      - A summary screen in plain words, which says that Codex can delete in
        the write folders and, with internet on, could send anything it can
        read anywhere. Then "Start? [Y/n]".
   3. **Codex opens** in the same terminal, inside the container. When the
      person quits Codex, the containers are removed. The setup's Codex
      history is kept, so `codex resume` works next time.
3. **Other commands:**
   - `um-codex setups` lists, edits and deletes setups.
   - `um-codex key` replaces the key (masked prompt; checked against the
     Toolkit's `/models` when it can be reached).
   - `um-codex doctor` checks Docker, the key, the images and the Toolkit,
     and prints diagnostics with no secrets in them.
   - `um-codex update` installs the newest signed release beside this one,
     pulls its images and switches to it; `--rollback` switches back
     (docs/RELEASING.md). Once a day a launch says when one is out.
   - `um-codex uninstall`.

   The installers call some of these, so their names, flags and exit codes
   are an interface:
   - `um-codex ui [--detach] [--no-browser]`: the launcher window (M5).
     `--detach` (what the app and the shortcuts run) starts it in the
     background and returns at once; `--no-browser` prints the sign-in link
     instead of opening the browser. A second one opens the first one's
     page again. Exit 0.
   - `um-codex launch --setup <id or name>`: what the launcher window runs
     in the terminal it opens: no questions; 1 when the setup isn't there,
     or a folder is refused or now leads somewhere else.
   - `um-codex launch --from-app`: what the app and the shortcuts ran before
     M5 (kept working for them), so the folder the terminal opened in isn't
     offered as the working folder (see the Setup step above).
   - `um-codex key [--from-stdin]`: exit 0 saved, 1 refused or invalid,
     2 cancelled (Ctrl-C at the masked prompt, or an empty entry). The Mac
     installer runs `um-codex key < /dev/tty`, so the key never passes
     through its shell; `--from-stdin` reads one line.
   - `um-codex pull`: pulls every image in `images.json`; a local `:dev`
     image that's already present is skipped. Nonzero on failure, and a plain
     message when Docker isn't running.
   - `um-codex doctor [--quiet] [--fix-docker]`: `--quiet` prints nothing but
     one line on failure (a Toolkit that can't be reached, off the VPN, is a
     note there, not a failure; a refused key is a failure); `--fix-docker` opens Docker Desktop and, on
     Windows, offers the logon-right fix (as the launch does).
   - `um-codex update [--rollback]`: 0 updated (or already the newest),
     1 refused or failed (a launch running, no pinned release key, a
     development copy, a release that fails a check), with nothing changed.
   - `um-codex uninstall [--delete-data|--keep-data] [--yes]`: first asks
     "Uninstall UM-Codex? [y/N]" (no: nothing removed, exit 1). Then it removes, by
     label only, UM-Codex's containers and networks (and, with
     `--delete-data`, each setup's Codex home volume), the key, the images
     (asked first; the gateway's nginx only if no container uses it) and,
     with `--delete-data`, the data folder's contents. It never removes the
     program files (`<data folder>/app`, which the installers own and their
     uninstall scripts remove afterwards). From DataLab's `setup.uninstall`,
     with the #36 fixes. `--yes` asks nothing: images go, and data stays
     unless `--delete-data`. With no terminal to answer a question
     (EOF), `um-codex` takes it as no and exits 1, without a traceback.

## How it runs (one launch)

```
host                                     Docker
────                                     ──────
um-codex (Python)                        network umcodex-<id>-int (internal: no route out)
 ├─ relay on 127.0.0.1:<port> ◄──────────  gateway (nginx, pinned) ◄── agent: codex (TUI)
 │   checks the launch token,               also on a bridge network,        /work         rw  working folder
 │   adds the Toolkit key                   to reach the host's relay        /mnt/write/*  rw  more write folders
 └─ docker exec -it agent codex                                              /mnt/read/*   ro  read-only folders
     (the person's terminal)                                                 /codex-home       setup's volume
                                         internet on: agent also joins       config.toml   ro  from the host
                                         network umcodex-<id>-net (bridge)
```

- **Relay:** a small asyncio HTTP relay in the `um-codex` process (aiohttp's
  server in a background thread, httpx to the Toolkit; both pinned). It's
  adapted from DataLab's `relay/` (with its retry and recovery, minus the
  data-session policy). It accepts only this launch's random token, swaps in
  the Toolkit key and streams the reply. It relays GET and POST under `/v1/`
  only. If the Toolkit ever echoed the key, it's removed from the reply
  before it reaches the container, even when split across chunks. It's only
  ever bound to 127.0.0.1, on a free port, and it ends when the launch ends.
  The gateway reaches it at `host.docker.internal` (with
  `--add-host host.docker.internal:host-gateway`).
- **Gateway:** DataLab's nginx container and config, minus `/mcp`. Codex's
  `base_url` is `http://gateway/v1`. It's on the launch's internal network
  and on a bridge of its own (`umcodex-<id>-gw`, not Docker's shared default
  bridge), through which it reaches the relay.
- **Agent:** this repo's image, `ghcr.io/sripadalab-um/um-codex-agent`, pinned
  by digest. It's a non-root `agent` user with passwordless sudo inside the
  container, has no Docker socket, isn't privileged, and adds no host
  capabilities.
  - **Internet off:** it's on the internal network only, with DataLab's
    no-DNS setting.
  - **Internet on:** it's on a normal bridge network too, with full internet.
    Model calls still go through the gateway.
  - In both, its `host.docker.internal` points nowhere (`192.0.2.1`), so the
    easy way to the computer's own localhost services is closed.
    A known limit, found in the M1 live check and kept by decision: with the
    internet on, the container can still reach programs that listen only on
    this computer's localhost through Docker Desktop's host address (by IP),
    and computers on the person's local network and VPN ranges. The relay
    there still needs the launch token, and the key is never reachable, but
    other local programs and machines are; the summary screen says so. With
    the internet off, none of these is reachable.
  - `--pids-limit 4096`. No `--memory`: Docker Desktop's own VM limit (set in
    its settings) already bounds it, and a fixed number here would be either
    above that limit (meaningless) or below what some work needs.
  - **A watchdog ends a forgotten launch.** The agent's main process runs the
    image's own command in the background and asks the relay, through the
    gateway with the launch token, every 15 s whether the launch is still on
    (`/v1/_umcodex/alive`, answered by the relay, never sent upstream). After
    four failures in a row (about a minute) it exits, and the container
    (started with `--rm`) removes itself. This covers `um-codex` being killed
    in any way, on any OS, without depending on signals. The gateway and
    networks left behind hold nothing and go at the next launch, by label.
  - Docker's default capabilities stay (so `sudo` works); nothing is added.
- **Codex home is a named Docker volume per setup** (`umcodex-home-<setup>`),
  not a host folder. DataLab learned that Codex makes Linux symlinks there,
  and the Windows uninstaller then tripped on them (#36). A volume also keeps
  Codex's history off the host's synced folders.
- **config.toml** is written by the host and mounted read-only over the
  volume. From DataLab's `codex_config.py`, it sets:
  - `model_provider = "toolkit"`, pointing at the gateway, with `env_key` for
    the launch token;
  - `sandbox_mode = "danger-full-access"`, because the container is the
    sandbox;
  - `approval_policy`: `never` (the default) or `on-request`, from the setup
    (with "never" and browser actions to approve, a `granular` policy that
    behaves as "never" for commands: see M2b);
  - `web_search = "live"` when the internet is on, otherwise `disabled`;
  - with the browser tool on (internet on only), `[mcp_servers.browser]`
    (see M2b);
  - analytics, feedback and update checks off.

  Codex's other features stay at Codex's defaults: full power.
- **AGENTS.md** in the image tells Codex where things are: the folders, what's
  read-only, and that it has `sudo`. The container copies it into
  `$CODEX_HOME/AGENTS.md` at every start (it's the app's file). It tells
  Codex to read `/etc/um-codex/launch.md` first. That's a plain-text note
  written by the host for each launch and mounted read-only as one file: the
  setup's name, `/work` and each `/mnt/write/*` and `/mnt/read/*` with its
  folder on the computer, internet on or off, the browser tool (on or off,
  and whether each action is approved), and the approval policy.
- **The launch's files** (`config.toml`, `launch.md`, `gateway.conf`, and the
  env file with the token, deleted once the agent has started) are in
  `launches/<id>/` in UM-Codex's data folder, never in a folder the agent can
  write. The folder is removed when the launch ends.
- **The terminal:**
  - The container starts with the image's command (copy AGENTS.md into
    Codex home, then sleep), then `docker exec -it -w /work -e TERM=…
    <agent> codex` runs in the foreground with the person's terminal size.
    `um-codex launch -- <args>` passes arguments to `codex` (for example
    `resume`). On Windows, the same works in Windows Terminal and
    PowerShell.
  - Ctrl-C belongs to Codex.
  - A closed terminal still cleans up: SIGHUP and SIGTERM on a Mac, and on
    Windows a console handler (`SetConsoleCtrlHandler`, for Close, Logoff and
    Shutdown) that removes the containers with short Docker timeouts within
    the ~5 s Windows allows. The watchdog is the backstop.
  - On Windows without a console (Git Bash's mintty), `um-codex` says to use
    Windows Terminal or PowerShell instead.
  - When `docker exec` ends, `um-codex` removes the containers and network.
    If `um-codex` itself is killed, the next launch removes leftovers by label.
    Each launch holds an OS file lock (`launches/<id>/lock`) while it runs, so
    cleanup tells a leftover from a launch that's still going; labels also
    carry the data folder (`umcodex.instance`), so one data folder never
    removes another's launches.
- **Two launches at once** each get their own containers, network and token.
  Two launches of the *same* setup share its Codex home volume, which Codex
  handles: sessions are separate files.

## The key

ITS's articles put the key in `~/.codex/auth.json`. In a container with
internet on, that would let anything Codex runs (or a web page's prompt
injection) read it and send it out. Here the key is:
- in the Keychain or Credential Manager (DataLab's `credentials.py`);
- read only by the relay on the host;
- never in a container, an environment variable, a file, a log or diagnostics.
  The relay drops a request ID or error code that holds the key before
  logging it, and HTTP libraries' debug logs (which print headers) are kept
  off. `UMCODEX_UPSTREAM` (tests only) may point only at http://127.0.0.1,
  localhost or [::1], so it can't send the key to another host.

The container has only a per-launch token, which works only through that
launch's gateway, and only while the launch lasts.

## Folder rules

These come from DataLab's mount checks (`sessions/mounts.py` and
`inputs.private_place`), loosened to fit this purpose:
- Paths must be absolute and must exist. They're resolved, so a symlink
  can't widen what's shared.
- Refused for every access (the folder itself, anything inside it, and
  anything holding it):
  - the home folder itself, `/`, or a whole drive or volume (`C:\`);
  - UM-Codex's own data folder, and its program files (`<data folder>/app`);
  - the key store, `~/.ssh`, `~/.aws`, `~/.config/gh`, `~/.codex`,
    `~/.gnupg`, `~/.kube`, `~/.azure`, `~/.config/gcloud`;
  - places whose programs this computer runs later: `~/.local/bin` (where
    the `um-codex` command is), `~/.local/share/uv`, `~/Library/LaunchAgents`,
    the Windows Startup folder;
  - Docker's own folders.

  The person gets a plain reason. Subfolders of home are fine.
- Folders are compared by name and by identity on disk (device and inode,
  for the folder and each folder it's in), so another name for the same
  folder (a Mac firmlink such as `/System/Volumes/Data/Users/...`, Windows'
  `\\localhost\C$\` or `\\?\` forms) is caught too.
- Each launch checks a saved setup's folders again. If one now resolves
  somewhere else (a link was put in its path, perhaps by an earlier launch
  in a write folder), a loud warning names both places and the person must
  type `yes`; otherwise they change the setup.
- The same folder can't be both read-only and writable. A read-only folder
  inside a writable one stays readable through the writable mount; the
  summary screen says so.
- Windows: paths aren't converted. `--mount` takes the Windows path as it is
  (CSV-quoted), as DataLab's mounts do. Folders on a network drive get a
  warning, not a refusal.
- **Code in a write folder can run on the host later.** Codex can write
  anything in the write folders, including files the person's own tools run
  on this computer: git hooks (`.git/hooks`), a `Makefile`, `package.json`
  scripts, `.envrc` (direnv), `.vscode/tasks.json`, a virtual environment's
  scripts. Running those tools there afterwards runs what Codex (or a prompt
  injection it read) put there. UM-Codex doesn't scan for this; the README
  says so, and the protected places above keep the obvious autostart and
  program folders out.

## Code layout

```
um-codex/
  pyproject.toml            package "umcodex", command "um-codex", Python ≥3.13
  src/umcodex/
    cli.py                  argument parsing; launch is the default command
    ui/                     the launcher window (M5): server.py (the API), protection.py (from DataLab
                            web.py), picker.py (from DataLab), opener.py (where Codex opens), static/ (the page)
    setups.py               saved setups (TOML in the data folder), prompts, validation
    folders.py              folder rules (from DataLab mounts/inputs)
    launch.py               one launch: relay, network, gateway, agent, exec, cleanup
    paths.py                the data folder per OS (from DataLab config.py), and the program files' folder
    relay.py                (from DataLab relay/__init__ + recovery, policy trimmed)
    containers.py           docker commands, labels, cleanup (from DataLab containers.py)
    codex_config.py         config.toml (from DataLab)
    credentials.py          (from DataLab)
    secret_prompt.py        (from DataLab)
    docker_path.py          (from DataLab)
    windows_vm.py           (from DataLab: DockerDoctor, the logon-right fix, the restart)
    doctor.py               checks and diagnostics
    toolkit.py              model list, key check
    uninstall.py            `um-codex uninstall` (from DataLab setup.uninstall and storage.size_of)
    signing.py              Ed25519 release signatures (from DataLab)
    release_keys.py         the pinned release public keys (from DataLab; empty until the maintainer adds one)
    releases.py             which GitHub release is offered, and its checks (from DataLab)
    update.py               `um-codex update`, rollback, the daily notice (from DataLab's updater, simpler)
    gateway.conf            (from DataLab, /mcp removed)
    images.json             pinned image digests (stamped by the release)
  images/agent/             Dockerfile, AGENTS.md (from DataLab's image: Codex, Node, Python, R; DataLab skills removed; build tools added),
                            smoke.sh, browser-check.js (the browser tool's MCP check)
  installer/macos/          install.sh, uninstall.sh (from DataLab, trimmed)
  installer/windows/        install.ps1, uninstall.ps1 (from DataLab, trimmed)
  branding/                 build.py and the mark (from DataLab's "1b": Block M, spark, "codex" under it)
  scripts/                  build-release.sh, sign-release.py, release-version.sh (from DataLab)
  tests/
  .github/workflows/        ci.yml, release.yml (from DataLab: tests, Windows tests, installer parse and run, signed release)
```

## What's new compared with DataLab

- **The launch questions and saved setups:** prompt and validation code, all
  new.
- **Writable mounts.** DataLab never mounts host folders writable. This is
  the deliberate difference, and the summary screen makes it visible.
- **The internet-on network:** DataLab's research proxy is replaced by a
  plain bridge network. Squid isn't needed, because there's no allowlist.
- **An interactive `docker exec -it`,** in place of DataLab's app-server
  JSON-RPC. It's simpler: no runtime, events or store.

Left out (DataLab only): the web app, SQLite, sessions/conversations,
Oracle, the knowledge base and pipelines, GitHub, safety checks, exports,
modes, rigor, and the frontend.

## Milestones

1. **M1, runs from source on a Mac:**
   - `uv run um-codex`: setup prompts, relay, gateway, agent image built
     locally, Codex opens, internet on and off both work, cleanup.
   - Tests for folder rules, config, the relay token and cleanup.
   - Done on branch `m1-core` (2026-10-01). The live check ran real launches
     on a Mac against a local stub instead of the Toolkit
     (`UMCODEX_UPSTREAM`), with internet off and on: networks, mounts and
     flags as above; `curl https://example.com` failed with the internet off
     and worked with it on; the stub received Codex's requests with the key
     swapped in; the key wasn't in `docker inspect`, the container's
     environment or any file in it (`grep -r /`); `codex exec` answered
     through the relay; everything but the setup's volume was removed
     afterwards. Codex's interactive TUI itself was not driven. After the
     review fixes: with `um-codex` killed (SIGKILL) mid-launch, the watchdog
     ended the agent container in about a minute, and the next launch's
     cleanup removed the gateway and networks.
2. **M2, installers and CI:**
   - the Mac and Windows installers (Docker step, uv, key, launcher, icon);
   - uninstallers;
   - CI with Windows tests and the installer parse and run steps;
   - the agent image built and pushed to GHCR.
3. **M2b, browser tool (asked for on 2026-10-01; built on branch
   `m2b-browser`, 2026-10-01):**
   - **The question.** Only when the internet is on: "Browser tool on?
     (Codex can open websites in a fresh browser inside the sandbox; it has
     none of your logins.) [y/N]" (default off), then, when it's on,
     "Approve each browser action (opening pages, clicking, typing)? [Y/n]"
     (default yes). Both are saved with
     the setup (`browser`, `browser_asks`); setups saved before M2b have
     neither, which means off. Turning the internet off turns the browser
     tool off. The summary screen says "Browser tool: ON. Codex can open
     websites in a fresh browser inside the sandbox; it has none of your
     logins." and whether it asks before each browser action ("opening
     pages, clicking, typing; reading a page doesn't ask"), or "Browser
     tool: off." with the internet on. launch.md says the same to Codex,
     and the image's AGENTS.md has a short section on the tool.
   - **The image.** `@playwright/mcp` 0.0.83 (pinned; its Playwright is
     1.64.0-alpha-1790635538000), installed with Codex in the Node stage
     and linked as `/usr/local/bin/playwright-mcp`. Its Playwright's own
     Chromium build (Chrome for Testing 155.0.8059.12, revision 1247,
     downloaded by `playwright-mcp install-browser --with-deps --no-shell
     chromium`) is in `/opt/ms-playwright` (`PLAYWRIGHT_BROWSERS_PATH`),
     readable by everyone, with the system libraries it needs. Playwright
     publishes this build for linux amd64 and arm64 (Ubuntu 24.04, the
     Rocker base). The headless shell isn't installed: the full build runs
     in Chrome's new headless mode. `smoke.sh` starts the server with the
     launch's arguments, as `agent`, and reads a heading from a `data:` page
     (`um-codex-browser-check`, which speaks MCP over stdio: `initialize`,
     `tools/list`, `browser_navigate`, `browser_snapshot`).
   - **Size:** about +600 MB unpacked (577 MB for Chromium and its
     libraries, 19 MB for the MCP package): `docker image ls` showed 4.7 GB
     before and 5.56 GB after on arm64, and the content to download went
     from 1.2 GB to 1.46 GB.
   - **config.toml** (only with the internet and the tool on):
     ```toml
     [mcp_servers.browser]
     command = "/usr/local/bin/playwright-mcp"
     args = ["--headless", "--browser", "chromium", "--isolated", "--output-dir", "/tmp/um-codex-browser"]
     cwd = "/work"
     env = { PLAYWRIGHT_BROWSERS_PATH = "/opt/ms-playwright" }
     startup_timeout_sec = 60
     tool_timeout_sec = 180
     default_tools_approval_mode = "writes"   # "approve" when the person said no
     ```
     - It runs inside the agent container over stdio, as `agent`, with no
       display. `--browser chromium` is Playwright's Chromium (the default
       is Google Chrome, which isn't installed and has no arm64 Linux
       build); Playwright runs it without Chrome's own sandbox, as it does
       for this build on Linux. `--isolated` keeps the profile in memory:
       a fresh browser each launch, nothing kept.
     - The residual risk of that unsandboxed Chromium: a page that exploits
       it gets only what the `agent` user already has in this container (the
       chosen folders, the internet, `sudo` inside the container), nothing
       on the host.
     - Files the server names itself (page snapshots, unnamed screenshots)
       go to `/tmp/um-codex-browser` in the container and go with it. A
       screenshot Codex saves under a file name is saved relative to `/work`
       (the server's working folder); Codex is told (AGENTS.md, launch.md)
       to save one only when the person asks. Taking a screenshot is marked
       read-only, so it doesn't ask.
     - `env`: Codex starts MCP servers with only a few variables (HOME,
       PATH, LANG and the like; `rmcp-client`'s `DEFAULT_ENV_VARS`), so the
       browsers' folder is passed on. The launch token isn't.
     - Approval values in Codex 0.157.1 (`AppToolApproval`): `auto`,
       `prompt`, `writes`, `approve`. **With `approval_policy = "never"`
       and full access, Codex approves every MCP call without asking and
       turns down MCP approval prompts** (`codex-mcp`'s
       `mcp_permission_prompt_is_auto_approved`, and
       `request_mcp_tool_user_approval`). So when the setup runs commands
       without asking but wants each browser action approved, the policy is
       `approval_policy = { granular = { sandbox_approval = false, rules =
       false, mcp_elicitations = true, request_permissions = false,
       skill_approval = false } }`. Checked against the `rust-v0.157.1`
       source (and by an independent review), it's the same as "never" for
       commands, patches, permissions and network (with full access, no
       command needs a prompt, and command and rule prompts are turned
       down without asking), and browser actions are asked about. The
       other differences from "never":
       - installing a skill's MCP dependencies asks "Install MCP servers?"
         (`mcp_skill_dependencies.rs`) instead of skipping them;
       - MCP elicitations with an empty form are shown instead of accepted
         (`session/mcp.rs`);
       - the model's permissions instructions describe the granular policy;
       - Codex's status line shows it in place of "never";
       - hooks see `permission_mode` "default".

       With "ask me before commands" (`on-request`) the policy stays as it
       is.
     - **Which actions ask:** `writes` asks before every tool the server
       doesn't mark read-only. In `@playwright/mcp` 0.0.83's `tools/list`
       the read-only ones (`readOnlyHint: true`) are `browser_snapshot`,
       `browser_take_screenshot`, `browser_find`, `browser_console_messages`,
       `browser_network_requests`, `browser_network_request` and
       `browser_wait_for`; all the others are marked read-write and
       destructive, among them `browser_navigate`, `browser_navigate_back`,
       `browser_click`, `browser_type`, `browser_fill_form`,
       `browser_press_key`, `browser_select_option`, `browser_hover`,
       `browser_evaluate`, `browser_run_code_unsafe`, `browser_file_upload`,
       `browser_tabs` and `browser_close`. `prompt` would ask before every
       call, snapshots too, and Codex's "remember for this session" doesn't
       apply to `prompt` or `writes`.
   - **Live check** (this Mac, arm64, Docker Desktop; `um-codex-agent:dev`
     rebuilt from this branch; containers, networks and volume made from
     `LaunchSpec` as a launch makes them, then removed; the model was a stub
     inside the container, so no key was used):
     - MCP over stdio with Codex's small environment: `initialize`
       (Playwright 1.64.0-alpha-1790635538000) and `tools/list` (25 tools)
       answered; with the internet on, `browser_navigate` to
       https://example.com returned "Page Title: Example Domain" and
       `browser_snapshot` returned the live page (its `link "Learn more"`;
       example.com as served on 2026-10-01 has no heading element, only that
       title, a paragraph and the link); with the internet off, navigate
       failed with `net::ERR_NAME_NOT_RESOLVED`.
     - Codex 0.157.1 started the server from the rendered config.toml and
       offered its tools to the model (namespace `mcp__browser`, 25 tools).
       `codex exec` ran a `browser_navigate` the stub asked for and sent the
       page back to the model (`codex exec` always runs with approval
       "never", so it never asks).
     - Codex's terminal interface, driven in a pseudo-terminal inside the
       container. With `writes`, the stub asking for `browser_snapshot` and
       then `browser_navigate`: the snapshot ran without asking and the
       navigate asked (then ran after Enter), under both the granular
       policy and "ask me before commands"; with `approve`, neither asked.
       Earlier, with `prompt` and the stub asking for `browser_navigate`:
       - "approve each action" with "runs commands without asking" (the
         granular policy): Codex showed `Allow the browser MCP server to
         run tool "browser_navigate"? url: https://example.com` with
         "1. Allow" and "2. Cancel"; Enter ran it and the page (title
         "Example Domain") went back to the model; Esc sent back "user
         cancelled MCP tool call" and the browser didn't run;
       - the same policy didn't ask before a shell command (it ran);
       - "approve each action" with "ask me before commands" asked the same
         way;
       - "don't ask" (`approve`) ran the browser action without asking.
     - The same arguments built in an amd64 image (Rocker base, emulated on
       this Mac) loaded the smoke test's page too.
   - Not checked: the acceptance sentence with the real model ("open
     example.com and tell me its heading" after approval) needs a Toolkit
     key, so it's for the maintainer's first launch with the tool on.
   - It never controls the person's own computer, desktop or browser: the
     container can't reach them (see the end of this document).
4. **M3, releases:** signed releases (Ed25519, the `release` environment,
   the tag rules) and `um-codex update` with rollback. Built on branch
   `m3-release` (2026-10-01); docs/RELEASING.md has the details and the
   maintainer's one-time steps:
   - `release.yml` on a `v*` tag: all of CI (`ci.yml` through
     `workflow_call`), the tag checked against the version
     (`v0.1.0-alpha.2` is `0.1.0a2`) and a pinned key required; the agent
     image built for amd64 and arm64 (reused when `images/agent` is
     unchanged) and pinned by digest; the package with `images.json`
     stamped, `requirements.txt` with hashes, the installers with the
     release's address written in, `images.json` and `SHA256SUMS`
     (`scripts/build-release.sh`); `SHA256SUMS.sig` made in the `sign` job,
     the only one in the `release` environment; then the release, a normal one
     until a full release exists (so `releases/latest/download` works from
     the first alpha), marked the latest only if its version is the newest;
     after a full release, pre-release versions are marked pre-releases. Actions pinned by commit; a reused agent image must list
     both platforms and carry this workflow's build provenance.
   - `um-codex update`: DataLab's rules for which release is offered and
     how it's checked (signed `SHA256SUMS`, GitHub's checksums, hashed
     requirements, images matching the package's), installed beside with
     the installers' uv flags, images pulled, `current`/`previous` switched,
     older versions pruned; refused while a launch runs. `--rollback`. A
     launch checks at most once a day, waits 3 s at most, and prints one
     line when a newer release is out.
   - Not yet: the key is the maintainer's to make and pin
     (`release_keys.py` ships empty, so no release can be published and
     no installed copy offers an update until then); no release has been
     made; Windows update and rollback are unit-tested only.
5. **M4, "On this computer" mode (asked for on 2026-10-01):**
   - The first launch question becomes "Where should Codex run? In a
     sandbox (container) / On this computer". It's saved with the setup.
     The group is expected to use both.
   - On this computer:
     - A native Codex, pinned and installed by UM-Codex in its program
       folder, not whatever `codex` is on PATH.
     - The same localhost relay, so the key stays in the keychain and is
       never put in `auth.json`.
     - A working folder, and Codex's own sandbox as a choice: "full access"
       (the default) or "this folder only".
   - Browser control in the person's own browser: the Playwright MCP server
     connected to their running Chrome or Edge through its extension. Each
     action asks for approval by default.
   - Computer control:
     - First, a short spike on the pinned Codex: do `computer_use`,
       `browser_use` and `in_app_browser` work in the terminal Codex?
     - If they don't, add a computer-control MCP tool (screenshots, mouse,
       keyboard), with approval for each action.
     - On a Mac, this needs one-time Screen Recording and Accessibility
       permission.
   - The summary says plainly that Codex can do anything the person can do
     on this computer.
   - Docker becomes optional in the installer for people who use only this
     mode.
6. **M5, launcher window (asked for on 2026-10-01: the terminal's setup
   questions weren't friendly enough).** The UM-Codex app (Mac) and the
   Start menu and Desktop shortcuts (Windows) open a small page in the
   person's browser instead of a terminal full of questions. Typing
   `um-codex` in a terminal still asks the questions as before.
   - **`um-codex ui`** starts a small web server in the `um-codex` process
     (aiohttp, already a dependency), on 127.0.0.1 and a free port, and opens
     its page in the default browser. Plain HTML, CSS and JavaScript shipped
     in the package (`src/umcodex/ui/`), no build step. `--detach` starts it
     in the background with no window and returns at once (what the app and
     the shortcuts run). One at a time per data folder: the server holds a
     lock (`ui.lock`) and writes its port and a private control secret to
     `ui.json` (readable by the person only); a second `um-codex ui` asks the
     running one, with that secret, for a new sign-in link and opens that.
     The server ends after 15 minutes with no request from the page (the page
     asks every few seconds while it's open). Launches it started go on: each
     runs in its own terminal.
   - **Protection,** adapted from DataLab's `web.py` (`BrowserSession`,
     `ApiProtection`, `refuse_cross_site`) at 6b6fdca:
     - the opened URL carries a one-time sign-in token, exchanged for an
       HttpOnly, SameSite=Strict cookie named for the port; every `/api`
       request needs that cookie;
     - the Host header must be `127.0.0.1:<port>` or `localhost:<port>`
       (a DNS-rebinding page has another host name);
     - every request that changes something must be JSON, carry no
       `Sec-Fetch-Site` other than `same-origin`, and, if it has an `Origin`,
       be from this very origin;
     - no CORS headers, ever, so other pages can't read answers; DataLab's
       Content Security Policy (only the page's own files; `connect-src
       'self'`) and the other security headers on every response;
     - the access log is off (the sign-in URL holds the token), and nothing
       logs a request body (the key form posts the key).
   - **The page** (DataLab's "paper" look: white paper or dark, warm ink,
     hairline rules, serif headings; Maize and Blue only as small accents and
     in the mark):
     - a status line: Docker running or not ("Open Docker Desktop"; on
       Windows, when the virtual machine is refused, "Fix it" with the same
       explanation the terminal gives, then one administrator prompt);
       the key saved or not ("Replace key…": a small masked form posted to
       the local API, checked against the Toolkit's `/models`, saved in the
       keychain, never echoed or logged); an update when the daily check
       found one ("run um-codex update in a terminal");
     - running launches: "*setup* · Running since 14:05 · Stop";
     - saved setups as cards (name, working folder, other folders as chips
       marked read or read & write, internet, browser tool, approvals, "Open
       in"), with Start, Edit, Duplicate and Delete, and "New setup";
     - the setup form: name; working folder and more folders, each chosen with
       "Choose folder…" (the computer's own folder picker, from DataLab's
       `sessions/picker.py`, with its Windows bring-to-front fix: a web page
       can't name a path itself), each more folder a chip with a "Read only /
       Read & write" toggle; refusals shown in plain words under the folder
       (`folders.py`'s own reasons); Internet; Browser tool (only with the
       internet on) and "Approve each browser action"; "Ask me before
       commands"; the model (the Toolkit's list, default `gpt-5.6-terra`);
       "Open in": Terminal, or Codex app (shown, disabled, "coming soon":
       branch `spike-codex-app` is testing it);
     - before a start, the terminal's own summary (`setups.summary`) with
       Start and Back. If a saved folder now resolves somewhere else, the
       page shows both places and Start needs a tick in "Use them where they
       go now"; the setup is then saved with the folders as they resolve.
   - **Start** saves the setup as used and opens a new terminal window
     running `um-codex launch --setup <id>`: no questions; the setup's
     folders are checked again, and a refused or moved folder stops it with a
     plain message ("open UM-Codex to change it"). Docker and the key are
     still checked there (opening Docker Desktop, or on Windows offering the
     fix, and asking for a key if none is saved), as a fallback for what the
     page already shows. How it opens sits behind an `Opener` (`ui/opener.py`):
     - Terminal: on a Mac, `open -a Terminal` on a `.command` file written
       for that start (in the data folder's `ui/`, owner-only; it removes
       itself when it runs), holding one line with every part
       `shlex`-quoted. Opening a file needs no permission to control
       Terminal (AppleScript would ask for one), and a Terminal that wasn't
       running opens just that window. On Windows, Windows Terminal if it's
       installed, else Windows PowerShell in a new console, each with the
       command as `-EncodedCommand` (each part a single-quoted PowerShell
       string; no Windows or Windows Terminal quoting to get wrong).
       Windows PowerShell 5.1 can't pass a double quote inside an argument
       on reliably, so one is refused (no Windows path has one), and a part
       with a space that ends in backslashes gets them doubled. The setup's
       id must be Docker-safe, as `new_id` makes it (it names the setup's
       volume too), or the start is refused.
       The command runs the server's own Python (`-m umcodex`), so it's the
       same version, and carries the development variables (`UMCODEX_*`) the
       server was started with, and keyring's `PYTHON_KEYRING_BACKEND` (the
       launch must read the key from the store the page checked).
     - Codex app: a stub until that branch lands.
   - **Running launches** are the launch folders whose lock is held. Each
     launch writes `launch.json` there (setup id and name, start time).
     Stop removes that launch's containers and networks by label (instance
     and launch), as cleanup does; Codex's `docker exec` then ends, and
     that launch's `um-codex` cleans up the rest and says so in its window.
   - **The app and shortcuts:** the Mac app runs `um-codex ui --detach`
     and has no Dock icon of its own (`LSUIElement`), so no Terminal window
     opens until a setup is started. The Windows shortcuts run Windows
     PowerShell with a hidden window (minimized; it may flash for a moment)
     that runs `um-codex.exe ui --detach`; the server then has a console
     that's never shown, which the Docker commands it runs share (so they
     don't flash windows either).
   - `um-codex uninstall` closes a running launcher window first (over its
     control link), since its files are about to go.
   - The setup's `open_in` ("terminal" or "codex-app") is saved with it;
     setups saved before M5 have none, which means Terminal. The summary
     (both ways) now also says "These are your real files: changes and
     deletions there happen straight away, with no undo."
   - **Live check** (this Mac, 2026-10-01; `uv run um-codex ui --no-browser`
     with `UMCODEX_DATA_DIR` in a scratch folder, `um-codex-agent:dev`, a
     stub upstream on 127.0.0.1, and a stand-in key store holding a fake
     key, so neither the real key nor the real keychain was used): the page
     in the browser pane, light and dark; a fake key saved through "Add
     key…" (checked against the stub); a setup made through the API (the
     native picker needs a person), shown as a card and opened in the form;
     the summary; "Start in Terminal" opened one Terminal window running
     the launch (containers with `/work` rw and `/mnt/read/reference` ro;
     the fake key not in `docker inspect`, the container's environment or
     its files); the page showed it as running; Stop removed that launch's
     containers and networks only (another session's launch, of another data
     folder, was left running), and the launch's own `um-codex` cleaned up
     and logged Codex's exit. A setup saved with a link in its path showed
     the warning and kept Start disabled until "Use them where they go now"
     was ticked. A stand-in app bundle running `ui --detach` left its server
     running on its own (no Terminal window), and `close_running` ended it.
     In two earlier tries the launch in Terminal ended after about 40 s
     with nothing in the log (consistent with its window being closed; the
     cause wasn't found). The launch now logs Codex's exit code, and the
     signal when its terminal closes, so a repeat can be told apart.
   - Not checked: Windows (the shortcut, the hidden console, Windows
     Terminal and PowerShell windows, the picker), and the picker itself on
     a Mac (it needs a person); the real Mac installer's app.
7. **Acceptance, on a fresh Mac and a fresh Windows machine:**
   1. install from the README in under 20 minutes;
   2. launch with internet off: Codex answers, `curl https://example.com`
      fails, and it can write in the working folder but not in a read-only
      one;
   3. launch with internet on: `curl` works, and `pip install` works;
   4. the key isn't anywhere in the container (`grep -r` over `/`, `env`);
   5. quit, relaunch, and `codex resume` finds the last session;
   6. uninstall leaves nothing but the person's own folders.

## Open questions (with defaults)

- Linux hosts: not in v0. The articles cover Linux, and adding it later is
  mostly the installer.
- An install site like DataLab's: later. Until then, the README has the two
  install commands.
- Codex version: pinned in the image, and updated by a release. The image's
  `npm install -g @openai/codex@<version>` pins the version but isn't
  integrity-locked (no lockfile or hash for Codex's own npm dependencies), so
  a rebuild can pick up different dependency files; the release's provenance
  and digest pin what was actually built.
- Controlling the person's own computer (desktop, apps, their browser): out
  of scope. The container can't reach the host by design. A virtual desktop
  inside the container that the person watches (noVNC) is a possible later
  option, if the group needs GUI apps.
- Codex's own `browser_use`, `in_app_browser` and `computer_use` (checked on
  2026-10-01 with the pinned 0.157.1, in the agent container):
  - `codex features list` shows `browser_use`, `browser_use_external`,
    `browser_use_full_cdp_access`, `computer_use` and `in_app_browser` as
    "stable" and on.
  - In Codex's source at the `rust-v0.157.1` tag, each of these is
    documented as a "Requirements-only gate" for the desktop apps ("Allow
    Browser Use agent integration in desktop apps", "Allow the in-app
    browser pane in desktop apps", "Allow Codex Computer Use"), and nothing
    in the CLI or the terminal interface checks them (only a config test
    reads them). The `[browser_use]` and `[computer_use]` config tables are
    origin and app allow/deny lists for those integrations.
  - In the live check, the terminal Codex in the container offered the
    model no browser or computer tool of its own: the tools in its request
    were `exec_command`, `write_stdin`, the MCP resource tools,
    `request_user_input`, `view_image`, the multi-agent and goal tools,
    `web_search`, and the `mcp__browser` tools when the browser tool was on.
  - So in the terminal Codex inside the container they do nothing; the M2b
    browser tool (Playwright's MCP server) is what gives it a browser. Not
    checked: Codex's desktop app, and whether the Browser Use plugin could
    be installed in the terminal Codex (it would need a browser to drive,
    which the container has only through Playwright).
- The browser tool's size: the headless shell instead of the full Chromium
  build would be smaller, but it's Chrome's old headless mode, which more
  sites treat as a bot. Kept the full build; revisit if the image size
  matters more.
