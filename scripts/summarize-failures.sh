#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(basename "$SCRIPT_DIR")" == "repo-harness" ]]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
else
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
PROJECT_CLI="$REPO_ROOT/.ai/harness/bin/local-repo-harness"
SOURCE_ROOT="${REPO_HARNESS_SOURCE_ROOT:-${AGENTIC_DEV_ROOT:-${AGENTIC_DEV_SKILL_ROOT:-}}}"

if [[ -n "$SOURCE_ROOT" && -f "$SOURCE_ROOT/src/cli/index.ts" ]]; then
  if command -v bun >/dev/null 2>&1; then
    exec bun "$SOURCE_ROOT/src/cli/index.ts" run summarize-failures "$@"
  fi
fi

if [[ -x "$PROJECT_CLI" ]]; then
  exec "$PROJECT_CLI" run summarize-failures "$@"
fi

if command -v local-repo-harness >/dev/null 2>&1; then
  exec local-repo-harness run summarize-failures "$@"
fi

echo "Missing local-repo-harness CLI for helper summarize-failures" >&2
exit 1
