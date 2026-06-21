#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WRAPPER="$ROOT/bin/swarm_runtime_wrapper.py"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

assert_wrapper_json() {
  local file="$1"
  python3 - "$file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    json.load(handle)
PY
}

assert_no_traceback() {
  local file="$1"
  if grep -q "Traceback" "$file"; then
    echo "unexpected traceback in $file" >&2
    cat "$file" >&2
    exit 1
  fi
}

run_case() {
  local name="$1"
  shift
  set +e
  "$@" >"$TMPDIR/$name.out" 2>"$TMPDIR/$name.err"
  local status=$?
  set -e
  echo "$status" >"$TMPDIR/$name.status"
  assert_no_traceback "$TMPDIR/$name.out"
  assert_no_traceback "$TMPDIR/$name.err"
}

BAD_RUNTIME="$TMPDIR/bad-runtime.py"
cat >"$BAD_RUNTIME" <<'PY'
#!/usr/bin/env python3
print("not-json")
PY
chmod +x "$BAD_RUNTIME"

FAKE_NO_VALIDATION="$TMPDIR/fake-no-validation.py"
cat >"$FAKE_NO_VALIDATION" <<'PY'
#!/usr/bin/env python3
import json
import sys

commands = {
    name: {}
    for name in [
        "context-build",
        "prompt-build",
        "collect-merge",
        "transport-init",
        "transport-append-batch",
        "transport-collect",
        "append-message",
        "checkpoint",
        "finalize-round",
        "resume-plan",
        "validate-round",
        "validate-discussion",
        "trace",
        "evidence",
        "validate-host-step",
        "capability-doctor",
        "init",
        "adapter-smoke",
        "validate-loop",
    ]
}

if sys.argv[1:3] == ["runtime-contract", "--full"] or sys.argv[1:2] == ["runtime-contract"]:
    print(
        json.dumps(
            {
                "ok": True,
                "contract": {
                    "runtime": {"compatibility": "swarm-runtime-v2-alpha"},
                    "commands": commands,
                },
            }
        )
    )
else:
    print(json.dumps({"ok": True, "args": sys.argv[1:]}))
PY
chmod +x "$FAKE_NO_VALIDATION"

echo "checking bad explicit runtime"
run_case bad-explicit python3 "$WRAPPER" --runtime "$BAD_RUNTIME" doctor
python3 - "$TMPDIR/bad-explicit.out" "$TMPDIR/bad-explicit.status" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
status = int(open(sys.argv[2], encoding="utf-8").read())
assert status != 0, status
assert data["ok"] is False
assert data["errors"][0]["code"] == "runtime_override_invalid"
assert [attempt["source"] for attempt in data["attempts"]] == ["--runtime"]
assert data.get("runtime", {}).get("source") != "vendored"
PY

echo "checking bad env runtime"
run_case bad-env env SWARM_DISCUSSION_RUNTIME="$BAD_RUNTIME" python3 "$WRAPPER" doctor
python3 - "$TMPDIR/bad-env.out" "$TMPDIR/bad-env.status" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
status = int(open(sys.argv[2], encoding="utf-8").read())
assert status != 0, status
assert data["ok"] is False
assert data["errors"][0]["code"] == "runtime_env_invalid"
assert [attempt["source"] for attempt in data["attempts"]] == ["SWARM_DISCUSSION_RUNTIME"]
assert data.get("runtime", {}).get("source") != "vendored"
PY

echo "checking empty env runtime falls back to vendored"
run_case empty-env env SWARM_DISCUSSION_RUNTIME= python3 "$WRAPPER" doctor
python3 - "$TMPDIR/empty-env.out" "$TMPDIR/empty-env.status" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
status = int(open(sys.argv[2], encoding="utf-8").read())
assert status == 0, status
assert data["ok"] is True
assert data["runtime"]["source"] == "vendored"
PY

echo "checking whitespace runtime command"
run_case whitespace python3 "$WRAPPER" --runtime "   " doctor
python3 - "$TMPDIR/whitespace.out" "$TMPDIR/whitespace.status" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
status = int(open(sys.argv[2], encoding="utf-8").read())
assert status != 0, status
assert data["ok"] is False
assert data["errors"][0]["code"] == "runtime_command_empty"
assert data["attempts"] == []
PY

echo "checking whitespace env runtime command"
run_case whitespace-env env SWARM_DISCUSSION_RUNTIME="   " python3 "$WRAPPER" doctor
python3 - "$TMPDIR/whitespace-env.out" "$TMPDIR/whitespace-env.status" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
status = int(open(sys.argv[2], encoding="utf-8").read())
assert status != 0, status
assert data["ok"] is False
assert data["errors"][0]["code"] == "runtime_command_empty"
assert data["attempts"] == []
PY

echo "checking missing validation contract"
run_case no-validation python3 "$WRAPPER" --runtime "$FAKE_NO_VALIDATION" runtime-contract
python3 - "$TMPDIR/no-validation.out" "$TMPDIR/no-validation.status" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
status = int(open(sys.argv[2], encoding="utf-8").read())
assert status != 0, status
assert data["ok"] is False
assert data["errors"][0]["code"] == "runtime_override_invalid"
assert any("validation" in item for item in data["errors"][0]["contractErrors"])
PY

echo "checking planned host diagnostics"
run_case host-diagnostics env -u SWARM_DISCUSSION_RUNTIME python3 "$WRAPPER" doctor
python3 - "$TMPDIR/host-diagnostics.out" "$TMPDIR/host-diagnostics.status" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
status = int(open(sys.argv[2], encoding="utf-8").read())
assert status == 0, status
host = data["hostDiagnostics"]
for key, path in {
    "coordinatorContract": "agents/swarm-coordinator.toml",
    "threadLifecycleOwner": "skills/swarm-discussion/SKILL.md",
}.items():
    item = host[key]
    assert item["path"] == path
    assert isinstance(item["exists"], bool)
    assert item["status"] == ("present" if item["exists"] else "planned")
    assert item["sprintRow"]
artifact_paths = data["artifactPaths"]
assert artifact_paths["normalDiscussionRoot"] == ".swarm/discussions"
assert artifact_paths["normalDiscussionPattern"] == ".swarm/discussions/<id>"
assert artifact_paths["smokeDiscussionRoot"] == "smoke/discussions"
assert artifact_paths["smokeDiscussionPattern"] == "smoke/discussions/<id>"
assert artifact_paths["requiredCertificationGates"] == [
    "runtime-contract",
    "vendor-manifest",
    "adapter-smoke",
    "validate-loop",
    "validate-discussion",
]
assert artifact_paths["wrapperCreatesDiscussionDirs"] is False
nested = host["nestedSubagentTopology"]
assert nested["supported"] is None
assert nested["usedByV1"] is True
assert nested["projectionOwner"] == "parent-skill"
assert nested["projectedAgentDir"] == ".codex/agents"
assert nested["expertTemplate"] == "agents/swarm-expert.toml"
PY

echo "checking clean doctor smoke fixture"
run_case clean-smoke env -u SWARM_DISCUSSION_RUNTIME python3 "$WRAPPER" doctor --smoke-fixture
python3 - "$TMPDIR/clean-smoke.out" "$TMPDIR/clean-smoke.status" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
status = int(open(sys.argv[2], encoding="utf-8").read())
assert status == 0, status
assert data["ok"] is True
assert data["runtime"]["source"] == "vendored"
assert data["vendorManifest"]["ok"] is True
assert data["fixtureSmoke"]["ok"] is True
assert data["fixtureSmoke"]["summary"]["loopOk"] is True
PY

echo "checking vendor manifest drift"
PKG="$TMPDIR/pkg"
mkdir -p "$PKG/bin" "$PKG/vendor"
cp "$WRAPPER" "$PKG/bin/swarm_runtime_wrapper.py"
cp -R "$ROOT/vendor/swarm-runtime" "$PKG/vendor/swarm-runtime"
python3 - "$PKG/vendor/swarm-runtime/vendor-manifest.json" <<'PY'
import json
import sys

path = sys.argv[1]
data = json.load(open(path, encoding="utf-8"))
first = sorted(data["files"])[0]
data["files"][first] = "0" * 64
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2, sort_keys=True)
PY
run_case manifest-drift env -u SWARM_DISCUSSION_RUNTIME python3 "$PKG/bin/swarm_runtime_wrapper.py" doctor --smoke-fixture
python3 - "$TMPDIR/manifest-drift.out" "$TMPDIR/manifest-drift.status" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
status = int(open(sys.argv[2], encoding="utf-8").read())
assert status != 0, status
assert data["ok"] is False
manifest = data["vendorManifest"]
assert manifest["ok"] is False
assert any(error["code"] == "vendored_file_drift" for error in manifest["errors"])
PY

echo "checking vendor manifest drift blocks primitive execution"
run_case manifest-drift-primitive env -u SWARM_DISCUSSION_RUNTIME python3 "$PKG/bin/swarm_runtime_wrapper.py" init --help
python3 - "$TMPDIR/manifest-drift-primitive.out" "$TMPDIR/manifest-drift-primitive.status" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
status = int(open(sys.argv[2], encoding="utf-8").read())
assert status != 0, status
assert data["ok"] is False
assert data["errors"][0]["code"] == "vendor_manifest_invalid"
assert data["vendorManifest"]["ok"] is False
PY

echo "checking primitive pass-through"
run_case primitive-help env -u SWARM_DISCUSSION_RUNTIME python3 "$WRAPPER" init --help
python3 - "$TMPDIR/primitive-help.out" "$TMPDIR/primitive-help.status" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
status = int(open(sys.argv[2], encoding="utf-8").read())
assert status == 0, status
assert data["ok"] is True
assert data["runtime"]["args"] == ["init", "--help"]
assert "usage: swarm-rt init" in data["stdout"]
PY

echo "runtime wrapper edge-case checks passed"
