#!/bin/sh
set -eu

REPO="Plural-Organization/Plural"
VERSION="${PLURAL_VERSION:-latest}"
BIN_DIR="${PLURAL_INSTALL_DIR:-$HOME/.local/bin}"
RELEASES="${PLURAL_RELEASE_URL:-https://github.com/$REPO/releases}"
HOST_PACKAGE="${PLURAL_HOST_PACKAGE:-}"
EXTRAS="${PLURAL_EXTRAS:-}"

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

latest_version() {
  tag="$(curl -fsSLI -o /dev/null -w '%{url_effective}' --retry 3 --connect-timeout 20 "$RELEASES/latest" 2>/dev/null || true)"
  case "$tag" in
    */tag/v[0-9]*) printf '%s\n' "${tag##*/tag/v}" ;;
    *) return 1 ;;
  esac
}

asset_url() {
  if [ "$VERSION" = "latest" ]; then
    echo "$RELEASES/latest/download/$1"
  else
    echo "$RELEASES/download/v${VERSION#v}/$1"
  fi
}

# The model SDKs are optional extras, so a demo or Claude Code install does not download them.
# An update keeps the SDKs the installed host already has, so it never drops a provider.
installed_extras() {
  python="$(uv tool dir 2>/dev/null || true)/plural-agent/bin/python"
  [ -x "$python" ] || return 0
  for sdk in anthropic openai; do
    "$python" -c "import $sdk" >/dev/null 2>&1 && printf '%s\n' "$sdk"
  done
  return 0
}

host_extras() {
  wanted="$(printf '%s\n' "$EXTRAS" | tr ',' ' ')"
  case "${PLURAL_PROVIDER:-}" in
    anthropic | anthropic_oauth) wanted="$wanted anthropic" ;;
    openai) wanted="$wanted openai" ;;
    *) ;;
  esac
  wanted="$wanted $(installed_extras | tr '\n' ' ')"
  chosen=""
  for extra in $wanted; do
    case " $chosen " in
      *" $extra "*) ;;
      *) chosen="$chosen $extra" ;;
    esac
  done
  printf '%s\n' "$chosen" | awk '{ gsub(/^ +| +$/, ""); gsub(/ +/, ","); print }'
}

# The host of this release is already installed with every SDK asked for: nothing to download.
# Only a pinned version can be compared, so "latest" that could not be resolved still installs.
host_is_current() {
  [ -z "$HOST_PACKAGE" ] || return 1
  [ "$VERSION" != "latest" ] || return 1
  have="$(uv tool list 2>/dev/null | awk '$1 == "plural-agent" { sub(/^v/, "", $2); print $2; exit }')"
  [ "$have" = "${VERSION#v}" ] || return 1
  have_extras=" $(installed_extras | tr '\n' ' ') "
  for extra in $(host_extras | tr ',' ' '); do
    case "$have_extras" in
      *" $extra "*) ;;
      *) return 1 ;;
    esac
  done
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
    package="plural-agent"
    extras="$(host_extras)"
    [ -z "$extras" ] || package="$package[$extras]"
    if [ "$VERSION" != "latest" ]; then
      package="$package==${VERSION#v}"
    fi
  fi
  if host_is_current; then
    step "plural-host is already up to date"
    return
  fi
  step "Installing the host (plural-host)"
  # No --python: any Python >= 3.12 on the machine works, and uv fetches one only when none does.
  # Only plural-agent is revalidated against the index, so a stale cache cannot keep an old host;
  # its dependencies are pinned by that release and come straight from uv's cache when it has them.
  uv tool install --force --refresh-package plural-agent "$package"
}

checksum_of() {
  awk '{print $1; exit}' "$1"
}

download() {
  if [ -t 2 ]; then
    curl -fL --progress-bar --retry 5 --retry-delay 2 --retry-connrefused --connect-timeout 20 -C - "$1" -o "$2"
  else
    curl -fsSL --retry 5 --retry-delay 2 --retry-connrefused --connect-timeout 20 -C - "$1" -o "$2"
  fi
}

install_client() {
  os="$(detect_os)"
  arch="$(detect_arch)"
  asset="plural-$os-$arch.tar.gz"
  cache="${XDG_CACHE_HOME:-$HOME/.cache}/plural"
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  curl -fsSL --retry 3 --connect-timeout 20 "$(asset_url "$asset.sha256")" -o "$work/$asset.sha256" || fail "could not download the checksum for $asset from $RELEASES"
  hash="$(checksum_of "$work/$asset.sha256")"
  [ -n "$hash" ] || fail "the checksum for $asset is empty"
  if [ -x "$BIN_DIR/plural" ] && [ "$(cat "$cache/installed-$os-$arch" 2>/dev/null || true)" = "$hash" ]; then
    step "plural is already up to date"
    return
  fi
  download_dir="$cache/$hash"
  mkdir -p "$download_dir"
  cp "$work/$asset.sha256" "$download_dir/$asset.sha256"
  if [ -f "$download_dir/$asset" ] && (cd "$download_dir" && sha256_check "$asset.sha256"); then
    step "Using the download from an earlier run"
  else
    step "Downloading plural for $os-$arch"
    download "$(asset_url "$asset")" "$download_dir/$asset" || fail "could not download $asset from $RELEASES, run the installer again to continue where it stopped"
    (cd "$download_dir" && sha256_check "$asset.sha256") || {
      rm -f "$download_dir/$asset"
      fail "checksum mismatch for $asset, run the installer again"
    }
  fi
  tar -xzf "$download_dir/$asset" -C "$work"
  mkdir -p "$BIN_DIR"
  mv -f "$work/plural" "$BIN_DIR/plural"
  chmod +x "$BIN_DIR/plural"
  printf '%s\n' "$hash" > "$cache/installed-$os-$arch"
  rm -rf "$download_dir"
}

on_path() {
  case ":$PATH:" in
    *":$1:"*) return 0 ;;
    *) return 1 ;;
  esac
}

if [ "${PLURAL_INSTALL_SOURCE_ONLY:-}" = 1 ]; then
  return 0 2>/dev/null || exit 0
fi

need curl
need tar

if [ "$VERSION" = "latest" ]; then
  resolved="$(latest_version || true)"
  if [ -n "$resolved" ]; then
    VERSION="$resolved"
  fi
fi

# The client download and the host install each wait on the network, so they run side by side.
client_log="$(mktemp)"
install_client >"$client_log" 2>&1 &
client_pid=$!
trap 'kill "$client_pid" 2>/dev/null || true; rm -f "$client_log"' EXIT
step "Downloading the client in the background"
install_host
if wait "$client_pid"; then
  trap - EXIT
  cat "$client_log"
  rm -f "$client_log"
else
  trap - EXIT
  cat "$client_log" >&2
  rm -f "$client_log"
  exit 1
fi

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
say "${DIM}The demo agent needs no key. plural offers to add the Anthropic or OpenAI SDK${RESET}"
say "${DIM}the first time you start it, or add one now:${RESET}"
say "  uv tool install --force 'plural-agent[anthropic]'   ${DIM}(or [openai])${RESET}"
say "  ANTHROPIC_API_KEY=... PLURAL_PROVIDER=anthropic plural"
if [ "$path_missing" = 1 ]; then
  say ""
  say "Open a new terminal, or run: export PATH=\"$BIN_DIR:\$PATH\""
fi
