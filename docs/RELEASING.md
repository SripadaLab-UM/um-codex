# Releasing UM-Codex

For the maintainer. How a release is made, signed and installed, and what to
set up once before the first one. Adapted from IHS DataLab's
`docs/DISTRIBUTION.md` at `6b6fdca` ("Release signing", "How an update is
installed", "Where the app lives", "For the maintainer: releasing").

## Before the first release (once)

Already set up on this repository:
- the **`release` environment**, with required reviewer `ataxali` and a
  deployment policy of tags matching `v*` only (a run from any other branch
  or tag can't use it);
- the **tag rulesets** (DataLab's two, copied here): only maintainers create
  `v*` tags, and they can't be moved or deleted.

Left for the maintainer. Nothing is published until all four are done: the
release workflow stops at its `version` job while
`src/umcodex/release_keys.py` pins no key, and at `sign` without the secret.

1. **Make the release key, on your own computer.** In a checkout of this
   repository:

   ```sh
   uv run python scripts/sign-release.py --new-key
   ```

   It prints a private key and a public key (Ed25519, base64). The private
   key goes only into step 2 (a copy in a password manager is fine); never
   commit it, paste it into an issue, a chat or a terminal session someone
   else records, or give it to a coding agent. UM-Codex's tools never make
   or see it.
2. **The secret:** in Settings → Environments → `release`, add the
   environment secret `RELEASE_SIGNING_KEY`: the private key from step 1.
3. **Pin the public key:** paste it into `RELEASE_KEYS` in
   `src/umcodex/release_keys.py` (replacing the TODO), with the date, and
   merge that through a pull request. A release signs only with a key its
   own package pins (`sign-release.py` refuses otherwise), so each version
   accepts the next one.
4. **Immutable releases:** Settings → General → Releases, turn on immutable
   releases, so a published release's files can't be replaced or added to.

And once, during the first release run (below): **make the image public.**
The first run pushes `ghcr.io/sripadalab-um/um-codex-agent`, which GitHub
creates as a private package. Once the run's `manifest` job has finished,
while `sign` waits for approval and before you approve it, open the
organisation's Packages → `um-codex-agent` → Package settings, set its
visibility to **Public** and connect it to this repository. A release whose
image can't be pulled without signing in would fail every install. (The
organisation must allow public packages.)

## Making a release

1. In a pull request, set `__version__` in `src/umcodex/__init__.py` to the
   new version (PEP 440: `0.1.0a2`, `0.2.0b1`, `1.0.0rc1`, `1.0.0`), and
   update the docs that change with it. Merge it once CI is green.
2. Tag the merged commit on `main` and push the tag. The tag is the version
   with a `v`, pre-releases written the usual way:

   ```sh
   git fetch origin && git tag v0.1.0-alpha.2 origin/main && git push origin v0.1.0-alpha.2
   ```

   `v0.1.0-alpha.2` (or `v0.1.0-a2`, `v0.1.0a2`) is version `0.1.0a2`;
   `-beta.N` is `bN`, `-rc.N` is `rcN`. A tag that doesn't match
   `__version__` stops the release before anything is built
   (`scripts/release-version.sh`).
3. In Actions, the **Release** run waits at `sign` for approval. The first
   time, make the image public now (above). Check the run is for the tag
   you pushed, then approve it. The release is published a minute later.
   Runs go one at a time (`concurrency: release`), and a running one is
   never cancelled. But GitHub keeps only one *pending* run per group: a
   second tag pushed while one run waits queues a run that cancels the first
   pending one. So push release tags one at a time, and if a run was
   cancelled, re-run it from Actions (Re-run all jobs).

### What the workflow does (`.github/workflows/release.yml`)

- `checks`: all of `ci.yml`, on the tagged commit.
- `version`: the tag matches the package version, and the package pins a
  valid release key (`sign-release.py --check-pinned`).
- `reuse`, `image`, `manifest`: the agent image
  `ghcr.io/sripadalab-um/um-codex-agent`, for `linux/amd64` and
  `linux/arm64`, keyed by `images/agent`'s git tree id. `image` and
  `manifest` attest the build's provenance (`actions/attest-build-provenance`,
  pushed to the registry). When `images/agent` is unchanged since an image
  already in the registry (tag `tree-<id>`), `reuse` takes that image only if
  its index lists both platforms and `gh attestation verify` finds
  provenance from this repository's `release.yml`; otherwise it's rebuilt.
  `manifest` reads the digest from what this run built (`tree-<id>`) or
  checked, checks both platforms again, tags it with the release tag and
  passes it on by digest.
- `package` (`scripts/build-release.sh`): builds the package from a copy of
  the source with `images.json` stamped (the agent image by digest, the
  gateway's nginx as pinned in `src/umcodex/images.json`), and gathers the
  release's files:

  | File | What |
  |---|---|
  | `umcodex-<version>-py3-none-any.whl` | the package |
  | `requirements.txt` | every dependency from `uv.lock` by version and hash (`uv export`), then the package by its checksum |
  | `images.json` | the agent and gateway images, by digest |
  | `install-macos.sh`, `install-windows.ps1` | the installers, with this release's address and package name written in (`RELEASE_BASE`/`RELEASE_WHEEL`, `$ReleaseBase`/`$ReleaseWheel`), so they need no arguments |
  | `uninstall-macos.sh`, `uninstall-windows.ps1` | the uninstallers |
  | `SHA256SUMS` | all of the above, by SHA-256 |

  It never sees the signing key.
- `sign`: the only job in the `release` environment (a test keeps it so).
  On a fresh runner it installs only the locked Python dependencies (no
  build, no Docker), checks every file against `SHA256SUMS` and that the
  files there are exactly those listed, and signs: `SHA256SUMS.sig`, with
  the environment's own `.venv/bin/python`, so uv never sees the key. It
  refuses a key the package doesn't pin.
- `publish`: `gh release create` with every file, and the flags
  `scripts/release-latest.py` gives. GitHub's `releases/latest` never points
  at a GitHub pre-release, and the install commands download from
  `releases/latest/download`, so until a full release exists every release
  (alphas included) is a normal release; `um-codex update` tells
  pre-releases by their version anyway. A release is marked the latest only
  when its version is newer (PEP 440) than every published release's tag,
  so a run approved late, or a fix on an older line, never takes "latest"
  from a newer version. Once a full release exists, a pre-release version
  (`v1.1.0-alpha.1` after `v1.0.0`) is marked a GitHub pre-release and never
  the latest, so new installs keep getting the newest full release.

Every action is pinned by its full commit, with its version in a comment
(a test rejects `@v...` references). The jobs that build or sign (`version`,
`package`, `sign`, `publish`) use the uv the installers pin, with its cache
off, and check out without keeping git credentials.

If signing fails or isn't approved, nothing is published; the agent image
stays in the registry, which is harmless (UM-Codex runs images only by the
digests in a signed `images.json`). Release tags can't be deleted or moved
(the tag ruleset has no bypass), so to recover: if the cause is outside the
tagged code (an approval, a GitHub outage, the secret), fix it and use
"Re-run failed jobs" on the same run; if the tagged code itself has to
change, fix it on `main`, bump `__version__`, and tag the new version.

Not automated: Authenticode-signing the Windows scripts (needs the lab's
certificate), and an install, update and rollback on a real Windows machine.
`release.yml` marks both as TODOs.

## For the install site

An install website (made separately, like DataLab's) only needs to link to
a release's files. Nothing about UM-Codex is configured by the site: there's
no lab settings file, and the installers carry everything they need.

**Files in every release** (`scripts/build-release.sh`), all listed in
`SHA256SUMS`, which is signed as `SHA256SUMS.sig`:

| File | What it is |
|---|---|
| `install-macos.sh` | Mac installer, stamped with its own release's address: needs no arguments |
| `install-windows.ps1` | Windows installer, stamped the same way |
| `uninstall-macos.sh` | Mac uninstaller (asks "Uninstall UM-Codex? [y/N]" first) |
| `uninstall-windows.ps1` | Windows uninstaller (the same question) |
| `umcodex-<version>-py3-none-any.whl` | The package, with the images pinned by digest inside |
| `requirements.txt` | Every dependency by version and hash, and the package by its checksum |
| `images.json` | The agent and gateway images, by digest |
| `SHA256SUMS`, `SHA256SUMS.sig` | Checksums of all of the above; the signature (Ed25519, key pinned in `src/umcodex/release_keys.py`) |

**Addresses.** `latest` always points at the newest release by version (the
`publish` job decides; see "Making a release"):

- Newest: `https://github.com/SripadaLab-UM/um-codex/releases/latest/download/<file>`
- One version: `https://github.com/SripadaLab-UM/um-codex/releases/download/v<version-tag>/<file>`

Releases are immutable, so a version's files never change once published.

**Commands to show people:**

- Install on a Mac (Terminal):
  `curl -fsSL https://github.com/SripadaLab-UM/um-codex/releases/latest/download/install-macos.sh | sh`
- Install on Windows (PowerShell; the first part turns on TLS 1.2, which
  older Windows PowerShell needs for GitHub):
  `[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm https://github.com/SripadaLab-UM/um-codex/releases/latest/download/install-windows.ps1 | iex`
- Uninstall on a Mac:
  `curl -fsSL https://github.com/SripadaLab-UM/um-codex/releases/latest/download/uninstall-macos.sh | sh`
- Uninstall on Windows:
  `[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm https://github.com/SripadaLab-UM/um-codex/releases/latest/download/uninstall-windows.ps1 | iex`
- Update an installed UM-Codex: `um-codex update` (it checks the signature itself).

A site that offers the files for download instead can link to them directly,
and show how to check one: `shasum -a 256 -c SHA256SUMS --ignore-missing`
on a Mac, or compare `Get-FileHash <file>` with `SHA256SUMS` on Windows.

**What people need before installing:** a U-M GPT Toolkit API key for Codex
(ITS's "Codex Setup" articles say how to get one); a Mac with macOS 14 or
newer, or Windows 10/11 with virtualization on; about 10 GB free for Docker
Desktop and the images. On a Michigan Medicine Windows computer, the
installer's one administrator step needs temporary administrator access
first. The installer says so, and its `-AdminAccessUrl` option takes that
page's address so it can name it. Options can't follow `| iex`; this form
passes them:
`[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; & ([scriptblock]::Create((irm https://github.com/SripadaLab-UM/um-codex/releases/latest/download/install-windows.ps1))) -AdminAccessUrl "https://<the page>"`
(the public repo never names the page; the site can).

## Release signing

`SHA256SUMS` is signed with the release key (Ed25519, `src/umcodex/signing.py`,
over a fixed UM-Codex prefix and the file's exact bytes, so a signature made
for anything else, DataLab's included, never passes). Each installed
UM-Codex trusts only the public keys pinned in its own package
(`release_keys.py`); with none pinned (or one that isn't a valid key) it
trusts no release and `um-codex update` says updates aren't set up. Since
`SHA256SUMS` names every other file by checksum, including
`requirements.txt` (every dependency by hash) and `images.json` (every
image by digest), the signature covers everything an update installs.

**Changing keys.** Release a version that pins both the current and the new
key (signed with the current one); the release after that can be signed
with the new key. Then replace `RELEASE_SIGNING_KEY`.

**What it protects against:** someone who can change the repository's
releases but doesn't hold the key (a token that can upload or replace
release files, a changed file in GitHub's storage or on the way, an index
serving other dependency files).

**What it doesn't:** code merged into `main` and released the normal way;
the build's own tools and dependencies; anyone who can approve the
`release` environment or holds the key; GitHub withholding new releases;
and the first install, which trusts the installer and package the person
downloaded (the installer checks the package against `requirements.txt`,
but nothing checks that pair against the key).

## How `um-codex update` works (`src/umcodex/update.py`)

1. **Check** (`releases.py`), without signing in: the repository's releases
   from GitHub's API. Offered: never a draft; only a tag that's a PEP 440
   version newer than the installed one; pre-releases only while the
   installed version is itself one (as DataLab's "auto" channel); only a
   release with the package for exactly that version, `requirements.txt`,
   `images.json`, `SHA256SUMS` and `SHA256SUMS.sig`, each with GitHub's own
   checksum (`digest`). Releases missing any of these are skipped. The
   newest one's `SHA256SUMS` must be signed by a pinned key and list the
   other three with GitHub's checksums, or it's refused (not passed over).
2. **Download and check** into `<app>/downloads/<version>/`: each file must
   match the signed `SHA256SUMS` (downloads follow GitHub's redirects only to
   its own hosts, over https). `requirements.txt` must pin every dependency
   as `name==version` with hashes and name the package once, by its
   checksum, and hold nothing else. `images.json` must pin exactly the agent
   (`ghcr.io/sripadalab-um/um-codex-agent`) and gateway images by digest,
   and match the new package's own `images.json`.
3. **Install beside** in `<app>/versions/<version>/` with the installers'
   own uv flags (`uv venv --no-config --python 3.13`, plus
   `--python-preference only-managed` on a Mac; `uv pip install --no-config
   --require-hashes --only-binary :all: --default-index
   https://pypi.org/simple --link-mode copy -r requirements.txt`), with no
   `UV_*`, `PIP_*` or `PYTHON*` variables from the environment; check the
   new `um-codex --version`, then write `.complete` with the package's
   checksum (as the installers do, so the same package is reused; a reused
   folder that no longer passes `--version` is removed and installed
   afresh). uv is the installers' own: `%LOCALAPPDATA%\UM-Codex\uv\uv.exe`
   on Windows, `~/.local/bin/uv` on a Mac, before any other on PATH.
4. **Pull** the new version's images with its own `um-codex pull`.
5. **Switch**: on Windows first, `bin\um-codex.exe` becomes a copy of the
   new version's launcher (copied beside it as `.um-codex.exe.new`, the
   running one renamed aside, then moved into place, as the installer does);
   then `previous` names the running version and `current` the new one, each
   one-line file replaced whole.
6. **Prune** every version but those two (only folders named as versions),
   each unmarked (its `.complete` removed) before it's deleted, so one whose
   removal stops part way never counts as installed.

It refuses while any launch is running (each launch holds a lock), runs one
at a time, and undoes what it installed if a step fails, so the running
version stays the one in use. It works only in a copy the installer made
(not a development checkout). `um-codex update --rollback` switches
`current` and `previous`, then pulls that version's images (usually still
there; if that fails it says to run `um-codex pull`).

**At launch**, at most once a day, `um-codex` asks the same question and,
when a newer release is out, prints one line: "UM-Codex X is available: run
um-codex update". It waits for GitHub 3 seconds at most (a slower answer is
remembered for the next launch), and says nothing when offline, in a
development copy, or while no key is pinned. It remembers the last check in
`update-check.json` in the data folder. `UMCODEX_NO_UPDATE_CHECK=1` turns it
off.

## Where the app lives

As the installers lay it out (docs/INSTALLING.md):
`~/Library/Application Support/UM-Codex/app` on a Mac,
`%LOCALAPPDATA%\UM-Codex\app` on Windows (`UMCODEX_INSTALL_DIR` for tests).

```
versions/<version>/   one Python environment per version; .complete when whole
current               the version the launchers run
previous              the one before the last switch
bin/um-codex          the command (Mac: a shim that runs `current`;
                      Windows: um-codex.exe, a copy of current's own launcher)
downloads/<version>/  a release's files while it's being installed
update.lock           held while an update or rollback runs
```

## Testing it without GitHub

`tests/test_release.py` runs `scripts/build-release.sh`, signs its files with
a throwaway key, serves them as GitHub's API does on 127.0.0.1
(`tests/fake_github.py`) and installs them with `um-codex update` (uv and the
new version's commands stood in for). `UMCODEX_RELEASES_API` points the
check at such a stand-in, on this computer only.
