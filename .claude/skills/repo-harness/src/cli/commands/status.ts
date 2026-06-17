/**
 * `local-repo-harness status` — read-only summary of CLI install state + route coverage.
 *
 * Reports per-host install detection (target.detect), managed-entry count vs
 * expected, route registry summary, and current repo opt-in marker presence.
 * No mutations.
 */

import * as fs from 'fs';
import * as path from 'path';
import { execFileSync } from 'child_process';
import * as os from 'os';
import { fileURLToPath } from 'url';
import { ALL_TARGETS } from '../installer/targets/registry';
import { ROUTES } from '../hook/route-registry';
import { isManagedEntry, type HooksByEvent } from '../installer/managed-entries';
import { readJsonOrEmpty } from '../installer/shared';
import { locationToScope, type InstallScope, type Location } from '../installer/types';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = path.resolve(SCRIPT_DIR, '..', '..', '..');

function readPackageVersion(): string {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(PACKAGE_ROOT, 'package.json'), 'utf-8')) as {
      version?: unknown;
    };
    return typeof pkg.version === 'string' && pkg.version.trim() ? pkg.version : 'unknown';
  } catch {
    return 'unknown';
  }
}

export const CLI_VERSION = readPackageVersion();

const OPT_IN_MARKER = '.ai/harness/workflow-contract.json';
const POLICY_FILE = '.ai/harness/policy.json';
const PROJECT_RUNTIME_BIN = '.ai/harness/bin/local-repo-harness-hook';

export interface StatusReport {
  cli: { version: string };
  targets: Array<{
    id: string;
    displayName: string;
    location: Location;
    scope: Exclude<InstallScope, 'none'>;
    installed: boolean;
    alreadyConfigured: boolean;
    configPath?: string;
    detail?: string;
    managedEntryCount: number;
    expectedEntryCount: number;
  }>;
  repo: {
    inGitRepo: boolean;
    repoRoot?: string;
    optIn: boolean;
    optInMarker: string;
    policyPath?: string;
  };
  scopes: {
    intent: {
      hooks: InstallScope | 'unknown';
      runtime: string;
      skills: InstallScope | 'unknown';
      externalTools: InstallScope | 'unknown';
      codegraphMcp: InstallScope | 'unknown';
      brain: string;
    };
    hooks: Array<{
      host: string;
      scope: Exclude<InstallScope, 'none'>;
      status: 'configured' | 'missing' | 'not-applicable';
      path?: string;
    }>;
    runtime: {
      mode: string;
      status: 'present' | 'missing' | 'not-required' | 'unknown';
      path?: string;
    };
    skills: Array<{
      host: 'codex' | 'claude';
      scope: Exclude<InstallScope, 'none'>;
      status: 'present' | 'missing';
      path: string;
    }>;
    externalTools: {
      scope: InstallScope | 'unknown';
      waza: 'present' | 'missing' | 'skipped' | 'unknown';
      mermaid: 'present' | 'missing' | 'skipped' | 'unknown';
    };
    codegraph: {
      index: { status: 'present' | 'missing'; path?: string };
      mcpScope: InstallScope | 'mixed' | 'unknown';
      hosts: Array<{
        host: 'codex' | 'claude';
        scope: Exclude<InstallScope, 'none'>;
        status: 'configured' | 'missing';
        path: string;
      }>;
    };
    brain: {
      mode: string;
      manifest: 'present' | 'missing' | 'not-required' | 'unknown';
      path?: string;
    };
  };
  routes: { total: number; byEvent: Record<string, number> };
}

export function resolveRepoRoot(cwd: string): string | null {
  try {
    const out = execFileSync('git', ['-C', cwd, 'rev-parse', '--show-toplevel'], {
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    return out.trim() || null;
  } catch {
    return null;
  }
}

function homeDir(): string {
  return process.env.HOME ?? os.homedir();
}

function readJsonSafe(filePath: string): Record<string, any> | null {
  if (!fs.existsSync(filePath)) return null;
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf-8')) as Record<string, any>;
  } catch {
    return null;
  }
}

function policyFor(repoRoot: string | null): { path?: string; data: Record<string, any> } {
  if (!repoRoot) return { data: {} };
  const policyPath = path.join(repoRoot, POLICY_FILE);
  return { path: policyPath, data: readJsonSafe(policyPath) ?? {} };
}

function scopeValue(value: unknown): InstallScope | 'unknown' {
  return value === 'user' || value === 'project' || value === 'none' ? value : 'unknown';
}

function executableStatus(filePath: string): StatusReport['scopes']['runtime']['status'] {
  if (!fs.existsSync(filePath)) return 'missing';
  try {
    fs.accessSync(filePath, fs.constants.X_OK);
    return 'present';
  } catch {
    return 'missing';
  }
}

function skillPath(repoRoot: string | null, host: 'codex' | 'claude', scope: Exclude<InstallScope, 'none'>): string {
  if (scope === 'project') {
    return path.join(repoRoot ?? process.cwd(), host === 'codex' ? '.agents' : '.claude', 'skills', 'repo-harness', 'SKILL.md');
  }
  return path.join(homeDir(), host === 'codex' ? '.codex' : '.claude', 'skills', 'repo-harness', 'SKILL.md');
}

function externalSkillPath(repoRoot: string | null, name: string, scope: InstallScope | 'unknown'): string | null {
  if (scope === 'project') return path.join(repoRoot ?? process.cwd(), '.agents', 'skills', name, 'SKILL.md');
  if (scope === 'user') return path.join(homeDir(), '.codex', 'skills', name, 'SKILL.md');
  return null;
}

function fileContains(filePath: string, pattern: RegExp): boolean {
  if (!fs.existsSync(filePath)) return false;
  try {
    return pattern.test(fs.readFileSync(filePath, 'utf-8'));
  } catch {
    return false;
  }
}

function claudeMcpConfigured(filePath: string): boolean {
  const data = readJsonSafe(filePath);
  return Boolean(data?.mcpServers?.codegraph);
}

function mcpScopeFromHosts(hosts: StatusReport['scopes']['codegraph']['hosts']): StatusReport['scopes']['codegraph']['mcpScope'] {
  const configured = hosts.filter((host) => host.status === 'configured');
  if (configured.length === 0) return 'none';
  const scopes = new Set(configured.map((host) => host.scope));
  if (scopes.size > 1) return 'mixed';
  return configured[0].scope;
}

function buildScopeSummary(
  repoRoot: string | null,
  targets: StatusReport['targets'],
): StatusReport['scopes'] {
  const policy = policyFor(repoRoot).data;
  const hookIntent = scopeValue(policy.host_adapters?.scope);
  const skillIntent = scopeValue(policy.skills?.repo_harness_scope ?? policy.external_tooling?.repo_harness_skills?.scope);
  const externalIntent = scopeValue(policy.external_tooling?.scope);
  const codegraphMcpIntent = scopeValue(policy.external_tooling?.codegraph?.mcp_scope ?? policy.codegraph?.mcp_scope);
  const brainMode = String(policy.brain?.mode ?? policy.external_tooling?.gbrain?.mode ?? 'unknown');
  const runtimeMode = String(policy.host_adapters?.hook_runtime_mode ?? 'unknown');
  const runtimePath = repoRoot ? path.join(repoRoot, PROJECT_RUNTIME_BIN) : undefined;
  const runtimeRequired = runtimeMode === 'project-vendored-bun' || hookIntent === 'project';

  const hooks = targets.map((target) => ({
    host: target.id,
    scope: target.scope,
    status: target.alreadyConfigured ? 'configured' as const : 'missing' as const,
    path: target.configPath,
  }));

  const skills: StatusReport['scopes']['skills'] = [];
  for (const host of ['codex', 'claude'] as const) {
    for (const scope of ['user', 'project'] as const) {
      const skill = skillPath(repoRoot, host, scope);
      skills.push({
        host,
        scope,
        status: fs.existsSync(skill) ? 'present' : 'missing',
        path: skill,
      });
    }
  }

  const wazaPath = externalSkillPath(repoRoot, 'health', externalIntent);
  const mermaidPath = externalSkillPath(repoRoot, 'mermaid', externalIntent);
  const externalTools = {
    scope: externalIntent,
    waza: externalIntent === 'none'
      ? 'skipped' as const
      : wazaPath
        ? (fs.existsSync(wazaPath) ? 'present' as const : 'missing' as const)
        : 'unknown' as const,
    mermaid: externalIntent === 'none'
      ? 'skipped' as const
      : mermaidPath
        ? (fs.existsSync(mermaidPath) ? 'present' as const : 'missing' as const)
        : 'unknown' as const,
  };

  const codegraphHosts: StatusReport['scopes']['codegraph']['hosts'] = [
    {
      host: 'codex',
      scope: 'project',
      status: repoRoot && fileContains(path.join(repoRoot, '.codex', 'config.toml'), /\[mcp_servers\.codegraph\]/)
        ? 'configured'
        : 'missing',
      path: path.join(repoRoot ?? process.cwd(), '.codex', 'config.toml'),
    },
    {
      host: 'claude',
      scope: 'project',
      status: repoRoot && claudeMcpConfigured(path.join(repoRoot, '.mcp.json')) ? 'configured' : 'missing',
      path: path.join(repoRoot ?? process.cwd(), '.mcp.json'),
    },
    {
      host: 'codex',
      scope: 'user',
      status: fileContains(path.join(homeDir(), '.codex', 'config.toml'), /\[mcp_servers\.codegraph\]/)
        ? 'configured'
        : 'missing',
      path: path.join(homeDir(), '.codex', 'config.toml'),
    },
    {
      host: 'claude',
      scope: 'user',
      status: claudeMcpConfigured(path.join(homeDir(), '.claude.json')) ? 'configured' : 'missing',
      path: path.join(homeDir(), '.claude.json'),
    },
  ];

  const brainManifestPath = repoRoot ? path.join(repoRoot, '.ai', 'harness', 'brain-manifest.json') : undefined;
  return {
    intent: {
      hooks: hookIntent,
      runtime: runtimeMode,
      skills: skillIntent,
      externalTools: externalIntent,
      codegraphMcp: codegraphMcpIntent,
      brain: brainMode,
    },
    hooks,
    runtime: {
      mode: runtimeMode,
      status: runtimeRequired && runtimePath ? executableStatus(runtimePath) : runtimeRequired ? 'missing' : 'not-required',
      path: runtimePath,
    },
    skills,
    externalTools,
    codegraph: {
      index: {
        status: repoRoot && fs.existsSync(path.join(repoRoot, '.codegraph')) ? 'present' : 'missing',
        path: repoRoot ? path.join(repoRoot, '.codegraph') : undefined,
      },
      mcpScope: mcpScopeFromHosts(codegraphHosts),
      hosts: codegraphHosts,
    },
    brain: {
      mode: brainMode,
      manifest: brainMode === 'skip'
        ? 'not-required'
        : brainManifestPath
          ? (fs.existsSync(brainManifestPath) ? 'present' : 'missing')
          : 'unknown',
      path: brainManifestPath,
    },
  };
}

function countManagedEntries(filePath: string): number {
  if (!fs.existsSync(filePath)) return 0;
  try {
    const data = readJsonOrEmpty<{ hooks?: HooksByEvent }>(filePath);
    let count = 0;
    for (const entries of Object.values(data.hooks ?? {})) {
      count += (entries ?? []).filter(isManagedEntry).length;
    }
    return count;
  } catch {
    return 0;
  }
}

export function runStatus(cwd: string = process.cwd()): StatusReport {
  const byEvent: Record<string, number> = {};
  for (const r of ROUTES) {
    byEvent[r.event] = (byEvent[r.event] ?? 0) + 1;
  }

  const repoRoot = resolveRepoRoot(cwd);
  const repo: StatusReport['repo'] = {
    inGitRepo: repoRoot !== null,
    optInMarker: OPT_IN_MARKER,
    optIn: false,
  };
  if (repoRoot) {
    repo.repoRoot = repoRoot;
    repo.optIn = fs.existsSync(path.join(repoRoot, OPT_IN_MARKER));
    repo.policyPath = path.join(repoRoot, POLICY_FILE);
  }

  const targets: StatusReport['targets'] = [];
  const expectedEntryCount = ROUTES.length;
  for (const target of ALL_TARGETS) {
    for (const location of ['global', 'local'] as const) {
      if (!target.supportsLocation(location)) continue;
      if (location === 'local' && !repoRoot) {
        targets.push({
          id: target.id,
          displayName: target.displayName,
          location,
          scope: locationToScope(location),
          installed: false,
          alreadyConfigured: false,
          detail: 'not in a git repo',
          managedEntryCount: 0,
          expectedEntryCount,
        });
        continue;
      }
      const det = target.detect(location, { cwd: location === 'local' ? repoRoot ?? cwd : cwd });
      const managedEntryCount = det.configPath ? countManagedEntries(det.configPath) : 0;
      targets.push({
        id: target.id,
        displayName: target.displayName,
        location,
        scope: locationToScope(location),
        installed: det.installed,
        alreadyConfigured: det.alreadyConfigured,
        configPath: det.configPath,
        managedEntryCount,
        expectedEntryCount,
      });
    }
  }

  const scopes = buildScopeSummary(repoRoot, targets);

  return { cli: { version: CLI_VERSION }, targets, repo, scopes, routes: { total: ROUTES.length, byEvent } };
}

export function formatStatus(report: StatusReport, asJson = false): string {
  if (asJson) return JSON.stringify(report, null, 2);
  const lines: string[] = [];
  lines.push(`repo-harness ${report.cli.version}`);
  lines.push('');
  lines.push('Hosts:');
  for (const t of report.targets) {
    let status: string;
    if (!t.installed) status = 'host not detected';
    else if (!t.alreadyConfigured) status = 'host present, repo-harness not installed';
    else status = `${t.managedEntryCount}/${t.expectedEntryCount} managed entries`;
    if (t.detail) status = `${status}; ${t.detail}`;
    lines.push(`  ${t.id} (${t.scope}): ${status}`);
    if (t.configPath) lines.push(`    ${t.configPath}`);
  }
  lines.push('');
  lines.push('Scopes:');
  lines.push(`  intent: hooks=${report.scopes.intent.hooks}; runtime=${report.scopes.intent.runtime}; skills=${report.scopes.intent.skills}; external-tools=${report.scopes.intent.externalTools}; codegraph-mcp=${report.scopes.intent.codegraphMcp}; brain=${report.scopes.intent.brain}`);
  lines.push('  hooks:');
  for (const hook of report.scopes.hooks) {
    lines.push(`    ${hook.host} ${hook.scope}: ${hook.status}${hook.path ? ` at ${hook.path}` : ''}`);
  }
  lines.push(`  runtime: ${report.scopes.runtime.mode} (${report.scopes.runtime.status})${report.scopes.runtime.path ? ` at ${report.scopes.runtime.path}` : ''}`);
  lines.push(`  skills: ${report.scopes.skills.map((skill) => `${skill.host} ${skill.scope}=${skill.status}`).join(', ')}`);
  lines.push(`  external tools: scope=${report.scopes.externalTools.scope}; waza=${report.scopes.externalTools.waza}; mermaid=${report.scopes.externalTools.mermaid}`);
  lines.push(`  codegraph: index=${report.scopes.codegraph.index.status}; mcp=${report.scopes.codegraph.mcpScope}`);
  lines.push(`  brain: mode=${report.scopes.brain.mode}; manifest=${report.scopes.brain.manifest}`);
  lines.push('');
  lines.push('Routes:');
  lines.push(`  ${report.routes.total} total`);
  for (const [event, count] of Object.entries(report.routes.byEvent)) {
    lines.push(`    ${event}: ${count}`);
  }
  lines.push('');
  lines.push('Current repo:');
  if (report.repo.inGitRepo) {
    lines.push(`  git root: ${report.repo.repoRoot}`);
    lines.push(`  opt-in (${report.repo.optInMarker}): ${report.repo.optIn ? 'yes' : 'no'}`);
  } else {
    lines.push('  not in a git repo');
  }
  return lines.join('\n');
}
