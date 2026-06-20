#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MARKETPLACE_NAME="swarm-discussion-codex-root-smoke"
PLUGIN_NAME="swarm-discussion"
PLUGIN_VERSION="0.1.0"
SELF_TEST_DENYLIST=0

for arg in "$@"; do
  case "$arg" in
    --self-test-denylist)
      SELF_TEST_DENYLIST=1
      ;;
    *)
      echo "unknown argument: $arg" >&2
      exit 64
      ;;
  esac
done

require_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "missing required command: $name" >&2
    exit 1
  fi
}

require_command git
require_command python3

if [[ "$SELF_TEST_DENYLIST" -eq 0 ]]; then
  require_command codex
fi

TMP_ROOT="$(mktemp -d /tmp/codex-root-plugin-install.XXXXXX)"
MARKETPLACE_ROOT="$TMP_ROOT/marketplace"
PUBLIC_ROOT="$MARKETPLACE_ROOT/swarm-discussion-codex-root"
export CODEX_HOME="$TMP_ROOT/codex-home"
mkdir -p "$CODEX_HOME" "$PUBLIC_ROOT" "$MARKETPLACE_ROOT/.agents/plugins"

cleanup() {
  set +e
  if [[ "$SELF_TEST_DENYLIST" -eq 0 && -n "${CODEX_HOME:-}" && -d "${CODEX_HOME:-}" ]]; then
    CODEX_HOME="$CODEX_HOME" codex plugin remove "$PLUGIN_NAME" --marketplace "$MARKETPLACE_NAME" >/dev/null 2>&1
    CODEX_HOME="$CODEX_HOME" codex plugin marketplace remove "$MARKETPLACE_NAME" >/dev/null 2>&1
  fi
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

python3 - "$ROOT" "$PUBLIC_ROOT" "$SELF_TEST_DENYLIST" <<'PY'
import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
public_root = Path(sys.argv[2]).resolve()
self_test = sys.argv[3] == "1"

required_paths = [
    ".codex-plugin/plugin.json",
    "agents/swarm-coordinator.toml",
    "agents/swarm-expert.toml",
    "skills/swarm-discussion/SKILL.md",
    "bin/swarm_runtime_wrapper.py",
    "vendor/swarm-runtime/runtime/swarm_rt.py",
    "vendor/swarm-runtime/vendor-manifest.json",
]

forbidden_prefixes = [
    ".agents/",
    "plugins/",
    "conformance/",
    "smoke/discussions/",
]

forbidden_exact = {
    "scripts/check-codex-marketplace-install.sh",
    "docs/researches/codex-coordinator-thread-archive-policy.md",
    "docs/researches/codex-installed-agent-namespacing.md",
    "docs/researches/codex-plugin-install-layout.md",
}


def forbidden_reason(path: str):
    if path in forbidden_exact:
        return "historical file"
    for prefix in forbidden_prefixes:
        if path.startswith(prefix):
            return f"forbidden prefix {prefix}"
    return None


if self_test:
    probe = ".agents/plugins/marketplace.json"
    if forbidden_reason(probe):
        print(f"denylist_self_test_ok forbidden_path={probe}", file=sys.stderr)
        raise SystemExit(42)
    print("denylist_self_test_failed: legacy marketplace path was allowed", file=sys.stderr)
    raise SystemExit(0)

tracked = subprocess.check_output(
    ["git", "-C", str(root), "ls-files"],
    text=True,
).splitlines()
tracked_set = set(tracked)

missing = [path for path in required_paths if path not in tracked_set]
violations = [(path, forbidden_reason(path)) for path in tracked if forbidden_reason(path)]
violations = [(path, reason) for path, reason in violations if reason]

if missing or violations:
    if missing:
        print("missing required tracked public paths:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
    if violations:
        print("forbidden tracked public paths:", file=sys.stderr)
        for path, reason in violations:
            print(f"  - {path} ({reason})", file=sys.stderr)
    raise SystemExit(1)

for rel in tracked:
    src = root / rel
    dst = public_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_symlink():
        os.symlink(os.readlink(src), dst)
    elif src.is_file():
        shutil.copy2(src, dst)
    else:
        raise SystemExit(f"tracked path is not a regular file or symlink: {rel}")

print(f"public_snapshot_ok files={len(tracked)} root={public_root}")
PY

python3 - "$MARKETPLACE_ROOT/.agents/plugins/marketplace.json" "$MARKETPLACE_NAME" "$PLUGIN_NAME" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
marketplace_name = sys.argv[2]
plugin_name = sys.argv[3]

payload = {
    "name": marketplace_name,
    "plugins": [
        {
            "name": plugin_name,
            "source": {
                "source": "local",
                "path": "./swarm-discussion-codex-root",
            },
            "policy": {
                "installation": "AVAILABLE",
                "authentication": "ON_INSTALL",
            },
            "category": "Developer Tools",
            "interface": {
                "displayName": "Swarm Discussion",
            },
        }
    ],
}
manifest_path.write_text(json.dumps(payload, indent=2) + "\n")
print(f"marketplace_manifest={manifest_path}")
PY

echo "codex_version=$(codex --version)"
echo "CODEX_HOME=$CODEX_HOME"

CODEX_HOME="$CODEX_HOME" codex plugin marketplace add "$MARKETPLACE_ROOT"
CODEX_HOME="$CODEX_HOME" codex plugin marketplace list

AVAILABLE_JSON="$TMP_ROOT/available.json"
CODEX_HOME="$CODEX_HOME" codex plugin list --available --json > "$AVAILABLE_JSON"
python3 - "$AVAILABLE_JSON" "$PUBLIC_ROOT" "$MARKETPLACE_NAME" "$PLUGIN_NAME" "$PLUGIN_VERSION" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
expected_source = Path(sys.argv[2]).resolve()
marketplace_name = sys.argv[3]
plugin_name = sys.argv[4]
plugin_version = sys.argv[5]
plugin_id = f"{plugin_name}@{marketplace_name}"

available = payload.get("available")
if not isinstance(available, list):
    raise SystemExit("available plugin list must be an array")
matches = [item for item in available if item.get("pluginId") == plugin_id]
if len(matches) != 1:
    raise SystemExit(f"expected one available {plugin_id} plugin, found {len(matches)}")
plugin = matches[0]
checks = {
    "name": plugin_name,
    "marketplaceName": marketplace_name,
    "version": plugin_version,
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
python3 - "$INSTALLED_JSON" "$MARKETPLACE_NAME" "$PLUGIN_NAME" "$PLUGIN_VERSION" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
marketplace_name = sys.argv[2]
plugin_name = sys.argv[3]
plugin_version = sys.argv[4]
plugin_id = f"{plugin_name}@{marketplace_name}"

installed = payload.get("installed")
if not isinstance(installed, list):
    raise SystemExit("installed plugin list must be an array")
matches = [item for item in installed if item.get("pluginId") == plugin_id]
if len(matches) != 1:
    raise SystemExit(f"expected one installed {plugin_id} plugin, found {len(matches)}")
plugin = matches[0]
checks = {
    "name": plugin_name,
    "marketplaceName": marketplace_name,
    "version": plugin_version,
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

for rel in \
  ".agents" \
  "plugins" \
  "conformance" \
  "smoke/discussions" \
  "scripts/check-codex-marketplace-install.sh" \
  "docs/researches/codex-coordinator-thread-archive-policy.md" \
  "docs/researches/codex-installed-agent-namespacing.md" \
  "docs/researches/codex-plugin-install-layout.md"
do
  if [[ -e "$PLUGIN_ROOT/$rel" ]]; then
    echo "installed plugin contains forbidden path: $rel" >&2
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

echo "root plugin install smoke passed"
