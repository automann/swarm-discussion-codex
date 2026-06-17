#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
  cd "$REPO_ROOT"
elif [[ "$SCRIPT_DIR" == */.ai/harness/scripts ]]; then
  cd "$SCRIPT_DIR/../../.."
else
  cd "$SCRIPT_DIR/.."
fi

if [[ -f ".ai/hooks/lib/workflow-state.sh" ]]; then
  # shellcheck source=/dev/null
  . ".ai/hooks/lib/workflow-state.sh"
  workflow_write_handoff "${1:-manual}"
  echo "Updated $(workflow_handoff_file)"
  if [[ "${REPO_HARNESS_SKIP_RESUME_REFRESH:-0}" != "1" && -f "scripts/codex-handoff-resume.sh" ]]; then
    bash scripts/codex-handoff-resume.sh --cwd "$(pwd -P)" --reason "${1:-manual}" >/dev/null
  fi
  exit 0
fi

mkdir -p .ai/harness/handoff
cat > .ai/harness/handoff/current.md <<EOF_HANDOFF
# Harness Handoff

> **Generated**: $(date '+%Y-%m-%d %H:%M:%S')
> **Reason**: ${1:-manual}
EOF_HANDOFF
echo "Updated .ai/harness/handoff/current.md"
if [[ "${REPO_HARNESS_SKIP_RESUME_REFRESH:-0}" != "1" && -f "scripts/codex-handoff-resume.sh" ]]; then
  bash scripts/codex-handoff-resume.sh --cwd "$(pwd -P)" --reason "${1:-manual}" >/dev/null
fi
