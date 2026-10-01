#!/bin/sh
# UM-Codex installer for macOS.
# Adapted from IHS DataLab's installer/macos/install.sh at 6b6fdca: the Docker
# Desktop step is DataLab's, unchanged but for names; docs/INSTALLING.md lists
# every DataLab finding kept here, so later changes keep them.
#
#   sh install.sh --package <umcodex .whl file or URL> [--requirements <requirements.txt or URL>]
#                 [--install-docker] [--replace-key]
#
# or, straight from the web:
#
#   curl -fsSL <url>/install-macos.sh | sh -s -- --package <url> --requirements <url>
#
# requirements.txt comes with each release: every dependency pinned by version
# and hash, and the package by its checksum. It's found automatically if it
# sits next to a local package file. Nothing is installed that it doesn't name.
#
# What it does:
#   1. Checks that Docker Desktop is installed and running, and starts it if it
#      isn't. If it's missing, offers to download Docker's official Docker Desktop
#      for this Mac and checks it's signed by Docker Inc. On an administrator
#      account, Docker's own installer puts it in /Applications (you type your
#      password once, for sudo); otherwise it's copied to Applications. Then it
#      opens it (its first-run window asks you to accept Docker's agreement) and
#      waits until it's running. --install-docker answers yes to that offer.
#   2. Installs uv (a Python installer) for you, if it isn't there already.
#   3. Installs UM-Codex, with its own Python, in your user account (no admin
#      rights). Each version gets its own folder, so a newer one installs beside
#      the one in use and the previous version is kept. The `um-codex` command
#      goes in ~/.local/bin.
#   4. Downloads the pinned container images (`um-codex pull`).
#   5. Asks for your U-M GPT Toolkit API key (one * per character) and hands it
#      to `um-codex key --from-stdin`, which saves it in your macOS Keychain. A
#      key that's saved already is kept, unless --replace-key.
#   6. Adds the UM-Codex app (it opens Terminal running `um-codex`) to
#      /Applications, or to ~/Applications if you can't add to /Applications
#      without sudo, and a shortcut to it on your Desktop. At the end it says
#      where everything went and offers to show the app in Finder and open it.
#
# UMCODEX_SYSTEM_APPLICATIONS (for tests) stands in for /Applications.

# The whole script is one { ... } block, so sh reads all of it before running
# any of it: a download cut short runs nothing, and with `curl ... | sh` no
# command it runs can read the rest of the script as its input.
{
set -eu

# Everything goes in your own user account: never run this as root.
[ "$(id -u)" -ne 0 ] || { echo "Run this without sudo."; exit 1; }
# Nothing from the environment may steer uv or pip (another index, checks
# turned off) or Python.
for name in $(env | sed -n 's/^\(UV_[A-Za-z0-9_]*\)=.*/\1/p; s/^\(PIP_[A-Za-z0-9_]*\)=.*/\1/p'); do
  unset "$name"
done
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP VIRTUAL_ENV

UV_VERSION=0.12.19
# Where `um-codex key` keeps the Toolkit key (umcodex/credentials.py): only
# whether it's there is looked up, never the key itself.
KEY_SERVICE=UM-Codex
KEY_ACCOUNT=toolkit-api-key
PACKAGE=""
REQUIREMENTS=""
INSTALL_DOCKER="ask"
REPLACE_KEY="no"
# Your PATH as it was, to say whether `um-codex` works as a plain command.
PATH_BEFORE="$PATH"
while [ $# -gt 0 ]; do
  case "$1" in
    --package) [ $# -ge 2 ] || { echo "--package needs a file or URL."; exit 2; }; PACKAGE="$2"; shift 2 ;;
    --requirements) [ $# -ge 2 ] || { echo "--requirements needs a file or URL."; exit 2; }; REQUIREMENTS="$2"; shift 2 ;;
    --install-docker) INSTALL_DOCKER="yes"; shift ;;
    --replace-key) REPLACE_KEY="yes"; shift ;;
    *) echo "Unknown option: $1"; exit 2 ;;
  esac
done
if [ -z "$PACKAGE" ]; then
  echo "Usage: sh install.sh --package <umcodex .whl file or URL> [--requirements <file or URL>]"
  exit 2
fi

# /Applications (UMCODEX_SYSTEM_APPLICATIONS in tests), and your own.
SYSTEM_APPS="${UMCODEX_SYSTEM_APPLICATIONS:-/Applications}"
USER_APPS="$HOME/Applications"
# Cleans up on the way out, however it ends: Docker's disk image is detached
# a half-made copy of it removed, and the download folder removed (a partial
# download is kept, to resume).
STAGE=""
DOCKER_MOUNT=""
DOCKER_PARTIAL=""
# The half-made copy of Docker Desktop, if there is one (only ever that name).
remove_partial_copy() {
  case "$DOCKER_PARTIAL" in
    */.Docker.app.umcodex-partial) rm -rf "$DOCKER_PARTIAL" 2>/dev/null || true ;;
  esac
}
# shellcheck disable=SC2329 # run by the EXIT trap below
cleanup() {
  if [ -n "$DOCKER_MOUNT" ]; then
    hdiutil detach -quiet -force "$DOCKER_MOUNT" >/dev/null 2>&1 || true
    rmdir "$DOCKER_MOUNT" 2>/dev/null || true
  fi
  remove_partial_copy
  if [ -n "$STAGE" ]; then rm -rf "$STAGE"; fi
}
trap cleanup EXIT
trap 'echo; echo "Stopped. Run this installer again when you are ready: it carries on from where it"; echo "stopped (a partly downloaded Docker Desktop is resumed; a half-made copy was removed)."; exit 130' INT TERM HUP

step() { printf '\n\033[1m%s\033[0m\n' "$1"; }
# Questions are read from the terminal, even when this script arrives on a pipe.
ask() {
  printf '%s ' "$1"
  answer=""
  if [ -r /dev/tty ]; then read -r answer < /dev/tty || answer=""; fi
  case "$answer" in [nN]*) return 1 ;; *) return 0 ;; esac
}

# ------------------------------------------------------------ Docker Desktop
# Docker Desktop is found where it's installed (/Applications or
# ~/Applications), and its `docker` command even when it isn't on PATH (the
# /usr/local/bin link missing, or linking to a Docker.app elsewhere): then
# the command inside the app is used, by its full path, and its folder goes
# last on PATH for the rest of this install (it holds Docker's credential
# helpers too). UM-Codex does the same each time it starts
# (umcodex/docker_path.py).
#
# If Docker Desktop is missing, it offers to download Docker's official one
# for this Mac, checks it's signed and notarized by Docker Inc before running
# anything from it, and installs it. An existing Docker Desktop is never
# reinstalled, upgraded, reset or reconfigured, and its containers, images,
# volumes and settings are never touched.
#
# For tests: UMCODEX_DOCKER_WAIT_SECONDS and UMCODEX_DOCKER_POLL_SECONDS set
# how long and how often it waits for Docker; UMCODEX_INSTALL_STOP_AFTER_DOCKER=1
# stops once Docker is ready, before anything is installed.
DOCKER_TEAM_ID=9BNSXJN65R
DOCKER_BUNDLE_ID=com.docker.docker
# Signed by Docker Inc's Developer ID; for the app, also its bundle id.
DOCKER_SIGNER="anchor apple generic and certificate leaf[subject.OU] = \"$DOCKER_TEAM_ID\""
DOCKER_TERMS=https://www.docker.com/legal/docker-subscription-service-agreement/
DOCKER_PAGE=https://docs.docker.com/desktop/setup/install/mac-install/
# Docker Desktop supports the current and two previous major macOS releases:
# 14 (Sonoma) or newer as of Docker Desktop 4.93. The downloaded app's own
# minimum is checked as well, before installing it.
DOCKER_MIN_MACOS=14.0
# The download (about 0.6 GB), the app (about 2 GB) and room for its first start.
DOCKER_NEED_GB=6
DOCKER_POLL="${UMCODEX_DOCKER_POLL_SECONDS:-5}"
DOCKER_CACHE="$HOME/Library/Caches/UM-Codex/docker-desktop"
DOCKER=""
DOCKER_APP=""
DOCKER_ADDED_TO_PATH=0

# Whether $1 is a Docker Desktop app bundle (by its bundle id).
is_docker_bundle() {
  [ -d "$1" ] && [ ! -L "$1" ] || return 1
  [ "$(plutil -extract CFBundleIdentifier raw -o - "$1/Contents/Info.plist" 2>/dev/null)" = "$DOCKER_BUNDLE_ID" ]
}
# The Docker Desktop app, if one is installed: /Applications, then ~/Applications.
find_docker_app() {
  DOCKER_APP=""
  for dir in "$SYSTEM_APPS" "$USER_APPS"; do
    if [ -d "$dir/Docker.app" ]; then DOCKER_APP="$dir/Docker.app"; return 0; fi
  done
  return 1
}
# $1 with every symbolic link followed: the file it really is.
real_path() {
  p="$1"; hops=0
  while [ -L "$p" ] && [ "$hops" -lt 40 ]; do
    to="$(readlink "$p")" || return 1
    case "$to" in /*) p="$to" ;; *) p="$(dirname "$p")/$to" ;; esac
    hops=$((hops + 1))
  done
  dir="$(cd "$(dirname "$p")" 2>/dev/null && pwd -P)" || return 1
  printf '%s/%s\n' "$dir" "$(basename "$p")"
}
# Whether $1 is an app installed in an Applications folder (/Applications,
# ~/Applications, or a folder inside either). Anything else isn't taken for
# an installed Docker Desktop: Docker's own half-done install or uninstall
# (~/Library/Application Support/com.docker.install/in_progress/Docker.app),
# the Trash, a disk image, a cache.
in_applications_folder() {
  case "$1" in
    */com.docker.install/*|*/.Trash/*|*/Library/*|*/Caches/*|/Volumes/*|"$DOCKER_CACHE"/*) return 1 ;;
    "$SYSTEM_APPS"/*|"$USER_APPS"/*|/Applications/*) return 0 ;;
  esac
  return 1
}
# A Docker Desktop elsewhere in an Applications folder: the app the docker
# command on PATH really is (a link to a renamed Docker.app, or one in a
# subfolder), or failing that one Spotlight knows.
find_docker_app_elsewhere() {
  if [ -n "$DOCKER" ]; then
    real="$(real_path "$DOCKER" || true)"
    case "$real" in
      */Contents/Resources/bin/docker)
        bundle="${real%/Contents/Resources/bin/docker}"
        if in_applications_folder "$bundle" && is_docker_bundle "$bundle"; then
          DOCKER_APP="$bundle"; return 0
        fi ;;
    esac
  fi
  command -v mdfind >/dev/null 2>&1 || return 1
  found="$(mdfind "kMDItemCFBundleIdentifier == '$DOCKER_BUNDLE_ID'" 2>/dev/null || true)"
  while IFS= read -r bundle; do
    case "$bundle" in
      */Docker.app/*) continue ;;
      *.app)
        if in_applications_folder "$bundle" && is_docker_bundle "$bundle"; then
          DOCKER_APP="$bundle"; return 0
        fi ;;
    esac
  done <<FOUND
$found
FOUND
  return 1
}
# The docker command: on PATH, or where Docker Desktop keeps it. With
# "prefer-app", the one in DOCKER_APP comes first (just installed: not
# another Docker's, such as Colima's or Homebrew's, that's on PATH).
find_docker_cli() {
  DOCKER=""
  app_cli="${DOCKER_APP:+$DOCKER_APP/Contents/Resources/bin/docker}"
  if [ "${1:-}" = prefer-app ] && [ -n "$app_cli" ] && [ -x "$app_cli" ]; then
    DOCKER="$app_cli"
    # The one on PATH, when it's a link to this same command.
    on_path="$(command -v docker 2>/dev/null || true)"
    if [ -n "$on_path" ] && [ "$(real_path "$on_path" || true)" = "$(real_path "$app_cli" || true)" ]; then
      DOCKER="$on_path"
    fi
  else
    DOCKER="$(command -v docker 2>/dev/null || true)"
    if [ -n "$DOCKER" ]; then return 0; fi
    for candidate in ${app_cli:+"$app_cli"} "$HOME/.docker/bin/docker"; do
      if [ -x "$candidate" ]; then DOCKER="$candidate"; break; fi
    done
  fi
  [ -n "$DOCKER" ] || return 1
  # Last on PATH: it doesn't hide anything already there.
  case ":$PATH:" in
    *":$(dirname "$DOCKER"):"*) ;;
    *) PATH="$PATH:$(dirname "$DOCKER")"; export PATH; DOCKER_ADDED_TO_PATH=1 ;;
  esac
}
# Runs a command, giving up after $1 seconds (a starting Docker can hang):
# then it's sent SIGTERM, and SIGKILL 2 seconds later, and this returns 124.
# The limit is kept by a parent process, not by an alarm in the command
# itself: docker is a Go program, and Go ignores SIGALRM. Perl runs the
# command directly (no shell), in a process group of its own so anything it
# started goes too; without perl, a background watcher does the same.
# UMCODEX_TEST_WITHIN=sh (for tests) uses the watcher even with perl there.
within() {
  seconds="$1"; shift
  if [ "${UMCODEX_TEST_WITHIN:-}" != sh ] && command -v perl >/dev/null 2>&1; then
    perl -e '
      use POSIX ":sys_wait_h";
      my $seconds = shift;
      my $pid = fork;
      exit 127 unless defined $pid;
      if ($pid == 0) { setpgrp(0, 0); exec { $ARGV[0] } @ARGV; exit 127 }
      sub stop {
        kill "TERM", -$pid, $pid;
        for (1 .. 20) { return if waitpid($pid, WNOHANG) == $pid; select(undef, undef, undef, 0.1) }
        kill "KILL", -$pid, $pid;
        waitpid($pid, 0);
      }
      $SIG{INT} = sub { stop(); exit 130 };
      $SIG{TERM} = sub { stop(); exit 143 };
      $SIG{ALRM} = sub { stop(); exit 124 };
      alarm $seconds;
      waitpid($pid, 0);
      alarm 0;
      exit(($? & 127) ? 128 + ($? & 127) : $? >> 8);
    ' "$seconds" "$@"
  else
    flag="$(mktemp "${TMPDIR:-/tmp}/umcodex-within.XXXXXX")"
    "$@" &
    pid=$!
    ( /bin/sleep "$seconds"; : > "$flag.fired"; kill -TERM "$pid" 2>/dev/null
      /bin/sleep 2; kill -KILL "$pid" 2>/dev/null ) >/dev/null 2>&1 &
    watcher=$!
    status=0
    wait "$pid" || status=$?
    kill "$watcher" 2>/dev/null || true
    wait "$watcher" 2>/dev/null || true
    if [ -e "$flag.fired" ]; then status=124; fi
    rm -f "$flag" "$flag.fired"
    return "$status"
  fi
}
# Whether Docker's engine answers. DOCKER_HUNG=1 when `docker info` had to be
# stopped (the app is up but its engine isn't answering).
DOCKER_INFO_SECONDS="${UMCODEX_DOCKER_INFO_SECONDS:-20}"
DOCKER_HUNG=0
docker_ready() {
  [ -n "$DOCKER" ] || return 1
  answered=0
  within "$DOCKER_INFO_SECONDS" "$DOCKER" info >/dev/null 2>&1 || answered=$?
  if [ "$answered" -eq 124 ]; then DOCKER_HUNG=1; else DOCKER_HUNG=0; fi
  [ "$answered" -eq 0 ]
}
# Whether any of Docker Desktop's programs are running (to notice it quitting).
# The path is compared as plain text, whatever characters it has.
docker_app_alive() {
  running="$(ps -axo command= 2>/dev/null)" || return 0
  case "$running" in *"$1/Contents/MacOS/"*) return 0 ;; esac
  return 1
}
# Whether the text $1 has the line $2, or (has_line_starting) a line that
# starts with $2. Plain text, and no pipe (grep -q in a pipe can leave
# printf writing to a closed pipe: "write error: Broken pipe").
NL='
'
has_line() { case "$NL$1$NL" in *"$NL$2$NL"*) return 0 ;; esac; return 1; }
has_line_starting() { case "$NL$1" in *"$NL$2"*) return 0 ;; esac; return 1; }
# Whether $1 (a macOS version) is at least $2.
version_at_least() {
  awk -v have="$1" -v need="$2" 'BEGIN {
    split(have, h, "."); split(need, n, ".")
    for (i = 1; i <= 3; i++) { if (h[i] + 0 > n[i] + 0) exit 0; if (h[i] + 0 < n[i] + 0) exit 1 }
    exit 0 }'
}
free_gb() { df -Pk "$1" 2>/dev/null | awk 'NR == 2 { print int($4 / 1048576) }'; }
now() { date +%s; }
# Yes unless the person types n or no; pressing Return is yes. With no
# terminal to answer (a script, a pipe, CI), no: nothing is installed unasked.
ask_default_yes() {
  printf '%s ' "$1"
  answer=""
  [ -r /dev/tty ] || return 1
  read -r answer < /dev/tty 2>/dev/null || return 1
  case "$answer" in [nN]|[nN][oO]) return 1 ;; *) return 0 ;; esac
}
# For a Docker Desktop that doesn't come up: leftovers of an earlier install.
leftovers() {
  echo "  - If Docker Desktop was uninstalled or installed only partway before, programs"
  echo "    from it may still be running: quit them (Activity Monitor, search for docker,"
  echo "    Quit), or simply restart the Mac."
}
rerun() {
  echo "Then run this installer again, the same way: it carries on from where it stopped,"
  echo "and anything already done isn't done twice."
}
# $1 is Docker Desktop, signed by Docker Inc and notarized. Sets
# NOT_GENUINE to why not: "gatekeeper" when Gatekeeper is off, so macOS
# can't say whether it's notarized, otherwise "signature".
docker_app_is_genuine() {
  NOT_GENUINE=signature
  [ -d "$1" ] && [ ! -L "$1" ] || return 1
  codesign --verify --deep --strict -R="$DOCKER_SIGNER and identifier \"$DOCKER_BUNDLE_ID\"" "$1" \
    >/dev/null 2>&1 || return 1
  signed="$(codesign -dv --verbose=2 "$1" 2>&1)" || return 1
  has_line "$signed" "TeamIdentifier=$DOCKER_TEAM_ID" || return 1
  has_line "$signed" "Identifier=$DOCKER_BUNDLE_ID" || return 1
  assessed="$(spctl -a -vv -t exec "$1" 2>&1)" || return 1
  if ! has_line_starting "$assessed" "origin="; then
    NOT_GENUINE=gatekeeper
    return 1
  fi
  has_line "$assessed" "source=Notarized Developer ID" || return 1
  has_line "$assessed" "origin=Developer ID Application: Docker Inc ($DOCKER_TEAM_ID)"
}
detach_docker_image() {
  if [ -n "$DOCKER_MOUNT" ]; then
    hdiutil detach -quiet "$DOCKER_MOUNT" >/dev/null 2>&1 \
      || hdiutil detach -quiet -force "$DOCKER_MOUNT" >/dev/null 2>&1 || true
    rmdir "$DOCKER_MOUNT" 2>/dev/null || true
    DOCKER_MOUNT=""
  fi
}
# Stops the Docker Desktop install: the image detached, the partial copy
# and (with "delete") the download removed, then $2... printed.
stop_install() {
  what="$1"; shift
  detach_docker_image
  remove_partial_copy
  rm -f "$DOCKER_CACHE/copy-errors"
  if [ "$what" = delete ]; then rm -f "$DOCKER_CACHE/Docker-$arch.dmg"; fi
  for line; do echo "$line"; done
  rerun
  exit 1
}

# Downloads, checks and installs Docker Desktop, and sets DOCKER_APP. Its
# agreement is left for the person to accept when Docker first opens.
install_docker_desktop() {
  echo "Docker Desktop isn't installed. UM-Codex runs Codex in Docker, so it's needed."
  echo
  if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" = 1 ]; then
    arch=arm64; kind="Apple silicon"
  elif [ "$(uname -m)" = x86_64 ]; then
    arch=amd64; kind="Intel"
  else
    echo "This Mac's processor ($(uname -m)) isn't one Docker Desktop supports, so UM-Codex"
    echo "can't run on it. It needs a Mac with Apple silicon or an Intel processor."
    exit 1
  fi
  macos="$(sw_vers -productVersion 2>/dev/null || echo 0)"
  if ! version_at_least "$macos" "$DOCKER_MIN_MACOS"; then
    echo "Docker Desktop needs macOS $DOCKER_MIN_MACOS or newer, and this Mac has macOS $macos."
    echo "Update macOS first (Apple menu > System Settings > General > Software Update)."
    rerun
    echo "If this Mac can't be updated that far, UM-Codex can't run on it."
    exit 1
  fi
  # An administrator account installs it with Docker's own installer (its
  # supported command-line install: into /Applications, with its helper and
  # /usr/local/bin links set up, after the person types their password for
  # sudo). Other accounts get a copy of the app: in /Applications if they can
  # add to it without sudo, otherwise ~/Applications.
  case " $(id -Gn 2>/dev/null) " in
    *" admin "*) method=docker-installer; place="$SYSTEM_APPS" ;;
    *) method=copy
       if [ -d "$SYSTEM_APPS" ] && [ -w "$SYSTEM_APPS" ]; then place="$SYSTEM_APPS"; else place="$USER_APPS"; fi ;;
  esac
  for where in "$HOME" "$(dirname "$place")"; do
    have="$(free_gb "$where")"
    if [ -n "$have" ] && [ "$have" -lt "$DOCKER_NEED_GB" ]; then
      echo "Docker Desktop needs about $DOCKER_NEED_GB GB of free disk space (for the download,"
      echo "the app and its first start), and this Mac has $have GB free."
      echo "Free up some space (Apple menu > System Settings > General > Storage)."
      rerun
      exit 1
    fi
  done

  echo "This installer can download Docker Desktop for this Mac ($kind) from Docker"
  if [ "$method" = docker-installer ]; then
    echo "(desktop.docker.com), check that it's signed by Docker Inc, and install it in"
    echo "$place with Docker's own installer: macOS asks for your password once, in"
    echo "this window. The download is about 0.6 GB."
  else
    echo "(desktop.docker.com), check that it's signed by Docker Inc, and copy it to"
    echo "$place. The download is about 0.6 GB."
  fi
  echo "When Docker Desktop first opens, it shows the Docker Subscription Service"
  echo "Agreement ($DOCKER_TERMS)"
  echo "for you to read and accept yourself: this installer doesn't accept it for you."
  echo "Docker Desktop's license terms apply to its use; your organisation may have its"
  echo "own guidance about Docker."
  if [ "$INSTALL_DOCKER" != yes ] \
    && ! ask_default_yes "Download and install Docker Desktop? [Y/n]"; then
    echo
    echo "Docker Desktop wasn't installed, and nothing was changed. To install it yourself:"
    echo "  1. Download Docker Desktop for Mac ($kind) from $DOCKER_PAGE"
    echo "  2. Open Docker.dmg and drag Docker to Applications."
    echo "  3. Open Docker from Applications and finish its setup, until its whale icon"
    echo "     at the top of the screen says Docker Desktop is running."
    rerun
    exit 1
  fi

  mkdir -p "$DOCKER_CACHE"
  dmg="$DOCKER_CACHE/Docker-$arch.dmg"
  if [ -f "$dmg" ]; then
    echo "Using the Docker Desktop download from before."
  else
    echo "Downloading Docker Desktop…"
    got=0
    # Given up on if it stalls (under 10 kB/s for 2 minutes).
    curl -fL --proto '=https' --proto-redir '=https' --tlsv1.2 --retry 3 --connect-timeout 30 \
      --speed-limit 10240 --speed-time 120 --progress-bar -C - -o "$dmg.part" \
      "https://desktop.docker.com/mac/main/$arch/Docker.dmg" || got=$?
    if [ "$got" -ne 0 ]; then
      # 22: the server refused (a finished or stale part can't be resumed).
      # 33: it can't resume at all. Either way the next try starts afresh.
      case "$got" in 22|33) rm -f "$dmg.part" ;; esac
      echo
      echo "The Docker Desktop download didn't finish (curl stopped with code $got)."
      echo "Check this Mac is online (on a U-M network or VPN, desktop.docker.com must be"
      echo "reachable)."
      rerun
      echo "It continues the download where it stopped."
      exit 1
    fi
    mv "$dmg.part" "$dmg"
  fi

  echo "Checking the download…"
  # Docker signs the disk image itself too: checked before it's opened.
  if ! codesign --verify -R="$DOCKER_SIGNER" "$dmg" >/dev/null 2>&1; then
    stop_install delete \
      "The Docker Desktop download isn't signed by Docker Inc (team $DOCKER_TEAM_ID), so it" \
      "was deleted without being opened, and nothing was installed. This is unusual; a" \
      "network filter may have changed it. If it happens again, install Docker Desktop" \
      "yourself from $DOCKER_PAGE (or ask IT)."
  fi
  DOCKER_MOUNT="$(mktemp -d "$DOCKER_CACHE/mount.XXXXXX")"
  if ! hdiutil attach -quiet -nobrowse -readonly -noautoopen -mountpoint "$DOCKER_MOUNT" "$dmg" >/dev/null 2>&1; then
    rmdir "$DOCKER_MOUNT" 2>/dev/null || true
    DOCKER_MOUNT=""
    stop_install delete \
      "The Docker Desktop download couldn't be opened (it may be incomplete), so it was" \
      "deleted and nothing was installed. Running this again downloads it again."
  fi
  source_app="$DOCKER_MOUNT/Docker.app"
  if ! docker_app_is_genuine "$source_app"; then
    if [ "$NOT_GENUINE" = gatekeeper ]; then
      stop_install delete \
        "macOS's Gatekeeper is turned off on this Mac, so macOS can't confirm that the" \
        "downloaded Docker Desktop is notarized by Apple. Nothing from it was run or" \
        "installed, and the download was deleted. Turn Gatekeeper back on (ask IT if" \
        "your Mac is managed), or install Docker Desktop yourself from $DOCKER_PAGE."
    fi
    stop_install delete \
      "The downloaded Docker Desktop didn't pass macOS's checks: it must be signed and" \
      "notarized by Docker Inc (team $DOCKER_TEAM_ID). Nothing from it was run or installed," \
      "and the download was deleted. This is unusual; a network filter may have changed it." \
      "If it happens again, install Docker Desktop yourself from $DOCKER_PAGE (or ask IT)."
  fi
  needs="$(plutil -extract LSMinimumSystemVersion raw -o - "$source_app/Contents/Info.plist" 2>/dev/null || echo 0)"
  if ! version_at_least "$macos" "$needs"; then
    stop_install delete \
      "This Docker Desktop needs macOS $needs or newer, and this Mac has macOS $macos." \
      "Update macOS first (Apple menu > System Settings > General > Software Update)."
  fi
  echo "It's Docker Desktop $(plutil -extract CFBundleShortVersionString raw -o - "$source_app/Contents/Info.plist" 2>/dev/null || echo ''), signed and notarized by Docker Inc."

  installer_command="$source_app/Contents/MacOS/install"
  if [ "$method" = docker-installer ] && [ -x "$installer_command" ] && [ ! -L "$installer_command" ]; then
    install_with_dockers_installer
    return
  fi

  # Copied as it is (ditto keeps its signature), under a temporary name
  # until it's complete and checked again. /Applications if this account can
  # add to it without sudo, otherwise ~/Applications. Removed on the way out
  # if it doesn't get that far (Ctrl-C included).
  mkdir -p "$place" 2>/dev/null || true
  DOCKER_PARTIAL="$place/.Docker.app.umcodex-partial"
  remove_partial_copy
  copy_errors="$DOCKER_CACHE/copy-errors"
  echo "Copying Docker Desktop to ${place}…"
  copied=0
  ditto "$source_app" "$DOCKER_PARTIAL" 2>"$copy_errors" || copied=$?
  if [ "$copied" -ne 0 ] || [ -L "$DOCKER_PARTIAL" ] || [ ! -d "$DOCKER_PARTIAL" ]; then
    copy_failed "$place" "$copy_errors"
  fi
  if ! docker_app_is_genuine "$DOCKER_PARTIAL"; then
    stop_install delete \
      "The copy of Docker Desktop in $place didn't pass macOS's checks again, so it" \
      "was removed, with the download."
  fi
  # Checked again just before: if a Docker.app arrived meanwhile, mv would
  # put the copy inside it.
  if [ -e "$place/Docker.app" ] || [ -L "$place/Docker.app" ]; then
    stop_install keep \
      "A Docker.app appeared in $place while this copy was being made (did you" \
      "install Docker Desktop at the same time?). This copy was removed; that one was" \
      "left as it is."
  fi
  moved=0
  mv "$DOCKER_PARTIAL" "$place/Docker.app" 2>"$copy_errors" || moved=$?
  if [ "$moved" -ne 0 ]; then copy_failed "$place" "$copy_errors"; fi
  DOCKER_PARTIAL=""
  DOCKER_APP="$place/Docker.app"
  detach_docker_image
  rm -f "$dmg" "$copy_errors"
  rmdir "$DOCKER_CACHE" 2>/dev/null || true
  echo "Docker Desktop is installed in $(dirname "$DOCKER_APP")."
}
# Docker's own installer, from the checked disk image, run with sudo: the
# person types their password (sudo reads it from the terminal; nothing is
# passed to it). Docker's agreement isn't accepted here: Docker shows it
# when it first opens, for the person to accept.
install_with_dockers_installer() {
  echo
  echo "Installing Docker Desktop in $place with Docker's installer. macOS asks for your"
  echo "password (the one you log in to this Mac with) to install Docker Desktop: type it"
  echo "and press Return. Nothing shows as you type."
  status=0
  sudo "$installer_command" --user "$(id -un)" || status=$?
  if [ "$status" -ne 0 ]; then
    left=""
    if [ -e "$place/Docker.app" ]; then
      left="Docker's installer may have left $place/Docker.app partly installed: drag it to the Trash first."
    fi
    stop_install keep \
      "Docker Desktop wasn't installed: the password wasn't given or accepted, or Docker's" \
      "installer stopped (code $status). ${left:-Nothing was changed.}" \
      "If your account can't use sudo, ask IT, or install Docker Desktop yourself from" \
      "$DOCKER_PAGE."
  fi
  if ! docker_app_is_genuine "$place/Docker.app"; then
    stop_install keep \
      "Docker's installer finished, but $place/Docker.app didn't pass macOS's checks" \
      "(signed and notarized by Docker Inc, team $DOCKER_TEAM_ID). Drag it to the Trash, or" \
      "ask IT."
  fi
  DOCKER_APP="$place/Docker.app"
  detach_docker_image
  rm -f "$dmg"
  rmdir "$DOCKER_CACHE" 2>/dev/null || true
  echo "Docker Desktop is installed in $place."
}
# Why copying to $1 failed, from the errors in $2.
copy_failed() {
  if grep -q "Operation not permitted" "$2" 2>/dev/null; then
    stop_install keep \
      "macOS didn't let Terminal add Docker Desktop to $1 (\"Operation not permitted\")." \
      "Either allow it: System Settings > Privacy & Security > App Management, turn on" \
      "Terminal (then quit and reopen Terminal); or install into your own Applications" \
      "folder instead: create a folder called Applications in your home folder." \
      "Your organisation's device management may also block this: then ask IT."
  fi
  stop_install keep \
    "Docker Desktop couldn't be copied to $1. macOS or your organisation's" \
    "device management may not allow adding apps there. On a Mac your organisation" \
    "manages, install Docker Desktop from its Self Service app or ask IT; otherwise" \
    "check there's space and that you can add files to $1."
}

# Opens Docker Desktop and waits until it answers. $1: "new" right after
# installing it (with its first-run guide), otherwise "existing".
start_docker() {
  if [ "$1" = new ]; then
    limit="${UMCODEX_DOCKER_WAIT_SECONDS:-900}"
    echo
    echo "Docker Desktop is opening for the first time. In its window:"
    echo "  1. It shows the Docker Subscription Service Agreement. Read it and choose"
    echo "     Accept if you agree: Docker Desktop won't run without it. (If you decline,"
    echo "     it quits, and nothing else changes.)"
    echo "  2. Choose \"Use recommended settings\", then Finish. Type your Mac password if"
    echo "     asked (for Docker's helper)."
    case "$DOCKER_APP" in
      "$USER_APPS"/*)
        echo "     No administrator password? Choose \"Use advanced settings\" instead, set"
        echo "     the command line tools to \"User\", untick anything that needs a password,"
        echo "     then Finish." ;;
    esac
    echo "  3. Signing in to Docker is optional: choose Skip, or close the sign-in window."
    echo "     Skip any survey too."
    echo "This installer carries on by itself once Docker Desktop is running."
  else
    limit="${UMCODEX_DOCKER_WAIT_SECONDS:-300}"
    # An empty or damaged leftover isn't a Docker Desktop that can start.
    program="$(plutil -extract CFBundleExecutable raw -o - "$DOCKER_APP/Contents/Info.plist" 2>/dev/null || true)"
    if [ -z "$program" ] || [ ! -x "$DOCKER_APP/Contents/MacOS/$program" ]; then
      echo "$DOCKER_APP is there, but it isn't a complete Docker Desktop (it may be left"
      echo "over from an earlier install). Drag it to the Trash; your containers and images"
      echo "aren't in it."
      rerun
      echo "It then offers to install Docker Desktop."
      exit 1
    fi
    echo "Starting Docker Desktop… If its window asks you something (its agreement, your"
    echo "password, signing in), answer it there; signing in is optional."
  fi
  if ! open "$DOCKER_APP" >/dev/null 2>&1; then
    echo "Docker Desktop ($DOCKER_APP) couldn't be opened. If it's damaged, drag it to the"
    echo "Trash (your containers and images aren't in it); otherwise open it from"
    echo "Applications and wait until its whale icon at the top of the screen says it's running."
    rerun
    exit 1
  fi
  # Timed by the clock: each `docker info` is stopped after 20 seconds.
  # A Docker Desktop that was already installed, whose programs are running
  # but whose engine hasn't answered for 90 seconds, is restarted once
  # (`docker desktop restart`, which fixes a stuck engine). Never on a first
  # run: its window may still be waiting for the person.
  restart_after="${UMCODEX_DOCKER_RESTART_AFTER:-90}"
  restarted=0
  started="$(now)"
  said=0
  gone=0
  until docker_ready; do
    if [ -z "$DOCKER" ]; then find_docker_cli prefer-app || true; fi
    waited=$(($(now) - started))
    if [ "$waited" -ge "$limit" ]; then
      if [ "$limit" -ge 120 ]; then took="$((limit / 60)) minutes"; else took="$limit seconds"; fi
      if [ "$DOCKER_HUNG" = 1 ] || { [ "$1" = existing ] && docker_app_alive "$DOCKER_APP"; }; then
        echo "Docker Desktop is open, but its engine isn't answering after $took."
        echo "  1. Restart it: whale menu at the top of the screen > Restart."
        echo "  2. If that doesn't help: whale menu > Troubleshoot > Restart. If it still"
        echo "     doesn't answer, Troubleshoot offers \"Clean / Purge data\" and \"Reset to"
        echo "     factory defaults\": both DELETE Docker's containers, images and volumes"
        echo "     (for UM-Codex, your setups' Codex history), so only if you're sure."
        leftovers
        rerun
        exit 1
      fi
      echo "Docker Desktop isn't ready after $took."
      echo "  - If its window is asking something (its agreement, your password), answer it."
      echo "  - If it shows an error, choose Restart in its whale menu at the top of the screen."
      echo "  - Wait until the whale menu says Docker Desktop is running."
      leftovers
      rerun
      exit 1
    fi
    alive=1
    if ! docker_app_alive "$DOCKER_APP"; then alive=0; fi
    if [ "$waited" -ge 30 ] && [ "$alive" -eq 0 ]; then
      gone=$((gone + 1))
    else
      gone=0
    fi
    if [ "$1" = existing ] && [ "$restarted" -eq 0 ] && [ "$alive" -eq 1 ] \
      && [ "$waited" -ge "$restart_after" ] && [ -n "$DOCKER" ]; then
      restarted=1
      if within 20 "$DOCKER" desktop restart --help >/dev/null 2>&1; then
        echo "Docker Desktop is open but its engine isn't answering; restarting it…"
        within 120 "$DOCKER" desktop restart >/dev/null 2>&1 \
          || echo "(Docker Desktop's restart didn't finish; still waiting.)"
      fi
    fi
    if [ "$gone" -ge 2 ]; then
      echo "Docker Desktop closed before it was ready. If you declined its agreement, that's"
      echo "why: Docker Desktop doesn't run without it. When you're ready, open Docker from"
      echo "Applications, accept its agreement and finish its setup."
      leftovers
      rerun
      exit 1
    fi
    if [ "$waited" -ge $((said + 30)) ]; then
      said=$((waited - waited % 30))
      echo "Still waiting for Docker Desktop ($said seconds)…"
    fi
    sleep "$DOCKER_POLL"
  done
}

step "1/6 Docker Desktop"
find_docker_app || true
find_docker_cli || true
if docker_ready; then
  :
elif [ -n "$DOCKER_APP" ] || find_docker_app_elsewhere; then
  find_docker_cli prefer-app || true
  start_docker existing
else
  if [ -n "$DOCKER" ]; then
    echo "A docker command is installed ($DOCKER), but it isn't answering, and Docker"
    echo "Desktop isn't installed. If you use another Docker (Colima, OrbStack), start it"
    echo "and run this installer again. Otherwise:"
    echo
  fi
  install_docker_desktop
  find_docker_cli prefer-app || true
  start_docker new
fi
echo "Docker Desktop is running."
if [ "$DOCKER_ADDED_TO_PATH" = 1 ]; then
  echo "(Its docker command isn't on your PATH, which is fine: UM-Codex finds it in $(dirname "$DOCKER").)"
fi
if [ "${UMCODEX_INSTALL_STOP_AFTER_DOCKER:-}" = 1 ]; then
  echo "Stopping here: UMCODEX_INSTALL_STOP_AFTER_DOCKER is set."
  exit 0
fi

step "2/6 uv"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf --proto '=https' --proto-redir '=https' --tlsv1.2 "https://astral.sh/uv/$UV_VERSION/install.sh" | sh
fi
uv --version

step "3/6 UM-Codex"
# The package's file name carries its version: umcodex-<version>-py3-none-any.whl
WHEEL="$(basename "${PACKAGE%%\?*}")"
VERSION="$(printf '%s' "$WHEEL" | sed -n -e 's/^umcodex-\([0-9][A-Za-z0-9.+!]*[A-Za-z0-9]\)-py3-none-any\.whl$/\1/p' \
  -e 's/^umcodex-\([0-9]\)-py3-none-any\.whl$/\1/p')"
if [ -z "$VERSION" ]; then
  echo "The package must be a umcodex-<version>-py3-none-any.whl file."
  exit 2
fi
case "$PACKAGE" in
  *://*) ;;
  *) if [ -z "$REQUIREMENTS" ] && [ -f "$(dirname "$PACKAGE")/requirements.txt" ]; then
       REQUIREMENTS="$(dirname "$PACKAGE")/requirements.txt"
     fi ;;
esac
if [ -z "$REQUIREMENTS" ]; then
  echo "requirements.txt (every dependency, pinned by hash) wasn't found. Pass --requirements."
  exit 2
fi
# uv gets both files under plain names, from their own folder: it cuts a path
# at its first space ("Application Support", "OneDrive - …").
STAGE="$(mktemp -d)"
fetch() {
  case "$1" in
    https://*) curl -fsSL --proto '=https' --proto-redir '=https' --tlsv1.2 -o "$2" "$1" ;;
    *://*) echo "Only https downloads: $1"; exit 2 ;;
    *) cp "$1" "$2" ;;
  esac
}
fetch "$PACKAGE" "$STAGE/$WHEEL"
fetch "$REQUIREMENTS" "$STAGE/requirements.txt"
# The package must be the one requirements.txt names, by its checksum.
SHA256="$(shasum -a 256 "$STAGE/$WHEEL" | cut -d ' ' -f 1)"
if ! grep -qxF "./$WHEEL --hash=sha256:$SHA256" "$STAGE/requirements.txt"; then
  echo "requirements.txt doesn't name this package with this checksum. Use the two files"
  echo "from the same UM-Codex release."
  exit 1
fi
# Beside the data folder: versions/<version>/, current, previous, bin/um-codex.
ROOT="${UMCODEX_INSTALL_DIR:-$HOME/Library/Application Support/UM-Codex/app}"
TARGET="$ROOT/versions/$VERSION"
if [ -f "$TARGET/.complete" ] && grep -qF "\"wheel_sha256\": \"$SHA256\"" "$TARGET/.complete"; then
  echo "UM-Codex $VERSION is installed already."
else
  # A folder without .complete (or with another package) is replaced.
  rm -rf "$TARGET"
  mkdir -p "$ROOT/versions"
  uv venv -q --no-config --python 3.13 "$TARGET"
  # Every file checked against requirements.txt's hashes, only wheels, and
  # only from PyPI. Copied, not hardlinked into uv's cache (which fails in a
  # cloud-synced or redirected folder).
  (cd "$STAGE" && uv pip install -q --no-config --require-hashes --only-binary :all: \
    --default-index https://pypi.org/simple --link-mode copy --python "$TARGET/bin/python" -r requirements.txt)
  SAID="$("$TARGET/bin/um-codex" --version)"
  if [ "$SAID" != "UM-Codex $VERSION" ]; then
    echo "The installed UM-Codex says '$SAID', not $VERSION."
    rm -rf "$TARGET"
    exit 1
  fi
  sync
  printf '{"version": "%s", "wheel_sha256": "%s", "installed_at": "%s"}\n' \
    "$VERSION" "$SHA256" "$(date +%Y-%m-%dT%H:%M:%S%z)" > "$TARGET/.complete"
fi
# The launcher's command runs whichever version `current` names.
mkdir -p "$ROOT/bin"
cat > "$ROOT/bin/um-codex" <<'SHIM'
#!/bin/sh
# Runs the UM-Codex version named in ../current, or the one before
# (../previous) if that one can't run.
# UTF-8 for Python's own text files and console, whatever the locale.
export PYTHONUTF8=1
root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(head -n 1 "$root/current" 2>/dev/null || true)"
if [ -z "$version" ] || [ ! -x "$root/versions/$version/bin/um-codex" ]; then
  echo "UM-Codex ${version:-(none)} can't be opened; opening the version before it." >&2
  version="$(head -n 1 "$root/previous" 2>/dev/null || true)"
fi
exec "$root/versions/$version/bin/um-codex" "$@"
SHIM
chmod +x "$ROOT/bin/um-codex"
OLD="$(head -n 1 "$ROOT/current" 2>/dev/null || true)"
if [ -n "$OLD" ] && [ "$OLD" != "$VERSION" ]; then
  printf '%s\n' "$OLD" > "$ROOT/.previous.new" && mv "$ROOT/.previous.new" "$ROOT/previous"
fi
printf '%s\n' "$VERSION" > "$ROOT/.current.new" && mv "$ROOT/.current.new" "$ROOT/current"
UMCODEX="$ROOT/bin/um-codex"
"$UMCODEX" --version
# The plain `um-codex` command: a link in ~/.local/bin (uv's installer puts
# that folder on your shell's PATH). Only a link to this command is ever
# replaced: anything else of that name is left alone.
COMMAND_LINK="$HOME/.local/bin/um-codex"
LINKED=0
mkdir -p "$HOME/.local/bin"
if [ -L "$COMMAND_LINK" ] || [ ! -e "$COMMAND_LINK" ]; then
  to="$(readlink "$COMMAND_LINK" 2>/dev/null || echo "$UMCODEX")"
  if [ "$to" = "$UMCODEX" ]; then
    if rm -f "$COMMAND_LINK" && ln -s "$UMCODEX" "$COMMAND_LINK"; then LINKED=1; fi
  else
    echo "$COMMAND_LINK is a link to something else; it was left alone."
  fi
else
  echo "$COMMAND_LINK is already there and isn't UM-Codex's; it was left alone."
fi
# How to run it, said at the end: `um-codex` when ~/.local/bin was on your
# PATH already, otherwise the command's full path, quoted for the shell.
case ":$PATH_BEFORE:" in
  *":$HOME/.local/bin:"*) ON_PATH=1 ;;
  *) ON_PATH=0 ;;
esac
if [ "$LINKED" = 1 ] && [ "$ON_PATH" = 1 ]; then
  RUN_HOW="um-codex"
else
  RUN_HOW="'$(printf '%s' "$UMCODEX" | sed "s/'/'\\\\''/g")'"
fi

step "4/6 Container images"
if ! "$UMCODEX" pull; then
  echo "The container images couldn't all be downloaded (the messages above say why)."
  echo "Check this Mac is online and Docker Desktop is running."
  echo "Then run this installer again, the same way: it carries on from where it stopped,"
  echo "and anything already done isn't done twice."
  exit 1
fi

step "5/6 Toolkit key"
# Whether a key is saved already: the Keychain is asked whether the item is
# there, without reading the key.
key_saved() {
  security find-generic-password -s "$KEY_SERVICE" -a "$KEY_ACCOUNT" >/dev/null 2>&1
}
# A terminal to type in (not only one that exists: one this process can open).
have_terminal() { ( : < /dev/tty ) 2>/dev/null; }
# The masked prompt (DataLab's secret_prompt.py, for one key): one * per
# character, typed or pasted (at most 64, then "…"), with Backspace, Ctrl-U
# and Enter; Ctrl-C or an empty entry cancels. It says how many characters
# arrived, never any of them, removes spaces and line breaks at the ends and
# says so, and refuses a paste of more than one line (three tries). It reads
# and writes the terminal itself; only the key goes to its output, which is
# this script's variable and then `um-codex key --from-stdin`'s input: never a
# file, an argument or the environment. Exit 0 with a key, 2 without one.
# Python runs isolated (-I): nothing from the environment changes it.
ask_key() {
  "$TARGET/bin/python" -I - <<'PY'
import codecs, os, select, sys, termios

CAP = 64
try:
    tty = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
except OSError:
    sys.exit(2)


def say(text):
    os.write(tty, text.encode("utf-8"))


decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")


def read_char():
    while True:
        byte = os.read(tty, 1)
        if not byte:
            return decoder.decode(b"", final=True)
        char = decoder.decode(byte)
        if char:
            return char


def pending():
    return bool(select.select([tty], [], [], 0.05)[0])


def mask(count):
    return "*" * min(count, CAP) + ("…" if count > CAP else "")


def read_masked():
    """(value, multiline, extra line breaks), or None for Ctrl-C."""
    chars, shown = [], ""
    while True:
        char = read_char()
        if char in ("", "\x04"):
            return "".join(chars), False, 0
        if char in ("\r", "\n"):
            rest = []
            while pending():
                more = read_char()
                if more == "":
                    break
                rest.append(more)
            extra = "".join(rest)
            breaks = extra.count("\n") + extra.count("\r") - extra.count("\r\n")
            return "".join(chars), bool(extra.strip()), breaks
        if char == "\x03":
            return None
        if char in ("\x7f", "\x08"):
            if chars:
                chars.pop()
        elif char == "\x15":
            chars.clear()
        elif char == "\x1b":  # an escape sequence (an arrow key): skipped
            if pending() and read_char() in ("[", "O"):
                while pending():
                    if "@" <= read_char() <= "~":
                        break
            continue
        elif char == "\t" or (ord(char) >= 32 and ord(char) != 127):
            chars.append(char)
        else:
            continue
        new = mask(len(chars))
        keep = 0
        while keep < min(len(shown), len(new)) and shown[keep] == new[keep]:
            keep += 1
        say("\b \b" * (len(shown) - keep) + new[keep:])
        shown = new


def whitespace(text):
    breaks = text.count("\n") + text.count("\r") - text.count("\r\n")
    spaces = len(text.replace("\r\n", "").replace("\n", "").replace("\r", ""))
    parts = []
    if spaces:
        parts.append("a space" if spaces == 1 else f"{spaces} spaces")
    if breaks:
        parts.append("a line break" if breaks == 1 else f"{breaks} line breaks")
    return " and ".join(parts)


saved = termios.tcgetattr(tty)
quiet = termios.tcgetattr(tty)
# No echo, a character at a time, Ctrl-C/Ctrl-U as plain characters.
quiet[3] &= ~(termios.ECHO | termios.ICANON | termios.ISIG | termios.IEXTEN)
quiet[6][termios.VMIN] = 1
quiet[6][termios.VTIME] = 0
for _ in range(3):
    try:
        # Quiet before the prompt shows, so nothing typed after it is echoed.
        termios.tcsetattr(tty, termios.TCSANOW, quiet)
        say("Toolkit API key: ")
        entry = read_masked()
    finally:
        termios.tcsetattr(tty, termios.TCSANOW, saved)
    say("\n")
    if entry is None:
        say("Cancelled: no key was saved.\n")
        sys.exit(2)
    raw, multiline, extra_breaks = entry
    if multiline:
        say("That paste had more than one line, so it wasn't used. "
            "Copy just the one line and paste it again.\n")
        continue
    value = raw.strip()
    if not value:
        say("Nothing was entered, so nothing was saved.\n")
        sys.exit(2)
    start = raw[: len(raw) - len(raw.lstrip())]
    end = raw[len(raw.rstrip()):] + "\n" * extra_breaks
    say(f"✓ Received {len(value)} character{'' if len(value) == 1 else 's'}.\n")
    for removed, where in ((start, "start"), (end, "end")):
        if removed:
            say(f"  Removed {whitespace(removed)} from the {where}.\n")
    sys.stdout.write(value)
    sys.exit(0)
say("Nothing was saved.\n")
sys.exit(2)
PY
}
LATER="UM-Codex asks for it the first time it opens, or save it any time with: um-codex key"
if [ "$REPLACE_KEY" != yes ] && key_saved; then
  echo "A Toolkit API key is saved already, so it was kept. To replace it, run: um-codex key"
  echo "(or run this installer again with --replace-key)."
elif ! have_terminal; then
  echo "There's no terminal to type the key in, so it wasn't asked for."
  echo "$LATER"
else
  echo "Paste your U-M GPT Toolkit API key, then press Enter. Each character shows as *."
  echo "It's saved in your macOS Keychain and never goes into the container."
  echo "To skip this for now, press Enter on its own."
  tries=0
  while :; do
    tries=$((tries + 1))
    KEY=""
    got=0
    KEY="$(ask_key)" || got=$?
    if [ "$got" -ne 0 ] || [ -z "$KEY" ]; then
      KEY=""
      echo "$LATER"
      break
    fi
    # 0: saved. 1: the Toolkit refused it (not saved). 2: cancelled.
    saved=0
    printf '%s\n' "$KEY" | "$UMCODEX" key --from-stdin || saved=$?
    KEY=""
    case "$saved" in
      0) break ;;
      1) if [ "$tries" -ge 3 ]; then echo "$LATER"; break; fi
         echo "Try again (or press Enter on its own to skip)." ;;
      *) echo "$LATER"; break ;;
    esac
  done
  unset KEY
fi

step "6/6 Launcher"
NAME="UM-Codex"
BUNDLE="edu.umich.umcodex"
# Whether a bundle is UM-Codex's app (one this installer made).
ours() { [ -f "$1/Contents/Info.plist" ] && grep -qF "<string>$BUNDLE</string>" "$1/Contents/Info.plist"; }
# In /Applications, where people look, if you can add to it without sudo (an
# administrator account can); otherwise in your own Applications folder
# (~/Applications, which Finder, Spotlight and Launchpad also show). Only an
# app of ours is ever replaced: something else called "$NAME.app" is left alone.
# Makes $1/$NAME.app ready for a new copy: 0 when it is, 1 when what's there
# isn't ours, 2 when ours couldn't be replaced (open, or not ours to change).
prepare() {
  target="$1/$NAME.app"
  if [ -L "$target" ]; then return 1; fi
  if [ -e "$target" ]; then
    ours "$target" || return 1
    rm -rf "$target" 2>/dev/null || true
    [ ! -e "$target" ] || return 2
  fi
  mkdir -p "$target/Contents/MacOS" "$target/Contents/Resources" 2>/dev/null || return 2
}
APPS=""
if [ -d "$SYSTEM_APPS" ] && [ -w "$SYSTEM_APPS" ] && prepare "$SYSTEM_APPS"; then
  APPS="$SYSTEM_APPS"
else
  placed=0
  prepare "$USER_APPS" || placed=$?
  case "$placed" in
    0) APPS="$USER_APPS" ;;
    1) echo "$USER_APPS/$NAME.app is another app, not UM-Codex's, so it was left alone."
       echo "Move or rename it, then run this installer again (UM-Codex itself is installed:"
       echo "run $RUN_HOW)."
       exit 1 ;;
    *) echo "$USER_APPS/$NAME.app couldn't be replaced. Quit UM-Codex if it's open (or drag"
       echo "the app to the Trash), then run this installer again (UM-Codex itself is installed)."
       exit 1 ;;
  esac
fi
APP="$APPS/$NAME.app"
# The icon comes with the package. The app keeps its own copy, so removing
# this version's folder later doesn't take the icon with it.
ICONFILE=""
for found in "$TARGET"/lib/python*/site-packages/umcodex/branding/UM-Codex.icns; do
  if [ -f "$found" ] && cp "$found" "$APP/Contents/Resources/UM-Codex.icns"; then ICONFILE="UM-Codex"; fi
done
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE</string>
  <key>CFBundleExecutable</key><string>UM-Codex</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>$ICONFILE</string>
</dict></plist>
PLIST
# UM-Codex runs in a Terminal window: Codex's own interface is its front end.
# The app runs bin/um-codex, never a version's own folder: that opens the
# version `current` names, so the app (and the Desktop shortcut to it) keeps
# working when another version is installed.
# The path goes to AppleScript as an argument, single-quoted for this script
# ('\'' for a quote, as in /Users/o'brien), and AppleScript quotes it for
# Terminal's shell with `quoted form of`.
QUOTED="$(printf '%s' "$UMCODEX" | sed "s/'/'\\\\''/g")"
cat > "$APP/Contents/MacOS/UM-Codex" <<LAUNCH
#!/bin/sh
exec osascript - '$QUOTED' <<'OSA'
on run argv
  tell application "Terminal"
    activate
    do script (quoted form of item 1 of argv)
  end tell
end run
OSA
LAUNCH
chmod +x "$APP/Contents/MacOS/UM-Codex"
touch "$APP" # so Finder picks up the icon
echo "Added $NAME to $APPS."
# An earlier installer's copy in the other Applications folder would be a
# second, stale "$NAME".
for other in "$USER_APPS/$NAME.app" "$SYSTEM_APPS/$NAME.app"; do
  if [ "$other" != "$APP" ] && [ ! -L "$other" ] && ours "$other"; then
    if rm -rf "$other" 2>/dev/null; then
      echo "(Removed the copy an earlier installer put in $(dirname "$other").)"
    else
      echo "(An earlier copy is still in $(dirname "$other"); you can drag it to the Trash.)"
    fi
  fi
done
# A shortcut on the Desktop: a link to the app. One already there is replaced
# only if it's a link to this app, in either Applications folder.
DESKTOP_LINK=""
LINK="$HOME/Desktop/$NAME"
if [ -d "$HOME/Desktop" ]; then
  if [ -L "$LINK" ] || [ ! -e "$LINK" ]; then
    to="$(readlink "$LINK" 2>/dev/null || echo "$APP")"
    if [ "$to" = "$USER_APPS/$NAME.app" ] || [ "$to" = "$SYSTEM_APPS/$NAME.app" ]; then
      if rm -f "$LINK" 2>/dev/null && ln -s "$APP" "$LINK" 2>/dev/null; then
        DESKTOP_LINK="$LINK"
        echo "Added a shortcut to $NAME on your Desktop."
      else
        echo "A Desktop shortcut couldn't be added (macOS may not let Terminal use the Desktop)."
      fi
    else
      echo "Your Desktop already has a shortcut called $NAME to something else; it was left alone."
    fi
  else
    echo "Your Desktop already has something called $NAME; it was left alone."
  fi
fi

step "Done"
echo "$NAME is installed."
echo "  The app:           $APP"
if [ -n "$DESKTOP_LINK" ]; then echo "  Desktop shortcut:  $DESKTOP_LINK"; fi
if [ "$LINKED" = 1 ]; then echo "  The command:       $COMMAND_LINK"; fi
echo "  Program files:     $ROOT"
echo "Open it with the Desktop shortcut, from Applications in Finder, or with Spotlight"
echo "(Cmd-Space, then type $NAME). It opens a Terminal window, asks what Codex may"
echo "see and do, then starts Codex there."
echo "Or, in any Terminal window, in the folder you want to work in, run: $RUN_HOW"
if [ "$LINKED" = 1 ] && [ "$ON_PATH" = 0 ]; then
  echo "(In a new Terminal window plain um-codex may work too: ~/.local/bin wasn't on"
  echo "this window's PATH.)"
fi
# Only with someone at the keyboard: not when this runs from a script or CI
# (a terminal to answer in, and this output going to one).
# The install is finished by now, so Ctrl-C at these two optional questions
# just ends it, quietly and successfully (not "Stopped. Run this installer
# again ...", which is for an install that didn't finish).
if [ -t 1 ] && have_terminal; then
  trap 'echo; echo "OK."; exit 0' INT TERM HUP
  if ask "Show $NAME in Finder? [Y/n]"; then open -R "$APP" || true; fi
  if ask "Open $NAME now? [Y/n]"; then open "$APP" || true; fi
fi
exit 0
}
