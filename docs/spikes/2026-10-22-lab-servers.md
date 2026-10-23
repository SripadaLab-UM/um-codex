# Proposal: UM-Codex on the lab's servers

Date: 2026-10-22. **Not decided; nothing built.** Branch `lab-servers-plan`.
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
  folders and `/etc/subuid`. Nothing was changed on either. One side effect:
  `podman info` run as the maintainer's own account may have made an empty
  rootless store folder in that account's home.
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
   OpenAI's cloud, not the U-M GPT Toolkit (details below).
3. **Normal or high compute at sign-in or per project?** Per project, like a
   setup's internet switch, with a personal default chosen at first sign-in.
   Both tiers run on the compute server (the web server is too small, and
   hosts DataLab), with different limits; High adds the GPU. Changing it
   takes effect at the project's next start, since the files are on the
   compute server either way. Administrators decide who may use High.

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
- Both servers need the medical school network or VPN for SSH. **UNSURE:**
  whether the web server's HTTPS is reachable off VPN.

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
  (an administrator's table: GitHub id → uniqname; the uid and groups come
  from the compute server's own directory). Containers run as that uid and
  its groups, so a person can never reach a file through UM-Codex that their
  own account couldn't. The alternative, U-M's single sign-on (giving the
  uniqname directly), needs ITS to register the service.

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

### Compute

| | Standard | High |
|---|---|---|
| CPUs | 4 (example) | 16, pinned to one processor, as DataLab |
| Memory | 16 GB (example) | 64 to 128 GB |
| GPU | no | yes (through the GPU socket) |
| At once | a few per person | 1 per person, 2 in all (example) |

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
- **Whose key** is a decision: one lab key (as DataLab), or each person's own
  Toolkit key entered once in the page and kept encrypted (as DataLab keeps
  people's GitHub tokens). Per-person keys keep billing and limits per
  person, as the desktop has it now.

### Containers on the compute server: what changes

- **No `sudo` in the server's containers.** Podman there is rootful with no
  user namespace, so root in a container is root on every mounted folder: it
  could leave a setuid-root program in a project folder that the person (who
  also has a shell on that machine) could then run. So the agent runs as the
  person's uid with `--cap-drop ALL` and `no-new-privileges`. Python, R and
  Node packages still install into the project (uv, renv, npm); system
  packages come from the image. This is the one real loss against the
  desktop.
- The image needs to run as any uid (writable home and caches per project),
  as DataLab's agent already does.
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
- code-server can turn downloads off; for projects with identifiable data
  that may be wanted (a decision).

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

1. **Decide** the items below.
2. **Spike on the compute server** (needs the maintainer's OK: it runs
   containers there, under UM-Codex names, nothing of DataLab's touched):
   the agent image as a person's uid through the tunnelled Podman API, with
   code-server and the Codex extension and a stub upstream. Check: no sign-in
   screen; the extension uses the image's `codex` and the enforced settings;
   chats, approvals and diffs work; a dashboard through the port proxy; the
   GPU socket; a NAS folder as the person's uid; that UM-Codex's own
   container commands work on Podman (and fix those that don't).
3. **Server image variant:** code-server and the extension (pinned), any-uid
   support, no sudo; built and smoke-tested in release CI like the agent
   image (amd64 only).
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

## What the maintainer must decide or provide

1. **Go-ahead for the spike** on the compute server (step 2).
2. **Whose Toolkit key:** one lab key, or each person's own (entered in the
   page, kept encrypted). If per person: whether usage is billed per person
   today.
3. **Who may use it, and High:** the same GitHub team as DataLab? Who may
   use High and the GPU?
4. **Identity:** the GitHub → uniqname table kept by an administrator, or
   U-M single sign-on (needs ITS).
5. **Limits:** how much of the compute server the lab's apps may use in all
   (CPUs, memory, GPU), and the Standard and High sizes.
6. **Folders:** which roots people may add (the NAS share, a shared folder),
   where project folders live (local disk is fast but not known to be backed
   up; the NAS is large and slower), and whether either is backed up.
7. **Internet with study data:** may a project with NAS (study-data) folders
   have the internet on? Downloads allowed for such projects?
8. **No sudo** in the server's containers (above): acceptable?
9. **Service accounts:** DataLab's units and the tunnel run as the
   maintainer's own account today. UM-Codex's could use a service account on
   both servers (and a Podman-socket group under a neutral name).
10. **Secrets to place** (the maintainer places them, as for DataLab): the
    Toolkit key (if a lab key), the GitHub App client secret (or a second
    callback on the lab's App), a token-encryption key, the router signing
    secret.
11. **Off-VPN:** is the web server's HTTPS reachable without the VPN, and
    should UM-Codex be?

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
  prompt injection). The desktop accepts this for the person's own files;
  on the approved server it needs a rule (decision 7).
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
- **The VPN:** SSH (option A) needs it; HTTPS may too (decision 11).
- **Files leaving the server:** page downloads and the app's sftp copy files
  to laptops. Policy, not prevention, unless downloads are turned off.

## Not needed (compared with DataLab's High compute)

- **No sshfs mount on the web server.** The page, the editor and uploads all
  run in the container on the compute server, so the web server never reads
  a project's files.
- **No standard tier on the web server.** It stays for sign-in, the relay,
  the pages and DataLab.
