#!/bin/sh
set -eu

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"
fi

uv tool install --python 3.12 plural
echo "installed: run 'plural doctor'"
