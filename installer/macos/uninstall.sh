#!/bin/sh
# UM-Codex uninstaller for macOS.
# Adapted from IHS DataLab's installer/macos/uninstall.sh at 6b6fdca.
#
#   sh uninstall.sh [options for `um-codex uninstall`]
#
# First runs `um-codex uninstall`, which removes what UM-Codex keeps (it asks
# about your data and about the container images; it says what it does with
# the Toolkit key in your Keychain). Then it removes UM-Codex's
# program files (every version installed side by side), the `um-codex`
# command in ~/.local/bin, the UM-Codex app and its Desktop shortcut, and a
# Docker Desktop download the installer may have left. It never touches your
# own folders, uv, or Docker Desktop.
#
# UMCODEX_SYSTEM_APPLICATIONS (for tests) stands in for /Applications.
{
set -eu
[ "$(id -u)" -ne 0 ] || { echo "Run this without sudo."; exit 1; }
ROOT="${UMCODEX_INSTALL_DIR:-$HOME/Library/Application Support/UM-Codex/app}"
UMCODEX="$ROOT/bin/um-codex"

if [ -x "$UMCODEX" ] && [ -f "$ROOT/current" ]; then
  # It asks its questions in this terminal. If it stops (or you say no to
  # removing UM-Codex), nothing below is done either.
  "$UMCODEX" uninstall "$@"
  rm -rf "$ROOT"
  # The data folder, if `um-codex uninstall` left it empty.
  rmdir "$(dirname "$ROOT")" 2>/dev/null || true
else
  echo "UM-Codex's program files weren't found; skipping that part."
fi
# The `um-codex` command: only a link to this UM-Codex's command.
link="$HOME/.local/bin/um-codex"
if [ -L "$link" ] && [ "$(readlink "$link")" = "$UMCODEX" ]; then
  rm -f "$link"
fi
# The app, in ~/Applications or /Applications (only UM-Codex's own: its bundle
# id), and the Desktop shortcut to it (only a link to one of those apps).
SYSTEM_APPS="${UMCODEX_SYSTEM_APPLICATIONS:-/Applications}"
name="UM-Codex"
bundle="edu.umich.umcodex"
for app in "$HOME/Applications/$name.app" "$SYSTEM_APPS/$name.app"; do
  if [ ! -L "$app" ] && [ -f "$app/Contents/Info.plist" ] \
    && grep -qF "<string>$bundle</string>" "$app/Contents/Info.plist"; then
    rm -rf "$app" 2>/dev/null || echo "$app couldn't be removed; drag it to the Trash."
  fi
done
link="$HOME/Desktop/$name"
if [ -L "$link" ]; then
  case "$(readlink "$link")" in
    "$HOME/Applications/$name.app" | "$SYSTEM_APPS/$name.app") rm -f "$link" ;;
  esac
fi
# A Docker Desktop download the installer kept to resume (never Docker itself).
rm -rf "$HOME/Library/Caches/UM-Codex"
echo "UM-Codex has been removed. Docker Desktop is still installed; to remove it too,"
echo "use its whale menu > Troubleshoot > Uninstall (that deletes its containers,"
echo "images and volumes)."
exit 0
}
