# Proposal: UM-Codex on the lab's servers

Date: 2026-10-22. **The direction is decided ("Decisions" below), and the spike
ran ("The spike"); nothing is built yet.** Branch `lab-servers-plan`.
Question from the maintainer: move UM-Codex from people's own computers to
the lab's servers, using the large compute server's resources, the way
DataLab's "High compute" conversations now do. This note compares the ways
to do it, recommends one, and lists the steps, the decisions and the risks.

Names used here (the private server wiki has the real host names, paths and
groups; this repo is public, so they're not repeated):
- **the web server**: the lab's small front-door server (4 vCPU, 7.5 GB).
  Apache with HTTPS, and DataLab's shared copy with GitHub sign-in.
- **the compute server**: the lab's large server (32 cores, 754 GB, one
  48 GB Quadro RTX 8000, rootful Podman, approved for identifiable data).
- **the tunnel**: the web server opens SSH to the compute server (the other
  way is closed) and forwards Podman's API sockets and a relay socket over
  it. Built for DataLab on 2026-10-22; UM-Codex would get its own, under its
  own names, beside DataLab's.

How it was checked:
- **This repo** (DESIGN.md, the M6 spike and `src/`), DataLab's
  high-compute change (its `sessions/compute.py` and `docs/DISTRIBUTION.md`)
  and the private server wiki's pages on the compute server and DataLab.
- **Both servers, read only** (2026-10-22): the web server's Apache modules
  and sshd settings; the compute server's sshd, PAM, Podman, GPU use, home
  folders and `/etc/subuid`. Nothing was changed on the web server. On the
  compute server: the spike's containers (all removed) and UM-Codex's
  folders (see "The spike"); also, `podman info` run as the maintainer's own
  account may have made an empty rootless store folder in that account's
  home.
- **Docs:** learn.chatgpt.com (app server, remote connections).
- **Open VSX:** the Codex extension's listing and its linux-x64 package,
  unpacked in a scratch folder and read (not run).

Labels: **VERIFIED (live)** (seen on the servers), **VERIFIED (docs)**,
**VERIFIED (bundle)** (read in a package's code, not run), **UNSURE**.

## Summary

**Recommendation:** one UM-Codex service on the web server, with every
container on the compute server, and **the browser as the main way in**:
each project opens as a page with an editor, a file tree and OpenAI's own
Codex panel (code-server with the official Codex extension), plus a terminal
where the Codex terminal interface also runs. People install nothing. The
Codex desktop app over SSH comes second, for those who want it, on the same
containers. Each project is **Standard** or **High** compute, both on the
compute server. The Toolkit key stays on the web server, in a relay, as
today and as in DataLab. The desktop UM-Codex stays for work on files that
live on a person's own computer.

The three questions:

1. **Should Codex still be installed locally, connecting over SSH?** Not as
   the main way. It works (UM-Codex's M6 already runs the Codex app over SSH
   into its container), but every person then needs the VPN, an SSH key
   registered with the lab, and the desktop app, and the app's SSH mode has
   open problems on Windows. Offer it as a second front end (step 6 below):
   it's cheap, because the container side is M6's.
2. **Can Codex run in the browser?** Yes, self-hosted: the real Codex runs in
   the person's container and the page is code-server with OpenAI's Codex
   extension (on Open VSX, with a Linux build). OpenAI's own browser and
   remote modes don't fit: they need ChatGPT accounts and run through
   OpenAI's cloud, not the U-M GPT Toolkit (details below). The Codex
   **desktop app** itself can also be shown in a browser, by running its
   Linux build in the container and streaming the screen (spike 2, below):
   it works, but as an optional extra, not the main page.
3. **Normal or high compute at sign-in or per project?** Per project, like a
   setup's internet switch, with a personal default chosen at first sign-in.
   Both tiers run on the compute server (the web server is too small, and
   hosts DataLab), with different limits; High adds the GPU. Changing it
   takes effect at the project's next start, since the files are on the
   compute server either way. Anyone in the lab may use High (decided).

## What exists now

**UM-Codex (desktop).** Each launch: a relay in the `um-codex` process holds
the key (from the keychain) and accepts only a per-launch token; a gateway
container forwards Codex's model calls to it; the agent container sees only
the chosen folders; Codex opens in a terminal or, on a Mac, in the Codex app
through `um-codex ssh-proxy` (sshd in the container, reached with `docker
exec`). A launcher page on 127.0.0.1 picks folders, internet on or off, the
model and where it opens.

**DataLab's shared copy and High compute (VERIFIED, live and wiki).**
- One Python service on the web server, behind Apache, GitHub sign-in, each
  person's work answering 404 to everyone else. Its model key is a systemd
  credential; containers reach the relay through a gateway and never hold
  it.
- High conversations: containers on the compute server, started with the
  `docker` CLI through the tunnelled Podman socket; GPU containers through a
  second Podman socket whose containers get the GPU by default (Podman 4.9's
  Docker API drops GPU requests); the gateway mounts the forwarded relay
  socket; the conversation folder is on the compute server and mounted back
  with sshfs.
- Podman quirks: `--dns` turns off container name lookups (use
  `--add-host`); the Docker CLI can't read Podman's network objects
  (`network ls`/`inspect` fail); cgroup v1 means `nproc` and `free` show the
  whole machine, so the agent is told its limits and pinned to one
  processor's 16 cores.

**What the servers offer (VERIFIED, live, 2026-10-22).**
- The web server's Apache has `proxy_wstunnel` and `proxy_http2` loaded:
  WebSocket pages can be proxied as DataLab's are.
- The compute server: ssh sign-in goes through PAM with a second factor
  unless a key is used; people in the lab already have accounts and home
  folders there (remote desktops, their own Podman images). No `subuid`
  ranges are set for people, so rootless Podman isn't usable, and on cgroup
  v1 it couldn't enforce limits anyway. GPU at the time: 1.7 of 46 GB in use.
- Both servers need the medical school network or VPN, for SSH and (the
  maintainer confirms) for the web server's HTTPS too.

## OpenAI's own remote and browser modes

- **Codex in ChatGPT on the web (Codex cloud):** runs in OpenAI's cloud
  containers with a ChatGPT account. Not the Toolkit, not our server, not for
  identifiable data. VERIFIED (docs, spike of 2026-10-01).
- **Remote Control (phone or another desktop driving a host):** "Remote
  access supports hosts running the ChatGPT desktop app on macOS and
  Windows", signed in to the same ChatGPT account, through OpenAI's relay.
  Not usable for a Linux server or with the Toolkit. VERIFIED (docs).
- **`codex app-server --listen ws://…`** with `--ws-auth capability-token`
  or `signed-bearer-token`, and `codex --remote wss://…` as its terminal
  client: "experimental and unsupported", and requests with an `Origin`
  header are refused (403), so a web page can't connect to it directly;
  something of ours would sit between. VERIFIED (docs).
- **SSH remote connections in the desktop app:** documented, works with a
  custom provider and no ChatGPT sign-in (UM-Codex M6, hands-on). This is
  option A.
- **The Codex IDE extension** (`openai.chatgpt`) is on Open VSX, which
  code-server uses: version 26.5908.31748 (2026-09-11), with a linux-x64
  build bundling Codex 0.154.0-alpha.6.1. Its sign-in screen follows the same
  rule as the desktop app (`requiresAuth = requiresOpenaiAuth ?? true`), so
  a custom provider without `requires_openai_auth` should open with no
  sign-in, as the app does; its `chatgpt.cliExecutable` setting can point it
  at the image's pinned `codex` instead of its bundled one. VERIFIED
  (bundle); **not run**. Running it in code-server isn't a setup OpenAI
  documents. Open VSX lags the VS Code Marketplace by some weeks.

## The options

| | People install | Sign-in and isolation | Files | Dashboards | Windows | Effort |
|---|---|---|---|---|---|---|
| **A.** Codex app or CLI on the laptop, SSH to a container on the compute server | Codex app, VPN, an SSH key | SSH key registered in the web page; an SSH gate on the web server routes to the person's own container | the server's project and NAS folders; app uploads and downloads (sftp) | the app's port previews (SSH `-L`), as M6 | app's SSH mode has open bugs; a terminal works | small to medium, after the shared service |
| **B1.** Web terminal (Codex's terminal interface in a page) | a browser | GitHub sign-in on the web server; one container per project | server folders; no upload or download without more work | needs its own proxy | same as Mac | small, after the shared service |
| **B2.** Our own web UI over `codex app-server` (DataLab-style) | a browser | as B1 | whatever we build | whatever we build | same | large: approvals, diffs, files, terminal, all ours to build and keep up with Codex |
| **C.** code-server in the container, with the Codex extension and a terminal | a browser | as B1 | editor and file tree, drag-and-drop upload, download | code-server's own `/proxy/<port>/`, behind our sign-in | same | medium, after the shared service |
| **D.** A new kind of DataLab conversation | a browser | DataLab's | DataLab's uploads and exports | none | same | medium, but ties a full-power Codex to DataLab's data-safety promises |
| **E.** People sign in to the compute server and run `um-codex` there | SSH, VPN | their own accounts | their own | SSH forwards | n/a | blocked: the Podman socket is root; rootless isn't set up, and can't limit memory on cgroup v1 |

Every option keeps the same Toolkit-key rule (a relay on the web server adds
the key; containers hold a token) and the same GPU and memory story (the
container's limits on the compute server). They differ in the front end.

**Why C first, A second, not B2, D or E:**
- C gives the most for the least: an editor, a file tree with uploads and
  downloads, notebooks, a terminal, port previews for dashboards, and
  OpenAI's own Codex panel, with nothing to install on any OS. B1 comes free
  inside it (the terminal runs `codex`). Its pieces are maintained by others
  (code-server, the extension); UM-Codex keeps only the service around them.
- A is already mostly built (M6's container side: sshd, the token helper,
  the enforced settings) and suits people who like the desktop app. It needs
  keys and the VPN, so it's not the default.
- B2 would mean writing and maintaining a Codex client. DataLab does that for
  its own product; UM-Codex's point is full Codex, so use Codex's own UIs.
- D mixes internet-on, write-anything containers into the service that
  promises read-only, audited study-data access. Keep them apart; share the
  machinery (sign-in code, tunnel pattern) by copying, as UM-Codex already
  does.
- E would give each person root on the compute server.

## The recommended design

```
browser ─HTTPS─▶ Apache /um-codex/ ─▶ UM-Codex service (web server; Unix socket, as DataLab)
                                       ├─ GitHub sign-in, projects, Standard/High, audit
                                       ├─ relay: holds the Toolkit key ◀─────────────────────┐
                                       ├─ starts and stops containers ──▶ Podman API (tunnel) │
                                       └─ page proxy (HTTP + WebSocket) ──▶ router (tunnel)   │
                                                                                              │
compute server (rootful Podman)                                                               │
  per project: gateway ── agent container (runs as the person's own uid)                      │
               │          ├─ code-server + Codex extension, on a Unix socket ◀── router       │
               │          ├─ codex (terminal), sshd -i on demand (the app, step 6)            │
               │          └─ /work = the project folder; NAS folders as chosen               │
               └─ relay socket (forwarded back over the tunnel) ──────────────────────────────┘
```

### Sign-in and who is who

- GitHub sign-in, copied from DataLab's server mode (its `auth/` and the
  ownership check that answers 404 for anyone else's ids), with its own
  GitHub App callback or a second callback URL on the lab's App.
- **Each person is mapped to their university account on the compute server**
  by an administrator's table, GitHub id → uniqname (decided); the uid and
  groups come from the compute server's own directory. Containers run as
  that uid and its groups, so a person can never reach a file through
  UM-Codex that their own account couldn't. (U-M's single sign-on would give
  the uniqname directly, but needs ITS; not now.)
- The web server is reachable only on the medical school network or VPN,
  which the maintainer counts as a welcome extra layer.

### Projects (what "choose folders" becomes)

A **project** replaces a desktop setup. It has a name, a working folder and
the same switches (internet, browser tool, model, ask before commands), plus
the compute tier.
- **The working folder** (`/work`): a project folder UM-Codex makes for the
  person on the compute server, owned by their uid. They can also reach it
  from their own account there (remote desktop, sftp).
- **More folders, read only or read and write**: picked from places on the
  compute server the person's account can already read, below roots an
  administrator allows (the NAS share, a shared lab folder). The folder rules
  stay (resolved paths, no system or UM-Codex folders, no other person's
  projects), checked on the compute server's paths.
- **From the person's computer:** uploads (drag and drop in the page, or the
  Codex app's sftp). Laptop folders aren't mounted: that's what the desktop
  UM-Codex is for.
- **Git:** clone in the terminal (internet on), or with the person's own
  GitHub token later if wanted.
- Codex's home (history, its databases) stays per project on the compute
  server's local disk, not on the NAS (SQLite on NFS is a known trouble
  spot).
- **Where project folders live (decided):** a `um-codex` folder on the lab's
  NAS share (the share people already use for code and data), with
  `users/<uniqname>/projects/<project>` inside. `users/` is group-writable
  with the sticky bit, and each person's folder is theirs alone (0700), made
  as their uid, since the NAS maps root to nobody. Made on 2026-10-22, with
  the maintainer's folder in it.

### Compute

| | Standard | High |
|---|---|---|
| CPUs | 2 | 10, pinned to cores of one processor |
| Memory | 16 GB | 100 GB |
| GPU | no | yes (through the GPU socket) |
| At once | 2 per person | 1 per person, 2 in all |
| Who | everyone | everyone (decided) |

- High is the maintainer's 10 CPUs and 100 GB (tried in the spike: `nproc`
  said 10, the memory limit was 100 GB). Memory is plentiful on this machine
  (754 GB); CPUs are what's scarce (32). So the caps are on CPUs: two High
  projects (20 CPUs) plus a few Standard ones, with DataLab's High (up to
  2 × 16 CPUs, pinned to the two processors) beside them, already asks for
  more than 32 at the busiest. Suggested: UM-Codex's containers in a cgroup
  parent capped at 24 CPUs and 300 GB, and DataLab's High brought down to
  the same 10 CPUs, so the lab's apps can't starve remote desktops. Standard
  stays small because it's for editing, small analyses and Codex itself;
  anything heavy is a reason to pick High.
- Chosen per project (default from sign-in), changed between runs.
- The agent is told its limits (instructions and `UMCODEX_CPUS` /
  `OMP_NUM_THREADS`-style variables), as DataLab does, because `nproc` and
  `free` show the whole machine.
- **The lab apps share one budget on the compute server.** DataLab's High
  already takes up to 2 × 16 CPUs. UM-Codex's containers go under a cgroup
  parent of their own, with a cap, so remote desktops and other studies keep
  room (the wiki's "Next" item 1).
- One GPU, no partitioning: GPU projects are capped and the page says when
  it's busy.

### The key

- On the web server, in the UM-Codex service's relay, from a systemd
  credential (DataLab's way), never in a container, file the containers see,
  environment, log or diagnostics.
- The relay listens on a Unix socket that the tunnel forwards to the compute
  server; each project's gateway mounts it (DataLab's High pattern). The
  relay checks the project's token as today.
- **One lab key (decided)**, as DataLab. The audit log records who used it
  for which project (counts, not content).

### Containers on the compute server: what changes

- **No `sudo` in the server's containers (decided: only if a real need
  shows up).** Podman there is rootful with no user namespace, so root in a
  container is root on every mounted folder: it could leave a setuid-root
  program in a project folder that the person (who also has a shell on that
  machine) could then run. So the agent runs as the person's uid with
  `--cap-drop ALL` and `no-new-privileges` (in the spike, `sudo` then says
  "no new privileges" and stops). Python, R and Node packages still install
  into the project (uv, renv, npm); system packages come from the image.
- The image runs as any uid: Podman adds the uid to the container's
  `/etc/passwd` by itself, and `HOME` is set to a folder in the project's
  Codex home (checked in the spike).
- Networks as today (internal by default, a bridge when the internet is on),
  with `--add-host` instead of container names, and cleanup by container
  labels only (UM-Codex's `network ls` cleanup doesn't work through Podman's
  Docker API). Labels name UM-Codex and its instance, so nothing ever touches
  DataLab's containers on the same Podman.
- **Lifetime:** a project's container keeps running while its page or app is
  connected, or while a command runs in it, and stops after an idle time
  (with a longer "keep running" for long jobs, up to a cap). The desktop's
  watchdog (the container ends when the launch ends) becomes the service's
  idle rule. Codex's chats are kept in the project's Codex home and resume.

### The page (code-server)

- code-server, pinned, and the Codex extension, pinned by checksum, in a
  server variant of the agent image; the extension uses the image's `codex`
  and the same `/etc/codex` settings (provider through the gateway,
  requirements enforced).
- code-server listens on a Unix socket in the project's run folder, never a
  port, with its own password off (`--auth none`): the only way to it is the
  router.
- **The router** (a small UM-Codex process on the compute server, one
  forwarded socket over the tunnel) passes each request to the right
  project's socket only when the web server's service has signed it for that
  person and project. Apache → service → router → code-server, WebSockets
  included.
- Dashboards (Shiny 3838, Streamlit 8501, Dash 8050) open through
  code-server's port proxy, under the same sign-in.
- **Internet and downloads are each person's switches, per project
  (decided)**, like the desktop's internet switch. Downloads off starts
  code-server with `--disable-file-downloads`. The page says plainly what
  each switch means when a project has NAS folders.
- Settings the image sets for the page (from the spike): the Codex
  extension's `chatgpt.cliExecutable` in code-server's **User** settings
  (its Machine settings were ignored, and the extension then ran its own
  bundled Codex, 0.154.0-alpha, which showed a ChatGPT sign-in); VS Code's
  own Chat panel turned off (`chat.disableAIFeatures`), since it opens by
  default beside Codex; Codex's panel opened at start.
- **The page's own calls out.** In the person's browser, the extension's
  panel tries to reach OpenAI's feature-flag and event service
  (`ab.chatgpt.com`, `chatgpt.com/ces`); in the spike those failed only
  because the test browser had no route there. Apache can add a
  Content-Security-Policy that keeps the page's connections to its own
  address (to be checked that the panel still works with it).

### The Codex desktop app (step 6)

- The person adds an SSH public key in the page. The web server has one gate
  account whose `authorized_keys` lines force a UM-Codex command per key
  (`restrict`, no terminal, no forwarding on the gate itself).
- The desktop UM-Codex (or a one-line ssh config entry the page shows)
  writes `Host umcodex-<project>` with a ProxyCommand to that gate. The gate
  checks ownership, starts the container if needed, and runs `sshd -i` in it
  through the Podman API, exactly as `um-codex ssh-proxy` does with `docker
  exec` today. Port previews and sftp work as in M6, inside the container.
- The desktop launcher could offer this as a third "where": in a sandbox
  here, on this computer, or on the lab server.

## Migration steps, in order

1. ~~Decide~~ (done, below).
2. ~~Spike on the compute server~~ (done, below). Left for the pilot:
   internet on, the Content-Security-Policy, approvals ("ask before
   commands") in the panel, idle stop, two people at once.
3. **Server image variant:** code-server and the extension (pinned), the
   page's settings above, any-uid support, no sudo; built and smoke-tested
   in release CI like the agent image (amd64 only). The spike's version
   added 1.6 GB to the 4.7 GB agent image.
4. **Server set-up (the maintainer runs or approves each):** on the compute
   server, UM-Codex's folders, the router unit, the cgroup parent; on the
   web server, the UM-Codex unit (a service account, ideally), its tunnel
   unit (Podman sockets, the relay socket back, the router socket), its
   credentials, and an Apache location. Document it in the private wiki.
5. **`um-codex server` in this repo:** sign-in and ownership (copied from
   DataLab's server mode, said so at the top of each file), projects and
   folder rules for server paths, Standard/High, the relay on a Unix socket,
   container lifecycle through the tunnel, the router's signed requests, the
   audit log, an administrator page, `server install`/`rollback` (copied
   from DataLab). Tests at each boundary with shapes taken from the live
   Podman.
6. **Pilot** with the maintainer and one or two people, on non-sensitive
   folders: both tiers, internet on and off, a dashboard, a long job, idle
   stop.
7. **The Codex app over SSH** (the gate) and the desktop launcher's "on the
   lab server" choice.
8. **Open to the lab:** README section, the lab's guide, NAS roots enabled.
9. **Later:** U-M single sign-on, backups of project folders, per-project
   download policy.

Rough size (focused work): spike 1–2 days; image 2 days; service 6–10 days;
pilot fixes 2–4 days; the SSH gate 2–4 days.

## Decisions (the maintainer, 2026-10-22)

1. **Spike on the compute server:** go ahead (done, below).
2. **Toolkit key:** one lab key.
3. **Who:** anyone in the lab may use it, High and the GPU included.
4. **Identity:** GitHub sign-in, with an administrator's table GitHub id →
   uniqname.
5. **Limits:** High is 10 CPUs and 100 GB (the caps around it are a
   suggestion under "Compute").
6. **Folders:** projects live in a `um-codex` folder on the lab's NAS share
   (made; see "Projects"). Codex's homes stay on the compute server's local
   disk.
7. **Internet and downloads:** each person decides, per project.
8. **sudo:** none, unless a real need shows up.
9. **Service accounts:** no preference; UM-Codex runs as the maintainer's
   account like DataLab for now.
10. **Off-VPN:** no. The web server needs the medical school VPN, and that
    stays.

Still to provide, when building (the maintainer places secrets himself):
the lab key as UM-Codex's own systemd credential, a GitHub App client secret
(or a second callback URL on the lab's App), a token-encryption key and the
router's signing secret; and whether the NAS share is backed up.

## The spike (2026-10-22)

**What ran.** The maintainer's Mac stood in for the web server: UM-Codex's
own relay (`relay.Relay`, the key from the Mac's keychain, sent only to the
Toolkit) and an SSH tunnel to the compute server forwarding its two Podman
sockets here and the relay's socket there (a socket in a 0700 folder; the
gateway's nginx needs it 0666). Through that tunnel, the Docker CLI on the
Mac started, on the compute server, under UM-Codex labels and names: an
internal network, the pinned nginx gateway (proxying `/v1/` to the relay's
socket) and the released agent image (0.1.0-alpha.7) plus code-server
4.141.0 and the Codex extension 26.5908.31748 (checksum-pinned). Codex's
settings were written by UM-Codex's own `codex_config` (with `app=True`:
the token from `umcodex-token`, API login only, the model catalog from the
image's Codex and the Toolkit's list). The agent ran as the maintainer's uid
with `--cap-drop ALL`, `no-new-privileges`, `--cpus 10 --memory 100g
--cpuset-cpus 0-9`, `/work` on the NAS `um-codex` folder, Codex's home on
local disk, internet off. code-server listened on a Unix socket, forwarded
to 127.0.0.1 on the Mac, and a headless Chromium drove the page.

**What it showed (VERIFIED, live):**
- UM-Codex's container commands work through Podman's Docker API: `network
  create --internal`, `run` with labels, `--network-alias`, `inspect` of a
  container, `rm -f` and `network rm` by name, cleanup by label. As the wiki
  says, `--dns` stops name lookups, so the agent got `--add-host
  gateway:<ip>`.
- The relay through the forwarded socket: the gateway answered the
  watchdog's `/v1/_umcodex/alive` with 204 and anything else with 404; real
  model calls went through it. With the internet off, `https://example.com`
  failed.
- In the container: the person's uid and group, `sudo` refused,
  `nproc` = 10, a 100 GB memory limit, `codex-cli 0.157.1`, files written to
  the NAS as the person's uid.
- **The page:** with the image's Codex (see "The page" for the setting),
  Codex's panel opened with no sign-in, straight to its composer. A prompt
  made `hello.py`, ran it and answered "4 10" (10 CPUs), with the edit shown
  with Undo and Review. A second prompt wrote a Streamlit app and started it
  with `um-codex-dashboard`; it rendered in Chromium through
  `/proxy/8501/` (live updates over WebSocket included), and code-server's
  Ports tab listed it. The terminal ran Codex's own terminal interface
  (0.157.1, the provider's model, `/work`, full access).
- **The GPU:** the same agent started through the GPU socket with a plain
  `docker run`: Codex ran `nvidia-smi` and answered "Quadro RTX 8000, 46080
  MiB | 10 100g".
- Chats were kept in the project's Codex home across a restart of the
  container.

**Found along the way:**
- The gateway's relay socket can't be mounted under `/run`: with the
  gateway's tmpfs on `/var/run` (a link to `/run` in nginx's image) the
  start failed once in two ("tmpcopyup … lchown … no such file"). Mounted at
  `/umcodex/relay.sock` it was fine.
- The Codex extension spawns its own bundled Codex (0.154.0-alpha) unless
  `chatgpt.cliExecutable` is set in code-server's User settings; that one
  showed a ChatGPT sign-in. With the image's 0.157.1 there's none.
- The Claude desktop app's built-in browser can't register service workers,
  so VS Code's panels (webviews) don't load there; Chrome, Edge and Firefox
  do. Not a problem for people, only for testing from that pane.
- Codex 0.157.1 tries to sync OpenAI's curated plugins from GitHub and
  chatgpt.com at start; with the internet off that only logs warnings.
  Worth turning off in the managed settings for the server.

**Cleaned up:** containers, networks, sockets, the token, the spike image
and the spike's folders were removed. Kept on the compute server: the
pulled release agent and nginx images, an empty UM-Codex folder on local
disk, and the NAS `um-codex` folder with the maintainer's empty `projects`.

## Spike 2: the Codex desktop app, streamed to the browser (2026-10-23)

Asked by the maintainer: can the Codex desktop app itself run in a browser?
OpenAI has no browser version, but it ships the app for Linux (a public
preview since 2026-08-11: `chatgpt_amd64.deb` from
`persistent.oaistatic.com/codex-app-prod/linux/deb/latest/`, package
`chatgpt`, version 26.1016.61520 that day, 525 MB, 1.7 GB installed; Ubuntu
24.04, which is the agent image's base, is supported). So the app can run
in the person's container on a virtual screen, shown in the browser.

**What ran.** The same set-up as the first spike (tunnel, relay, gateway,
the person's uid, no capabilities, 10 CPUs and 100 GB, internet off), with
an image adding the `.deb` (checksum-pinned; its install script adds
OpenAI's apt repository, which the image then removes, so the version stays
put), TigerVNC's `Xvnc` (on the container's own localhost, no password:
only code-server's proxy reaches it), the openbox window manager, and noVNC
with websockify. The app ran as `chatgpt --no-sandbox --disable-gpu` (its
Chromium sandbox can't work with no capabilities; the container is the
sandbox), with `--shm-size 1g`. noVNC was opened through code-server's port
proxy (`/proxy/6080/vnc.html`), so it sat behind the same way in as the
page.

**What it showed (VERIFIED, live):**
- The app started with **no sign-in**. It opened on ChatGPT's "What type of
  work do you do?" onboarding (Skip works), then in **ChatGPT Work** mode;
  its menu switches to **Codex**. Its footer named the provider "U-M GPT
  Toolkit (through UM-Codex)", from UM-Codex's enforced settings, and it
  offered only Full access and the setup's model (5.6 Terra).
- Creating a project used a GTK folder picker inside the container
  (`/work` was listed). A prompt made `hello2.py`, ran it and answered "4 10
  codex-cli 0.157.1 10", with the app's own edit card (Undo, View changes).
  Model calls went through the gateway and relay as before.
- The app runs **its own bundled Codex, 0.163.0-alpha.11.1**, not the
  image's pinned 0.157.1 (the `codex` in the shell is still 0.157.1). It
  still obeyed `/etc/codex` (provider, permissions). Pointing it at the
  image's Codex (`CODEX_CLI_PATH`) wasn't tried.
- Memory: the container used about 1.0 GB in all with the app, Xvnc and
  code-server idle (the app's processes about 0.8 GB of that, its Codex
  0.3 GB). The image grew by 2.7 GB (9.0 GB in all with code-server).
- Keyboard: real key presses reach the app through noVNC. The test browser
  could only send text by synthetic key events (its "insert text" is
  ignored by noVNC, as is Ctrl+V from it); a person typing in a real browser
  has no such problem. Copy and paste between the person's computer and the
  app goes through noVNC's clipboard panel, by hand.

**Not checked:** the app's in-app browser for dashboards (it would run in
the container, on the virtual screen), approvals in the app, the app with
the internet on (it would then reach OpenAI's services from the container,
as the Mac app does), and how it feels over the VPN from home.

### The two pages compared

| | code-server + Codex panel (spike 1) | Desktop app, streamed (spike 2) |
|---|---|---|
| Looks like | VS Code in the browser, Codex in a side panel (the same chat UI as the app) | the Codex desktop app, exactly |
| How it's drawn | the browser draws it, so text and typing are local | a compressed picture from the server: some lag over the network (not timed) |
| Codex it runs | the image's pinned Codex (by setting) | the app's own bundled alpha, changing with each app version |
| Files | editor, file tree, drag-and-drop upload, download | the app's views; no upload or download through the stream |
| Copy and paste | normal | through noVNC's clipboard panel |
| Dashboards | code-server's `/proxy/<port>/`, checked | the app's in-app browser on the virtual screen (not checked) |
| Extra per project | ~0.2 GB memory (code-server) | ~0.8 GB memory, and about a fifth of a CPU at rest |
| Image | +1.6 GB | +2.7 GB more |
| Supported by OpenAI | the extension, yes; in code-server, not documented | the Linux app is a preview; streaming it, not documented |

**Recommendation:** keep code-server with the Codex panel as the page. Offer
the streamed app as an optional **App view** button on a project only if
people ask for it. If so: pin the `.deb`, check each app update the way this
spike did (its bundled Codex changes with it), and use KasmVNC rather than
TigerVNC + noVNC for seamless copy and paste and better image quality.

**Cleaned up:** the container, its networks and sockets, the spike image
and folders. Nothing new was kept.

## Risks

- **Not a supported setup.** The Codex extension in code-server, the app's
  SSH mode with a custom provider and the app-server internals can change in
  any update. Mitigation: pin both, check each update in the spike's way,
  keep the terminal (`codex` TUI) as the fallback that always works.
- **Root on the compute server.** Whoever can reach the Podman socket is root
  there, and so is any bug in the service's container commands. Keep the
  service's commands built from fixed argument lists, tested; the router
  and gate narrow; people never near the socket.
- **Study data and the internet.** A project with identifiable data and the
  internet on can send that data anywhere (or be told to by a web page's
  prompt injection). The maintainer chose to leave it to each person
  (decision 7), as on the desktop; the page must say it plainly.
- **Losing sudo** breaks workflows that install system packages; the image
  must carry more.
- **Sharing the machine:** one GPU without partitioning; CPU and memory
  shared with DataLab, remote desktops and other studies; cgroup v1
  reporting. Caps and clear "busy" messages.
- **Server maintenance:** HITS updates can overwrite Podman drop-ins, the
  GPU socket and CDI spec (the wiki lists them). UM-Codex adds a few files of
  its own to that list.
- **One person runs it all:** the maintainer's account, keys and approvals
  everywhere. Service accounts and the wiki reduce this.
- **The VPN:** everything needs it (decision 10): a layer of protection,
  and also no use from off-campus without it.
- **Files leaving the server:** page downloads and the app's sftp copy files
  to laptops. Policy, not prevention, unless downloads are turned off.

## Not needed (compared with DataLab's High compute)

- **No sshfs mount on the web server.** The page, the editor and uploads all
  run in the container on the compute server, so the web server never reads
  a project's files.
- **No standard tier on the web server.** It stays for sign-in, the relay,
  the pages and DataLab.
