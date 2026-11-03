#!/bin/sh
set -eu

REPO="Plural-Organization/Plural"
VERSION="${PLURAL_VERSION:-latest}"
BIN_DIR="${PLURAL_INSTALL_DIR:-$HOME/.local/bin}"
RELEASES="${PLURAL_RELEASE_URL:-https://github.com/$REPO/releases}"
HOST_PACKAGE="${PLURAL_HOST_PACKAGE:-}"
EXTRAS="${PLURAL_EXTRAS:-}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/plural"

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

# Stops a process and everything it started. Killing only the subshell of a download leaves its
# curl running, and a curl left behind writes into the cache while the next run resumes the same file.
stop_tree() {
  [ -n "${1:-}" ] || return 0
  for child in $(ps -axo pid=,ppid= 2>/dev/null | awk -v parent="$1" '$2 == parent { print $1 }'); do
    stop_tree "$child"
  done
  kill "$1" 2>/dev/null || true
}

# Two installs share one download cache, so only one runs at a time. A lock left by a process that
# is gone is taken over.
LOCK=""
acquire_lock() {
  mkdir -p "$CACHE"
  lock="$CACHE/install.lock"
  if ! mkdir "$lock" 2>/dev/null; then
    other="$(cat "$lock/pid" 2>/dev/null || true)"
    if [ -n "$other" ] && kill -0 "$other" 2>/dev/null; then
      fail "another plural install is running (process $other). Wait for it, or stop it and run this again"
    fi
    rm -rf "$lock"
    mkdir "$lock" 2>/dev/null || fail "another plural install is running. Wait for it, or stop it and run this again"
  fi
  printf '%s\n' "$$" > "$lock/pid"
  LOCK="$lock"
}

release_lock() {
  [ -z "$LOCK" ] || rm -rf "$LOCK"
  LOCK=""
}

mb() {
  awk -v bytes="$1" 'BEGIN { printf "%.1f", bytes / 1048576 }'
}

# The size a download will have, when the server says so.
content_length() {
  curl -fsSIL --connect-timeout 8 --max-time 20 "$1" 2>/dev/null |
    awk 'tolower($1) == "content-length:" { value = $2 } END { gsub(/\r/, "", value); print value + 0 }'
}

# The downloads run side by side in the background, so curl's own bar is off. On a terminal this shows
# one line that moves, so a slow connection does not look like a hang.
watch_downloads() {
  [ -t 2 ] || return 0
  seen=0
  while kill -0 "$1" 2>/dev/null || kill -0 "$2" 2>/dev/null; do
    line=""
    sum=0
    for name in plural plural-host; do
      entry="$(cat "$CACHE/progress-$name" 2>/dev/null || true)"
      [ -n "$entry" ] || continue
      target="${entry% *}"
      total="${entry##* }"
      [ -f "$target" ] || continue
      size="$(wc -c < "$target" | tr -d ' ')"
      sum=$((sum + size))
      if [ "${total:-0}" -gt 0 ] 2>/dev/null; then
        part="$(mb "$size")/$(mb "$total") MB"
      else
        part="$(mb "$size") MB"
      fi
      line="${line:+$line · }$name $part"
    done
    if [ -n "$line" ]; then
      printf '\r\033[K  %s · %s MB/s' "$line" "$(mb $((sum - seen)))" >&2
      seen=$sum
    fi
    sleep 1
  done
  printf '\r\033[K' >&2
}

fetch_small() {
  curl -fsSL --retry 2 --connect-timeout 8 "$(asset_url "$1")" -o "$2" 2>/dev/null
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

# A connection that stalls (under 1 KB/s for 30 s) is dropped and retried from where it stopped, so a
# dead link ends instead of waiting for ever.
download() {
  if [ -t 2 ]; then
    curl -fL --progress-bar --retry 5 --retry-delay 2 --retry-connrefused --connect-timeout 20 --speed-time 30 --speed-limit 1024 -C - "$1" -o "$2"
  else
    curl -fsSL --retry 5 --retry-delay 2 --retry-connrefused --connect-timeout 20 --speed-time 30 --speed-limit 1024 -C - "$1" -o "$2"
  fi
}

# tar reads xz itself on macOS; elsewhere it calls the xz program.
can_unpack_xz() {
  [ "$(uname -s)" = Darwin ] || command -v xz >/dev/null 2>&1
}

# Download, verify and place one frozen executable (plural, or plural-host). Returns 2 when this
# release has no such asset, so the caller can fall back.
install_binary() {
  name="$1"
  os="$(detect_os)"
  arch="$(detect_arch)"
  cache="$CACHE"
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  trap 'exit 143' TERM HUP
  # The xz archive is a third smaller, so it is what a slow connection should wait for. A release
  # from before it existed, or a machine that cannot unpack it, takes the gzip one.
  asset="$name-$os-$arch.tar.xz"
  if ! can_unpack_xz || ! fetch_small "$asset.sha256" "$work/$asset.sha256"; then
    asset="$name-$os-$arch.tar.gz"
    fetch_small "$asset.sha256" "$work/$asset.sha256" || return 2
  fi
  hash="$(checksum_of "$work/$asset.sha256")"
  [ -n "$hash" ] || fail "the checksum for $asset is empty"
  if [ -x "$BIN_DIR/$name" ] && [ "$(cat "$cache/installed-$name-$os-$arch" 2>/dev/null || true)" = "$hash" ]; then
    step "$name is already up to date"
    return 0
  fi
  download_dir="$cache/$hash"
  mkdir -p "$download_dir"
  cp "$work/$asset.sha256" "$download_dir/$asset.sha256"
  if [ -f "$download_dir/$asset" ] && (cd "$download_dir" && sha256_check "$asset.sha256"); then
    step "Using the download of $name from an earlier run"
  else
    step "Downloading $name for $os-$arch"
    printf '%s %s\n' "$download_dir/$asset" "$(content_length "$(asset_url "$asset")")" > "$cache/progress-$name"
    download "$(asset_url "$asset")" "$download_dir/$asset" || fail "could not download $asset from $RELEASES, run the installer again to continue where it stopped"
    (cd "$download_dir" && sha256_check "$asset.sha256") || {
      rm -f "$download_dir/$asset"
      fail "checksum mismatch for $asset, run the installer again"
    }
  fi
  tar -xf "$download_dir/$asset" -C "$work"
  mkdir -p "$BIN_DIR"
  if [ -d "$work/$name" ]; then
    # The host is a folder (its libraries sit beside it), so it lives in the data directory and
    # only a link to it goes on the PATH. It is swapped in whole, so a failed update leaves the old one.
    app_dir="${XDG_DATA_HOME:-$HOME/.local/share}/plural"
    mkdir -p "$app_dir"
    rm -rf "$app_dir/$name.new"
    mv "$work/$name" "$app_dir/$name.new"
    rm -rf "$app_dir/$name"
    mv "$app_dir/$name.new" "$app_dir/$name"
    ln -sf "$app_dir/$name/$name" "$BIN_DIR/$name"
  else
    mv -f "$work/$name" "$BIN_DIR/$name"
    chmod +x "$BIN_DIR/$name"
  fi
  printf '%s\n' "$hash" > "$cache/installed-$name-$os-$arch"
  rm -rf "$download_dir"
  rm -f "$cache/progress-$name"
}

install_client() {
  install_binary plural || fail "could not download the checksum for plural from $RELEASES"
}

# The frozen host needs no Python or uv. A release without one, or PLURAL_HOST_PACKAGE (a custom
# build to install from an index), takes the uv install.
install_host_any() {
  if [ -z "$HOST_PACKAGE" ]; then
    status=0
    install_binary plural-host || status=$?
    [ "$status" = 2 ] || return "$status"
    step "This release has no frozen host, installing it with uv"
  fi
  install_host
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

acquire_lock

# The client and the host each wait on the network, so they download side by side.
client_log="$(mktemp)"
host_log="$(mktemp)"
client_pid=""
host_pid=""
cleanup() {
  stop_tree "$client_pid"
  stop_tree "$host_pid"
  rm -f "$client_log" "$host_log" "$CACHE/progress-plural" "$CACHE/progress-plural-host"
  release_lock
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
install_client >"$client_log" 2>&1 &
client_pid=$!
install_host_any >"$host_log" 2>&1 &
host_pid=$!
step "Downloading plural and plural-host"
watch_downloads "$client_pid" "$host_pid"
failed=0
wait "$client_pid" || failed=1
cat "$client_log"
wait "$host_pid" || failed=1
cat "$host_log"
client_pid=""
host_pid=""
if [ "$failed" = 1 ]; then
  exit 1
fi
rm -f "$client_log" "$host_log"

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
say "${DIM}The demo agent needs no key. For a model, set a provider and its key:${RESET}"
say "  ANTHROPIC_API_KEY=... PLURAL_PROVIDER=anthropic plural"
if [ "$path_missing" = 1 ]; then
  say ""
  say "Open a new terminal, or run: export PATH=\"$BIN_DIR:\$PATH\""
fi
