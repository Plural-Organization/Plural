#!/bin/sh
# Freeze the host into a folder, with the Anthropic and OpenAI SDKs inside, so installing it is a
# download instead of a Python and a dependency resolve. Usage: scripts/build-host.sh [outdir]
# leaves <outdir>/plural-host/plural-host.
#
# The code is left as plain files (noarchive) instead of one zlib blob: xz packs those about twice
# as small, which is the size of the download.
set -eu
cd "$(dirname "$0")/.."
out="${1:-stage}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
uv run --python 3.12 --extra anthropic --extra openai --with pyinstaller sh -c '
  set -eu
  pyi-makespec --onedir --strip --name plural-host --specpath "$1" \
    --collect-submodules plural --collect-data plural --collect-submodules pydantic_ai \
    --collect-submodules anthropic --collect-submodules openai \
    --recursive-copy-metadata plural-agent --recursive-copy-metadata pydantic-ai-slim \
    --recursive-copy-metadata anthropic --recursive-copy-metadata openai \
    --recursive-copy-metadata mcp \
    --exclude-module hypothesis --exclude-module pytest --exclude-module tiktoken \
    --exclude-module IPython --exclude-module tkinter \
    scripts/host_entry.py >/dev/null
  sed -i.bak "s/noarchive=False/noarchive=True/" "$1/plural-host.spec"
  pyinstaller --noconfirm --clean --distpath "$2" --workpath "$1/build" "$1/plural-host.spec"
' sh "$work" "$out"
