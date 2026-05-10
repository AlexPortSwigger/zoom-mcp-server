#!/usr/bin/env bash
# Build per-platform .mcpb bundles using @anthropic-ai/mcpb.
#
# Each bundle ships native-extension wheels for Python 3.11, 3.12, and 3.13.
# server/main.py picks the matching version-specific subdir at startup.
#
# Usage:
#   ./scripts/build_mcpb.sh                  # build for the host platform only
#   ./scripts/build_mcpb.sh --all            # build for all platforms (needs internet)
#   ./scripts/build_mcpb.sh --tag <tag>      # build a specific tag
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
mkdir -p "$DIST"

declare -a PLATFORMS=("macosx_11_0_arm64" "macosx_11_0_x86_64" \
                      "manylinux_2_17_x86_64" "win_amd64")
declare -a TAGS=("darwin-arm64" "darwin-x64" "linux-x64" "win-x64")
declare -a PY_VERSIONS=("3.11" "3.12" "3.13")

host_tag() {
  local uname_s uname_m
  uname_s="$(uname -s)"
  uname_m="$(uname -m)"
  if [[ "$uname_s" == "Darwin" ]]; then
    if [[ "$uname_m" == "arm64" ]]; then echo "darwin-arm64"; else echo "darwin-x64"; fi
  elif [[ "$uname_s" == "Linux" ]]; then
    echo "linux-x64"
  else
    echo "win-x64"
  fi
}

ONLY_TAG=""
ALL=false
while [[ $# -gt 0 ]]; do
  case $1 in
    --all) ALL=true; shift ;;
    --tag) ONLY_TAG="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if ! $ALL && [[ -z "$ONLY_TAG" ]]; then
  ONLY_TAG="$(host_tag)"
fi

build_one() {
  local PIP_PLATFORM="$1"
  local TAG="$2"
  local STAGE="$ROOT/build/$TAG"
  echo "==> Building for $TAG ($PIP_PLATFORM)"
  rm -rf "$STAGE"
  mkdir -p "$STAGE/server"

  cp -r "$ROOT/server"        "$STAGE/"
  cp    "$ROOT/manifest.json" "$STAGE/"
  cp    "$ROOT/icon.png"      "$STAGE/"
  find "$STAGE/server" -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

  for PY in "${PY_VERSIONS[@]}"; do
    local LIBDIR="$STAGE/server/lib/py${PY//./}"
    mkdir -p "$LIBDIR"
    echo "    fetching wheels for Python $PY..."
    python3 -m pip download \
      --quiet \
      --platform "$PIP_PLATFORM" \
      --python-version "$PY" \
      --only-binary :all: \
      -d "$LIBDIR" \
      -r "$ROOT/requirements.txt"

    for whl in "$LIBDIR"/*.whl; do
      [ -f "$whl" ] || continue
      unzip -qo "$whl" -d "$LIBDIR"
      rm "$whl"
    done
  done

  npx --yes @anthropic-ai/mcpb pack "$STAGE" "$DIST/zoom-mcp-${TAG}.mcpb"
  rm -rf "$STAGE"
}

if $ALL; then
  for i in "${!PLATFORMS[@]}"; do
    build_one "${PLATFORMS[$i]}" "${TAGS[$i]}"
  done
else
  for i in "${!TAGS[@]}"; do
    if [[ "${TAGS[$i]}" == "$ONLY_TAG" ]]; then
      build_one "${PLATFORMS[$i]}" "${TAGS[$i]}"
      break
    fi
  done
fi

echo ""
echo "==> Bundles in $DIST:"
ls -lh "$DIST"
