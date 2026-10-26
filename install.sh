#!/bin/sh
set -eu

REPO="Plural-Organization/Plural"
VERSION="${PLURAL_VERSION:-latest}"
BIN_DIR="${PLURAL_INSTALL_DIR:-$HOME/.local/bin}"
RELEASES="${PLURAL_RELEASE_URL:-https://github.com/$REPO/releases}"
HOST_PACKAGE="${PLURAL_HOST_PACKAGE:-}"

if [ -t 1 ]; then
  BOLD="$(printf '\033[1m')"
  DIM="$(printf '\033[2m')"
  RED="$(printf '\033[31m')"
  RESET="$(printf '\033[0m')"
else
  BOLD=""
  DIM=""
  RED=""
  RESET=""
fi

say() {
  printf '%s\n' "$*"
}

step() {
  printf '%s>%s %s\n' "$BOLD" "$RESET" "$*"
}

fail() {
  printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

detect_os() {
  case "$(uname -s)" in
    Darwin) echo darwin ;;
    Linux) echo linux ;;
    *) fail "unsupported system: $(uname -s). On Windows use WSL." ;;
  esac
}

detect_arch() {
  case "$(uname -m)" in
    arm64 | aarch64) echo arm64 ;;
    x86_64 | amd64) echo x64 ;;
    *) fail "unsupported architecture: $(uname -m)" ;;
  esac
}

sha256_check() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c "$1" >/dev/null 2>&1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 -c "$1" >/dev/null 2>&1
  else
    fail "sha256sum or shasum is required to verify the download"
  fi
}

asset_url() {
  if [ "$VERSION" = "latest" ]; then
    echo "$RELEASES/latest/download/$1"
  else
    echo "$RELEASES/download/v${VERSION#v}/$1"
  fi
}

install_host() {
  if ! command -v uv >/dev/null 2>&1; then
    step "Installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="${XDG_BIN_HOME:-$HOME/.local/bin}:$HOME/.cargo/bin:$PATH"
    export PATH
    command -v uv >/dev/null 2>&1 || fail "uv was installed but is not on PATH; restart the shell and run this script again"
  fi
  package="$HOST_PACKAGE"
  if [ -z "$package" ]; then
    if [ "$VERSION" = "latest" ]; then
      package="plural-agent"
    else
      package="plural-agent==${VERSION#v}"
    fi
  fi
  step "Installing the host (plural-host)"
  uv tool install --force --python 3.12 "$package"
}

install_client() {
  os="$(detect_os)"
  arch="$(detect_arch)"
  asset="plural-$os-$arch.tar.gz"
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  step "Downloading plural for $os-$arch"
  curl -fsSL "$(asset_url "$asset")" -o "$work/$asset" || fail "could not download $asset from $RELEASES"
  curl -fsSL "$(asset_url "$asset.sha256")" -o "$work/$asset.sha256" || fail "could not download the checksum for $asset"
  (cd "$work" && sha256_check "$asset.sha256") || fail "checksum mismatch for $asset"
  tar -xzf "$work/$asset" -C "$work"
  mkdir -p "$BIN_DIR"
  mv -f "$work/plural" "$BIN_DIR/plural"
  chmod +x "$BIN_DIR/plural"
}

on_path() {
  case ":$PATH:" in
    *":$1:"*) return 0 ;;
    *) return 1 ;;
  esac
}

need curl
need tar

install_host
install_client

path_missing=0
if ! on_path "$BIN_DIR"; then
  path_missing=1
  uv tool update-shell >/dev/null 2>&1 || true
fi

PATH="$BIN_DIR:$PATH"
export PATH
installed="$("$BIN_DIR/plural" --version)" || fail "the installed client does not run"

say ""
say "${BOLD}plural $installed is installed${RESET}"
say ""
say "  cd your-project"
say "  plural"
say ""
say "${DIM}The demo agent needs no key. For a real model:${RESET}"
say "  ANTHROPIC_API_KEY=... PLURAL_PROVIDER=anthropic plural"
if [ "$path_missing" = 1 ]; then
  say ""
  say "Open a new terminal, or run: export PATH=\"$BIN_DIR:\$PATH\""
fi
