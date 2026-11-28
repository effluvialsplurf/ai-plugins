#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AG_DEST="${HOME}/.gemini/config/plugins"
SKILLS_DEST=""
BIN_DEST="${HOME}/.local/bin"
BIN_EXPLICIT=0

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
  --claude              Only manage Claude Code plugins
  --skills <dir>        Install/symlink portable skills into any Agent Skills directory
  --agents              Shorthand for --skills ~/.agents/skills
  --codex               Shorthand for --skills ~/.codex/skills
  --gemini-cli          Shorthand for --skills ~/.gemini/skills
  --opencode            Shorthand for --skills ~/.config/opencode/skills
  --bin-dir <dir>       Symlink CLI shims (plugins/*/bin, plugins/*/scripts/bin) into <dir> (default ~/.local/bin)
  --only <csv>          Comma-separated plugin or skill names to filter install
                        (e.g., --only <plugin>,<skill> or --only <plugin>)

Mode & Action Options:
  --link                Symlink plugins/skills for live iteration (default)
  --copy                Copy plugins/skills instead of symlinking
  --status              Show current install / link status
  --uninstall           Remove symlinks pointing to this repo (or print Claude uninstall commands)
  -h, --help            Show this help

Examples:
  ./install.sh                                      # Antigravity + Claude Code
  ./install.sh --claude --only <plugin>             # Single Claude Code plugin
  ./install.sh --only <plugin>                      # Works with default --all too
  ./install.sh --antigravity --copy                 # Standalone Antigravity copy
  ./install.sh --codex                              # Portable skills -> ~/.codex/skills
  ./install.sh --skills .cursor/skills --only <plugin>,<skill>
  ./install.sh --bin-dir ~/.local/bin --only <shim>
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
    --bin-dir)
      if [[ $# -lt 2 || -z "$2" || "$2" == -* ]]; then
        echo "Option --bin-dir requires a non-empty directory path." >&2
        usage >&2
        exit 1
      fi
      BIN_DEST="$2"
      BIN_EXPLICIT=1
      shift
      ;;
    --bin-dir=*)
      val="${1#*=}"
      if [[ -z "${val}" || "${val}" == -* ]]; then
        echo "Option --bin-dir requires a non-empty directory path." >&2
        usage >&2
        exit 1
      fi
      BIN_DEST="${val}"
      BIN_EXPLICIT=1
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

# Registry: plugins come from .claude-plugin/marketplace.json (name|relative source).
REGISTRY=()
reg_out="$(python3 -I - "${REPO_DIR}" <<'PY'
import json, re, sys
from pathlib import Path
seen = set()
for p in json.loads((Path(sys.argv[1]) / ".claude-plugin/marketplace.json").read_text())["plugins"]:
    n = p["name"]
    if not (isinstance(n, str) and re.fullmatch(r"[a-z0-9][a-z0-9._-]*", n) and p["source"] == "./plugins/" + n and n not in seen):
        sys.exit("invalid plugin entry in marketplace.json: %r" % (p,))
    seen.add(n)
    print(n, p["source"][2:], sep="|")
PY
)" || { echo "Registry: cannot read ${REPO_DIR}/.claude-plugin/marketplace.json" >&2; exit 1; }
while IFS= read -r line; do [[ -n "${line}" ]] && REGISTRY+=("${line}"); done <<< "${reg_out}"

# Skill registry: "skill_name|plugin_group|relative_source_path|default_included"
# CLI shim registry: "bin_name|plugin_group|relative_source_path"
SKILL_CATALOG=()
BIN_CATALOG=()
for reg_entry in "${REGISTRY[@]}"; do
  IFS='|' read -r reg_name reg_src <<< "${reg_entry}"
  for f in "${REPO_DIR}/${reg_src}"/skills/*/SKILL.md; do
    [[ -f "${f}" ]] || continue
    SKILL_CATALOG+=("$(basename "$(dirname "${f}")")|${reg_name}|$(dirname "${f#"${REPO_DIR}/"}")|yes")
  done
  for f in "${REPO_DIR}/${reg_src}"/bin/* "${REPO_DIR}/${reg_src}"/scripts/bin/*; do
    [[ -f "${f}" && -x "${f}" ]] || continue
    BIN_CATALOG+=("$(basename "${f}")|${reg_name}|${f#"${REPO_DIR}/"}")
  done
done

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

if [[ "${BIN_EXPLICIT}" -eq 1 ]]; then
  BIN_DEST="$(resolve_path_abs "${BIN_DEST}")"
fi

# Move dst into its own unique backup dir; fails if any step fails.
backup_existing() {
  local dst="$1" name="$2" root="${HOME}/.cache/ai-plugins-backups" backup
  mkdir -p "${root}" && backup="$(mktemp -u "${root}/${name}.bak.XXXXXX")" && mv "${dst}" "${backup}" \
    || { echo "cannot back up ${dst}" >&2; return 1; }
  echo "backed up existing ${dst} -> ${backup}"
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
      rm "${dst}" || return 1
    elif [[ -e "${dst}" ]]; then
      echo -n "${label}: "
      backup_existing "${dst}" "${name}" || return 1
    fi
    ln -s "${src}" "${dst}" || return 1
    echo "${label}: linked ${dst} -> ${src}"
  else
    if [[ -L "${dst}" ]]; then
      rm "${dst}" || return 1
    elif [[ -e "${dst}" ]]; then
      echo -n "${label}: "
      backup_existing "${dst}" "${name}" || return 1
    fi
    cp -R "${src}" "${dst}" || return 1
    find "${dst}" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    echo "${label}: copied ${src} -> ${dst}"
  fi
}

# Retarget links that still point into the old claude/ or antigravity/ layout to plugins/.
# Uses raw readlink (dangling links must resolve); links to anything else are left alone.
repair_legacy_links() {
  local dir="$1" l raw new
  [[ -d "${dir}" ]] || return 0
  for l in "${dir}"/*; do
    [[ -L "${l}" ]] || continue
    raw="$(readlink "${l}")"
    case "${raw}" in "${REPO_DIR}/claude/"*|"${REPO_DIR}/antigravity/"*) ;; *) continue ;; esac
    new="${REPO_DIR}/plugins/${raw#"${REPO_DIR}"/*/}"
    if [[ ! -e "${new}" ]]; then
      echo "warning: cannot repair ${l} -> ${raw}: ${new} does not exist" >&2
    elif rm "${l}" && ln -s "${new}" "${l}"; then
      echo "repaired ${l} -> ${new}"
    else
      echo "cannot repair ${l}" >&2
      return 1
    fi
  done
}

# Warn only (never write) about leftovers of the removed egm-runbook plugin.
warn_stale_claude_config() {
  local cfg="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}"
  if grep -q 'egm-runbook' <(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("statusLine",{}).get("command",""))' "${cfg}/settings.json" 2>/dev/null); then
    echo "warning: ${cfg}/settings.json statusLine still points at egm-runbook; edit or remove it (left unchanged)." >&2
  fi
  if grep -qs 'egm-runbook@ai-plugins' "${cfg}/settings.json" "${cfg}/plugins/installed_plugins.json"; then
    echo "warning: egm-runbook@ai-plugins is still installed/enabled; run: claude plugin uninstall egm-runbook@ai-plugins" >&2
  fi
}

status_antigravity() {
  echo "Antigravity plugins (${AG_DEST}):"
  for reg_entry in "${REGISTRY[@]}"; do
    IFS='|' read -r name reg_src <<< "${reg_entry}"
    src="${REPO_DIR}/${reg_src}"
    [[ -f "${src}/plugin.json" ]] || continue
    matches_filter "${name}" || continue
    dst="${AG_DEST}/${name}"
    if [[ -L "${dst}" ]]; then
      target="$(readlink -f "${dst}" 2>/dev/null || readlink "${dst}" 2>/dev/null || true)"
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
  for reg_entry in "${REGISTRY[@]}"; do
    IFS='|' read -r name reg_src <<< "${reg_entry}"
    src="${REPO_DIR}/${reg_src}"
    [[ -d "${src}" ]] || continue
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
      target="$(readlink -f "${dst}" 2>/dev/null || readlink "${dst}" 2>/dev/null || true)"
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

status_bin() {
  echo "CLI binaries (${BIN_DEST}):"
  local entry name group rel src dst target
  for entry in "${BIN_CATALOG[@]}"; do
    IFS='|' read -r name group rel <<< "${entry}"
    matches_filter "${name}" "${group}" || continue
    src="${REPO_DIR}/${rel}"
    dst="${BIN_DEST}/${name}"
    if [[ -L "${dst}" ]]; then
      target="$(readlink -f "${dst}" 2>/dev/null || readlink "${dst}" 2>/dev/null || true)"
      if [[ "${target}" == "${src}" ]]; then
        echo "  [linked]   ${name} -> ${target}"
      else
        echo "  [symlink]  ${name} -> ${target} (points elsewhere)"
      fi
    elif [[ -e "${dst}" ]]; then
      echo "  [file]     ${name} (standalone file)"
    else
      echo "  [missing]  ${name}"
    fi
  done
}

TOTAL_INSTALLED=0

install_bin() {
  local installed=0
  repair_legacy_links "${BIN_DEST}" || return 1
  local entry name group rel src dst
  for entry in "${BIN_CATALOG[@]}"; do
    IFS='|' read -r name group rel <<< "${entry}"
    matches_filter "${name}" "${group}" || continue
    src="${REPO_DIR}/${rel}"
    if [[ ! -x "${src}" ]]; then
      echo "Bin: source not executable: ${src}" >&2
      return 1
    fi
    mkdir -p "${BIN_DEST}" || return 1
    dst="${BIN_DEST}/${name}"
    if [[ -L "${dst}" && "$(readlink -f "${dst}" 2>/dev/null || true)" == "${src}" ]]; then
      echo "Bin: ${name} already linked -> ${src}"
      installed=$((installed + 1))
      continue
    fi
    if [[ -L "${dst}" || -e "${dst}" ]]; then
      echo -n "Bin: "
      backup_existing "${dst}" "${name}" || return 1
    fi
    # Always symlink, even under --copy: the launcher resolves the bundled
    # engine via Path(__file__).resolve().parents[1].
    ln -s "${src}" "${dst}" || return 1
    echo "Bin: linked ${dst} -> ${src}"
    installed=$((installed + 1))
  done
  TOTAL_INSTALLED=$((TOTAL_INSTALLED + installed))
  if [[ "${installed}" -eq 0 && "${BIN_EXPLICIT}" -eq 1 ]]; then
    echo "Bin: no binaries matched --only '${ONLY_FILTER}'" >&2
    return 1
  fi
  return 0
}

uninstall_bin() {
  local entry name group rel src dst
  for entry in "${BIN_CATALOG[@]}"; do
    IFS='|' read -r name group rel <<< "${entry}"
    matches_filter "${name}" "${group}" || continue
    src="${REPO_DIR}/${rel}"
    dst="${BIN_DEST}/${name}"
    if [[ -L "${dst}" && "$(readlink -f "${dst}" 2>/dev/null || true)" == "${src}" ]]; then
      rm "${dst}"
      echo "Bin: removed symlink ${dst}"
    else
      echo "Bin: skipped ${dst} (not a symlink to this repo)"
    fi
  done
}

install_antigravity() {
  local installed=0
  repair_legacy_links "${AG_DEST}" || return 1
  for reg_entry in "${REGISTRY[@]}"; do
    IFS='|' read -r name reg_src <<< "${reg_entry}"
    src="${REPO_DIR}/${reg_src}"
    [[ -f "${src}/plugin.json" ]] || continue
    matches_filter "${name}" || continue
    mkdir -p "${AG_DEST}"
    dst="${AG_DEST}/${name}"
    link_or_copy_dir "Antigravity" "${src}" "${dst}" "${name}" || return 1
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
  for reg_entry in "${REGISTRY[@]}"; do
    IFS='|' read -r name reg_src <<< "${reg_entry}"
    src="${REPO_DIR}/${reg_src}"
    [[ -f "${src}/plugin.json" ]] || continue
    matches_filter "${name}" || continue
    dst="${AG_DEST}/${name}"
    if [[ -L "${dst}" && "$(readlink -f "${dst}" 2>/dev/null || true)" == "${src}" ]]; then
      rm "${dst}"
      echo "Antigravity: removed symlink ${dst}"
    else
      echo "Antigravity: skipped ${dst} (not a symlink to this repo)"
    fi
  done
}

install_claude() {
  local plugins=() plugin
  for reg_entry in "${REGISTRY[@]}"; do
    plugin="${reg_entry%%|*}"
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

  warn_stale_claude_config

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
  claude plugin marketplace update ai-plugins || echo "warning: marketplace update failed; continuing" >&2

  for plugin in "${plugins[@]}"; do
    echo "Claude Code: installing ${plugin}@ai-plugins..."
    claude plugin install "${plugin}@ai-plugins"
  done

  echo "Claude Code: done. Restart Claude Code if a session is open."
}

uninstall_claude() {
  local plugins=() plugin
  for reg_entry in "${REGISTRY[@]}"; do
    plugin="${reg_entry%%|*}"
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
}

install_skills() {
  local dest
  dest="$(resolve_path_abs "${SKILLS_DEST}")"
  repair_legacy_links "${dest}" || return 1
  mkdir -p "${dest}"
  local entry skill group rel default_inc src dst
  local installed=0
  local installed_names=()

  for entry in "${SKILL_CATALOG[@]}"; do
    IFS='|' read -r skill group rel default_inc <<< "${entry}"
    if [[ -n "${ONLY_FILTER}" ]]; then
      matches_filter "${skill}" "${group}" || continue
    elif [[ "${default_inc}" != "yes" ]]; then
      continue
    fi
    src="${REPO_DIR}/${rel}"
    dst="${dest}/${skill}"
    link_or_copy_dir "Skills" "${src}" "${dst}" "${skill}" || return 1
    installed=$((installed + 1))
    installed_names+=("${skill}")
  done

  if [[ "${installed}" -eq 0 ]]; then
    echo "Skills: no skills matched --only '${ONLY_FILTER}'" >&2
    return 1
  fi

  echo ""
  echo "Notes for non-native harnesses (see ${REPO_DIR}/docs/PORTABILITY.md):"
  echo "  - helper scripts and templates live under ${REPO_DIR}/plugins/<plugin>/; skill scripts run from ${dest}/<skill>/scripts/."
  for skill in "${installed_names[@]}"; do
    for entry in "${BIN_CATALOG[@]}"; do
      IFS='|' read -r name group rel <<< "${entry}"
      [[ "${name}" == "${skill}" ]] || continue
      echo "  - ${skill}: needs the bundled engine; run ./install.sh --bin-dir ~/.local/bin --only ${skill}."
      if grep -q mcpServers "${REPO_DIR}/${rel%%/scripts/*}/.claude-plugin/plugin.json" 2>/dev/null; then
        echo "    Then register '${skill} mcp' as a stdio MCP server in your harness."
      fi
    done
  done
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
    if [[ -L "${dst}" && "$(readlink -f "${dst}" 2>/dev/null || true)" == "${src}" ]]; then
      rm "${dst}"
      echo "Skills: removed symlink ${dst}"
    fi
  done
}

# BIN_ONLY: --bin-dir given without any explicit target => bin actions only
BIN_ONLY=0
[[ "${BIN_EXPLICIT}" -eq 1 && "${TARGET_EXPLICIT}" -eq 0 ]] && BIN_ONLY=1
# BIN_AUTO: no --bin-dir => manage shims in the default bin dir alongside any target
BIN_AUTO=0
[[ "${BIN_EXPLICIT}" -eq 0 ]] && BIN_AUTO=1
WANT_BIN=0
[[ "${BIN_ONLY}" -eq 1 || "${BIN_AUTO}" -eq 1 || "${BIN_EXPLICIT}" -eq 1 ]] && WANT_BIN=1

case "${ACTION}" in
  status)
    if [[ "${BIN_ONLY}" -eq 0 ]]; then
      if [[ "${TARGET}" == "all" || "${TARGET}" == "antigravity" ]]; then status_antigravity; fi
      if [[ "${TARGET}" == "all" || "${TARGET}" == "claude" ]]; then status_claude; fi
      if [[ "${TARGET}" == "skills" ]]; then status_skills; fi
    fi
    if [[ "${WANT_BIN}" -eq 1 ]]; then status_bin; fi
    ;;
  install)
    rc=0
    if [[ "${BIN_ONLY}" -eq 1 ]]; then
      install_bin || rc=1
      exit "${rc}"
    fi
    if [[ "${TARGET}" == "all" || "${TARGET}" == "antigravity" ]]; then install_antigravity || rc=1; fi
    if [[ "${TARGET}" == "all" || "${TARGET}" == "claude" ]]; then install_claude || rc=1; fi
    if [[ "${TARGET}" == "skills" ]]; then install_skills || rc=1; fi
    if [[ "${TARGET}" == "all" && -n "${ONLY_FILTER}" && "${TOTAL_INSTALLED}" -eq 0 ]]; then
      echo "No Antigravity or Claude Code plugins matched --only '${ONLY_FILTER}'" >&2
      rc=1
    fi
    # No bin writes when the explicit target failed (e.g. matched nothing).
    if [[ "${rc}" -eq 0 ]]; then install_bin || rc=1; fi
    exit "${rc}"
    ;;
  uninstall)
    if [[ "${BIN_ONLY}" -eq 0 ]]; then
      if [[ "${TARGET}" == "all" || "${TARGET}" == "antigravity" ]]; then uninstall_antigravity; fi
      if [[ "${TARGET}" == "all" || "${TARGET}" == "claude" ]]; then uninstall_claude; fi
      if [[ "${TARGET}" == "skills" ]]; then uninstall_skills; fi
    fi
    if [[ "${TARGET}" == "all" || "${BIN_EXPLICIT}" -eq 1 ]]; then uninstall_bin; fi
    ;;
esac
