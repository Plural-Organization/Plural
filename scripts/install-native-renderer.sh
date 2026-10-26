#!/bin/sh
set -eu

version=$(node -p "require('./tui/package.json').dependencies['@opentui/core']")
packages=""
for platform in darwin-x64 darwin-arm64 linux-x64 linux-arm64 linux-x64-musl linux-arm64-musl win32-x64 win32-arm64; do
  packages="$packages @opentui/core-$platform@$version"
done

npm install --no-save --force --os=any --cpu=any $packages
