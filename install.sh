#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AG_DEST="${HOME}/.gemini/config/plugins"
CLAUDE_SETTINGS="${HOME}/.claude/settings.json"

MODE="link"
TARGET="all"
ACTION="install"

usage() {
  cat <<USAGE
Usage: ./install.sh [options]

Install or symlink plugins from this repo into Antigravity and Claude Code.

Options:
  --all           Manage both Antigravity and Claude Code plugins (default)
  --antigravity   Only manage Antigravity plugins (~/.gemini/config/plugins)
  --claude        Only manage Claude Code plugins (local marketplace + statusLine)
  --link          Symlink Antigravity plugins for live iteration (default)
  --copy          Copy Antigravity plugins instead of symlinking
  --status        Show current install / link status
  --uninstall     Remove Antigravity links pointing to this repo
  -h, --help      Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)         TARGET="all" ;;
    --antigravity) TARGET="antigravity" ;;
    --claude)      TARGET="claude" ;;
    --link)        MODE="link" ;;
    --copy)        MODE="copy" ;;
    --status)      ACTION="status" ;;
    --uninstall)   ACTION="uninstall" ;;
    -h|--help)     usage; exit 0 ;;
    *)             echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
  shift
done

status_antigravity() {
  echo "Antigravity plugins (${AG_DEST}):"
  for src in "${REPO_DIR}/antigravity"/*; do
    [[ -d "${src}" ]] || continue
    name="$(basename "${src}")"
    dst="${AG_DEST}/${name}"
    if [[ -L "${dst}" ]]; then
      target="$(readlink -f "${dst}")"
      if [[ "${target}" == "${src}" ]]; then
        echo "  [linked]   ${name} -> ${target}"
      else
        echo "  [symlink]  ${name} -> ${target} (points elsewhere)"
      fi
    elif [[ -d "${dst}" ]]; then
      echo "  [dir]      ${name} (copied/standalone directory)"
    else
      echo "  [missing]  ${name}"
    fi
  done
}

status_claude() {
  echo "Claude Code plugins (repo: ${REPO_DIR}):"
  for src in "${REPO_DIR}/claude"/*; do
    [[ -d "${src}" ]] || continue
    echo "  [available] $(basename "${src}")@ai-plugins"
  done
  if command -v claude >/dev/null 2>&1; then
    echo "  (run 'claude plugin list' to see active Claude Code installs)"
  fi
}

install_antigravity() {
  mkdir -p "${AG_DEST}"
  for src in "${REPO_DIR}/antigravity"/*; do
    [[ -d "${src}" ]] || continue
    name="$(basename "${src}")"
    dst="${AG_DEST}/${name}"

    if [[ "${MODE}" == "link" ]]; then
      if [[ -L "${dst}" ]]; then
        current="$(readlink -f "${dst}")"
        if [[ "${current}" == "${src}" ]]; then
          echo "Antigravity: ${name} already linked -> ${src}"
          continue
        fi
        rm "${dst}"
      elif [[ -e "${dst}" ]]; then
        backup="${dst}.bak.$(date +%Y%m%d-%H%M%S)"
        mv "${dst}" "${backup}"
        echo "Antigravity: backed up existing ${dst} -> ${backup}"
      fi
      ln -s "${src}" "${dst}"
      echo "Antigravity: linked ${dst} -> ${src}"
    else
      if [[ -L "${dst}" ]]; then
        rm "${dst}"
      elif [[ -e "${dst}" ]]; then
        backup="${dst}.bak.$(date +%Y%m%d-%H%M%S)"
        mv "${dst}" "${backup}"
        echo "Antigravity: backed up existing ${dst} -> ${backup}"
      fi
      cp -R "${src}" "${dst}"
      find "${dst}" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
      echo "Antigravity: copied ${src} -> ${dst}"
    fi
  done
}

uninstall_antigravity() {
  for src in "${REPO_DIR}/antigravity"/*; do
    [[ -d "${src}" ]] || continue
    name="$(basename "${src}")"
    dst="${AG_DEST}/${name}"
    if [[ -L "${dst}" && "$(readlink -f "${dst}")" == "${src}" ]]; then
      rm "${dst}"
      echo "Antigravity: removed symlink ${dst}"
    else
      echo "Antigravity: skipped ${dst} (not a symlink to this repo)"
    fi
  done
}

update_claude_statusline() {
  local statusline_path="${REPO_DIR}/claude/egm-runbook/scripts/statusline"
  [[ -f "${statusline_path}" && -f "${CLAUDE_SETTINGS}" ]] || return 0
  python3 - "${CLAUDE_SETTINGS}" "${statusline_path}" <<'PY'
import json, sys
from pathlib import Path

settings_path = Path(sys.argv[1])
statusline_path = sys.argv[2]
data = json.loads(settings_path.read_text(encoding="utf-8"))
sl = data.get("statusLine")
expected_cmd = f"python3 {statusline_path}"

if isinstance(sl, dict) and sl.get("type") == "command" and "egm-runbook/scripts/statusline" in str(sl.get("command", "")):
    if sl.get("command") != expected_cmd:
        sl["command"] = expected_cmd
        settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"Claude Code: updated statusLine -> {expected_cmd}")
    else:
        print(f"Claude Code: statusLine already points to {statusline_path}")
PY
}

install_claude() {
  if ! command -v claude >/dev/null 2>&1; then
    echo "Claude Code CLI not found on PATH."
    echo "In Claude Code, run:"
    echo "  /plugin marketplace add ${REPO_DIR}"
    echo "  /plugin install deep-review@ai-plugins"
    echo "  /plugin install build-loop@ai-plugins"
    echo "  /plugin install egm-runbook@ai-plugins"
    return 0
  fi

  echo "Claude Code: registering local marketplace ${REPO_DIR}..."
  claude plugin marketplace add "${REPO_DIR}" || true

  for plugin in deep-review build-loop egm-runbook; do
    echo "Claude Code: installing ${plugin}@ai-plugins..."
    claude plugin install "${plugin}@ai-plugins"
  done

  update_claude_statusline
  echo "Claude Code: done. Restart Claude Code if a session is open."
}

uninstall_claude() {
  echo "To uninstall Claude Code plugins, run:"
  echo "  claude plugin uninstall egm-runbook@ai-plugins"
  echo "  claude plugin uninstall build-loop@ai-plugins"
  echo "  claude plugin uninstall deep-review@ai-plugins"
  echo "  claude plugin marketplace remove ai-plugins"
}

case "${ACTION}" in
  status)
    [[ "${TARGET}" == "all" || "${TARGET}" == "antigravity" ]] && status_antigravity
    [[ "${TARGET}" == "all" || "${TARGET}" == "claude" ]] && status_claude
    ;;
  install)
    [[ "${TARGET}" == "all" || "${TARGET}" == "antigravity" ]] && install_antigravity
    [[ "${TARGET}" == "all" || "${TARGET}" == "claude" ]] && install_claude
    ;;
  uninstall)
    [[ "${TARGET}" == "all" || "${TARGET}" == "antigravity" ]] && uninstall_antigravity
    [[ "${TARGET}" == "all" || "${TARGET}" == "claude" ]] && uninstall_claude
    ;;
esac
