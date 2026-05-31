#!/bin/sh
set -eu

REPO="AlfonsoDehesa/recollectium"
INSTALL_DIR="${HOME}/.local/bin"
UV_BIN="${INSTALL_DIR}/uv"
TOOL_BIN_DIR=""
MANAGED_PATH_EDIT=""
COMPLETION_RC=""
COMPLETION_SHELL=""

info() {
  printf '%s\n' "$1"
}

fail() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\x08/\\b/g; s/\f/\\f/g; s/\n/\\n/g; s/\r/\\r/g; s/\t/\\t/g'
}

detect_uv_archive() {
  os=$(uname -s)
  arch=$(uname -m)

  case "$os:$arch" in
    Linux:x86_64|Linux:amd64) printf 'uv-x86_64-unknown-linux-gnu.tar.gz' ;;
    Linux:aarch64|Linux:arm64) printf 'uv-aarch64-unknown-linux-gnu.tar.gz' ;;
    Darwin:x86_64|Darwin:amd64) printf 'uv-x86_64-apple-darwin.tar.gz' ;;
    Darwin:arm64|Darwin:aarch64) printf 'uv-aarch64-apple-darwin.tar.gz' ;;
    *) fail "unsupported platform: ${os} ${arch}" ;;
  esac
}

install_uv() {
  if command_exists uv; then
    UV_BIN=$(command -v uv)
    info "uv already installed: ${UV_BIN}"
    return
  fi

  archive=$(detect_uv_archive)
  url="https://github.com/astral-sh/uv/releases/latest/download/${archive}"
  tmpdir=$(mktemp -d)
  trap 'rm -rf "$tmpdir"' EXIT HUP INT TERM

  mkdir -p "$INSTALL_DIR"
  info "Downloading uv..."
  curl -LsSf "$url" -o "${tmpdir}/${archive}" || fail "failed to download uv"
  tar -xzf "${tmpdir}/${archive}" -C "$tmpdir" || fail "failed to extract uv"
  found_uv=$(find "$tmpdir" -type f -name uv | head -n 1)
  [ -n "$found_uv" ] || fail "uv binary not found in archive"
  cp "$found_uv" "$UV_BIN"
  chmod +x "$UV_BIN"
  info "Installed uv: ${UV_BIN}"
}

resolve_ref() {
  if [ -n "${RECOLLECTIUM_INSTALL_REF:-}" ]; then
    printf '%s' "$RECOLLECTIUM_INSTALL_REF"
    return
  fi

  tag=$(curl -LsSf "https://api.github.com/repos/${REPO}/releases/latest" \
    | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
    | head -n 1 || true)
  if [ -n "$tag" ]; then
    printf '%s' "$tag"
  else
    info "No GitHub release found; installing from main."
    printf 'main'
  fi
}

ensure_path_hint() {
  [ -n "$TOOL_BIN_DIR" ] || fail "uv tool bin directory was not resolved"
  case ":${PATH}:" in
    *":${TOOL_BIN_DIR}:"*) return ;;
  esac

  profile="${HOME}/.profile"
  line="export PATH=\"${TOOL_BIN_DIR}:\$PATH\""
  if [ ! -f "$profile" ] || ! grep -F "$line" "$profile" >/dev/null 2>&1; then
    printf '\n# Recollectium CLI\n%s\n' "$line" >> "$profile"
    MANAGED_PATH_EDIT="${profile}: ${line}"
  fi
  info "Added ${TOOL_BIN_DIR} to ${profile}. Restart your shell if recollectium is not found."
}

resolve_tool_bin_dir() {
  TOOL_BIN_DIR=$("$UV_BIN" tool dir --bin 2>/dev/null || true)
  [ -n "$TOOL_BIN_DIR" ] || fail "failed to resolve uv tool bin directory"
  [ -d "$TOOL_BIN_DIR" ] || mkdir -p "$TOOL_BIN_DIR"
  command_path="${TOOL_BIN_DIR}/recollectium"
  if [ ! -x "$command_path" ]; then
    fail "recollectium executable was not installed in uv tool bin directory: ${TOOL_BIN_DIR}"
  fi
}

record_install_metadata() {
  state_dir="${XDG_STATE_HOME:-${HOME}/.local/state}/recollectium"
  metadata_path="${state_dir}/install.json"
  installed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  mkdir -p "$state_dir"
  escaped_ref=$(json_escape "$ref")

  path_edits="["
  if [ -n "$MANAGED_PATH_EDIT" ]; then
    escaped_path_edit=$(json_escape "$MANAGED_PATH_EDIT")
    path_edits="${path_edits}\"${escaped_path_edit}\""
  fi
  path_edits="${path_edits}]"

  completion_edits="["
  if [ -n "$COMPLETION_RC" ]; then
    escaped_completion_path=$(json_escape "$COMPLETION_RC")
    escaped_completion_shell=$(json_escape "$COMPLETION_SHELL")
    completion_edits="${completion_edits}{\"shell\": \"${escaped_completion_shell}\", \"path\": \"${escaped_completion_path}\", \"source_command\": \"recollectium completion --source ${escaped_completion_shell}\"}"
  fi
  completion_edits="${completion_edits}]"

  printf '{\n  "install_method": "bootstrap",\n  "source_ref": "%s",\n  "installed_at": "%s",\n  "managed_path_edits": %s,\n  "managed_completion_edits": %s\n}\n' "$escaped_ref" "$installed_at" "$path_edits" "$completion_edits" > "$metadata_path"
}

configure_shell_completion() {
  detected_shell="${SHELL##*/}"
  case "$detected_shell" in
    bash) shell="bash"; rc="${HOME}/.bashrc" ;;
    zsh)  shell="zsh"; rc="${HOME}/.zshrc" ;;
    fish) shell="fish"; rc="${HOME}/.config/fish/config.fish" ;;
    *)    shell="bash"; rc="${HOME}/.bashrc" ;;  # default to bash per spec
  esac

  PATH="${TOOL_BIN_DIR}:${INSTALL_DIR}:$PATH" "$UV_BIN" tool run --from "$package" recollectium completion --install "$shell" --yes >/dev/null \
    || fail "failed to configure shell completion"
  COMPLETION_RC="$rc"
  COMPLETION_SHELL="$shell"
  info "Shell completion configured in ${rc}."
}

install_uv
ref=$(resolve_ref)
package="git+https://github.com/${REPO}.git@${ref}"
info "Installing Recollectium from ${ref}..."
"$UV_BIN" tool install --python 3.12 --force "$package"
resolve_tool_bin_dir
info "Initializing Recollectium (config, database, model)..."
"$UV_BIN" tool run --from "$package" recollectium init || true
ensure_path_hint
configure_shell_completion
record_install_metadata
info "Recollectium installed. Try: recollectium --version"
