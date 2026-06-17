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

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

if [[ -f ".ai/hooks/lib/workflow-state.sh" ]]; then
  # shellcheck source=/dev/null
  . ".ai/hooks/lib/workflow-state.sh"
  contract_file="$(workflow_active_contract || true)"
  review_file="$(workflow_active_review || true)"
  checks_file="$(workflow_checks_file)"
else
  contract_file="$(find tasks/contracts -maxdepth 1 -name '*.contract.md' -type f 2>/dev/null | sort | head -n 1)"
  if [[ -n "$contract_file" ]]; then
    contract_slug="$(basename "$contract_file" | sed -E 's/\.contract\.md$//')"
    review_file="tasks/reviews/${contract_slug}.review.md"
  else
    review_file=""
  fi
  checks_file=".ai/harness/checks/latest.json"
fi

[[ -n "$contract_file" && -f "$contract_file" ]] || { echo "No active sprint contract found" >&2; exit 1; }

generated_at="$(date '+%Y-%m-%dT%H:%M:%S%z')"
run_stamp="$(date '+%Y%m%dT%H%M%S')"
run_id="${HOOK_RUN_ID:-${CLAUDE_RUN_ID:-${CODEX_RUN_ID:-run-${run_stamp}-$$}}}"
safe_run_id="$(printf '%s' "$run_id" | sed -E 's/[^A-Za-z0-9._-]+/-/g')"
contract_slug="$(basename "$contract_file" | sed -E 's/\.contract\.md$//')"
safe_contract_slug="$(printf '%s' "$contract_slug" | sed -E 's/[^A-Za-z0-9._-]+/-/g')"
runs_dir=".ai/harness/runs"
if declare -F workflow_runs_dir >/dev/null 2>&1; then
  runs_dir="$(workflow_runs_dir)"
fi
run_file="${runs_dir}/${safe_run_id}-${safe_contract_slug}.json"

mkdir -p "$(dirname "$checks_file")"
mkdir -p "$runs_dir"
contract_report="$(mktemp)"
checks_report="$(mktemp)"
trap 'rm -f "$contract_report" "$checks_report"' EXIT

contract_command="bash scripts/verify-contract.sh --contract $contract_file --strict --report-file <temp>"
set +e
contract_output="$(bash scripts/verify-contract.sh --contract "$contract_file" --strict --report-file "$contract_report" 2>&1)"
contract_exit=$?
set -e

if [[ -n "$contract_output" ]]; then
  printf '%s\n' "$contract_output"
fi

review_status="fail"
review_message="Sprint review recommends pass."
if [[ -z "$review_file" || ! -f "$review_file" ]]; then
  review_message="Missing sprint review file."
  echo "Missing sprint review file" >&2
elif grep -Eq '^> \*\*Recommendation\*\*:[[:space:]]*pass([[:space:]]*)$' "$review_file"; then
  review_status="pass"
else
  review_message="Sprint review does not recommend pass."
  echo "Sprint review does not recommend pass" >&2
fi

external_status="missing"
external_reviewer=""
external_source=""
external_message="External acceptance status is unavailable."
if declare -F workflow_external_acceptance_status >/dev/null 2>&1; then
  external_row="$(workflow_external_acceptance_status "$review_file")"
  IFS=$'\t' read -r external_status external_reviewer external_source external_message <<< "$external_row"
fi

status="fail"
exit_code=1
if [[ "$contract_exit" -eq 0 && "$review_status" == "pass" ]]; then
  status="pass"
  exit_code=0
fi

if command -v jq >/dev/null 2>&1 && jq -e . "$contract_report" >/dev/null 2>&1; then
  jq -n \
    --slurpfile contract_report "$contract_report" \
    --arg status "$status" \
    --arg source "verify-sprint" \
    --arg command "bash scripts/verify-sprint.sh" \
    --arg generated_at "$generated_at" \
    --arg run_id "$run_id" \
    --arg run_file "$run_file" \
    --arg contract_file "$contract_file" \
    --arg contract_status "$([[ "$contract_exit" -eq 0 ]] && printf pass || printf fail)" \
    --arg contract_command "$contract_command" \
    --argjson contract_exit "$contract_exit" \
    --arg review_file "${review_file:-}" \
    --arg review_status "$review_status" \
    --arg review_message "$review_message" \
    --arg external_status "$external_status" \
    --arg external_reviewer "$external_reviewer" \
    --arg external_source "$external_source" \
    --arg external_message "$external_message" \
    --argjson exit_code "$exit_code" \
    '{
      status: $status,
      source: $source,
      command: $command,
      exit_code: $exit_code,
      generated_at: $generated_at,
      run_id: $run_id,
      run_file: $run_file,
      lifecycle: {
        latest: ".ai/harness/checks/latest.json",
        snapshot: $run_file,
        evidence_tier: "raw-verification"
      },
      contract: {
        file: $contract_file,
        status: $contract_status,
        command: $contract_command,
        exit_code: $contract_exit,
        report: ($contract_report[0] // {})
      },
      review: {
        file: $review_file,
        status: $review_status,
        message: $review_message
      },
      external_acceptance: {
        status: $external_status,
        reviewer: $external_reviewer,
        source: $external_source,
        message: $external_message
      }
    }' > "$checks_report"
else
  cat > "$checks_report" <<EOF_CHECKS
{
  "status": "$(json_escape "$status")",
  "source": "verify-sprint",
  "command": "bash scripts/verify-sprint.sh",
  "exit_code": $exit_code,
  "generated_at": "$(json_escape "$generated_at")",
  "run_id": "$(json_escape "$run_id")",
  "run_file": "$(json_escape "$run_file")",
  "lifecycle": {
    "latest": ".ai/harness/checks/latest.json",
    "snapshot": "$(json_escape "$run_file")",
    "evidence_tier": "raw-verification"
  },
  "contract": {
    "file": "$(json_escape "$contract_file")",
    "status": "$([[ "$contract_exit" -eq 0 ]] && printf pass || printf fail)",
    "command": "$(json_escape "$contract_command")",
    "exit_code": $contract_exit
  },
  "review": {
    "file": "$(json_escape "${review_file:-}")",
    "status": "$(json_escape "$review_status")",
    "message": "$(json_escape "$review_message")"
  },
  "external_acceptance": {
    "status": "$(json_escape "$external_status")",
    "reviewer": "$(json_escape "$external_reviewer")",
    "source": "$(json_escape "$external_source")",
    "message": "$(json_escape "$external_message")"
  }
}
EOF_CHECKS
fi

cp "$checks_report" "$checks_file"
cp "$checks_report" "$run_file"

if [[ "$exit_code" -eq 0 ]]; then
  echo "Sprint verification passed"
  echo "Run snapshot: $run_file"
else
  echo "Sprint verification failed" >&2
  echo "Run snapshot: $run_file" >&2
fi

exit "$exit_code"
