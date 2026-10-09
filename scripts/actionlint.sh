#!/usr/bin/env bash
# Lint every workflow in .github/workflows with one pinned actionlint (v1-e01-t15-promotion-guard-sweep).
#
# ci.yml's workflow-lint job runs this on the runner, and it runs the same way in a checkout:
#
#   uv run scripts/actionlint.sh
#
# It downloads the pinned release from GitHub and refuses it unless its SHA-256 matches the value
# below, copied from the release's published actionlint_<version>_checksums.txt. It then runs it
# from the repository root, over every workflow unless arguments name files. actionlint runs
# ShellCheck over each `run:` block when `shellcheck` is on PATH: the ubuntu-24.04 runner image has
# it, and `uv run` puts the dev group's on PATH. This prints which one it found, or that none was.
#
# To move to a new actionlint, change VERSION and every checksum together, from that release's
# checksums file. Exit codes: actionlint's own (0 clean, 1 findings), or 2 if it could not be run.
set -euo pipefail

VERSION=1.7.12
case "$(uname -s)_$(uname -m)" in
  Linux_x86_64) PLATFORM=linux_amd64 SHA256=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8 ;;
  Linux_aarch64) PLATFORM=linux_arm64 SHA256=325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6 ;;
  Darwin_arm64) PLATFORM=darwin_arm64 SHA256=aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f ;;
  Darwin_x86_64) PLATFORM=darwin_amd64 SHA256=5b44c3bc2255115c9b69e30efc0fecdf498fdb63c5d58e17084fd5f16324c644 ;;
  *)
    echo "actionlint.sh: no pinned actionlint checksum for $(uname -s) $(uname -m)" >&2
    exit 2
    ;;
esac

archive="actionlint_${VERSION}_${PLATFORM}.tar.gz"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if ! curl -fsSL --retry 3 -o "$work/$archive" \
  "https://github.com/rhysd/actionlint/releases/download/v${VERSION}/${archive}"; then
  echo "actionlint.sh: could not download $archive" >&2
  exit 2
fi
if command -v sha256sum > /dev/null; then
  actual=$(sha256sum "$work/$archive" | cut -d' ' -f1)
else
  actual=$(shasum -a 256 "$work/$archive" | cut -d' ' -f1)
fi
if [ "$actual" != "$SHA256" ]; then
  echo "actionlint.sh: $archive has SHA-256 $actual, not the published $SHA256; refusing to run it" >&2
  exit 2
fi
tar -xzf "$work/$archive" -C "$work" actionlint

if command -v shellcheck > /dev/null; then
  echo "actionlint $VERSION ($PLATFORM, checksum verified), with $(shellcheck --version | sed -n 's/^version: /shellcheck /p') from $(command -v shellcheck)"
else
  echo "actionlint $VERSION ($PLATFORM, checksum verified), without shellcheck: run: blocks are not shell-checked"
fi

cd "$(git rev-parse --show-toplevel)"
"$work/actionlint" "$@"
