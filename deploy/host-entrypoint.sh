#!/bin/sh
set -eu

data="${PLURAL_DATA_DIR:-/data}"
workspace="${PLURAL_WORKSPACE:-$data/workspace}"
mkdir -p "$data" "$workspace"

: "${PLURAL_RELAY_URL:?set PLURAL_RELAY_URL to your relay, for example wss://relay.example.com}"

if [ -n "${GIT_URL:-}" ] && [ -z "$(ls -A "$workspace")" ]; then
  git clone ${GIT_BRANCH:+--branch "$GIT_BRANCH"} "$GIT_URL" "$workspace"
  git -C "$workspace" remote set-url origin "$(printf '%s' "$GIT_URL" | sed -E 's#://[^/@]+@#://#')"
fi

if [ -z "${PLURAL_ROOM:-}" ]; then
  if [ ! -s "$data/room" ]; then
    printf 'r_%s\n' "$(od -An -N10 -tx1 /dev/urandom | tr -d ' \n')" > "$data/room"
  fi
  PLURAL_ROOM="$(cat "$data/room")"
fi

exec plural-host host \
  --workspace "$workspace" \
  --relay "$PLURAL_RELAY_URL" \
  --room "$PLURAL_ROOM" \
  --name "${PLURAL_HOST_NAME:-host}"
