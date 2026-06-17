/**
 * Codex CLI hook-runtime target.
 *
 * Writes 8 managed adapter entries to either ~/.codex/hooks.json
 * (--location global, user-scoped) or <repo>/.codex/hooks.json
 * (--location local, project-scoped). Project hooks are loaded by Codex from
 * the trusted project .codex layer; local installs intentionally do not mutate
 * ~/.codex/config.toml.
 *
 * Tag-based managed entries (`MANAGED_TAG` from managed-entries.ts) ensure
 * uninstall removes only what install wrote, preserving any sibling
 * user-authored hook entries on the same file.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import type {
  AgentTarget,
  DetectionResult,
  InstallOptions,
  Location,
  WriteResult,
} from '../types';
import {
  atomicWriteFileSync,
  deepEqual,
  formatJson,
  readJsonOrEmpty,
} from '../shared';
import {
  buildManagedHooks,
  isManagedEntry,
  mergeHooks,
  stripManagedEntries,
  type HooksByEvent,
} from '../managed-entries';

interface HooksFile {
  hooks?: HooksByEvent;
  [key: string]: unknown;
}

function globalConfigPath(): string {
  // Prefer $HOME env so tests can isolate via temp dirs; os.homedir() is
  // cached and ignores runtime $HOME mutations in some Node/Bun versions.
  return path.join(process.env.HOME ?? os.homedir(), '.codex', 'hooks.json');
}

function globalTomlConfigPath(): string {
  return path.join(process.env.HOME ?? os.homedir(), '.codex', 'config.toml');
}

function projectConfigPath(cwd: string): string {
  return path.join(cwd, '.codex', 'hooks.json');
}

function resolveHooksPath(loc: Location, cwd: string): string {
  return loc === 'global' ? globalConfigPath() : projectConfigPath(cwd);
}

function ensureRequestUserInputToml(): WriteResult['files'][number] {
  const filePath = globalTomlConfigPath();
  fs.mkdirSync(path.dirname(filePath), { recursive: true });

  const desiredLine = 'default_mode_request_user_input = true';
  if (!fs.existsSync(filePath)) {
    atomicWriteFileSync(filePath, `${desiredLine}\n`);
    return { path: filePath, action: 'created' };
  }

  const current = fs.readFileSync(filePath, 'utf-8');
  if (/^default_mode_request_user_input\s*=\s*true\s*$/m.test(current)) {
    return { path: filePath, action: 'unchanged' };
  }

  let next: string;
  if (/^default_mode_request_user_input\s*=/m.test(current)) {
    next = current.replace(/^default_mode_request_user_input\s*=.*$/m, desiredLine);
  } else if (/^\[/m.test(current)) {
    next = current.replace(/^\[/m, `${desiredLine}\n\n[`);
  } else {
    next = `${current.replace(/\s*$/, '')}\n${desiredLine}\n`;
  }

  if (next === current) {
    return { path: filePath, action: 'unchanged' };
  }
  atomicWriteFileSync(filePath, next);
  return { path: filePath, action: 'updated' };
}

class CodexTarget implements AgentTarget {
  readonly id = 'codex' as const;
  readonly displayName = 'Codex CLI';
  readonly docsUrl = 'https://developers.openai.com/codex/config-advanced';

  supportsLocation(_loc: Location): boolean {
    return true;
  }

  detect(loc: Location, opts: InstallOptions = {}): DetectionResult {
    const filePath = resolveHooksPath(loc, opts.cwd ?? process.cwd());
    const installed = fs.existsSync(path.dirname(filePath));
    let alreadyConfigured = false;
    if (fs.existsSync(filePath)) {
      try {
        const data = readJsonOrEmpty<HooksFile>(filePath);
        for (const entries of Object.values(data.hooks ?? {})) {
          if ((entries ?? []).some(isManagedEntry)) {
            alreadyConfigured = true;
            break;
          }
        }
      } catch {
        // Invalid JSON: surface configPath but report not-configured.
      }
    }
    return { installed, alreadyConfigured, configPath: filePath };
  }

  install(loc: Location, opts: InstallOptions): WriteResult {
    const filePath = resolveHooksPath(loc, opts.cwd ?? process.cwd());
    const data = readJsonOrEmpty<HooksFile>(filePath);
    const cleaned = stripManagedEntries(data.hooks);
    const managed = buildManagedHooks('codex', {
      runtimeMode: opts.runtimeMode ?? (loc === 'local' ? 'project-vendored-bun' : 'global-path'),
    });
    const merged = mergeHooks(cleaned, managed);
    const next: HooksFile = { ...data, hooks: merged };
    const nextContent = formatJson(next);
    const files: WriteResult['files'] = [];

    const created = !fs.existsSync(filePath);
    if (!created) {
      const current = fs.readFileSync(filePath, 'utf-8');
      if (current === nextContent) {
        files.push({ path: filePath, action: 'unchanged' });
        if (loc === 'global') files.push(ensureRequestUserInputToml());
        return { files };
      }
    }
    atomicWriteFileSync(filePath, nextContent);
    files.push({ path: filePath, action: created ? 'created' : 'updated' });
    if (loc === 'global') files.push(ensureRequestUserInputToml());
    return {
      files,
      notes: loc === 'global'
        ? (created
          ? ['Restart Codex to register new hook trust hashes.']
          : ['Existing hash entries stay trusted; only new (command, key) tuples re-prompt.'])
        : ['Trust the project .codex layer in Codex before project hooks run.'],
    };
  }

  uninstall(loc: Location, opts: InstallOptions = {}): WriteResult {
    const filePath = resolveHooksPath(loc, opts.cwd ?? process.cwd());
    if (!fs.existsSync(filePath)) {
      return { files: [{ path: filePath, action: 'not-found' }] };
    }
    const data = readJsonOrEmpty<HooksFile>(filePath);
    const cleaned = stripManagedEntries(data.hooks);
    if (deepEqual(cleaned, data.hooks ?? {})) {
      return { files: [{ path: filePath, action: 'not-found' }] };
    }
    const next: HooksFile = { ...data, hooks: cleaned };
    atomicWriteFileSync(filePath, formatJson(next));
    if (loc === 'local') {
      return { files: [{ path: filePath, action: 'removed' }] };
    }
    return {
      files: [{ path: filePath, action: 'removed' }],
      notes: ['~/.codex/config.toml [hooks.state] entries are not GC-ed by Codex; remove manually if desired.'],
    };
  }

  describePaths(loc: Location, opts: InstallOptions = {}): string[] {
    const hooksPath = resolveHooksPath(loc, opts.cwd ?? process.cwd());
    return loc === 'global' ? [hooksPath, globalTomlConfigPath()] : [hooksPath];
  }
}

export const codexTarget: AgentTarget = new CodexTarget();
