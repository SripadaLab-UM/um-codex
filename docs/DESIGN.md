# UM-Codex: design

Status: v0 design, 2026-10-01. Source of most of the machinery:
[IHS DataLab](https://github.com/SripadaLab-UM/ihs-datalab) at `6b6fdca`
(0.3.0b6). Every copied module says so in its first lines.

## What it is

Full-power OpenAI Codex, on U-M GPT Toolkit, running inside a Docker
container on a Mac or Windows computer. There's no web app and no knowledge
base: **Codex's own terminal interface is the front end**, or, on a Mac,
Codex's desktop app working in the container (M6). At each launch the
person decides what the container can see and do, then Codex opens in their
terminal (or the app).

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
   with Codex in it (or, for a setup that opens in the Codex app, UM-Codex's
   copy of the app: M6). Or the person types `um-codex` in any terminal, which
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
   - `um-codex launch [--setup <id or name>] --open app|terminal`: where
     Codex opens (default: this terminal). `--open app` (M6, Mac only) runs
     the launch here, holding the relay, while the Codex desktop app works
     in the sandbox; the launcher window runs it in the background with no
     window. 1 when the app isn't installed, the ssh line isn't allowed (it
     asks in a terminal), or the setup already runs in the app.
   - `um-codex ssh-proxy <setup> [--docker <path>] [--data-dir <path>]`:
     hidden, for ssh's ProxyCommand only (M6). Nothing on stdout but ssh's
     own bytes; 1 with a plain line on stderr when the setup isn't running.
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
     with `--delete-data`, the data folder's contents. It also takes the
     Codex app's ssh entries out (M6): the `Include ~/.ssh/um-codex/config`
     line at the top of `~/.ssh/config` (and its backup, if the file is now
     the same as it; a file UM-Codex made for that one line goes whole) and
     `~/.ssh/um-codex`. It never removes the
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
                                         internet on: agent also joins       /etc/codex    ro  enforced settings
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
- **Codex's settings: three layers** (codex_config.py; checked in the
  rust-v0.157.1 source, `codex-rs/config/src/loader` and
  `config_requirements.rs`). The host writes three files into the launch's
  folder, mounted read-only as one folder at `/etc/codex`, where Codex reads
  them on Linux:
  - **`requirements.toml`**, which Codex enforces over every other setting
    (it refuses to save the keys it fixes):
    - `model_provider = "toolkit"` ("exact provider selection, overriding
      local and session configuration") and `[model_providers.toolkit]`
      (replaces any provider of that name, whole): the gateway's URL, with
      `env_key` for the launch token;
    - `model_catalog_json` (see "Models" below), `check_for_update_on_startup
      = false`, feedback off;
    - `allowed_sandbox_modes = ["read-only", "danger-full-access"]` (Codex
      requires read-only in the list) and, with the internet off,
      `allowed_web_search_modes = ["disabled"]`.
  - **`managed_config.toml`**, a config layer above all the others (the
    person's `config.toml`, profiles, `-c` flags); on Unix this is Codex's
    "legacy managed config", still read by 0.157.1:
    - `model`: the setup's;
    - `sandbox_mode = "danger-full-access"`, because the container is the
      sandbox;
    - `approval_policy`: `never` (the default) or `on-request`, from the setup
      (with "never" and browser actions to approve, a `granular` policy that
      behaves as "never" for commands: see M2b). Codex also makes this the
      only allowed policy, so `/permissions` can't change it, and `codex
      exec` (which asks for "never") falls back to it with a warning;
    - `web_search = "live"` when the internet is on, otherwise `disabled`;
    - with the browser tool on (internet on only), `[mcp_servers.browser]`
      (see M2b);
    - analytics off; the two "switch to a newer model" prompts Codex knows by
      name hidden; `/work` trusted.
  - **`models.json`**: the model catalog (below).

  `$CODEX_HOME/config.toml`, in the setup's volume, is the person's own
  writable file: Codex saves its preferences there (reasoning effort, the
  TUI's notices and choices). Nothing is mounted over it. A model chosen with
  `/model` applies to that session; Codex saves it, says "a higher-priority
  configuration layer overrides the saved value", and the next launch uses
  the setup's model again. A config.toml the person writes can still change
  their own Codex inside their own container (tools, MCP servers, hooks,
  instructions, reasoning, history), but not the provider or its gateway
  (checked live: another provider, a `toolkit` provider with another URL, a
  profile and `-c model_provider=…` all still went to the gateway). And no
  Codex setting can change what the container reaches: the container and
  the relay decide that.

  Before this, config.toml itself was mounted read-only, and the TUI failed
  to save its preferences ("failed to persist config at
  /codex-home/config.toml"). Volumes from then hold an empty, root-owned
  config.toml (Docker's mount point); Codex replaces it at its first save (it
  writes a new file and renames it over the old one, and the folder is the
  agent's), so nothing needs migrating: checked live.

  Codex's other features stay at Codex's defaults: full power.
- **Models.** Without a catalog, Codex asks the provider for `/models`, and
  can't read the Toolkit's answer (`{"object", "total", "data": [{"id",
  "slug", "canonical_slug", "object"}]}`; Codex wants `{"models": [...]}`
  with instructions, tools, reasoning levels and context window per model:
  "failed to decode models response"). It then falls back to the list built
  into Codex, whose entries offer upgrades: in 0.157.1, `gpt-5.6-terra`
  offers `gpt-6-sol`. So a launch on the default model showed a "switch to
  GPT-6-Sol" prompt, and accepting it changed the session's model. Now each
  launch writes a catalog (`model_catalog_json`, enforced): Codex's own
  entries (`codex debug models --bundled`, run in a throwaway container from
  the agent image with no network) for the models the Toolkit lists
  (`toolkit.list_models`, on the host, with the key) and the setup's model,
  all shown in `/model`, with no upgrade offers. With a catalog Codex never
  asks for `/models` (its static model manager) and lists only these. A
  Toolkit model Codex has no entry for (`gpt-4.1`, `o3`, …) isn't listed in
  `/model`, but still works as a setup's model, with Codex's fallback
  settings. If the Toolkit can't be reached the catalog is the setup's model
  alone; if Codex's list can't be read the launch runs without a catalog.
- **AGENTS.md** in the image tells Codex where things are: the folders, what's
  read-only, and that it has `sudo`. The container copies it into
  `$CODEX_HOME/AGENTS.md` at every start (it's the app's file). It tells
  Codex to read `/etc/um-codex/launch.md` first. That's a plain-text note
  written by the host for each launch and mounted read-only as one file: the
  setup's name, `/work` and each `/mnt/write/*` and `/mnt/read/*` with its
  folder on the computer, internet on or off, the browser tool (on or off,
  and whether each action is approved), and the approval policy.
- **The launch's files** (`codex/` with the three files above, `launch.md`,
  `gateway.conf`, and the env file with the token, deleted once the agent
  has started) are in
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
    codex_config.py         Codex's enforced settings and model catalog (from DataLab's config.toml)
    codex_app.py            "Open in: Codex app" (M6): ssh files, ssh-proxy, the container's ssh side,
                            the app copy, the launch held while the app uses it
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
                            smoke.sh, browser-check.js (the browser tool's MCP check),
                            sshd_config, profile.sh, umcodex-token (the Codex app's ssh entry, M6)
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
   - **managed_config.toml** (config.toml until the settings were split into
     layers; only with the internet and the tool on):
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
     `ui.json` (readable by the person only: mode 0600 on a Mac; on Windows,
     where that mode does nothing, the file takes `%LOCALAPPDATA%`'s
     permissions, which give the person, SYSTEM and administrators access
     and no other account); a second `um-codex ui` asks the
     running one, with that secret, for a new sign-in link and opens that.
     `--detach` waits up to 10 s for the background server's `ui.json`
     (carrying a nonce of that start) or for it to hand over to one already
     running; otherwise it says so in a native message box (`osascript
     display dialog` on a Mac, `MessageBoxW` on Windows) pointing to
     `um-codex.log`, where what the server printed and any exception are
     logged.
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
       "Open in": Terminal, or Codex app (M6);
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
     - Codex app: see M6.
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
   - `um-codex uninstall`, `um-codex update` and `--rollback` close a
     running launcher window first (over its control link): its files are
     about to go or be replaced. If the installed version still changes
     under a running window (an installer run again), the page says "UM-Codex
     X is installed; this window is still Y" with Reopen, which ends this
     server and starts the installed version's (`bin/um-codex ui --detach`).
   - Saved setups are changed under a lock (`setups.toml.lock`: a thread
     lock and an OS file lock), each write through a temporary file of its
     own and a rename, so neither the page's parallel requests nor a
     launch's `mark_used` loses another's change.
   - Start is refused while Docker isn't running ("Docker Desktop isn't
     running. Open it first."), with Open Docker Desktop (or, on Windows,
     Fix it…) on the summary page. While a start runs its button is
     disabled; the card says "Starting…" until the launch's `launch.json`
     shows it running, then "Running · Stop" in place of Start.
   - The page: paths show the folder's name in bold with its parent
     shortened (`~`, a middle ellipsis), the whole path in the tooltip and a
     Copy button; the summary shows each folder as `/work ← ~/…/thesis`.
     The first run shows three steps (add the key, Docker running, a new
     setup), and a new setup opens on "Choose working folder…". The form
     reports every problem at once, in its order, each tied to its field
     (`aria-describedby`), and focuses the first; focus stays put when the
     form redraws; questions before Delete and Stop start on Cancel. The key
     field shows dots but isn't a password field (`-webkit-text-security`;
     `type=password` with `autocomplete=new-password` where that's not
     supported), so browsers don't offer to save it, and it's emptied
     whenever its box closes. The page keeps asking for the state while a
     box is open, so an open box never counts as the page being gone.
   - Diagnostics: before a launch removes its containers it logs the
     agent's state (status, exit code, OOM-killed, finish time) and the last
     lines it printed; the watchdog prints "watchdog: launch gone, ending"
     before it ends one; the server logs each Stop it's asked for, and
     whether the native picker was cancelled (osascript's -128) or failed
     (shown on the page).
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
   - **Live check after the review fixes** (same stand-ins, a fresh data
     folder): the first-run checklist; the key box shows dots in a text
     field and Escape empties it (whether a browser offers to save it can't
     be seen in the test browser); an empty new setup reported both
     problems at once and focused "Choose working folder…"; focus stayed on
     the Internet switch through its redraw; cards and the summary showed
     short paths and `/work ← …`; Start went "Starting…" then "Running ·
     Stop" on the card; Stop's question started on Cancel; the log had the
     Stop request and the agent's state. The Docker-stopped summary was
     checked by setting the page's state (Docker itself wasn't stopped:
     other sessions use it). `ui --detach` returned at once with its
     server up, and a second one handed over to it.
   - Not checked: Windows (the shortcut, the hidden console, Windows
     Terminal and PowerShell windows, the picker), and the picker itself on
     a Mac (it needs a person); the real Mac installer's app.
7. **M6, "Open in: Codex app" (asked for on 2026-10-01, after the spike;
   built on branch `m6-codex-app`).** Codex's desktop app (OpenAI's
   ChatGPT desktop app, `ChatGPT.app`, bundle id `com.openai.codex`) as the
   front end of a launch, with every file, command and model call inside
   the container. From the spike (`docs/spikes/2026-10-01-codex-desktop-app.md`)
   and its hands-on results (`-test-results.md`); the test build on branch
   `spike-codex-app` (21db539) was ported, not merged. **Mac only for now**
   (see Windows below). `codex_app.py`.
   - **The route:** the app's SSH "Connections". Each setup is one stable
     ssh host, `umcodex-<setup id>` (the app keeps its switch, projects and
     chats by that name), reached through `docker exec`, so nothing listens
     on a port and it works with the internet off.
   - **The image** (`images/agent`): `openssh-server` (with `sftp-server`;
     the app uses sftp for files), `/run/sshd`, no host keys (each container
     makes its own), `agent`'s password field `*` (sshd without PAM refuses
     a locked account even for a key) and its login shell bash (the app runs
     `$SHELL -l -i -c`). `/etc/um-codex/sshd_config`: key-only, `AllowUsers
     agent`, no root, no passwords or keyboard-interactive, no agent or X11
     forwarding, `AllowTcpForwarding local` with `PermitOpen` only to the
     container's own localhost (the app's previews of the container's
     ports), no tunnels or remote forwards, `internal-sftp`, and `SetEnv`
     with the image's variables. `/etc/profile.d/um-codex.sh` exports
     `CODEX_HOME=/codex-home` and the PATH for login shells (without it the
     app-server would use `~/.codex`). `/usr/local/bin/umcodex-token` prints
     the launch token file. `smoke.sh` checks `sshd -t`, the login shell's
     `CODEX_HOME` and `codex`, and the helper.
   - **This computer's ssh files:**
     - `~/.ssh/um-codex/` (0700): a key pair per setup
       (`<setup>_ed25519`, 0600, kept between launches) and `config` (0600),
       rewritten whole at each launch in the app: one `Host` per setup with
       a key, with `User agent`, its `IdentityFile`, `IdentitiesOnly`,
       `IdentityAgent none`, `ForwardAgent no`, `ForwardX11 no`, no password
       or keyboard-interactive, `StrictHostKeyChecking no` and
       `UserKnownHostsFile /dev/null` (the transport is `docker exec` on this
       computer, and every container has a new host key), and `ProxyCommand
       <um-codex> ssh-proxy <setup> --docker <docker>`, with absolute paths
       (the app checks the command in its own short PATH): an installed copy's
       launcher (`<app>/bin/um-codex`, which follows updates), else this
       Python (`-m umcodex`); `--data-dir` only when `UMCODEX_DATA_DIR` is
       set. Words with spaces are double-quoted, `%` doubled (ssh's tokens).
       The app adds only `BatchMode`, timeouts and keep-alives itself.
     - **The one line in the person's own file:** `Include
       ~/.ssh/um-codex/config` at the very top of `~/.ssh/config` (the app
       follows only top-level Includes; an Include after a `Host` belongs to
       it). Added **only with consent**: the launcher shows the explanation
       (`codex_app.INCLUDE_EXPLAINED`) with Allow the first time an app setup
       is started; the terminal asks the same with "[y/N]"; a launch with
       no terminal and no line stops with a plain message. The file is
       backed up first (`~/.ssh/config.um-codex-backup`, once), changed in
       place (its permissions kept), or created 0600 if there was none.
       `um-codex uninstall` removes the line, the backup when the file is
       then the same as it, and `~/.ssh/um-codex`. Deleting a setup removes
       its key and Host.
   - **The container:** a launch as any other (relay, gateway, token,
     folders, internet on or off), labelled `umcodex.ssh=<setup>`. Then, as
     root through `docker exec`: a host key, the setup's public key in
     `agent`'s `authorized_keys`, and the launch token in
     `/run/um-codex/token` (0640 root:agent, written from the container's
     own environment, never a command line). One app launch per setup at a
     time (the proxy must find exactly one sandbox).
   - **`um-codex ssh-proxy <setup>`** (hidden): finds the running agent by
     label (setup, data folder, `umcodex.app`) and becomes `docker exec -i
     -u root <agent> /usr/sbin/sshd -i -f /etc/um-codex/sshd_config`: one
     sshd per connection, on ssh's stdin and stdout. With nothing running it
     says so on stderr and exits 1.
   - **Codex's settings in the container** go in the same `/etc/codex`
     layers as every launch (#12), with two differences for an app launch:
     - `requirements.toml`: the provider's credential is
       `[model_providers.toolkit.auth] command =
       "/usr/local/bin/umcodex-token"` instead of `env_key` (ssh sessions
       don't get `docker run -e`; Codex 0.157.1 refuses both together), and
       `default_permissions = ":danger-full-access"` with
       `[allowed_permission_profiles]` allowing only `:danger-full-access`.
       The app starts each chat with a permission profile of its choosing
       (`thread/start` `permissions`); a disallowed one falls back to the
       requirements' default (core config's `resolve_default_permissions`),
       where a disallowed legacy `sandbox` falls back to read-only. In the
       container both read-only and `:workspace` need a Linux sandbox it
       can't make: checked live, `permissions = ":workspace"` without these
       lines gave `readOnly` and every command failed with bwrap's "No
       permissions to create a new namespace"; with them, no profile,
       `:workspace` and `:read-only` all ran with `dangerFullAccess`.
       `configRequirements/read` returns both, which the app reads to decide
       what it offers.
     - `managed_config.toml`: `forced_login_method = "api"`, so no ChatGPT
       sign-in is offered inside the container (it would put ChatGPT tokens
       in the setup's volume).
   - **UM-Codex's copy of the app:** a second, separate copy, as the app's
     own "Codex Demo" launcher opens one: `open -n --env
     CODEX_HOME=<data>/codex-app/codex-home --env
     CODEX_ELECTRON_USER_DATA_PATH=<data>/codex-app/user-data <app> --args
     --user-data-dir=<data>/codex-app/user-data [<link>]`. The person's own
     copy and `~/.codex` are never touched. The app is found in
     `/Applications` or `~/Applications` (`ChatGPT.app`, or `Codex.app`), by
     its bundle id, else through Spotlight (`mdfind
     kMDItemCFBundleIdentifier`). If the copy is already running (a main
     process with its `--user-data-dir` in its arguments), no second one is
     started: it's brought forward (AppKit's `activateWithOptions` through
     `osascript -l JavaScript`, which needs no permission to control other
     apps); if macOS declines, the launcher says to switch to it.
     - **Its own (local) side:** its `config.toml` gets UM-Codex's provider
       at each launch (the Toolkit through this launch's relay on
       127.0.0.1, `auth.command = /bin/cat <data>/codex-app/launch-token`, a
       0600 file removed when the launch ends, `forced_login_method =
       "api"`, analytics, feedback and update checks off); the app's other
       settings there are kept. So it opens with no sign-in (the test). Its
       local chats run on the Mac, not in the sandbox, and work only while a
       launch runs; the launcher says so.
     - Not installed: "Codex app" in the form is disabled with "The Codex
       app isn't installed. It's part of OpenAI's ChatGPT desktop app: get
       it from https://chatgpt.com/download, then come back. Terminal works
       in the meantime."
   - **The first time for a setup** (the one-step link with `projectPath`
     and `enabled=true` didn't connect in the hands-on test): the copy opens
     on the documented `codex://settings/connections/ssh/add?name=<alias>`
     link (it adds the host, switched off), and the launcher shows the steps:
     switch to UM-Codex's Codex window; Settings → Connections, turn on
     `<alias>`; start a chat in the project "work" (Remote · `<alias>`), or
     add the folder `/work`; check that it shows Remote · `<alias>`. The
     launch watches the container every 2 s for the app's `codex app-server
     --listen` (`pgrep -f`, as the test's monitor did) and then marks the
     launch "Connected ✓" (`launch.json`) and the setup as connected once
     (`<data>/codex-app/hosts.json`). Later launches of that setup pass no
     link (it would switch the host off again) and show "Waiting for the
     Codex app to reconnect…" with "It doesn't connect: show the steps".
     If the copy was already running the first time, the link can't reach
     it; the steps are the same (the host is in the ssh config the app reads).
   - **The launcher window:** "Open in: Codex app" is enabled when the app
     is installed. Start for an app setup asks for the ssh line once (above),
     then starts `um-codex launch --setup <id> --open app` in the background
     (its own session, no window; output to `<data>/ui/app-launch.log`, its
     steps to `um-codex.log`), which holds the relay until it's stopped. The
     running list and the card say "Running in the Codex app"; below it the
     guide or "Connected ✓", and the plain lines: "Chats must show Remote ·
     `<alias>` to run in the sandbox. Other chats in that Codex window run on
     this computer, not in the sandbox, and work only while a setup is
     running." and "The Codex app's own browser runs on this computer, not
     in the sandbox; use the Browser tool for browsing inside it." (also on
     the summary before Start). Stop removes the containers (the launch then
     ends and cleans up); its question adds that the app will say it can't
     reconnect, which is expected.
   - **Lifetime:** the launch runs until Stop (or Ctrl-C when it was started
     in a terminal). If `um-codex` is killed, the watchdog ends the container
     as for any launch. The app's remote app-server lives in the container
     and goes with it.
   - **Windows:** the ssh side is written to work there (Windows OpenSSH
     reads `%USERPROFILE%\.ssh\config` and runs a double-quoted ProxyCommand
     itself; `ssh-proxy` runs `docker exec` as a child, since Windows has no
     exec), but it isn't verified, and opening a second copy of the Store
     app with its own `CODEX_HOME` and profile isn't known to work (the
     spike's open question; packaged apps don't take a plain `open -n
     --env`). So "Codex app" is disabled on Windows ("works with UM-Codex on
     a Mac only, for now"), and `--open app` refuses there.
   - **Live check** (this Mac, 2026-10-01; `um-codex-agent:m6` built from
     this branch, the launcher's API with a scratch data folder, the real
     key through the relay and the Include line already present, so the
     person's own app, `~/.codex` and key were never touched):
     - Start through the API ran the launch in the background and opened
       UM-Codex's copy on the add link (its process carried the scratch
       `--user-data-dir`); the person's own copy kept running.
     - `ssh umcodex-<id>` through the ProxyCommand: `agent`,
       `CODEX_HOME=/codex-home`, codex-cli 0.157.1, `/work` the scratch
       folder, the token file 0640 root:agent; with the internet off,
       `curl https://example.com` failed to resolve.
     - The app's own commands replayed exactly (its login-shell wrapper,
       `command -v codex`, `codex --version`, the `nohup codex -c
       features.code_mode_host=true app-server --listen unix://` start, then
       `ssh -T … exec codex app-server proxy` with a WebSocket handshake):
       `initialize` gave `codexHome` `/codex-home`; `account/read`
       `requiresOpenaiAuth: false`; `config/read` for `/work`
       `danger-full-access`, `never`, `toolkit`, `forced_login_method
       "api"`; a turn ran `pwd`/`whoami` (`/work`, `agent`) and wrote a file
       that appeared on the Mac, through the Toolkit.
     - The launch noticed the app-server and showed "Connected ✓" on the
       page; Stop ended the launch, removed the containers and the copy's
       token file, and ssh then said the setup isn't running.
     - `codex exec` over ssh wrote a file through the Toolkit.
     - A second launch (internet on, browser tool on) passed no link, found
       the copy running and brought it to the front; `curl` gave HTTP 200
       and the browser tool's MCP server was in the managed settings.
     - Permissions: see above (`:workspace` → read-only → bwrap failure
       without the requirements lines; all full access with them).
     - Deleting the setup removed its key and Host.
   - **Not checked** (needs a person or computer use, steps in
     `docs/spikes/2026-10-01-m6-codex-app-gui-test.md`): turning the host on
     and opening `/work` in the copy, that the app's permission control
     shows only full access, that a later launch reconnects with no steps,
     the copy's local chats after a launch with a new relay port, the
     bring-forward when the copy is behind other windows, and Windows.
8. **Acceptance, on a fresh Mac and a fresh Windows machine:**
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
    browser tool (Playwright's MCP server) is what gives it a browser. In
    the desktop app (M6), the in-app browser runs on the Mac, not in the
    sandbox, and a remote chat couldn't drive it (the hands-on test). Not
    checked: whether the Browser Use plugin could
    be installed in the terminal Codex (it would need a browser to drive,
    which the container has only through Playwright).
- The browser tool's size: the headless shell instead of the full Chromium
  build would be smaller, but it's Chrome's old headless mode, which more
  sites treat as a bot. Kept the full build; revisit if the image size
  matters more.
