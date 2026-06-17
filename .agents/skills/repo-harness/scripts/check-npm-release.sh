#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=/dev/null
. "$ROOT/scripts/lib/js-runtime.sh"
PACKAGE_NAME="$(rh_run_js_source <<'JS_EOF'
const fs = require("fs");
const pkg = JSON.parse(fs.readFileSync("package.json", "utf8"));
console.log(pkg.name);
JS_EOF
)"
PACKAGE_VERSION="$(rh_run_js_source <<'JS_EOF'
const fs = require("fs");
const pkg = JSON.parse(fs.readFileSync("package.json", "utf8"));
console.log(pkg.version);
JS_EOF
)"
NPM_RELEASE_REGISTRY="${NPM_RELEASE_REGISTRY:-https://registry.npmjs.org/}"
LOOKUP_STDERR="$(mktemp)"
trap 'rm -f "$LOOKUP_STDERR"' EXIT

echo "[release] package: ${PACKAGE_NAME}@${PACKAGE_VERSION}"
echo "[release] registry: ${NPM_RELEASE_REGISTRY}"
if npm view "${PACKAGE_NAME}@${PACKAGE_VERSION}" version --json --registry "$NPM_RELEASE_REGISTRY" >/dev/null 2>"$LOOKUP_STDERR"; then
  echo "[release] ERROR: ${PACKAGE_NAME}@${PACKAGE_VERSION} already exists on npm." >&2
  echo "[release] Bump package.json, CLI version, status version, and tests before publishing." >&2
  exit 1
fi

if ! grep -Eq 'E404|404 Not Found|No match found|not in this registry' "$LOOKUP_STDERR"; then
  echo "[release] ERROR: unable to prove ${PACKAGE_NAME}@${PACKAGE_VERSION} is unpublished." >&2
  cat "$LOOKUP_STDERR" >&2
  exit 1
fi

bun install --frozen-lockfile
BUN_TEST_TIMEOUT_MS="${BUN_TEST_TIMEOUT_MS:-60000}"
BUN_TEST_MAX_CONCURRENCY="${BUN_TEST_MAX_CONCURRENCY:-4}"
bun test --timeout "$BUN_TEST_TIMEOUT_MS" --max-concurrency "$BUN_TEST_MAX_CONCURRENCY"
bash scripts/check-deploy-sql-order.sh
bash scripts/check-architecture-sync.sh
bash scripts/check-task-sync.sh
bash scripts/check-runtime-compat.sh
if [[ -f scripts/prepare-handoff.sh ]]; then
  REPO_HARNESS_SKIP_RESUME_REFRESH=1 bash scripts/prepare-handoff.sh "release gate" >/dev/null
fi
if [[ -f scripts/codex-handoff-resume.sh ]]; then
  bash scripts/codex-handoff-resume.sh --cwd . --reason "release gate" >/dev/null
fi
bash scripts/check-task-workflow.sh --strict
bun scripts/inspect-project-state.ts --repo . --format text >/dev/null
bash scripts/migrate-project-template.sh --repo . --dry-run >/dev/null
npm pack --dry-run --json >/dev/null

echo "[release] OK: npm package gate passed."
