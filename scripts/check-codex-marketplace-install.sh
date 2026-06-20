#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MARKETPLACE_NAME="swarm-discussion-codex"
PLUGIN_NAME="swarm-discussion"
PLUGIN_VERSION="0.1.0"

require_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "missing required command: $name" >&2
    exit 1
  fi
}

require_command codex
require_command python3

TMP_ROOT="$(mktemp -d /tmp/codex-marketplace-install.XXXXXX)"
export CODEX_HOME="$TMP_ROOT/codex-home"
mkdir -p "$CODEX_HOME"

cleanup() {
  set +e
  if [[ -n "${CODEX_HOME:-}" && -d "${CODEX_HOME:-}" ]]; then
    CODEX_HOME="$CODEX_HOME" codex plugin remove "$PLUGIN_NAME" --marketplace "$MARKETPLACE_NAME" >/dev/null 2>&1
    CODEX_HOME="$CODEX_HOME" codex plugin marketplace remove "$MARKETPLACE_NAME" >/dev/null 2>&1
  fi
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

echo "codex_version=$(codex --version)"
echo "CODEX_HOME=$CODEX_HOME"

CODEX_HOME="$CODEX_HOME" codex plugin marketplace add "$ROOT"
CODEX_HOME="$CODEX_HOME" codex plugin marketplace list

AVAILABLE_JSON="$TMP_ROOT/available.json"
CODEX_HOME="$CODEX_HOME" codex plugin list --available --json > "$AVAILABLE_JSON"
python3 - "$AVAILABLE_JSON" "$ROOT/plugins/swarm-discussion" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
expected_source = Path(sys.argv[2]).resolve()
available = payload.get("available")
if not isinstance(available, list):
    raise SystemExit("available plugin list must be an array")
matches = [
    item
    for item in available
    if item.get("pluginId") == "swarm-discussion@swarm-discussion-codex"
]
if len(matches) != 1:
    raise SystemExit(f"expected one available swarm-discussion plugin, found {len(matches)}")
plugin = matches[0]
checks = {
    "name": "swarm-discussion",
    "marketplaceName": "swarm-discussion-codex",
    "version": "0.1.0",
    "installPolicy": "AVAILABLE",
    "authPolicy": "ON_INSTALL",
}
for key, expected in checks.items():
    actual = plugin.get(key)
    if actual != expected:
        raise SystemExit(f"available plugin {key} expected {expected!r}, got {actual!r}")
if plugin.get("installed") is not False or plugin.get("enabled") is not False:
    raise SystemExit("available plugin should not be installed or enabled before add")
source = plugin.get("source")
if not isinstance(source, dict) or source.get("source") != "local":
    raise SystemExit("available plugin source must be local")
source_path = source.get("path")
if not isinstance(source_path, str) or Path(source_path).resolve() != expected_source:
    raise SystemExit(f"available plugin source path mismatch: {source_path!r}")
print("available_plugin_ok")
PY

CODEX_HOME="$CODEX_HOME" codex plugin add "$PLUGIN_NAME" --marketplace "$MARKETPLACE_NAME"

INSTALLED_JSON="$TMP_ROOT/installed.json"
CODEX_HOME="$CODEX_HOME" codex plugin list --json > "$INSTALLED_JSON"
python3 - "$INSTALLED_JSON" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
installed = payload.get("installed")
if not isinstance(installed, list):
    raise SystemExit("installed plugin list must be an array")
matches = [
    item
    for item in installed
    if item.get("pluginId") == "swarm-discussion@swarm-discussion-codex"
]
if len(matches) != 1:
    raise SystemExit(f"expected one installed swarm-discussion plugin, found {len(matches)}")
plugin = matches[0]
checks = {
    "name": "swarm-discussion",
    "marketplaceName": "swarm-discussion-codex",
    "version": "0.1.0",
    "installPolicy": "AVAILABLE",
    "authPolicy": "ON_INSTALL",
}
for key, expected in checks.items():
    actual = plugin.get(key)
    if actual != expected:
        raise SystemExit(f"installed plugin {key} expected {expected!r}, got {actual!r}")
if plugin.get("installed") is not True or plugin.get("enabled") is not True:
    raise SystemExit("installed plugin should be installed and enabled after add")
print("installed_plugin_ok")
PY

PLUGIN_ROOT="$CODEX_HOME/plugins/cache/$MARKETPLACE_NAME/$PLUGIN_NAME/$PLUGIN_VERSION"
if [[ ! -d "$PLUGIN_ROOT" ]]; then
  echo "installed plugin root missing: $PLUGIN_ROOT" >&2
  exit 1
fi

python3 - "$CODEX_HOME" "$PLUGIN_ROOT" <<'PY'
import sys
from pathlib import Path

home = Path(sys.argv[1]).resolve()
plugin_root = Path(sys.argv[2]).resolve()
try:
    plugin_root.relative_to(home)
except ValueError:
    raise SystemExit(f"plugin root is outside isolated CODEX_HOME: {plugin_root}")
print(f"plugin_root={plugin_root}")
PY

required_paths=(
  ".codex-plugin/plugin.json"
  "agents/swarm-coordinator.toml"
  "agents/swarm-expert.toml"
  "skills/swarm-discussion/SKILL.md"
  "bin/swarm_runtime_wrapper.py"
  "vendor/swarm-runtime/runtime/swarm_rt.py"
  "vendor/swarm-runtime/vendor-manifest.json"
)

for rel in "${required_paths[@]}"; do
  if [[ ! -e "$PLUGIN_ROOT/$rel" ]]; then
    echo "installed plugin missing required path: $rel" >&2
    exit 1
  fi
  echo "present $rel"
done

if [[ ! -x "$PLUGIN_ROOT/bin/swarm_runtime_wrapper.py" ]]; then
  echo "installed wrapper is not executable" >&2
  exit 1
fi

excluded_paths=(
  "smoke"
  "conformance"
  "docs"
  "tasks"
  "plans"
  ".ai"
  ".claude"
  ".codex"
)

for rel in "${excluded_paths[@]}"; do
  if [[ -e "$PLUGIN_ROOT/$rel" ]]; then
    echo "installed plugin contains excluded path: $rel" >&2
    exit 1
  fi
  echo "absent $rel"
done

DOCTOR_JSON="$TMP_ROOT/doctor.json"
python3 "$PLUGIN_ROOT/bin/swarm_runtime_wrapper.py" doctor --smoke-fixture > "$DOCTOR_JSON"
python3 - "$DOCTOR_JSON" "$CODEX_HOME" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
code_home = Path(sys.argv[2]).resolve()
if payload.get("ok") is not True:
    raise SystemExit("wrapper doctor returned ok=false")
if payload.get("vendorManifest", {}).get("ok") is not True:
    raise SystemExit("wrapper doctor vendorManifest.ok is not true")
if payload.get("fixtureSmoke", {}).get("ok") is not True:
    raise SystemExit("wrapper doctor fixtureSmoke.ok is not true")
plugin_root = payload.get("wrapper", {}).get("pluginRoot")
if not isinstance(plugin_root, str):
    raise SystemExit("wrapper doctor did not report wrapper.pluginRoot")
try:
    Path(plugin_root).resolve().relative_to(code_home)
except ValueError:
    raise SystemExit(f"wrapper doctor pluginRoot is outside isolated CODEX_HOME: {plugin_root}")
print(
    "doctor_ok vendorManifestOk=True fixtureSmokeOk=True "
    f"pluginRoot={Path(plugin_root).resolve()}"
)
PY

echo "local marketplace install smoke passed"
