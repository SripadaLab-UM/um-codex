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
2. **Launch:** the app (or its Desktop or Start menu shortcut) opens a
   terminal that runs `um-codex launch --from-app`, or the person types
   `um-codex` in any terminal.
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
   - `um-codex launch --from-app`: what the app and the shortcuts run (Mac
     and Windows), so the folder the terminal opened in isn't offered as the
     working folder (see the Setup step above).
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
  - `approval_policy`: `never` (the default) or `on-request`, from the setup;
  - `web_search = "live"` when the internet is on, otherwise `disabled`;
  - analytics, feedback and update checks off.

  Codex's other features stay at Codex's defaults: full power.
- **AGENTS.md** in the image tells Codex where things are: the folders, what's
  read-only, and that it has `sudo`. The container copies it into
  `$CODEX_HOME/AGENTS.md` at every start (it's the app's file). It tells
  Codex to read `/etc/um-codex/launch.md` first. That's a plain-text note
  written by the host for each launch and mounted read-only as one file: the
  setup's name, `/work` and each `/mnt/write/*` and `/mnt/read/*` with its
  folder on the computer, internet on or off, and the approval policy.
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
  images/agent/             Dockerfile, AGENTS.md (from DataLab's image: Codex, Node, Python, R; DataLab skills removed; build tools added)
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
3. **M2b, browser tool (asked for on 2026-10-01):**
   - A launch question, offered only when the internet is on: "Browser
     tool: on/off" (default off). It's saved with the setup.
   - When it's on, Codex gets the Playwright MCP server as a tool. It runs
     inside the agent container with headless Chromium, so the browser is a
     fresh one with none of the person's logins. It can open pages, click,
     fill in forms, read pages and take screenshots, and screenshots are
     saved under /work if the person asks.
   - Each browser action needs the person's approval by default (MCP
     `default_tools_approval_mode = "prompt"`). The setup can change that to
     "don't ask".
   - The image gets Chromium and the pinned Playwright MCP package. Its size
     cost is reported in the PR.
   - It never controls the person's own computer, desktop or browser: the
     container can't reach them (see the end of this document).
   - Acceptance: with internet on and the tool on, "open example.com and
     tell me its heading" works after approval. With internet off, the
     question isn't offered.
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
6. **Acceptance, on a fresh Mac and a fresh Windows machine:**
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
  of scope. The container can't reach the host by design. Codex's own
  `browser_use`, `in_app_browser` and `computer_use` features target its
  desktop and IDE apps. Whether any of them works in the terminal Codex
  inside the container is to be checked with the pinned version, and noted
  here. A virtual desktop inside the container that the person watches
  (noVNC) is a possible later option, if the group needs GUI apps.
