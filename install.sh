#!/bin/sh
set -eu

PACKAGE="${PLURAL_INSTALL_SOURCE:-plural-agent}"

say() {
  printf '%s\n' "$*"
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

case "$(uname -s)" in
  Darwin | Linux) ;;
  *) fail "unsupported OS: $(uname -s). On Windows use WSL." ;;
esac

if ! command -v uv >/dev/null 2>&1; then
  command -v curl >/dev/null 2>&1 || fail "curl is required to install uv"
  say "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="${XDG_BIN_HOME:-$HOME/.local/bin}:$HOME/.cargo/bin:$PATH"
  export PATH
  command -v uv >/dev/null 2>&1 || fail "uv was installed but is not on PATH; restart the shell and rerun"
fi

say "Installing Plural"
uv tool install --force --python 3.12 "$PACKAGE"

uv tool update-shell >/dev/null 2>&1 || true

say ""
say "Plural installed. If 'plural' is not found, restart your shell."
say "Next: plural doctor"
