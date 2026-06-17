/**
 * `local-repo-harness install --target codex|claude|both --location global|local`
 * or `--scope user|project|none`
 *
 * Resolves --target to AgentTarget list, calls target.install(loc, opts)
 * for each, prints WriteResult lines. Idempotent: re-run with no diff
 * returns `action: 'unchanged'` (verified by tests/cli/install.test.ts).
 *
 * Target/location matrix:
 *   - codex + global → writes ~/.codex/hooks.json
 *   - codex + local  → writes <cwd>/.codex/hooks.json
 *   - claude + global → writes ~/.claude/settings.json
 *   - claude + local  → writes <cwd>/.claude/settings.json (Phase 1C concern)
 *   - both + global   → codex + claude
 *   - both + local    → codex + claude project adapters
 */

import {
  scopeToLocation,
  type InstallScope,
  type Location,
} from '../installer/types';
import { ALL_TARGETS, getTarget, listTargetIds } from '../installer/targets/registry';
import { execFileSync } from 'child_process';
import {
  resolveRuntimeMode,
  type RuntimeSelection,
} from '../installer/hook-command';
import { installProjectRuntime } from '../installer/project-runtime';

export type InstallTargetSpec = 'codex' | 'claude' | 'both';

export interface InstallCommandOptions {
  target: InstallTargetSpec;
  location?: Location;
  scope?: InstallScope;
  cwd?: string;
  runtime?: RuntimeSelection;
}

export interface InstallCommandResult {
  exitCode: number;
  lines: string[];
}

function resolveLocation(opts: InstallCommandOptions): Location | null {
  if (opts.scope === 'none') return null;
  if (opts.scope) return scopeToLocation(opts.scope);
  if (opts.location) return opts.location;
  throw new Error('local-repo-harness install: either location or scope is required');
}

function resolveTargets(spec: InstallTargetSpec) {
  if (spec === 'both') return [...ALL_TARGETS];
  const t = getTarget(spec);
  if (!t) {
    throw new Error(
      `local-repo-harness install: unknown --target "${spec}" (known: ${listTargetIds().join(', ')}, both)`,
    );
  }
  return [t];
}

function resolveProjectCwd(opts: InstallCommandOptions, location: Location): string | undefined {
  if (location === 'global') return opts.cwd;
  const cwd = opts.cwd ?? process.cwd();
  try {
    const out = execFileSync('git', ['-C', cwd, 'rev-parse', '--show-toplevel'], {
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    return out.trim() || cwd;
  } catch {
    return cwd;
  }
}

export function runInstall(opts: InstallCommandOptions): InstallCommandResult {
  const targets = resolveTargets(opts.target);
  const location = resolveLocation(opts);
  const lines: string[] = [];
  let exitCode = 0;

  if (location === null) {
    for (const target of targets) {
      lines.push(`[${target.id}] skipped: --scope none`);
    }
    return { exitCode: 0, lines };
  }

  const projectCwd = resolveProjectCwd(opts, location);
  const runtimeMode = resolveRuntimeMode(location, opts.runtime ?? 'auto');
  if (location === 'global' && runtimeMode === 'project-vendored-bun') {
    lines.push('[runtime] error: --runtime project-vendored-bun requires --scope project or --location local');
    return { exitCode: 2, lines };
  }
  if (location === 'local' && runtimeMode === 'project-vendored-bun') {
    try {
      const runtime = installProjectRuntime(projectCwd ?? process.cwd());
      for (const file of runtime.files) {
        lines.push(`[runtime] ${file.action}: ${file.path}`);
      }
      for (const note of runtime.notes ?? []) {
        lines.push(`[runtime] note: ${note}`);
      }
    } catch (err) {
      lines.push(`[runtime] error: ${(err as Error).message}`);
      exitCode = 1;
      return { exitCode, lines };
    }
  } else if (location === 'local' && runtimeMode === 'global-path') {
    lines.push('[runtime] warning: project scope is using global PATH runtime; isolation is weaker.');
  }

  for (const target of targets) {
    if (!target.supportsLocation(location)) {
      if (opts.target === 'both') {
        lines.push(`[${target.id}] skipped: --location ${location} not supported`);
        continue;
      }
      lines.push(`[${target.id}] error: --location ${location} not supported`);
      exitCode = 2;
      continue;
    }
    try {
      const result = target.install(location, { cwd: projectCwd, runtimeMode });
      for (const file of result.files) {
        lines.push(`[${target.id}] ${file.action}: ${file.path}`);
      }
      for (const note of result.notes ?? []) {
        lines.push(`[${target.id}] note: ${note}`);
      }
    } catch (err) {
      lines.push(`[${target.id}] error: ${(err as Error).message}`);
      if (exitCode === 0) exitCode = 1;
    }
  }

  return { exitCode, lines };
}

export function runUninstall(opts: Omit<InstallCommandOptions, 'runtime'>): InstallCommandResult {
  const targets = resolveTargets(opts.target);
  const location = resolveLocation(opts);
  const lines: string[] = [];
  let exitCode = 0;

  if (location === null) {
    for (const target of targets) {
      lines.push(`[${target.id}] skipped: --scope none`);
    }
    return { exitCode: 0, lines };
  }

  const projectCwd = resolveProjectCwd(opts, location);
  for (const target of targets) {
    if (!target.supportsLocation(location)) {
      if (opts.target === 'both') {
        lines.push(`[${target.id}] skipped: --location ${location} not supported`);
        continue;
      }
      lines.push(`[${target.id}] error: --location ${location} not supported`);
      exitCode = 2;
      continue;
    }
    try {
      const result = target.uninstall(location, { cwd: projectCwd });
      for (const file of result.files) {
        lines.push(`[${target.id}] ${file.action}: ${file.path}`);
      }
      for (const note of result.notes ?? []) {
        lines.push(`[${target.id}] note: ${note}`);
      }
    } catch (err) {
      lines.push(`[${target.id}] error: ${(err as Error).message}`);
      if (exitCode === 0) exitCode = 1;
    }
  }

  return { exitCode, lines };
}
