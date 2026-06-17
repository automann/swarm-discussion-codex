#!/bin/bash
# Reject a factor candidate and record the reason.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ -f "$SCRIPT_DIR/lib/js-runtime.sh" ]]; then
  # shellcheck source=/dev/null
  . "$SCRIPT_DIR/lib/js-runtime.sh"
fi

NAME=""
REASON=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="${2:-}"; shift 2 ;;
    --reason) REASON="${2:-}"; shift 2 ;;
    --help)
      echo "Usage: bash scripts/factor-lab-reject.sh --name <slug> --reason <text>"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$NAME" || -z "$REASON" ]]; then
  echo "--name and --reason are required" >&2
  exit 1
fi

SLUG="$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
REGISTRY="$REPO_ROOT/tasks/factors/registry.json"
CANDIDATE_DIR="$REPO_ROOT/.claude/.factor-cache/candidates/$SLUG"

rh_run_js_source "$REGISTRY" "$SLUG" "$REASON" <<'NODE_EOF'
const fs = require("fs");
const [,, registryPath, slug, reason] = process.argv;
const registry = JSON.parse(fs.readFileSync(registryPath, "utf8"));

registry.candidates ??= [];
registry.promoted ??= [];
registry.rejected ??= [];

const idx = registry.candidates.findIndex((entry) => entry.slug === slug);
if (idx === -1) {
  console.error(`Candidate not found in registry: ${slug}`);
  process.exit(1);
}

registry.candidates.splice(idx, 1);
registry.rejected.push({
  slug,
  reason,
  rejected_at: new Date().toISOString()
});

fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2) + "\n");
NODE_EOF

rm -rf "$CANDIDATE_DIR"

echo "[FactorFactory] Rejected factor ${SLUG}"
