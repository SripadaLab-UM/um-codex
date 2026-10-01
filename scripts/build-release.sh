#!/bin/sh
# Build a UM-Codex release's files. Adapted from IHS DataLab's
# scripts/build-release.sh and the `package` job of its release.yml at 6b6fdca.
#
#   AGENT_IMAGE=ghcr.io/sripadalab-um/um-codex-agent@sha256:... RELEASE_TAG=v0.1.0-alpha.2 \
#     sh scripts/build-release.sh [<output folder, default dist/release>]
#
# The output folder gets exactly the files a release publishes:
#   umcodex-<version>-py3-none-any.whl   the package, with images.json pinned by digest inside
#   requirements.txt                     every dependency from uv.lock by version and hash,
#                                        then the package by its checksum
#   images.json                          the images this release runs, by digest
#   install-macos.sh, uninstall-macos.sh, install-windows.ps1, uninstall-windows.ps1
#                                        the installers, with this release's address and
#                                        package name written in, so that
#                                        `curl .../releases/latest/download/install-macos.sh | sh`
#                                        and `irm .../install-windows.ps1 | iex` need no arguments
#   SHA256SUMS                           every file above, by SHA-256 (the release workflow
#                                        signs it: SHA256SUMS.sig)
#
# Nothing in the repository changes: the package is built from a copy of
# pyproject.toml, uv.lock and src/. REPOSITORY (default SripadaLab-UM/um-codex)
# names where the release is published.
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
out="${1:-$root/dist/release}"
repository="${REPOSITORY:-SripadaLab-UM/um-codex}"
: "${AGENT_IMAGE:?AGENT_IMAGE (the agent image, pinned by digest) is needed}"
: "${RELEASE_TAG:?RELEASE_TAG (the tag being released, e.g. v0.1.0-alpha.2) is needed}"
version="$(sh scripts/release-version.sh "$RELEASE_TAG")"

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi
}
pinned() {
  printf '%s' "$1" | grep -Eq '^[^@[:space:]]+@sha256:[0-9a-f]{64}$'
}

gateway="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["gateway"])' src/umcodex/images.json)"
for image in "$AGENT_IMAGE" "$gateway"; do
  pinned "$image" || { echo "Not pinned by digest: '$image'" >&2; exit 1; }
done
case "$AGENT_IMAGE" in
  ghcr.io/sripadalab-um/um-codex-agent@*) ;;
  *) echo "The agent image must be ghcr.io/sripadalab-um/um-codex-agent: '$AGENT_IMAGE'" >&2; exit 1 ;;
esac
images_json="$(printf '{\n  "agent": "%s",\n  "gateway": "%s"\n}\n' "$AGENT_IMAGE" "$gateway")"

build="$(mktemp -d)"
trap 'rm -rf "$build"' EXIT
cp pyproject.toml uv.lock "$build/"
cp -R src "$build/src"
find "$build/src" -name __pycache__ -type d -prune -exec rm -rf {} +
# The package runs exactly the images the release lists.
printf '%s' "$images_json" > "$build/src/umcodex/images.json"
(cd "$build" && uv build -q --wheel --out-dir "$build/dist")
wheel="umcodex-$version-py3-none-any.whl"
[ -f "$build/dist/$wheel" ] || { echo "The build didn't make $wheel:" >&2; ls "$build/dist" >&2; exit 1; }
# Every dependency from uv.lock, pinned by version and hash (--locked: refuses
# a lock that doesn't match pyproject.toml), then the package itself by its
# checksum. The installers and `um-codex update` install exactly this, with
# `uv pip install --require-hashes --only-binary :all: -r requirements.txt`.
(cd "$build" && uv export -q --locked --no-dev --no-emit-project --format requirements-txt \
  -o requirements.txt)
grep -q -- '--hash=sha256:' "$build/requirements.txt" || { echo "uv export gave no hashes." >&2; exit 1; }
digest="$(sha256 "$build/dist/$wheel")"
printf './%s --hash=sha256:%s\n' "$wheel" "${digest%% *}" >> "$build/requirements.txt"

rm -rf "$out"
mkdir -p "$out"
cp "$build/dist/$wheel" "$build/requirements.txt" "$out/"
printf '%s' "$images_json" > "$out/images.json"
# The installers, with this release's own address written in (not "latest":
# an installer always installs the release it came with).
base="https://github.com/$repository/releases/download/$RELEASE_TAG"
stamp() {  # <source> <destination> <base line> <stamped base line> <wheel line> <stamped wheel line>
  [ "$(grep -cxF "$3" "$1")" = 1 ] && [ "$(grep -cxF "$5" "$1")" = 1 ] || {
    echo "$1 doesn't have the lines '$3' and '$5' (once each) to write the release into." >&2
    exit 1
  }
  awk -v a="$3" -v b="$4" -v c="$5" -v d="$6" \
    '{ if ($0 == a) print b; else if ($0 == c) print d; else print }' "$1" > "$2"
}
stamp installer/macos/install.sh "$out/install-macos.sh" \
  'RELEASE_BASE=""' "RELEASE_BASE=\"$base\"" 'RELEASE_WHEEL=""' "RELEASE_WHEEL=\"$wheel\""
# shellcheck disable=SC2016 # PowerShell's own $ names, as they are in the file
stamp installer/windows/install.ps1 "$out/install-windows.ps1" \
  '$ReleaseBase = ""' "\$ReleaseBase = \"$base\"" '$ReleaseWheel = ""' "\$ReleaseWheel = \"$wheel\""
cp installer/macos/uninstall.sh "$out/uninstall-macos.sh"
cp installer/windows/uninstall.ps1 "$out/uninstall-windows.ps1"
(cd "$out" && sha256 -- * > SHA256SUMS)
echo "Built UM-Codex $version's release files in $out."
