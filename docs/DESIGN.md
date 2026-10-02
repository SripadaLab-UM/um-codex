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
   launcher window in the browser (`um-codex ui`, M5 below). Usually one
   click (M7): the first time, "Choose a folder and start…" and Codex
   starts there with the defaults; after that, "Start <last setup>". Saved
   setups are cards that always show what Codex can do with them; Start opens
   UM-Codex's copy of the Codex app (M6) or a terminal with Codex in it. Or the
   person types `um-codex` in any terminal, which asks the questions below in
   the terminal.
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
     Codex opens (default: this terminal). `--open app` (M6; Windows experimental) runs
     the launch here, holding the relay, while the Codex desktop app works
     in the sandbox; the launcher window runs it in the background with no
     window. 1 when the app isn't installed, the ssh line isn't allowed (it
     asks in a terminal), or the setup already runs in the app.
   - `um-codex ssh-include` (M7): the installers' one question about the
     Codex app's line in `~/.ssh/config`. Asks only on a Mac with the Codex
     app installed and the line missing ("Add that line now? [Y/n]", Return
     is yes). No terminal: says so and exits 1, adding nothing. A "no" is
     remembered in the data folder and not asked again unless
     `--ask-again`. Exit 0 when the line is there or isn't needed here, 1
     when it wasn't added.
   - `um-codex update --from-launcher` (hidden, M7): the launcher window's
     Update; as `um-codex update`, but it doesn't close the window that ran
     it.
   - `um-codex ssh-proxy <setup> [--docker <path>] [--data-dir <path>]`:
     hidden, for ssh's ProxyCommand only (M6). Nothing on stdout but ssh's
     own bytes; 1 with a plain line on stderr when the setup isn't running.
   - `um-codex launch --from-app`: what the app and the shortcuts ran before
     M5 (kept working for them), so the folder the terminal opened in isn't
     offered as the working folder (see the Setup step above).
   - `um-codex launchers --write <path>...`: the installers' way to write
     the Mac app (a `.app` folder) or the Windows shortcuts (`.lnk` files)
     at the places they chose; `um-codex launchers --refresh [--dry-run]`:
     what `um-codex update` and `--rollback` run with the version switched
     to, rewriting this install's own launchers where they are if they're out
     of date (never through a link, never another account's app). Exit 0, or
     1 when one couldn't be written (it says what to do). A rollback to a
     version without the command (0.1.0-alpha.1) has the newer code write
     that version's launchers (format 1).
     `launchers.py` is the one place that says what they contain
     (docs/INSTALLING.md, "Keeping the app and shortcuts up to date").
   - `um-codex key [--from-stdin]`: exit 0 saved, 1 refused or invalid,
     2 cancelled (Ctrl-C at the masked prompt, or an empty entry). The Mac
     installer runs `um-codex key < /dev/tty`, so the key never passes
     through its shell; `--from-stdin` reads one line.
   - `um-codex pull` (the installers' image step, and `um-codex update`'s,
     which runs the new version's own): pulls every image in `images.json`;
     a local `:dev` image that's already present is skipped, and so is an
     image pinned by digest that's already here (that exact version can't
     have changed). A failed `docker pull` is tried twice more (after 3 s,
     then 10 s), and if the image turns out to be here by that digest
     after all, that's success: a registry can answer "not found" for a
     moment (the Windows tester's update). Nonzero on failure, with a
     message that says which kind (Docker isn't running or stopped, the
     registry or the network, the disk full) and quotes Docker's own line.
     In a terminal Docker's progress is shown; otherwise (the launcher's
     Update writes to a file) `docker pull --quiet` and one line per image.
     Each line is flushed before a child process writes, and `update`'s
     steps flush too, so the order is right when stdout is a file or a pipe.
   - `um-codex doctor [--quiet] [--fix-docker]`: `--quiet` prints nothing but
     one line on failure (a Toolkit that can't be reached, off the VPN, is a
     note there, not a failure; a refused key is a failure); `--fix-docker` opens Docker Desktop and, on
     Windows, offers the logon-right fix (as the launch does).
   - `um-codex update [--rollback]`: 0 updated (or already the newest),
     1 refused or failed (a launch running, no pinned release key, a
     development copy, a release that fails a check), with nothing changed.
   - `um-codex uninstall [--delete-data|--keep-data] [--yes]`: first asks
     "Uninstall UM-Codex? [y/N]" (no: nothing removed, exit 1). Then it removes, by
     label only, its data folder's containers and networks (its
     `umcodex.instance` label; and, with `--delete-data`, each of its
     setups' Codex home volume), the key, the images
     (asked first; the gateway's nginx only if no container uses it) and,
     with `--delete-data`, the data folder's contents. It also takes the
     Codex app's ssh entries out (M6): its own data folder's
     (`~/.ssh/um-codex/installs/<id>`), then, unless another UM-Codex data
     folder on this computer still has hosts there, the `Include
     ~/.ssh/um-codex/config` line at the top of `~/.ssh/config` (and its
     backup, if the file is now the same as it; a file UM-Codex made for that
     one line goes whole) and `~/.ssh/um-codex`. It never removes the
     program files (`<data folder>/app`, which the installers own and their
     uninstall scripts remove afterwards). From DataLab's `setup.uninstall`,
     with the #36 fixes. `--yes` asks nothing: images go, and data stays
     unless `--delete-data`. With no terminal to answer a question
     (EOF), `um-codex` takes it as no and exits 1, without a traceback.
     **Scope.** Everything goes by the data folder's own instance label,
     so another data folder's containers, networks and volumes (a
     development or test copy's, whose launch may be running) are never
     removed; it says when some were left. The key (there's one, in the
     keychain) and the images are shared by every data folder, so only the
     installed copy's data folder (`paths.default_data_dir`, compared
     resolved) removes them, and the images only when no other data
     folder's containers are here. An uninstall of another data folder
     (`UMCODEX_DATA_DIR`) keeps both and says so, and takes out only its
     own ssh entries (the Include line stays while others use it).

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
      requires read-only in the list; managed_config.toml's `sandbox_mode`
      already limits the modes the same way, so this is defence in depth in
      case that legacy file goes) and, with the internet off,
      `allowed_web_search_modes = ["disabled"]`.
  - **`managed_config.toml`**, the top config *layer*, above the person's
    `config.toml`, profiles and `-c` flags; on Unix this is Codex's "legacy
    managed config", still read by 0.157.1. It isn't above everything:
    options passed as overrides rather than config (`codex -m/-s/-a`, the
    app server's `thread/start` parameters, `/model` for a session) win over
    it. For the model that's harmless: every model goes through the gateway.
    For the sandbox it isn't a way out either: a mode the requirements don't
    allow (`-s workspace-write`, or a client sending it) is refused and
    Codex falls back to **read-only**, where every command fails (Codex's
    own sandbox, bwrap, can't run in the container). M6 (the Codex app) must
    check what the app sends in `thread/start`; the hands-on test showed
    "Full access" in the app, so it looks fine. This layer holds:
    - `model`: the setup's;
    - `sandbox_mode = "danger-full-access"`, because the container is the
      sandbox;
    - `approval_policy`: `never` (the default) or `on-request`, from the setup
      (with "never" and browser actions to approve, a `granular` policy that
      behaves as "never" for commands: see M2b). Codex also makes this the
      only allowed policy, so `/permissions` can't change it, and `codex
      exec` (which asks for "never") falls back to it with a warning. With
      the granular policy the TUI shows the same warning ("Configured value
      for `approval_policy` is disallowed by requirements; falling back to
      required value Granular…") once a turn starts: harmless, the policy
      stays the setup's and browser actions are still asked about (checked
      live);
    - `web_search = "live"` when the internet is on, otherwise `disabled`;
    - with the browser tool on (internet on only), `[mcp_servers.browser]`
      (see M2b), each of its tools' approval pinned, and
      `[features.code_mode] direct_only_tool_namespaces = ["mcp__browser"]`
      (below);
    - analytics off; `/work` trusted; `[notice.model_migrations]
      "gpt-5.4-mini" = "gpt-6-luna"`, marking as seen the one "switch to a
      newer model" prompt built into Codex 0.157.1 (every other one comes
      from a catalog's upgrade offers, and UM-Codex's catalog has none).
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
  settings; Codex then warns "Model metadata for `<model>` not found.
  Defaulting to fallback metadata; this can degrade performance and cause
  issues." Codex's list is read once per agent image (kept in the data
  folder's `codex-models/`, by image ID); the throwaway container is named
  `<agent>-models` and removed with the launch's other containers. If the Toolkit can't be reached the catalog is the setup's model
  alone; if Codex's list can't be read the launch runs without a catalog.
- **AGENTS.md** in the image tells Codex where things are: the folders, what's
  read-only, and that it has `sudo`. The container copies it into
  `$CODEX_HOME/AGENTS.md` at every start (it's the app's file). It tells
  Codex to read `/etc/um-codex/launch.md` first. That's a plain-text note
  written by the host for each launch and mounted read-only as one file: the
  setup's name, `/work` and each `/mnt/write/*` and `/mnt/read/*` with its
  folder on the computer, internet on or off, the browser tool (on or off,
  and whether each action is approved), and the approval policy.
- **Research and development tools and skills** (`images/agent/skills/`):
  the image adds uv, ipykernel/nbconvert (notebooks run headless; no
  Jupyter server), Streamlit and Dash (Python), renv and Shiny (R), Quarto
  1.10.18 (SHA256-checked for amd64 and arm64), TypeScript and esbuild.
  Quarto's own Pandoc and Typst are the image's `pandoc` (R Markdown uses it
  too) and `typst`, so HTML, Word and PDF (Typst, no TeX) reports work
  offline. Python packages are installed from `requirements.txt` with
  hashes (`--require-hashes`, compiled for Linux on both architectures).
  - Eight skills (environments, analysis, research handoffs, figures,
    reports, notebooks, dashboards, development) are short offline
    instructions. They're user skills: Codex 0.157.1 finds them in
    `$HOME/.agents/skills` (HOME=/home/agent; `ext/skills/src/host_roots.rs`)
    and they're on by default, in the terminal and over ssh. Not
    `/etc/codex/skills`: the launch's `/etc/codex` mount hides the image's.
    No `[[skills.config]]` entries: Codex reads those only from the person's
    `config.toml` and `-c` flags (`config/src/skills_config.rs`), so a
    person can still turn one off. `~/.agents` belongs to agent, so a
    session can add skills there, for that launch; a project's
    `.agents/skills` under `/work` is kept.
  - Codex's own bundled skills (skill-installer, imagegen, openai-docs, …)
    reach GitHub or OpenAI, so managed_config.toml turns them off
    (`[skills.bundled] enabled = false`; `bundled_skills_enabled_from_stack`
    reads the effective config, which includes that layer): Codex neither
    installs them in `$CODEX_HOME/skills/.system` nor lists them.
  - Helpers: `um-codex-env` makes a project `.venv` without downloads (with
    `--image-packages`, a `.pth` fallback to `/opt/venv`, recorded; it never
    replaces an existing one). R projects use renv with its cache off, so the
    library is copied into the project. `um-codex-dashboard` runs Shiny
    (3838), Streamlit (8501) or Dash (8050) on the container's 127.0.0.1
    (`--host` to change), with debug/reload/browser launch off, and refuses
    a port in use. UM-Codex publishes no ports: the Codex app's ssh
    connection can forward one (sshd allows local forwarding to loopback);
    a terminal launch has no host preview.
  - The build's smoke test (run with `--network=none`) executes all of this:
    a notebook (and its HTML export), Quarto HTML/DOCX/Typst PDF, R Markdown
    HTML/DOCX, Pandoc's Typst PDF, an image-backed venv, a copied renv
    library, TypeScript and esbuild builds, each dashboard's button and
    callback in headless Chromium (and that it listens only on loopback),
    and Codex's app-server `skills/list` (the eight skills enabled; Codex's
    bundled ones listed by default and absent with them off).
  - **/codex-home stays empty in the image.** Docker copies it into every new
    setup's volume (`containers.py` mounts the volume without `nocopy`), so
    anything Codex writes there at build time (installation id, sqlite
    databases, bundled skills) would be shared by every setup. Every Codex
    run in the checks uses a throwaway `CODEX_HOME`, and the last build stage
    fails if `/codex-home` holds anything but alpha.3's `tmp/arg0`. It also
    removes the smoke test's caches and temp folders.
  - The arm64 image is 6.40 GB (alpha.3: 5.57 GB), mostly Quarto (about
    440 MB) and the Streamlit/Dash Python stack. amd64 is first
    smoke-tested by release CI's native amd64 runner, which must pass before
    a release: under emulation on an Apple silicon Mac the notebook kernel
    check times out (as ZeroMQ subprocesses do under Rosetta).
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
    launchers.py            what the Mac app and Windows shortcuts contain; written by the installers,
                            brought up to date by update, rollback and a launch (when the recorded format differs)
    gateway.conf            (from DataLab, /mcp removed)
    images.json             pinned image digests (stamped by the release)
  images/agent/             Dockerfile, AGENTS.md (from DataLab's image: Codex, Node, Python, R; DataLab skills removed; build tools added),
                            smoke.sh, browser-check.js (the browser tool's MCP check),
                            skills/ (UM-Codex's skills), project-env.py, dashboard.py and their checks
                            (capability-check.py, dashboard-check.js, skills-check.py),
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

     [mcp_servers.browser.tools.browser_navigate]   # and each of the 25 tools
     approval_mode = "prompt"   # read-only tools, or the person said no: "approve"

     [features.code_mode]
     direct_only_tool_namespaces = ["mcp__browser"]
     ```
     - **Each tool's approval is pinned** (from `src/umcodex/browser_tools.json`,
       the pinned server's `tools/list`; a test checks it against the image
       when Docker and the image are there). A per-tool `approval_mode` beats
       `default_tools_approval_mode` (`core/src/mcp_tool_call.rs`), and
       config.toml is the person's (so the agent's) to write: without the
       pins, the agent could switch off the approvals for later launches.
       This layer beats config.toml. It's a soft control all the same: with
       full access in the container, the agent could drive Chromium itself
       with shell commands, unasked.
     - **Code-mode models.** gpt-5.6-* and gpt-6-* run "code mode only":
       their tools are nested in one `exec` tool, and MCP tools are
       deferred, missing from its description. `direct_only_tool_namespaces`
       (`features/src/feature_configs.rs`; tested upstream in
       `core/tests/suite/mcp_tool_exposure.rs`) keeps the browser's tools as
       direct, top-level model tools. Checked live (stub upstream,
       gpt-5.6-terra): the first request carried the `mcp__browser`
       namespace with its 25 tools; and with `approval_mode = "approve"`
       written into config.toml for `browser_navigate` (and as the default),
       Codex still asked "Allow the browser MCP server to run tool
       browser_navigate?", and ran it once allowed.
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
       Start and Back (M7 replaced this page: the facts are on the card).
       If a saved folder now resolves somewhere else, the
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
     that runs `bin\um-codex.exe ui --detach`; the server then has a console
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
   `spike-codex-app` (21db539) was ported, not merged. **On Windows, experimental**
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
     - **Windows permissions:** Windows OpenSSH accepts its files when only
       the person, SYSTEM and Administrators have rights to them. Python
       3.13's `mkdir(mode=0o700)` gives a Windows folder SYSTEM,
       Administrators and OWNER RIGHTS, and ssh.exe refuses a config file
       with OWNER RIGHTS ("Bad permissions"); through the Include line that
       broke every host in the person's `~/.ssh/config` (found on a Windows
       laptop, 2026-10-02). What a new file inherits also depends on the
       folder above and the account (on CI's administrator account a file in
       an inheriting folder still got OWNER RIGHTS). So on Windows the folders
       are made without a mode, and UM-Codex's own ssh folders and files
       (`~/.ssh/um-codex`, `installs/<id>`, `config`, `hosts`, `owner`,
       `missing`, the keys, and `~/.ssh` and its `config` only when UM-Codex
       makes them) are set with `icacls` to exactly those three (the
       person's SID from `whoami /user`), not inherited. A `~/.ssh` that's
       there keeps its own. CI's Windows job checks it with the real ssh.exe,
       in a folder that hands down OWNER RIGHTS.
     - `~/.ssh/um-codex/` (0700) is shared by every UM-Codex data folder on
       the computer (the installed copy's, a development copy's
       `UMCODEX_DATA_DIR`). Each one keeps its own files in
       `installs/<install id>/` (0700; the id is the data folder's launch
       instance label, `containers.instance_of`): a key pair per setup
       (`<setup>_ed25519`, 0600, kept between launches), `hosts` (its Host
       blocks) and `owner` (its data folder's path). At each launch in the
       app it rewrites its own `hosts`: one `Host` per **saved** setup that
       has a key there (its own keys that belong to no saved setup are
       removed then). Then `config` (0600) is written whole (a temporary
       file and a rename) as all data folders' `hosts` together. Every change
       there is made under one lock (`~/.ssh/um-codex/.lock`, `locks.held`),
       so launches of different data folders at once can't lose each other's
       hosts. A data folder never deletes another's files on sight. When
       another's data folder is **definitively** gone (the folder it was in
       is there and readable, and it isn't), its Hosts leave `config` at
       once and the time is noted (`missing.json`); its folder is removed
       (logged) only after 30 days gone. Its keys open only its own
       sandboxes and are made anew at its next launch, so removing them
       loses nothing; the wait is for a folder put back, and keeps `~/.ssh`
       from collecting private keys of throwaway development folders. A
       data folder that can't be told about (on an unmounted volume, an
       owner file or folder that can't be read, no owner file) keeps its
       Hosts and keys. A data folder is never made where its parent isn't
       (nothing under an unmounted volume's path on the boot disk), and
       `~/.ssh` is made 0700 if it isn't there. The
       installed copy's hosts keep the plain alias `umcodex-<setup>`; another
       data folder's carry its install id, `umcodex-<setup>_<first 8 of the
       id>` (a setup id never has `_`), so two data folders' hosts never
       share a name; the seeded app state, the local-chats provider and the
       launch's state use the same alias. Up to 0.1.0a3 each data folder
       kept its keys straight in `~/.ssh/um-codex` and each launch rewrote
       `config` from its own setups, removing every other key and Host
       (another data folder's too: found in the M7 check). The first launch
       now moves this data folder's flat keys into its own folder (and
       removes its flat keys of deleted setups); any other flat key is left
       alone. A flat key's data folder is read from its Host's ProxyCommand
       (`--data-dir`, else the installed copy's). The Hosts in `config` that
       use a flat key still there are kept after the others, until that key
       or its data folder is gone. A setup id has no `_` (a saved one with
       it is left out, with the reason in the log).
     - **Mixed versions:** a copy still on 0.1.0a3 knows none of this. Its
       launch rewrites `config` with only its own Hosts (the others' come
       back at their next launch) and removes flat keys it doesn't know (it
       never looks in `installs/`), and its uninstall removes the line and
       all of `~/.ssh/um-codex`. Update every copy on the computer.
       The app follows Includes in included files too (its bundle, 26.928:
       each file's top-level `Include`s, with globs), but one plain file
       doesn't rely on that. Each `Host` has `User agent`, its `IdentityFile`,
       `IdentitiesOnly`, `IdentityAgent none`, `ForwardAgent no`,
       `ForwardX11 no`, `ForwardX11Trusted no`, `Tunnel no`, `ControlMaster
       no`, `ControlPath none`, `GSSAPIAuthentication no`, `UpdateHostKeys
       no`, no password or keyboard-interactive, `StrictHostKeyChecking no`
       and `UserKnownHostsFile /dev/null` (the transport is `docker exec` on
       this computer, and every container has a new host key), and
       `ProxyCommand <um-codex> ssh-proxy <setup> --docker <docker>`, with
       absolute paths (the app checks the command in its own short PATH): an
       installed copy's launcher (`<app>/bin/um-codex`, which follows
       updates), else this Python (`-m umcodex`); `--data-dir` only when
       `UMCODEX_DATA_DIR` is set. `%` is doubled (ssh's tokens); on a Mac
       each word is then `shlex.quote`d, since ssh runs the command with the
       person's shell (checked with real ssh under sh, bash and zsh: paths
       with spaces, `$`, backticks, quotes, `;`, `&`, `|`, `%` and globs
       arrive unchanged); on Windows, where OpenSSH splits it as a Windows
       command line, a word with a space is double-quoted. The app adds only
       `BatchMode`, timeouts and keep-alives itself.
     - Because the Include is the first line of `~/.ssh/config`, these
       values win (ssh keeps the first value it reads). Options set only in
       the person's own `Host *` (a `LocalForward`, `DynamicForward` and the
       like) still apply to these hosts; the container's sshd allows only
       local forwards to its own localhost, so they reach nothing on the
       person's side.
     - The person's own ChatGPT app reads the same `~/.ssh/config`, so it
       lists the `umcodex-*` hosts too (switched off). The README says so;
       they work there only while the setup runs, and the work is still in
       the sandbox.
     - **The one line in the person's own file:** `Include
       ~/.ssh/um-codex/config` at the very top of `~/.ssh/config` (the app
       follows only top-level Includes; an Include after a `Host` belongs to
       it). Added **only with consent**: since M7 the installers ask once
       (`um-codex ssh-include`, [Y/n]); if it's still missing, the setup's
       card in the launcher explains it and its button says "Add the line
       and start" (the click is the consent; M6 asked in a pop-up with
       Allow); the terminal asks with "[y/N]"; a launch with no terminal
       and no line stops with a plain message. The file is read
       as bytes (its line endings, CRLF too, are kept) and backed up first
       (`~/.ssh/config.um-codex-backup`; a backup that no longer matches the
       file is refreshed), then replaced atomically (a temporary file renamed
       onto the real path, so a `~/.ssh/config` that's a link stays one), with
       its permissions kept, or created 0600 if there was none. A file that
       isn't UTF-8 text is left alone, with a plain message.
       `um-codex uninstall` removes its own data folder's ssh files (its
       flat keys too, known by its saved setups or their Hosts); then, when
       no other data folder that isn't definitively gone has any there (an
       older copy's flat key counts only while its Host and data folder
       are there), the line, the backup when the file is then the same as
       it, and all of `~/.ssh/um-codex`, leftovers included. Deleting a
       setup removes its key and Host.
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
     layers as every launch (#12):
     - every launch, terminal too: `requirements.toml` has
       `default_permissions = ":danger-full-access"` with
       `[allowed_permission_profiles]` allowing only `:danger-full-access`
       (below). Checked in the terminal: Codex starts ("permissions: YOLO
       mode") and `/permissions` offers only "Full Access"; the two other
       choices are shown disabled.
     - an app launch only: the provider's credential is
       `[model_providers.toolkit.auth] command =
       "/usr/local/bin/umcodex-token"` instead of `env_key` (ssh sessions
       don't get `docker run -e`; Codex 0.157.1 refuses both together).
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
     copy and `~/.codex` are never touched. It does share the app's
     runtime cache with the person's copy: our copy may update the shared
     runtime in `~/.cache/codex-runtimes` (about 1 GB), as any second copy
     of the app would; the app downloads to a staging folder, swaps it in
     by renaming and rolls back a failed swap (the maintainer accepted this,
     2026-10-02). The app is found in
     `/Applications` or `~/Applications` (`ChatGPT.app`, or `Codex.app`), by
     its bundle id, else through Spotlight (`mdfind
     kMDItemCFBundleIdentifier`). If the copy is already running (a main
     process with its `--user-data-dir` in its arguments), no second one is
     started: it's brought forward (AppKit's `activateWithOptions` through
     `osascript -l JavaScript`, which needs no permission to control other
     apps); if macOS declines, the launcher says to switch to it.
     - **Local chats are blocked** (the maintainer's decision, 2026-10-01).
       A chat that isn't Remote · `umcodex-…` would run on the Mac, outside
       the sandbox. The copy's `config.toml` gets UM-Codex's provider at
       each launch: a custom one without `requires_openai_auth` (so the copy
       opens with no sign-in, as in the test), `forced_login_method = "api"`,
       analytics, feedback and update checks off, with no credential, whose
       base URL is `http://127.0.0.1:<port>/um-codex-local/<alias>/v1` on a
       small **local-chats responder** (`relay.local_chats_app`, run by
       `codex_app.LocalChatsServer`), never the relay: it has no key and
       calls nothing. It answers `POST …/responses` with a normal streamed
       assistant message: "This UM-Codex window only works in Remote chats.
       Start a chat on Remote · `<alias>` (its project in the sidebar). Local
       chats would run on your Mac, outside the sandbox." (naming the setups
       running in the app now), or, with none running, that no setup is
       running and to start one. Anything else there gets 404.
       - **The port is fixed per data folder** (`codex-app/local-chats-port`,
         chosen once): the copy keeps the config it started with while it
         runs, so a launch's own port (the first version used the relay's)
         was gone after Stop and Start, and an old local chat showed
         "Reconnecting… waiting for network" (the GUI test's step 12). Every
         app launch and the launcher window serve it: whichever binds it
         first; the others see it's there (`/um-codex-local/_whoami`, by
         data folder) and take it over when that process ends (a launch
         checks every 2 s, the window every 10 s). If another program holds
         the port, a new one is chosen and kept (the copy follows after its
         next restart). With no launch and no launcher window running,
         nothing answers, and local chats wait for the network.
       - A failing `auth.command` was tried instead (a helper printing the
         reminder and exiting 1): Codex 0.159.2 retries it for ever,
         showing only "Reconnecting... waiting for network".
       - Checked: the app's bundled Codex (0.159.2) with the copy's config
         showed the message during a launch, after Stop (the launcher window
         answering), and after Start again, all on the same port; the
         responder never reaches the Toolkit (it has no client or key).
         `codex_app.LOCAL_CHATS = True` switches back to the test's behaviour
         (the Toolkit through the relay with the launch token).
     - The app's other settings in that `config.toml` are kept. If it
       doesn't parse, it's moved aside as `config.toml.bad-<time>` (and
       logged) before UM-Codex's settings are written.
     - Not installed: "Codex app" in the form is disabled with "The Codex
       app isn't installed. It's part of OpenAI's ChatGPT desktop app: get
       it from https://chatgpt.com/download, then come back. Terminal works
       in the meantime."
   - **The copy is set up before it opens** (asked for after the GUI test:
     adding the connection and the project by hand was too hard). The app
     (26.928) keeps its state in `$CODEX_HOME/.codex-global-state.json`
     (and `.bak`, read when the first doesn't parse): a plain JSON object,
     loaded once at start and rewritten by the app as things change, each
     key checked against a schema (a value that fails is dropped). So, only
     while UM-Codex's copy isn't running, a launch merges in (`seeded_state`,
     with the shapes the app itself wrote in the GUI test):
     - the host: `codex-managed-remote-connections` (`hostId`
       `remote-ssh-discovered:<alias>`, `source` `discovered`),
       `remote-connection-auto-connect-by-host-id` true, its analytics id;
     - its project: `remote-projects` (`/work`, named after the setup, a
       stable id from the alias), first in `project-order` and the sidebar,
       and `selected-project`, so the copy opens on it;
     - pop-ups: `electron:onboarding-projectless-completed` (the welcome
       flow's route goes to the app when it's true; the person's role isn't
       answered for them), `electron:onboarding-hide-first-new-thread-promos`,
       and `seen-model-upgrade-list` with the models the app's bundled Codex
       would announce. The copy's own side also gets a model catalog
       (`model_catalog_json`: the bundled Codex's list, `debug models
       --bundled`, with no `availability_nux` or `upgrade`), so no model
       qualifies for an announcement; the remote side already has
       UM-Codex's catalog. Nothing switches the model.

     The rest of the file is kept; it's written whole (temporary file and
     rename), with its backup. If a key UM-Codex touches has a shape it
     doesn't know (an app update), nothing is changed and the launcher shows
     the steps; a version other than the tested ones (`TESTED_APP_VERSIONS`,
     26.928.x) is tried and logged. **A known fragility:** these are the
     app's internals, not an interface.

     Checked live with a fresh data folder (app 26.928.40906): Start, and
     the copy opened on the setup's project with Remote · `<alias>`
     connected, "Full access" and the setup's model, with no onboarding and
     no model announcement, and the launch saw the app-server start (about
     19 s, no clicks). After Stop and Start (the copy still open) it
     reconnected by itself in about 9 s, and the app had kept the seeded
     host and project.
   - **When it can't be set up** (the copy was already open, or the file's
     shape is unknown), the copy opens on the documented
     `codex://settings/connections/ssh/add?name=<alias>` link (if the host
     never connected) and the launcher shows the steps the GUI test found:
     switch to UM-Codex's Codex window; Settings → Connections → Add, choose
     `<alias>`, Add (it's switched on and connects); Home → Choose project →
     Create project, named after the setup, "Add a folder on this computer"
     → `<alias>` → Add, `/work`, Return, Create project; start a chat there
     and check it shows Remote · `<alias>`; and, for pop-ups: choose Skip,
     and Continue with current model.
   - **Connected:** the launch watches the container every 2 s for the
     app's `codex app-server --listen` (`pgrep -f`) and then marks the launch
     "Connected ✓" (`launch.json`) and the setup as connected once
     (`<data>/codex-app/hosts.json`); the launcher's banner follows ("is
     running…", then "working in the sandbox"). Later launches pass no link
     and show "Waiting for the Codex app to reconnect…" with "It doesn't
     connect: show the steps".
   - **The launcher window:** "Open in: Codex app" is enabled when the app
     is installed. Start for an app setup asks for the ssh line once (above),
     then starts `um-codex launch --setup <id> --open app` in the background
     (its own session, no window; output to `<data>/ui/app-launch.log`, its
     steps to `um-codex.log`), which holds the relay until it's stopped. The
     running list and the card say "Running in the Codex app"; below it the
     guide or "Connected ✓", and the plain lines: "Chats must show Remote ·
     `<alias>` to run in the sandbox. Other (local) chats in that Codex
     window would run on this computer, outside the sandbox, so they're
     blocked: they only answer with that reminder.", "The app may show the
     chat's permissions as Custom (greyed): UM-Codex fixes them to full
     access inside the sandbox, so there's nothing to choose there." (the GUI
     test saw Custom; a seeded copy showed "Full access") and "The Codex
     app's own browser runs on this computer, not in the sandbox; use the
     Browser tool for browsing inside it." (also on the summary before
     Start). The app marks a local chat only by the absence of the Remote ·
     `<alias>` strip and globe. Stop removes the containers (the launch then
     ends and cleans up); its question adds that the app will say it can't
     reconnect, which is expected.
   - **Lifetime:** the launch runs until Stop (or Ctrl-C when it was started
     in a terminal). If `um-codex` is killed, the watchdog ends the container
     as for any launch. The app's remote app-server lives in the container
     and goes with it.
   - **Windows** (branch `m6-windows-codex-app`; checked on a Windows 11
     laptop, 2026-10-02, app 26.928.4866.0). **On, experimental**
     (`codex_app.WINDOWS_COPY = True`, after the hands-on test below passed;
     False switches it off again, "works with UM-Codex on a Mac only, for
     now", and `UMCODEX_WINDOWS_CODEX_APP=1` then turns it on for a test).
     The installers' Include question (`um-codex ssh-include`) is asked on
     Windows too, under the Mac's rules (only at a terminal, Return is yes,
     a "no" is kept).
     - **The app:** the Microsoft Store (MSIX) package `OpenAI.Codex`
       (family `OpenAI.Codex_2p2nqsd0c76g0`, AUMID
       `OpenAI.Codex_2p2nqsd0c76g0!App`), in `C:\Program
       Files\WindowsApps\OpenAI.Codex_<version>_x64__2p2nqsd0c76g0\app\ChatGPT.exe`.
       It has no execution alias for ChatGPT.exe (only for its Chrome native
       host and command runner), a `codex:` protocol in its manifest (it
       doesn't register one itself on Windows), a packaged sandbox service,
       and file/registry write virtualization off. It's found with
       `Get-AppxPackage -Name OpenAI.Codex` each time (an update changes the
       folder), and its version is read from the folder's name.
     - **The app's code** (its `app.asar`, read-only): the profile is
       `CODEX_ELECTRON_USER_DATA_PATH` if set, on every platform. On Windows
       the single-instance lock is always taken, and it's per profile (taken
       after the profile is set), so a copy with its own profile runs beside
       the person's. Codex's home is `CODEX_HOME`, else `~/.codex`, kept after
       the app loads the shell's environment only when
       `CODEX_ELECTRON_USER_DATA_PATH` is set; `.codex-global-state.json` is
       in that home, as on a Mac, and the seeding is the same code. The
       "Codex Demo" launcher is Mac only (`/usr/bin/open`, a fixed
       `/Applications/ChatGPT.app`): there's nothing to copy on Windows.
     - **How the copy is started** (tried by hand, with the person's own
       app open throughout):
       - **ChatGPT.exe run directly** (CreateProcess, with `CODEX_HOME` and
         `CODEX_ELECTRON_USER_DATA_PATH` in its environment and
         `--user-data-dir=<profile>`): works. A second, separate instance
         opened. Its app-server (`codex.exe ... app-server`) used the given
         `CODEX_HOME` (its `config.toml`, state file and databases went
         there), and the person's copy carried on. It runs **without the
         package's identity** (not in `tasklist /apps`), which Microsoft
         doesn't support for Store apps: what's tied to the package (its
         sandbox service, for local agent work) may not work in it. Local
         chats are blocked anyway.
       - **The shared runtime cache** (accepted by the maintainer,
         2026-10-02, as on a Mac): the copy shares the app's copied
         binaries (`%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>`, named by
         content, unchanged by the tests) and its primary runtime in
         `~/.cache/codex-runtimes` (`os.homedir()`, not `CODEX_HOME`) with
         the person's copy. Either copy updates that runtime when it's
         behind: a download (about 1 GB) into
         `codex-runtime-install-<random>`, then the current one renamed to
         `.previous-<uuid>`, the new one renamed in, and a rollback if that
         fails (Windows refuses to rename a folder whose programs are
         running). There's no switch for it outside the app's dev builds
         (`CODEX_ELECTRON_PRIMARY_RUNTIME_UPDATE_MODE`). The first test copy
         began that download, and being stopped half way left its 1 GB
         staging folder behind (removed by hand). So the fallback doesn't
         stop the copy while a staging folder made in the last 30 minutes is
         there (the app removes it when it's done; its files can't tell,
         since they're extracted with the archive's own old times: about
         20,000 of them, a 500 MB download), for up to 20 more minutes
         (`WINDOWS_UPDATE_GRACE_SECONDS`), and the launcher's note says the
         window may download an update (about 1 GB) the first time. A
         separate `USERPROFILE` for the copy would isolate the cache but
         also move the ssh config it reads; not done.
       - **In the package** (`Invoke-CommandInDesktopPackage -PackageFamilyName
         OpenAI.Codex_2p2nqsd0c76g0 -AppId App`, with the variables set in
         the calling shell): it runs with the identity and takes
         `--user-data-dir`, but **got none of the caller's environment**, so
         its app-server used the person's `~/.codex`. In the hands-on test
         that copy changed the person's `~/.codex` (config.toml, the state
         file, the databases) in the half minute before it was stopped.
         UM-Codex never starts the copy this way. AUMID activation
         (`IApplicationActivationManager::ActivateApplication`) wasn't tried
         after that: it takes arguments only, and in its code the app reads
         Codex's home from `CODEX_HOME` alone (or WSL's, when set to run
         Codex in WSL): no argument, file or registry key.
     - **So, experimental, with safeguards** (the maintainer agreed to the
       direct start on 2026-10-02; `codex_app_windows.py`):
       - The package is looked up afresh at every launch (`Get-AppxPackage
         -Name OpenAI.Codex`, its InstallLocation + `app\ChatGPT.exe`, never
         a saved path) and used only if its family is
         `OpenAI.Codex_2p2nqsd0c76g0` and its publisher OpenAI's Store
         certificate name.
       - The copy is the exe itself (CreateProcess, detached, never waited
         for; never an activation), with `CODEX_HOME` and
         `CODEX_ELECTRON_USER_DATA_PATH` set, `--user-data-dir`, and the
         person's other `CODEX_`, `OPENAI_` and proxy variables left out
         (the copy talks only to 127.0.0.1, and runs ssh). `check_paths`
         refuses to start it unless both folders are inside UM-Codex's
         `codex-app` folder and neither is (nor holds) `~/.codex` or the
         app's own profile (`%APPDATA%\Codex*`).
       - It must then show up as ours, within 15 checks: a `Win32_Process`
         `ChatGPT.exe` without `--type=` whose `--user-data-dir` (the whole
         argument quoted, the value quoted, or bare) is the copy's profile,
         compared exactly after Windows' normalising (case, separators,
         `..`), and in its long and 8.3 forms. The person's own copy has no
         `--user-data-dir`, and a folder beside ours doesn't match. Then the
         launch must see the app-server in the container ("Connected")
         within 3 minutes (15 when the person has the first steps to do by
         hand), or longer while a runtime download is under way (below).
         Otherwise UM-Codex stops the copy it started: right before, it
         checks that the PID is still that copy's main process (a number can
         be reused), then `taskkill /PID <pid> /T /F`. It ends the launch,
         says to use Open in: Terminal (`WINDOWS_FALLBACK`), and marks the
         launch `"fallback": "terminal"` for the launcher.
       - The copy's state is seeded as on a Mac (same file, same shapes),
         only while it isn't running. A `codex://` link goes only in the
         copy's own arguments (the app reads links from its command line on
         Windows too); one opened through Windows would reach the person's
         own app, which the package registers.
       - From the review (2026-10-02):
         - PowerShell's output is read as UTF-8 (`[Console]::OutputEncoding`
           set first, `encoding="utf-8"`): Windows PowerShell 5.1 otherwise
           writes it in the OEM code page, so a profile under `C:\Users\José`
           came back as "Jos?" and the copy was never found. The process the
           launch started is also kept: if the lookup still can't find the
           copy while that process runs, it's the copy (a second one on the
           same profile hands over and ends), and `stop` may end it by that
           handle (a held process's number can't be reused).
         - The fallback stops the copy only if no other setup's launch in
           the Codex app (this data folder's) is running: they share it. What
           it says depends on what became of the copy (`WINDOWS_FALLBACKS`:
           stopped, shared, still open, never opened), and it's kept in
           `codex-app/fallbacks.json` for the setup's card (the launch's own
           folder is gone by then), which shows it with "Open in Terminal
           instead" until the next Start or a connection. The card also
           shows a refused copy, and says "taskbar" on Windows (the launch's
           `icon`).
         - "Codex app" is unavailable on Windows without Windows' own ssh
           (`System32\OpenSSH\ssh.exe`, the OpenSSH Client optional feature),
           with a plain message on how to add it.
         - The ssh files' permissions: an icacls or whoami failure on a file
           or folder the Include reaches stops the launch (the file is taken
           away again: ssh skips an Include that matches nothing, but refuses
           one it can't trust, and every host with it), with a plain message;
           a failed SID lookup isn't kept.
         - The Include line: on Windows the new `~/.ssh/config` (a new file)
           and its backup get the original's access rules (`Get-Acl` SDDL,
           `Set-Acl`), then Windows' ssh is asked to read it (`ssh -G`); on
           "Bad permissions" the file is put back as it was. An `~/.ssh` with
           exactly Python 3.13's 0o700 rules (SYSTEM, Administrators, OWNER
           RIGHTS, protected) that UM-Codex made (its note in
           `~/.ssh/um-codex`, or that folder there) is repaired: the person
           given full rights, then OWNER RIGHTS removed (removing it alone
           would leave the person without access).
         - The copy's environment also leaves out `ELECTRON_*` and
           `NODE_OPTIONS`; `check_paths` also refuses the person's own
           `CODEX_HOME`; the newest registered version of the package is used.
       - The launcher's notes add `WINDOWS_NOTES`: experimental, no Windows
         sandbox or Computer Use in UM-Codex's window, and an app component
         update (about 1 GB) may download the first time.
       - An already-open copy is brought forward with
         `WScript.Shell.AppActivate(<pid>)`. The catalog comes from
         `app\resources\codex.exe debug models --bundled` (0.159.2, with a
         throwaway `CODEX_HOME`, `USERPROFILE`, and no console window).
     - **The ssh side:** Windows OpenSSH reads `%USERPROFILE%\.ssh\config`
       and runs a double-quoted ProxyCommand itself; `ssh-proxy` runs `docker
       exec` as a child, since Windows has no exec. The app runs the first
       `ssh.exe` on its PATH; Git for Windows' (its `usr\bin`, OpenSSH 10.3,
       MSYS) runs a ProxyCommand through `/bin/sh` (which drops the Windows
       path's backslashes) or `$SHELL`, so the copy never connected when it
       was first. The copy's PATH now starts with `System32\OpenSSH`, and
       `SHELL` is left out of its environment. The ssh folders' Windows
       permissions: see "This computer's ssh files".
     - **Hands-on test** (Windows 11 laptop, 2026-10-02, app 26.928.4866.0,
       alpha.3 installed, this branch's code run with its Python, the
       person's own ChatGPT app open throughout):
       - ssh, as the app runs it (Windows OpenSSH 9.5p2, `~/.ssh/config`
         with the Include, the installed `um-codex.exe ssh-proxy` by its
         path): `ssh -o BatchMode=yes umcodex-<setup> "codex --version"` →
         `codex-cli 0.157.1` in about 1.6 s. The login shell has bash,
         `CODEX_HOME=/codex-home`, codex on PATH, user `agent`; `nohup codex
         … app-server --listen unix://` starts; `ssh -T … codex app-server
         proxy` answers the WebSocket upgrade (101); sftp works.
       - The app's own steps (its log): `codex_path_probe` 2.0 s,
         `codex_version_probe` 2.7 s, `app_server_bootstrap` 2.2 s, all code
         0. No "codex path probe timed out" (openai/codex#42995); no console
         windows flashed (#47602).
       - A launch through `AppHold`: the copy was seeded and opened on the
         setup's project with Remote · `umcodex-<setup>` (the person's
         screenshot), and the launch saw "Connected" in under 30 seconds. A
         Remote chat ran in the sandbox (it listed `/work`, `whoami` said
         `agent`); a local chat only answered the reminder (whose "on your
         Mac" is now "on this computer").
       - The fallback, before the PATH fix: no connection in 180 s, so the
         copy was stopped by its PID, the sandbox ended and the launcher
         said to use Terminal; the person's own app carried on.
       - `taskkill /T /F` once reported a failure for a copy that did end
         (a helper already ending), so `stop` checks the copy is gone
         rather than taskkill's code.
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
     - After merging #12's review fixes (browser tools pinned and direct), a
       launch held the same way (internet and browser tool on, the app not
       opened) again ran a `:workspace` chat with full access and a turn
       through the Toolkit.
   - **GUI test** (the maintainer's computer-use agent, 2026-10-01, at
     b32b68e, before the copy was set up automatically): no sign-in,
     connecting, commands in `/work` as `agent`, hello.txt on the Mac, the
     models, the internet, the browser tool's approval card, the local block,
     Stop, and the restart reconnecting by itself (24–32 s) passed; step 12
     (an old local chat after Stop and Start) failed, which the fixed port
     fixes. The steps it found for the connection and project are the
     fallback above.
   - **Not checked** (steps in `docs/spikes/2026-10-01-m6-codex-app-gui-test.md`):
     the local-chats message inside the app's window after a restart, a
     second setup in the same copy, pop-ups after an app update, and
     Windows.
8. **M7, "One click" (asked for on 2026-10-02, after the maintainer tried
   alpha.3: too many pop-ups, alerts and steps before Codex was running).**
   Built on branch `m7-one-click`. Starting Codex is usually one click; every
   safety fact stays on screen, as short lines instead of pop-ups and a page.
   - **First run** (no setups): the page has one main action, "Choose a
     folder and start…", with what it means right under it, before the
     click: Codex starts in the Codex app (or Terminal) on that folder; it
     can change and delete files there (real files, no undo); the internet
     is on, so it could send what it reads anywhere (and reach this
     computer, the local network and VPN). Then the native picker, and a
     setup is made from the folder alone and started at once: no form, no
     summary page, no confirmation. Notes about the folder (a network drive
     on Windows) show on its card. "Choose options first…" opens the form
     instead. "Choose another folder…" (returning) has the same short line
     (`aria-describedby`).
   - **Returning:** "Start <last setup>" at the top (the setup used last;
     while it runs, its status line instead), and Start on every card,
     which starts at once. "Choose another folder…" makes and starts a new
     setup the first run's way; "New setup with options…" opens the form.
   - **Defaults for a new setup** (the API fills in whatever the page
     doesn't send; `server.setup_from`): **Open in: Codex app** when it's
     installed and usable (a Mac), else Terminal (`Launcher.default_open_in`);
     the model `gpt-5.6-terra`; commands without asking; the browser tool
     off; **the internet on**. The internet was off by default until M7. It's
     on now because the group wants full power (the Goal above: "Internet on
     means the whole internet"), and a setup with it off can't install
     packages or read documentation, which is much of what Codex is asked to
     do; the risk is the one the summary always named (Codex could send what
     it can read anywhere), so that line is on every card, under "Access",
     and one switch in Edit turns it off. The terminal's own question still
     defaults to off.
   - **The name** is no longer in the main flow: a new setup is named after
     its working folder, made unique among the setups (`setups.default_name`:
     "thesis", "thesis 2", …, letter case aside; a duplicate of "thesis 2" is
     "thesis 3"). It's the card's title and the Codex app's project name.
     The card has Rename (inline: Enter saves, Escape cancels, the typed
     name kept while the page redraws, focus back on Rename afterwards;
     `POST /api/setups/<id>/rename`, which refuses a name another setup has,
     letter case aside), and the form has it under More options (empty: the
     folder's name; an edit without one keeps the name).
   - **The cards** show, always: the folders (working folder and more, read
     only or read & write) with "Codex can change and delete files there:
     your real files, no undo."; under Access, "Internet on: Codex can reach
     the whole internet, so it could send what it can read anywhere (also
     programs on this computer and your local network or VPN)." or
     "Internet off: Codex can reach only the model.", and the browser tool
     ("a fresh browser in the sandbox, with none of your logins", and
     whether it asks); under Codex, where it opens, the model, and whether
     it asks before commands. The form shows the same block under "What
     Codex gets", with "Your Toolkit key stays on this computer; the
     sandbox never sees it."
   - **One status line per card** replaces the notices ("Starting in the
     Codex app…", "is running…", "Connected" banners): Starting… → Opening
     Codex… → "Connected ✓ The Codex app is working in the sandbox
     (<alias>)." (in Terminal: "Running in Terminal since 14:05"). Problems
     go on that line too. Screen readers hear a line when it changes (one
     polite live region), not every redraw of the page. The Codex app's first-time steps (only when its
     copy couldn't be set up) and its notes ("Use chats that show Remote ·
     <alias>; local chats are blocked.", folded) are under it.
   - **No pop-ups on the way to Codex.** A question in a pop-up is kept only
     before Stop and Delete (they can't be undone) and Windows' Fix it (an
     administrator prompt follows). Inline instead:
     - the key: a field under the status strip, shown when none is saved
       (Replace shows it again); a Start that needed it goes on once it's
       saved;
     - Docker Desktop closed: Start opens it and starts once it's running
       (up to 3 minutes; the card says "Opening Docker Desktop… Codex starts
       as soon as it's running.");
     - a saved folder that now leads somewhere else (a real risk): the card
       shows both paths and why, and its button becomes "Use them where they
       go now, and start". The request carries the places the card showed
       (`confirm_moved`: each `now`), and the server refuses (`field:
       "moved"`) unless they're exactly where the folders lead now, so a
       folder that moved again since isn't confirmed by an older click. Saving
       the setup (Edit → Save, "Open in Terminal instead") with a moved
       folder's saved path needs the same confirmation (`Launcher.update`):
       otherwise saving would store where it leads now and skip the
       question; it's matched however the path is spelled (`link/`,
       `link/.`, `a//link`, letter case), and the form then shows both
       places with "Use them where they go now, and save". Choosing the
       folder again in the picker is a new choice (it comes back as its real
       path). Moved folders are found folder by folder (`setups.moved`): one
       that's refused now (gone, say) is skipped, never hiding another that
       moved, on the card or in a save. The big Start at the top waits for it;
     - the Codex app's ssh line, when the installer didn't add it: the card
       explains it and its button says "Add the line and start"
       (`allow_ssh_include` in the start request: the line is added, backed
       up, then the start goes on), with "Open in Terminal instead";
     - a folder the picker or the folder rules refuse: under the button that
       chose it.
   - **The form**, for Edit and "New setup with options…", is in sections:
     **Folder** (working folder; more folders, each Read only / Read &
     write), **Access** (Internet; Browser tool; Approve each browser
     action), **Codex** (Model; Open in; **More options**, folded: Ask
     before commands, and the name). M4's "Where Codex runs: In the sandbox
     / On this computer" will go under More options, with its caution. Then
     "Save and start" (only Save while the setup runs), Save, Cancel.
   - **Models newest first** (`toolkit.by_release`, used by the page and
     the terminal's list): by the version in the slug, as numbers (6 before
     5.10 before 5.6 before 5.5; 5.4.1 before 5.4), GPT before the o-series,
     names without a version last; within a version, Codex's own catalog
     order (`codex debug models --bundled`, 0.157.1: astra, sol, terra,
     luna), then the plain version, then other variants by name. The
     setup's model stays selected (`gpt-5.6-terra` for a new one).
   - **The status strip** is one quiet line while all is well (Docker
     running · Toolkit key saved · Replace · version · Check for updates);
     anything that needs doing gets a line of its own (Docker not running,
     with Open Docker Desktop or Fix it…; no key; an update; a newer
     install, with Reopen).
   - **Update from the launcher** (asked for during M7). When the daily
     check, or **Check for updates** (`update.check_now`: GitHub now, the
     same signature checks), finds a newer release, the strip says
     "UM-Codex X is available · Update". Update runs this version's
     `um-codex update --from-launcher` in the background (the same code path
     and checks; the window isn't closed), and shows fixed words for its
     progress (`UPDATE_STEPS`: Checking for a newer version…,
     Downloading…, Installing…, Getting the new image…), each picked by a
     line the update prints, never the line itself, so nothing it prints
     reaches the page; its output goes to `um-codex.log`. Then "Updated to
     UM-Codex X. Reopen to use it." (Reopen: the existing path that starts
     the installed version's window), "UM-Codex X is the newest version.",
     or "The update didn't finish, so this version is still the one in use.
     What happened is in um-codex.log, in UM-Codex's data folder." (update.py
     undoes a failed step itself). Refused while a setup runs: "Stop running
     setups first: “thesis”." (checked under the same lock Start takes, and
     Start is refused while it runs: "Updating… wait for it to finish, then
     start."). The update runs in a session of its own (a new process group
     with no window on Windows) with its output in `ui/update.log`, which the
     window reads for the progress words, so it goes on whatever happens to
     the window; while it runs the window doesn't end when idle, refuses to
     be closed over its control link and to Reopen, and doesn't offer
     Reopen for a newer install. Once it has updated, only Reopen is
     offered (a second Update is refused), so the version in use is never
     the one an update prunes. `um-codex uninstall` refuses while an update
     holds its lock ("UM-Codex is updating…"). Rollback stays in the terminal.
   - **The installers ask about the ssh line** (`um-codex ssh-include`,
     above, and docs/INSTALLING.md), so a start in the Codex app needs no
     question later. It needs a terminal (no terminal: a message, exit 1,
     nothing added). A "no" is kept (`ssh-include-declined` in the data
     folder), so installing again doesn't ask again; `um-codex ssh-include
     --ask-again` does, and the card still offers "Add the line and start".
   - **Clicks, from the launcher's page to a connected Codex app chat** (a
     Mac with the Codex app installed, the key saved and Docker running;
     the native folder picker counted apart):

     | | alpha.3 | M7 |
     |---|---|---|
     | First run | 7 clicks + picker: New setup, Choose working folder…, (picker), Open in: Codex app, Save, Start, "Start in Codex app" on the summary page, Allow in the ssh pop-up | **1 click + picker**: Choose a folder and start…, (picker) |
     | First run, the installer didn't add the ssh line | (as above) | 2 clicks + picker (+ "Add the line and start") |
     | Returning | 2 clicks: Start, "Start in Codex app" | **1 click**: Start "<setup>" |
     | Pop-up questions on the way | 1 (the ssh line) | 0 |
     | Pages on the way | 3 (list, form, summary) | 1 |
     | Notices shown | 3 (Saved, Starting in the Codex app, running/connected) | 0 (the card's status line) |

     In Terminal, alpha.3's first run was 5 clicks + picker and M7's is 1 +
     picker; returning, 2 and 1.
   - **Live check** (this Mac, 2026-10-02; `uv run um-codex ui --no-browser`
     with `UMCODEX_DATA_DIR` in a scratch folder, `um-codex-agent:dev` built
     from this branch, a stub upstream on 127.0.0.1 and a stand-in key store
     holding a fake key, so neither the real key nor the keychain was used;
     the person's own ChatGPT app, UM-Codex's installed copy and `~/.codex`
     were left alone):
     - the first-run page with the key field inline; the fake key saved
       there (checked against the stub);
     - "Choose a folder and start…" (the native picker was stood in for in
       the test browser, since it needs a person at the desktop; a picker
       that failed showed its line under the button) made "thesis" with the
       internet on and Open in: Codex app, and started it at once;
       UM-Codex's own copy of the app opened on the project "thesis",
       Remote · umcodex-thesis-…, connected, Full access, 5.6 Terra, and
       the card went Starting… → Opening Codex… → Connected ✓ in about 20 s;
       `codex exec` over its ssh host got the stub's answer through the
       relay, with the fake key swapped in;
     - Stop (its question), then "Start “thesis”": connected again in about
       10 s, one click;
     - the Edit form's sections and model order (gpt-6-astra … gpt-5.4,
       gpt-5.6-terra selected); a setup whose folder was swapped for a link
       showed both paths and "Use them where they go now, and start"; the
       ssh-line card and the Update line were checked by setting the page's
       state; Check for updates and Update through the API: refused while a
       setup ran, then (a development copy) the plain failure line, with
       the reason in `um-codex.log`; light mode and a phone-width window.
   - **Found while checking:** installs with different data folders share
     `~/.ssh/um-codex`, and each launch in the app rewrites its `config`
     from its own setups, removing the others' keys and hosts (the scratch
     launch removed the installed copy's; they were restored from a copy
     taken first). Fixed after M7: each data folder has its own folder
     there, and `config` is all of them together (M6, "This computer's ssh
     files").
   - **Not checked:** Windows; the real native picker (it needs a person);
     a real update from the launcher (it needs two published releases);
     the installers' question in a real install (the installer tests run
     the real `um-codex ssh-include` in a terminal, with a stand-in Codex
     app).
9. **Acceptance, on a fresh Mac and a fresh Windows machine:**
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
