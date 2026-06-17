#!/bin/bash
# Delegate workflow migrations to the best available repo-harness template source.
#
# Generated projects keep installed workflow runtime state under .ai/. The
# template source lives in AGENTIC_DEV_ROOT, AGENTIC_DEV_SKILL_ROOT, or
# ~/Projects/repo-harness. Retired legacy install paths are not
# searched.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT=""
if REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
  :
elif [[ "$SCRIPT_DIR" == */.ai/harness/scripts ]]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd -P)"
else
  PARENT_DIR="$SCRIPT_DIR/.."
  REPO_ROOT="$(cd "$PARENT_DIR" && pwd -P)"
fi

resolve_repo_harness_source_root() {
  if [[ -n "${AGENTIC_DEV_ROOT:-}" ]]; then
    printf '%s\n' "$AGENTIC_DEV_ROOT"
    return 0
  fi

  if [[ -n "${AGENTIC_DEV_SKILL_ROOT:-}" ]]; then
    printf '%s\n' "$AGENTIC_DEV_SKILL_ROOT"
    return 0
  fi

  local project_roots=(
    "$REPO_ROOT/.agents/skills/repo-harness"
    "$REPO_ROOT/.claude/skills/repo-harness"
  )
  local project_root
  for project_root in "${project_roots[@]}"; do
    if [[ -f "$project_root/scripts"/migrate-project-template.sh ]]; then
      printf '%s\n' "$project_root"
      return 0
    fi
  done

  if [[ -n "${HOME:-}" ]]; then
    local roots=(
      "$HOME/Projects/repo-harness"
      "$HOME/.codex/skills/repo-harness"
      "$HOME/.claude/skills/repo-harness"
      "$HOME/.agents/skills/repo-harness"
    )

    local root
    for root in "${roots[@]}"; do
      if [[ -d "$root" ]]; then
        printf '%s\n' "$root"
        return 0
      fi
    done

    printf '%s\n' "${roots[0]}"
    return 0
  fi

  printf '%s\n' "/Users/ancienttwo/.agents/skills/repo-harness"
}

SOURCE_ROOT="$(resolve_repo_harness_source_root)"
SOURCE_SCRIPT="$SOURCE_ROOT/scripts"/migrate-project-template.sh

if [[ ! -f "$SOURCE_SCRIPT" ]]; then
  echo "[migrate] repo-harness template source migration script not found: $SOURCE_SCRIPT" >&2
  echo "[migrate] Set AGENTIC_DEV_ROOT or AGENTIC_DEV_SKILL_ROOT to the skill root." >&2
  exit 1
fi

exec bash "$SOURCE_SCRIPT" "$@"
