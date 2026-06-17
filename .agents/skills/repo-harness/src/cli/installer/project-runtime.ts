import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';
import type { WriteResult } from './types';

export const PROJECT_HOOK_BIN_REL = '.ai/harness/bin/local-repo-harness-hook';
export const PROJECT_RUNTIME_ROOT_REL = '.ai/harness/runtime/local-repo-harness';
export const PROJECT_RUNTIME_VERSION_REL = `${PROJECT_RUNTIME_ROOT_REL}/.version`;

const PACKAGE_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const RUNTIME_SOURCE_FILES = [
  'src/cli/hook-entry.ts',
  'src/cli/hook/runtime.ts',
  'src/cli/hook/route-registry.ts',
  'src/cli/hook/state-snapshot.ts',
  'src/cli/hook/prompt-guard-decision.ts',
  'src/cli/hook/prompt-intents.ts',
  'src/cli/commands/prompt-guard-decision.ts',
] as const;

type FileResult = WriteResult['files'][number];

function readPackageVersion(): string {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(PACKAGE_ROOT, 'package.json'), 'utf-8')) as {
      version?: unknown;
    };
    return typeof pkg.version === 'string' ? pkg.version : 'unknown';
  } catch {
    return 'unknown';
  }
}

function ensureExecutable(filePath: string): void {
  try {
    fs.chmodSync(filePath, 0o755);
  } catch {
    // Best effort; write/copy failures are surfaced by the caller.
  }
}

function writeFileIfChanged(filePath: string, content: string, mode?: number): FileResult {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const created = !fs.existsSync(filePath);
  if (!created && fs.readFileSync(filePath, 'utf-8') === content) {
    if (mode !== undefined) fs.chmodSync(filePath, mode);
    return { path: filePath, action: 'unchanged' };
  }
  fs.writeFileSync(filePath, content, { mode });
  return { path: filePath, action: created ? 'created' : 'updated' };
}

function copyFileIfChanged(src: string, dest: string): FileResult {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const created = !fs.existsSync(dest);
  const srcContent = fs.readFileSync(src);
  if (!created && fs.readFileSync(dest).equals(srcContent)) {
    return { path: dest, action: 'unchanged' };
  }
  fs.writeFileSync(dest, srcContent);
  return { path: dest, action: created ? 'created' : 'updated' };
}

function listFiles(root: string): string[] {
  if (!fs.existsSync(root)) return [];
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(fullPath);
      } else if (entry.isFile()) {
        out.push(path.relative(root, fullPath));
      }
    }
  };
  walk(root);
  return out.sort();
}

function syncDirectory(srcRoot: string, destRoot: string): FileResult {
  const existed = fs.existsSync(destRoot);
  fs.mkdirSync(destRoot, { recursive: true });
  let changed = false;
  const expected = new Set<string>();

  for (const rel of listFiles(srcRoot)) {
    expected.add(rel);
    const result = copyFileIfChanged(path.join(srcRoot, rel), path.join(destRoot, rel));
    if (result.action !== 'unchanged') changed = true;
    if (rel.endsWith('.sh')) ensureExecutable(path.join(destRoot, rel));
  }

  for (const rel of listFiles(destRoot)) {
    if (!expected.has(rel)) {
      fs.rmSync(path.join(destRoot, rel), { force: true });
      changed = true;
    }
  }

  return { path: destRoot, action: existed ? (changed ? 'updated' : 'unchanged') : 'created' };
}

function renderProjectHookWrapper(): string {
  return `#!/usr/bin/env bash
set -euo pipefail

event="\${1:-}"
route=""
args=("$@")
for ((i = 0; i < \${#args[@]}; i++)); do
  if [[ "\${args[$i]}" == "--route" ]]; then
    next=$((i + 1))
    route="\${args[$next]:-}"
  fi
done

script_path="\${BASH_SOURCE[0]}"
script_dir="$(cd "\${script_path%/*}" && pwd -P)"
runtime_root="$(cd "$script_dir/../runtime/local-repo-harness" 2>/dev/null && pwd -P || true)"
hook_entry="$runtime_root/src/cli/hook-entry.ts"

find_bun() {
  if command -v bun >/dev/null 2>&1; then
    command -v bun
    return 0
  fi
  if [[ -x "\${HOME:-}/.bun/bin/bun" ]]; then
    printf '%s\\n' "\${HOME}/.bun/bin/bun"
    return 0
  fi
  return 1
}

runtime_unavailable() {
  local reason="$1"
  if [[ "$event" == "SessionStart" ]]; then
    printf '[local-repo-harness] project hook runtime unavailable: %s\\n' "$reason" >&2
    return 0
  fi
  if [[ "$event" == "PreToolUse" && "$route" == "edit" ]]; then
    printf '[local-repo-harness] required project hook runtime unavailable: %s\\n' "$reason" >&2
    return 2
  fi
  return 0
}

if [[ -z "$runtime_root" || ! -f "$hook_entry" ]]; then
  runtime_unavailable "missing $hook_entry"
  exit $?
fi

bun_bin="$(find_bun || true)"
if [[ -z "$bun_bin" ]]; then
  runtime_unavailable "Bun is required; install Bun or reinstall with --runtime global-path"
  exit $?
fi

export REPO_HARNESS_HOOK_CLI="$hook_entry"
export REPO_HARNESS_PROJECT_RUNTIME_ROOT="$runtime_root"
exec "$bun_bin" "$hook_entry" "$@"
`;
}

export function installProjectRuntime(cwd: string): WriteResult {
  const repoRoot = path.resolve(cwd);
  const runtimeRoot = path.join(repoRoot, PROJECT_RUNTIME_ROOT_REL);
  const files: WriteResult['files'] = [];

  files.push(writeFileIfChanged(path.join(repoRoot, PROJECT_HOOK_BIN_REL), renderProjectHookWrapper(), 0o755));

  for (const rel of RUNTIME_SOURCE_FILES) {
    files.push(copyFileIfChanged(path.join(PACKAGE_ROOT, rel), path.join(runtimeRoot, rel)));
  }

  files.push(syncDirectory(path.join(PACKAGE_ROOT, 'assets/hooks'), path.join(runtimeRoot, 'assets/hooks')));
  files.push(writeFileIfChanged(path.join(repoRoot, PROJECT_RUNTIME_VERSION_REL), `${readPackageVersion()}\n`));

  return {
    files,
    notes: ['Project hook runtime installed under .ai/harness/bin and .ai/harness/runtime.'],
  };
}
