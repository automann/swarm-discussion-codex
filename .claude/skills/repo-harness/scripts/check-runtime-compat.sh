#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
paths=()
issues=0
node_eval_pattern="node -""e"
bun_eval_pattern="bun -""e"
runtime_eval_pattern='"$runtime" -'"e"

usage() {
  cat <<'USAGE_EOF'
Usage: scripts/check-runtime-compat.sh [--repo <path>] [--path <path>]...

Checks executable repo-harness runtime surfaces for Bun/Node-incompatible shell
JavaScript invocation patterns.
USAGE_EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      ROOT="$(cd "${2:-}" && pwd)"
      shift 2
      ;;
    --path)
      paths+=("${2:-}")
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "check-runtime-compat: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "${#paths[@]}" -eq 0 ]]; then
  paths=(
    "scripts"
    "assets/templates/helpers"
    "assets/hooks"
    ".ai/hooks"
    "src/cli/repo-adoption/reclaim-runtime.ts"
  )
fi

report() {
  local file="$1"
  local line_no="$2"
  local rule="$3"
  local reason="$4"

  printf '[runtime-compat] %s:%s: %s: %s\n' "$file" "$line_no" "$rule" "$reason"
  issues=$((issues + 1))
}

is_hook_eval_allowlisted() {
  local rel="$1"

  case "$rel" in
    assets/hooks/hook-input.sh|.ai/hooks/hook-input.sh|\
    assets/hooks/post-bash.sh|.ai/hooks/post-bash.sh|\
    assets/hooks/subagent-return-channel-guard.sh|.ai/hooks/subagent-return-channel-guard.sh|\
    assets/hooks/prompt-guard.sh|.ai/hooks/prompt-guard.sh|\
    assets/hooks/security-sentinel.sh|.ai/hooks/security-sentinel.sh|\
    assets/hooks/session-start-context.sh|.ai/hooks/session-start-context.sh)
      return 0
      ;;
  esac

  return 1
}

scan_file() {
  local file="$1"
  local rel="$2"
  local line_no=0
  local line

  case "$rel" in
    scripts/check-runtime-compat.sh)
      return 0
      ;;
  esac

  while IFS= read -r line || [[ -n "$line" ]]; do
    line_no=$((line_no + 1))

    if [[ "$line" =~ (^|[[:space:]])(node|bun)[[:space:]]+-[[:space:]].*\<\< ]]; then
      report "$rel" "$line_no" "rh-js-stdin-node" "do not run JavaScript through runtime stdin; use scripts/lib/js-runtime.sh"
    fi

    if { [[ "$line" =~ (^|[[:space:]])\"?\$[A-Za-z_][A-Za-z0-9_]*\"?[[:space:]]+-[[:space:]].*\<\< ]] || \
         [[ "$line" =~ (^|[[:space:]])\"?\$runtime\"?[[:space:]]+\<\< ]]; } && \
       [[ "$line" != *"PY_EOF"* ]]; then
      report "$rel" "$line_no" "rh-js-stdin-runtime" "do not run JavaScript through dynamic runtime stdin; use rh_run_js_source"
    fi

    if [[ "$line" == *'["repo-harness", "run"'* ]] || \
       [[ "$line" == *"['repo-harness', 'run'"* ]] || \
       [[ "$line" == *"exec repo-harness run"* ]] || \
       [[ "$line" == *"command -v repo-harness"* ]]; then
      report "$rel" "$line_no" "rh-stale-wrapper-fallback" "generated executable wrappers must dispatch through local-repo-harness"
    fi

    if [[ "$line" == *"$node_eval_pattern"* ]] || [[ "$line" == *"$bun_eval_pattern"* ]] || [[ "$line" == *"$runtime_eval_pattern"* ]]; then
      if is_hook_eval_allowlisted "$rel"; then
        if grep -q 'process\.argv' "$file"; then
          report "$rel" "$line_no" "rh-eval-argv" "allowlisted hook evals must read environment variables, not process.argv"
        fi
      else
        report "$rel" "$line_no" "rh-eval-argv" "unreviewed shell eval can diverge between Bun and Node; use rh_run_js_source or add a narrow allowlist"
      fi
    fi
  done < "$file"
}

collect_files() {
  local input="$1"
  local path="$ROOT/$input"

  if [[ -f "$path" ]]; then
    printf '%s\n' "$path"
  elif [[ -d "$path" ]]; then
    find "$path" -type f \( -name '*.sh' -o -name '*.ts' \) \
      -not -path '*/node_modules/*' \
      -not -path '*/.git/*' \
      | sort
  fi
}

while IFS= read -r file; do
  [[ -n "$file" ]] || continue
  rel="${file#$ROOT/}"
  scan_file "$file" "$rel"
done < <(
  for input in "${paths[@]}"; do
    collect_files "$input"
  done | sort -u
)

if [[ "$issues" -gt 0 ]]; then
  exit 1
fi

echo "[runtime-compat] OK"
