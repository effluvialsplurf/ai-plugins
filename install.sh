#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AG_DEST="${HOME}/.gemini/config/plugins"
CLAUDE_SETTINGS="${HOME}/.claude/settings.json"
SKILLS_DEST=""

MODE="link"
TARGET="all"
TARGET_EXPLICIT=0
ACTION="install"
ONLY_FILTER=""

usage() {
  cat <<USAGE
Usage: ./install.sh [options]

Install or symlink plugins and portable skills from this repo into Antigravity,
Claude Code, or any Agent-Skills-compatible harness (Codex CLI, Gemini CLI,
Cursor, Windsurf, OpenCode, Kiro, ~/.agents/skills, etc.).

Target Options (pick at most one):
  --all                 Manage both Antigravity and Claude Code plugins (default)
  --antigravity         Only manage Antigravity plugins (~/.gemini/config/plugins)
  --claude              Only manage Claude Code plugins (local marketplace + statusLine)
  --skills <dir>        Install/symlink portable skills into any Agent Skills directory
  --agents              Shorthand for --skills ~/.agents/skills
  --codex               Shorthand for --skills ~/.codex/skills
  --gemini-cli          Shorthand for --skills ~/.gemini/skills
  --opencode            Shorthand for --skills ~/.config/opencode/skills
  --only <csv>          Comma-separated plugin or skill names to filter install
                        (e.g., --only deep-review,lean-design or --only build-loop)

Mode & Action Options:
  --link                Symlink plugins/skills for live iteration (default)
  --copy                Copy plugins/skills instead of symlinking
  --status              Show current install / link status
  --uninstall           Remove symlinks pointing to this repo (or print Claude uninstall commands)
  -h, --help            Show this help

Examples:
  ./install.sh                                      # Antigravity + Claude Code
  ./install.sh --claude --only deep-review          # Single Claude Code plugin
  ./install.sh --only deep-review                   # Works with default --all too
  ./install.sh --antigravity --copy                 # Standalone Antigravity copy
  ./install.sh --codex                              # Portable skills -> ~/.codex/skills
  ./install.sh --skills .cursor/skills --only deep-review,lean-design
USAGE
}

set_target() {
  local new_target="$1"
  local new_skills_dest="${2:-}"
  if [[ "${TARGET_EXPLICIT}" -eq 1 ]]; then
    echo "Conflicting target options: specify only one of --all, --antigravity, --claude, --skills, --agents, --codex, --gemini-cli, --opencode." >&2
    exit 1
  fi
  TARGET="${new_target}"
  SKILLS_DEST="${new_skills_dest}"
  TARGET_EXPLICIT=1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)         set_target "all" ;;
    --antigravity) set_target "antigravity" ;;
    --claude)      set_target "claude" ;;
    --agents)      set_target "skills" "${HOME}/.agents/skills" ;;
    --codex)       set_target "skills" "${HOME}/.codex/skills" ;;
    --gemini-cli)  set_target "skills" "${HOME}/.gemini/skills" ;;
    --opencode)    set_target "skills" "${HOME}/.config/opencode/skills" ;;
    --skills|--skills-dir)
      if [[ $# -lt 2 || -z "$2" || "$2" == -* ]]; then
        echo "Option $1 requires a non-empty target directory path." >&2
        usage >&2
        exit 1
      fi
      set_target "skills" "$2"
      shift
      ;;
    --skills=*|--skills-dir=*)
      val="${1#*=}"
      if [[ -z "${val}" || "${val}" == -* ]]; then
        echo "Option ${1%%=*} requires a non-empty target directory path." >&2
        usage >&2
        exit 1
      fi
      set_target "skills" "${val}"
      ;;
    --only)
      if [[ $# -lt 2 || -z "$2" || "$2" == -* ]]; then
        echo "Option --only requires a non-empty comma-separated list of plugin/skill names." >&2
        usage >&2
        exit 1
      fi
      ONLY_FILTER="$2"
      shift
      ;;
    --only=*)
      val="${1#*=}"
      if [[ -z "${val}" || "${val}" == -* ]]; then
        echo "Option --only requires a non-empty comma-separated list of plugin/skill names." >&2
        usage >&2
        exit 1
      fi
      ONLY_FILTER="${val}"
      ;;
    --link)        MODE="link" ;;
    --copy)        MODE="copy" ;;
    --status)      ACTION="status" ;;
    --uninstall)   ACTION="uninstall" ;;
    -h|--help)     usage; exit 0 ;;
    *)             echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
  shift
done

# Portable skill registry: "skill_name|plugin_group|relative_source_path|default_included"
SKILL_CATALOG=(
  "deep-review|deep-review|claude/deep-review/skills/deep-review|yes"
  "receiving-deep-review|deep-review|claude/deep-review/skills/receiving-deep-review|yes"
  "build-loop|build-loop|claude/build-loop/skills/build-loop|yes"
  "context-costs|build-loop|claude/build-loop/skills/context-costs|yes"
  "lean-design|lean-runbook|antigravity/lean-runbook/skills/lean-design|yes"
  "lean-runbook|lean-runbook|antigravity/lean-runbook/skills/lean-runbook|yes"
  "runbook|egm-runbook|claude/egm-runbook/skills/runbook|no"
)

matches_filter() {
  local name="$1"
  local group="${2:-}"
  [[ -z "${ONLY_FILTER}" ]] && return 0
  local IFS=','
  for item in ${ONLY_FILTER}; do
    item="${item#"${item%%[![:space:]]*}"}"
    item="${item%"${item##*[![:space:]]}"}"
    if [[ "${item}" == "${name}" ]] || [[ -n "${group}" && "${item}" == "${group}" ]]; then
      return 0
    fi
  done
  return 1
}

resolve_path_abs() {
  local p="$1"
  if [[ "${p}" == "~"* ]]; then
    p="${HOME}${p#\~}"
  fi
  if [[ "${p}" != /* ]]; then
    p="$(pwd)/${p}"
  fi
  echo "${p}"
}

link_or_copy_dir() {
  local label="$1"
  local src="$2"
  local dst="$3"
  local name="$4"

  if [[ "${MODE}" == "link" ]]; then
    if [[ -L "${dst}" ]]; then
      local current
      current="$(readlink -f "${dst}")"
      if [[ "${current}" == "${src}" ]]; then
        echo "${label}: ${name} already linked -> ${src}"
        return 0
      fi
      rm "${dst}"
    elif [[ -e "${dst}" ]]; then
      local backup_dir="${HOME}/.cache/ai-plugins-backups"
      mkdir -p "${backup_dir}"
      local backup="${backup_dir}/${name}.bak.$(date +%Y%m%d-%H%M%S)"
      mv "${dst}" "${backup}"
      echo "${label}: backed up existing ${dst} -> ${backup}"
    fi
    ln -s "${src}" "${dst}"
    echo "${label}: linked ${dst} -> ${src}"
  else
    if [[ -L "${dst}" ]]; then
      rm "${dst}"
    elif [[ -e "${dst}" ]]; then
      local backup_dir="${HOME}/.cache/ai-plugins-backups"
      mkdir -p "${backup_dir}"
      local backup="${backup_dir}/${name}.bak.$(date +%Y%m%d-%H%M%S)"
      mv "${dst}" "${backup}"
      echo "${label}: backed up existing ${dst} -> ${backup}"
    fi
    cp -R "${src}" "${dst}"
    find "${dst}" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    echo "${label}: copied ${src} -> ${dst}"
  fi
}

status_antigravity() {
  echo "Antigravity plugins (${AG_DEST}):"
  for src in "${REPO_DIR}/antigravity"/*; do
    [[ -d "${src}" ]] || continue
    name="$(basename "${src}")"
    matches_filter "${name}" || continue
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
    name="$(basename "${src}")"
    matches_filter "${name}" || continue
    echo "  [available] ${name}@ai-plugins"
  done
  if command -v claude >/dev/null 2>&1; then
    echo "  (run 'claude plugin list' to see active Claude Code installs)"
  fi
}

status_skills() {
  local dest
  dest="$(resolve_path_abs "${SKILLS_DEST}")"
  echo "Portable skills (${dest}):"
  local entry skill group rel default_inc src dst target
  for entry in "${SKILL_CATALOG[@]}"; do
    IFS='|' read -r skill group rel default_inc <<< "${entry}"
    if [[ -n "${ONLY_FILTER}" ]]; then
      matches_filter "${skill}" "${group}" || continue
    elif [[ "${default_inc}" != "yes" ]]; then
      continue
    fi
    src="${REPO_DIR}/${rel}"
    dst="${dest}/${skill}"
    if [[ -L "${dst}" ]]; then
      target="$(readlink -f "${dst}")"
      if [[ "${target}" == "${src}" ]]; then
        echo "  [linked]   ${skill} -> ${target}"
      else
        echo "  [symlink]  ${skill} -> ${target} (points elsewhere)"
      fi
    elif [[ -d "${dst}" ]]; then
      echo "  [dir]      ${skill} (copied/standalone directory)"
    else
      echo "  [missing]  ${skill}"
    fi
  done
}

TOTAL_INSTALLED=0

install_antigravity() {
  local installed=0
  for src in "${REPO_DIR}/antigravity"/*; do
    [[ -d "${src}" ]] || continue
    name="$(basename "${src}")"
    matches_filter "${name}" || continue
    mkdir -p "${AG_DEST}"
    dst="${AG_DEST}/${name}"
    link_or_copy_dir "Antigravity" "${src}" "${dst}" "${name}"
    installed=$((installed + 1))
  done
  TOTAL_INSTALLED=$((TOTAL_INSTALLED + installed))
  if [[ "${installed}" -eq 0 && "${TARGET}" != "all" ]]; then
    echo "Antigravity: no plugins matched --only '${ONLY_FILTER}'" >&2
    return 1
  fi
  return 0
}

uninstall_antigravity() {
  for src in "${REPO_DIR}/antigravity"/*; do
    [[ -d "${src}" ]] || continue
    name="$(basename "${src}")"
    matches_filter "${name}" || continue
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
  local plugins=()
  for plugin in deep-review build-loop egm-runbook; do
    if matches_filter "${plugin}"; then
      plugins+=("${plugin}")
    fi
  done
  if [[ "${#plugins[@]}" -eq 0 ]]; then
    if [[ "${TARGET}" != "all" ]]; then
      echo "Claude Code: no plugins matched --only '${ONLY_FILTER}'" >&2
      return 1
    fi
    return 0
  fi

  TOTAL_INSTALLED=$((TOTAL_INSTALLED + ${#plugins[@]}))

  if ! command -v claude >/dev/null 2>&1; then
    echo "Claude Code CLI not found on PATH."
    echo "In Claude Code, run:"
    echo "  /plugin marketplace add ${REPO_DIR}"
    for plugin in "${plugins[@]}"; do
      echo "  /plugin install ${plugin}@ai-plugins"
    done
    return 0
  fi

  echo "Claude Code: registering local marketplace ${REPO_DIR}..."
  claude plugin marketplace add "${REPO_DIR}" || true

  for plugin in "${plugins[@]}"; do
    echo "Claude Code: installing ${plugin}@ai-plugins..."
    claude plugin install "${plugin}@ai-plugins"
  done

  if matches_filter "egm-runbook"; then
    update_claude_statusline
  fi
  echo "Claude Code: done. Restart Claude Code if a session is open."
}

uninstall_claude() {
  local plugins=()
  for plugin in egm-runbook build-loop deep-review; do
    if matches_filter "${plugin}"; then
      plugins+=("${plugin}")
    fi
  done
  if [[ "${#plugins[@]}" -eq 0 ]]; then
    return 0
  fi
  echo "To uninstall Claude Code plugins, run:"
  for plugin in "${plugins[@]}"; do
    echo "  claude plugin uninstall ${plugin}@ai-plugins"
  done
  if [[ -z "${ONLY_FILTER}" ]]; then
    echo "  claude plugin marketplace remove ai-plugins"
  fi
  if matches_filter "egm-runbook"; then
    echo "  (if configured, also remove or update 'statusLine' in ~/.claude/settings.json)"
  fi
}

install_skills() {
  local dest
  dest="$(resolve_path_abs "${SKILLS_DEST}")"
  mkdir -p "${dest}"
  local entry skill group rel default_inc src dst
  local installed=0
  local saw_build_loop=0
  local saw_egm_runbook=0
  local saw_lean_design=0
  local saw_lean_runbook=0

  for entry in "${SKILL_CATALOG[@]}"; do
    IFS='|' read -r skill group rel default_inc <<< "${entry}"
    if [[ -n "${ONLY_FILTER}" ]]; then
      matches_filter "${skill}" "${group}" || continue
    elif [[ "${default_inc}" != "yes" ]]; then
      continue
    fi
    src="${REPO_DIR}/${rel}"
    dst="${dest}/${skill}"
    link_or_copy_dir "Skills" "${src}" "${dst}" "${skill}"
    installed=$((installed + 1))
    [[ "${skill}" == "build-loop" ]] && saw_build_loop=1
    [[ "${skill}" == "runbook" ]] && saw_egm_runbook=1
    [[ "${skill}" == "lean-design" ]] && saw_lean_design=1
    [[ "${skill}" == "lean-runbook" ]] && saw_lean_runbook=1
  done

  if [[ "${installed}" -eq 0 ]]; then
    echo "Skills: no skills matched --only '${ONLY_FILTER}'" >&2
    return 1
  fi

  if [[ "${saw_build_loop}" -eq 1 || "${saw_lean_design}" -eq 1 || "${saw_lean_runbook}" -eq 1 || "${saw_egm_runbook}" -eq 1 ]]; then
    echo ""
    echo "Notes for non-native harnesses (see ${REPO_DIR}/docs/PORTABILITY.md):"
    if [[ "${saw_build_loop}" -eq 1 ]]; then
      echo "  - build-loop: templates/ and helper scripts live in ${REPO_DIR}/claude/build-loop/ (use references/version-custom-harness.md for custom models; stall-watch.sh needs Bash 4+ & GNU find)."
    fi
    if [[ "${saw_lean_design}" -eq 1 ]]; then
      echo "  - lean-design: invoke scripts/design_check.py from ${dest}/lean-design/scripts/design_check.py; SKILL.md swarm prose can be mapped manually or converted via docs/CONVERSION-PROMPTS.md."
    fi
    if [[ "${saw_lean_runbook}" -eq 1 ]]; then
      echo "  - lean-runbook: invoke scripts/runbook.py CLI from ${dest}/lean-runbook/scripts/runbook.py; Antigravity hooks/swarm/run_workflow require conversion (docs/CONVERSION-PROMPTS.md)."
    fi
    if [[ "${saw_egm_runbook}" -eq 1 ]]; then
      echo "  - egm-runbook (runbook): CLI is at ${REPO_DIR}/claude/egm-runbook/scripts/runbook.py; hooks & '!' override require Claude Code or conversion (docs/CONVERSION-PROMPTS.md)."
    fi
  fi
}

uninstall_skills() {
  local dest
  dest="$(resolve_path_abs "${SKILLS_DEST}")"
  local entry skill group rel default_inc src dst
  for entry in "${SKILL_CATALOG[@]}"; do
    IFS='|' read -r skill group rel default_inc <<< "${entry}"
    if [[ -n "${ONLY_FILTER}" ]]; then
      matches_filter "${skill}" "${group}" || continue
    fi
    src="${REPO_DIR}/${rel}"
    dst="${dest}/${skill}"
    if [[ -L "${dst}" && "$(readlink -f "${dst}")" == "${src}" ]]; then
      rm "${dst}"
      echo "Skills: removed symlink ${dst}"
    fi
  done
}

case "${ACTION}" in
  status)
    if [[ "${TARGET}" == "all" || "${TARGET}" == "antigravity" ]]; then status_antigravity; fi
    if [[ "${TARGET}" == "all" || "${TARGET}" == "claude" ]]; then status_claude; fi
    if [[ "${TARGET}" == "skills" ]]; then status_skills; fi
    ;;
  install)
    rc=0
    if [[ "${TARGET}" == "all" || "${TARGET}" == "antigravity" ]]; then install_antigravity || rc=1; fi
    if [[ "${TARGET}" == "all" || "${TARGET}" == "claude" ]]; then install_claude || rc=1; fi
    if [[ "${TARGET}" == "all" && -n "${ONLY_FILTER}" && "${TOTAL_INSTALLED}" -eq 0 ]]; then
      echo "No Antigravity or Claude Code plugins matched --only '${ONLY_FILTER}'" >&2
      rc=1
    fi
    if [[ "${TARGET}" == "skills" ]]; then install_skills || rc=1; fi
    exit "${rc}"
    ;;
  uninstall)
    if [[ "${TARGET}" == "all" || "${TARGET}" == "antigravity" ]]; then uninstall_antigravity; fi
    if [[ "${TARGET}" == "all" || "${TARGET}" == "claude" ]]; then uninstall_claude; fi
    if [[ "${TARGET}" == "skills" ]]; then uninstall_skills; fi
    ;;
esac
