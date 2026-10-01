#!/bin/sh
# The package version a release tag stands for, checked against the package.
# From IHS DataLab's release.yml (its `version` job) at 6b6fdca.
#
#   sh scripts/release-version.sh v0.1.0-alpha.2     prints 0.1.0a2
#
# Pre-releases included: v0.1.0-alpha.2 is version 0.1.0a2 (PEP 440), so each
# pre-release has its own version and updates can tell them apart. Exit 1 if
# the tag doesn't match src/umcodex/__init__.py's __version__ (run from the
# repository's top folder), so nothing is built or published under the wrong
# name.
set -eu
tag="${1:-}"
case "$tag" in
  v[0-9]*) ;;
  *) echo "A release tag looks like v0.1.0 or v0.1.0-alpha.2, not '$tag'." >&2; exit 1 ;;
esac
version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/umcodex/__init__.py)
wanted=$(printf '%s' "${tag#v}" | sed -E \
  -e 's/-(alpha|a)\.?([0-9]+)$/a\2/' -e 's/-(beta|b)\.?([0-9]+)$/b\2/' -e 's/-rc\.?([0-9]+)$/rc\1/')
if [ -z "$version" ] || [ "$wanted" != "$version" ]; then
  echo "Tag $tag doesn't match the package version ${version:-(none found)} (src/umcodex/__init__.py)." >&2
  exit 1
fi
printf '%s\n' "$version"
