/**
 * `local-repo-harness doctor` — read-only readiness diagnostics.
 *
 * Built-in checks: PATH resolution, CLI version, per-host install detection,
 * Codex user-level trust state count, and target-aware CodeGraph readiness.
 * Never mutates.
 */

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { spawnSync } from 'child_process';
import { ALL_TARGETS } from '../installer/targets/registry';
import { checkCodegraph, type CodegraphCheckResult } from '../tools/codegraph';
import { CLI_VERSION, runStatus, type StatusReport } from './status';
import { runSecurityScan, type SecurityScanReport, type SecurityScanScope } from './security';
import { isOptIn, resolveHooksDir, resolveRepoRoot } from '../hook/runtime';
import { ROUTES } from '../hook/route-registry';

const TRUST_STATE_LINE = /^\[hooks\.state\."[^"]+\/\.codex\/hooks\.json:/;
const PACKAGE_NAME = 'local-repo-harness';
const UPDATE_CHECK_ENV = 'REPO_HARNESS_CHECK_UPDATES';
const LATEST_VERSION_ENV = 'REPO_HARNESS_LATEST_VERSION';

export type CheckStatus = 'ok' | 'warn' | 'fail' | 'na';

export interface DoctorCheckResult {
  id: string;
  describe: string;
  status: CheckStatus;
  detail: string;
}

export interface DoctorCheck {
  id: string;
  describe: string;
  run(): Omit<DoctorCheckResult, 'id' | 'describe'>;
}

export interface DoctorReport {
  checks: DoctorCheckResult[];
  summary: { ok: number; warn: number; fail: number; na: number };
}

const REGISTERED_CHECKS: DoctorCheck[] = [];

export function registerCheck(check: DoctorCheck): void {
  REGISTERED_CHECKS.push(check);
}

/** Test seam — Phase 1C tests reset after each. */
export function clearRegisteredChecks(): void {
  REGISTERED_CHECKS.length = 0;
}

function homeDir(): string {
  return process.env.HOME ?? os.homedir();
}

function hasProjectHookIntent(statusReport: StatusReport): boolean {
  return statusReport.repo.inGitRepo && statusReport.repo.optIn && statusReport.scopes.intent.hooks === 'project';
}

function checkPath(statusReport: StatusReport): DoctorCheckResult {
  const id = 'cli-on-path';
  const describe = 'local-repo-harness resolvable via PATH';
  if (hasProjectHookIntent(statusReport)) {
    const projectCli = statusReport.repo.repoRoot
      ? path.join(statusReport.repo.repoRoot, '.ai/harness/bin/local-repo-harness')
      : '.ai/harness/bin/local-repo-harness';
    return {
      id,
      describe,
      status: 'na',
      detail: `project hook scope is intended; global PATH CLI is not required; project_cli=${projectCli}`,
    };
  }
  const result = spawnSync('which', ['local-repo-harness'], { encoding: 'utf-8' });
  if (result.status === 0 && (result.stdout ?? '').trim()) {
    return { id, describe, status: 'ok', detail: (result.stdout as string).trim() };
  }
  return {
    id,
    describe,
    status: 'warn',
    detail: 'local-repo-harness not on PATH (host adapter shim exits 0 silently when CLI is missing)',
  };
}

function checkVersion(): DoctorCheckResult {
  return { id: 'cli-version', describe: 'local-repo-harness CLI version', status: 'ok', detail: CLI_VERSION };
}

function parseVersion(value: string): number[] | null {
  const match = value.trim().replace(/^v/, '').match(/^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/);
  if (!match) return null;
  return match.slice(1).map((part) => Number(part));
}

function compareVersions(a: string, b: string): number | null {
  const left = parseVersion(a);
  const right = parseVersion(b);
  if (!left || !right) return null;
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const diff = (left[index] ?? 0) - (right[index] ?? 0);
    if (diff !== 0) return diff > 0 ? 1 : -1;
  }
  return 0;
}

function readLatestPackageVersion(): { version?: string; error?: string } {
  if (process.env[LATEST_VERSION_ENV]) {
    return { version: process.env[LATEST_VERSION_ENV] };
  }

  const result = spawnSync('npm', ['view', PACKAGE_NAME, 'version', '--json'], {
    encoding: 'utf-8',
    timeout: 5000,
  });
  if (result.status !== 0 || result.error) {
    return { error: result.stderr || result.stdout || String(result.error?.message ?? result.error ?? 'npm view failed') };
  }
  try {
    const parsed = JSON.parse(result.stdout);
    return { version: typeof parsed === 'string' ? parsed : String(parsed) };
  } catch {
    return { version: result.stdout.trim().replace(/^"|"$/g, '') };
  }
}

function checkCliUpdate(): DoctorCheckResult {
  const id = 'cli-update';
  const describe = 'local-repo-harness latest version advisory';
  if (process.env[UPDATE_CHECK_ENV] !== '1') {
    return {
      id,
      describe,
      status: 'na',
      detail: `disabled; Agent can run ${UPDATE_CHECK_ENV}=1 local-repo-harness doctor --json before updating`,
    };
  }

  const latest = readLatestPackageVersion();
  if (!latest.version) {
    return { id, describe, status: 'na', detail: `latest unavailable; ${latest.error ?? 'unknown error'}` };
  }

  const comparison = compareVersions(CLI_VERSION, latest.version);
  if (comparison === null) {
    return { id, describe, status: 'warn', detail: `current=${CLI_VERSION}; latest=${latest.version}; unable to compare versions` };
  }
  if (comparison < 0) {
    return {
      id,
      describe,
      status: 'warn',
      detail: `current=${CLI_VERSION}; latest=${latest.version}; agent_action=npm install -g ${PACKAGE_NAME}@latest && local-repo-harness init`,
    };
  }
  return { id, describe, status: 'ok', detail: `current=${CLI_VERSION}; latest=${latest.version}` };
}

function checkTargetInstall(target: (typeof ALL_TARGETS)[number], statusReport: StatusReport): DoctorCheckResult {
  const id = `${target.id}-adapter`;
  const describe = `${target.displayName} global adapter`;
  if (hasProjectHookIntent(statusReport)) {
    return {
      id,
      describe,
      status: 'na',
      detail: `project hook scope is intended; global ${target.id} adapter is not required; see project-${target.id}-adapter`,
    };
  }
  const det = target.detect('global');
  if (!det.installed) {
    return {
      id,
      describe,
      status: 'warn',
      detail: `${target.displayName} host not detected; install when host is set up`,
    };
  }
  if (!det.alreadyConfigured) {
    return {
      id,
      describe,
      status: 'warn',
      detail: `host detected but local-repo-harness not installed (run: local-repo-harness install --target ${target.id} --location global)`,
    };
  }
  return { id, describe, status: 'ok', detail: `installed at ${det.configPath}` };
}

function checkHookScopeIntent(statusReport: StatusReport): DoctorCheckResult {
  const id = 'hook-scope-intent';
  const describe = 'Configured hook adapter scope intent';
  if (!statusReport.repo.inGitRepo || !statusReport.repo.optIn) {
    return { id, describe, status: 'na', detail: 'repo is not opted in' };
  }
  const intent = statusReport.scopes.intent;
  return {
    id,
    describe,
    status: intent.hooks === 'unknown' ? 'warn' : 'ok',
    detail: `hooks=${intent.hooks}; runtime=${intent.runtime}; policy=${statusReport.repo.policyPath ?? 'missing'}`,
  };
}

function checkProjectAdapter(statusReport: StatusReport, host: 'codex' | 'claude'): DoctorCheckResult {
  const id = `project-${host}-adapter`;
  const describe = `${host === 'codex' ? 'Codex' : 'Claude Code'} project adapter`;
  if (!statusReport.repo.inGitRepo || !statusReport.repo.optIn) {
    return { id, describe, status: 'na', detail: 'repo is not opted in' };
  }
  const entry = statusReport.targets.find((target) => target.id === host && target.scope === 'project');
  if (entry?.alreadyConfigured) {
    return {
      id,
      describe,
      status: 'ok',
      detail: `${entry.managedEntryCount}/${entry.expectedEntryCount} managed entries at ${entry.configPath}`,
    };
  }
  if (statusReport.scopes.intent.hooks === 'project') {
    return {
      id,
      describe,
      status: 'fail',
      detail: `project hook scope is intended but ${host} project adapter is missing${entry?.configPath ? ` at ${entry.configPath}` : ''}`,
    };
  }
  return {
    id,
    describe,
    status: 'na',
    detail: `project adapter not intended (hook scope intent=${statusReport.scopes.intent.hooks})`,
  };
}

function checkMixedScopeAdapters(statusReport: StatusReport): DoctorCheckResult {
  const id = 'mixed-scope-adapters';
  const describe = 'User/project adapter overlap';
  if (!statusReport.repo.inGitRepo || !statusReport.repo.optIn) {
    return { id, describe, status: 'na', detail: 'repo is not opted in' };
  }
  const projectConfigured = statusReport.targets.filter((target) => target.scope === 'project' && target.alreadyConfigured);
  const userConfigured = statusReport.targets.filter((target) => target.scope === 'user' && target.alreadyConfigured);
  if (statusReport.scopes.intent.hooks === 'project' && userConfigured.length > 0) {
    return {
      id,
      describe,
      status: 'warn',
      detail: `project-only intent with user adapters still configured: ${userConfigured.map((target) => `${target.id}:${target.configPath}`).join(', ')}`,
    };
  }
  if (projectConfigured.length > 0 && userConfigured.length > 0) {
    return {
      id,
      describe,
      status: 'warn',
      detail: `both project and user adapters are configured: project=${projectConfigured.length}; user=${userConfigured.length}`,
    };
  }
  return {
    id,
    describe,
    status: 'ok',
    detail: `project=${projectConfigured.length}; user=${userConfigured.length}`,
  };
}

function checkProjectHookRuntime(statusReport: StatusReport): DoctorCheckResult {
  const id = 'project-hook-runtime';
  const describe = 'Project hook runtime executable';
  if (!statusReport.repo.inGitRepo || !statusReport.repo.optIn) {
    return { id, describe, status: 'na', detail: 'repo is not opted in' };
  }
  const runtime = statusReport.scopes.runtime;
  if (runtime.status === 'not-required') {
    return { id, describe, status: 'na', detail: `runtime mode=${runtime.mode}` };
  }
  if (runtime.status === 'present') {
    return { id, describe, status: 'ok', detail: `${runtime.mode} at ${runtime.path}` };
  }
  return {
    id,
    describe,
    status: 'fail',
    detail: `${runtime.mode} runtime missing or not executable at ${runtime.path}; remediation=local-repo-harness install --target both --scope project`,
  };
}

function checkProjectSkills(statusReport: StatusReport): DoctorCheckResult {
  const id = 'project-skills';
  const describe = 'Project-scoped local-repo-harness skills';
  if (!statusReport.repo.inGitRepo || !statusReport.repo.optIn) {
    return { id, describe, status: 'na', detail: 'repo is not opted in' };
  }
  if (statusReport.scopes.intent.skills !== 'project') {
    return {
      id,
      describe,
      status: statusReport.scopes.intent.skills === 'none' ? 'ok' : 'na',
      detail: `skill scope intent=${statusReport.scopes.intent.skills}`,
    };
  }
  const projectSkills = statusReport.scopes.skills.filter((skill) => skill.scope === 'project');
  const missing = projectSkills.filter((skill) => skill.status !== 'present');
  if (missing.length === 0) {
    return {
      id,
      describe,
      status: 'ok',
      detail: projectSkills.map((skill) => `${skill.host}:${skill.path}`).join(', '),
    };
  }
  return {
    id,
    describe,
    status: 'fail',
    detail: `missing project skills: ${missing.map((skill) => `${skill.host}:${skill.path}`).join(', ')}`,
  };
}

function checkThirdPartyTooling(statusReport: StatusReport): DoctorCheckResult {
  const id = 'third-party-tooling';
  const describe = 'Third-party skill/tooling scope';
  if (!statusReport.repo.inGitRepo || !statusReport.repo.optIn) {
    return { id, describe, status: 'na', detail: 'repo is not opted in' };
  }
  const tooling = statusReport.scopes.externalTools;
  const detail = `scope=${tooling.scope}; waza=${tooling.waza}; mermaid=${tooling.mermaid}; gbrain=${statusReport.scopes.brain.mode}; codegraph-mcp-intent=${statusReport.scopes.intent.codegraphMcp}`;
  if (tooling.scope === 'none') {
    return { id, describe, status: 'ok', detail };
  }
  if (tooling.scope === 'project' && (tooling.waza === 'missing' || tooling.mermaid === 'missing')) {
    return { id, describe, status: 'warn', detail };
  }
  return { id, describe, status: tooling.scope === 'unknown' ? 'warn' : 'ok', detail };
}

function checkCodexTrustState(): DoctorCheckResult {
  const id = 'codex-trust-state';
  const describe = 'Codex user-level trust hash registration (~/.codex/config.toml)';
  const configPath = path.join(homeDir(), '.codex', 'config.toml');
  if (!fs.existsSync(configPath)) {
    return { id, describe, status: 'na', detail: 'Codex config.toml not found' };
  }
  try {
    const raw = fs.readFileSync(configPath, 'utf-8');
    let count = 0;
    for (const line of raw.split('\n')) {
      if (TRUST_STATE_LINE.test(line)) count++;
    }
    if (count === 0) {
      return {
        id,
        describe,
        status: 'warn',
        detail: 'no user-level trust hashes registered (restart Codex and accept the trust prompt)',
      };
    }
    return {
      id,
      describe,
      status: 'ok',
      detail: `${count} user-level trust hash entries`,
    };
  } catch (err) {
    return { id, describe, status: 'fail', detail: `error reading config.toml: ${(err as Error).message}` };
  }
}

function doctorStatusForCodegraph(status: CodegraphCheckResult['status']): CheckStatus {
  if (status === 'present') return 'ok';
  if (status === 'missing') return 'fail';
  return 'warn';
}

function formatCodegraphDetail(result: CodegraphCheckResult): string {
  const raw = result.raw as Record<string, any>;
  const indexStatus = raw.project_index?.status ?? 'unknown';
  const codexMcpStatus = raw.mcp_hosts?.codex?.status ?? 'unknown';
  const claudeMcpStatus = raw.mcp_hosts?.claude?.status ?? 'unknown';
  const bits = [
    result.reason,
    `source=${result.resolution.source}`,
    `version=${result.resolution.version ?? 'unknown'}`,
    `codex-mcp=${codexMcpStatus}`,
    `claude-mcp=${claudeMcpStatus}`,
    `index=${indexStatus}`,
  ];
  if (result.resolution.globalFallbackUsed) bits.push('global-fallback=true');
  const remediation = codegraphRemediation(result);
  if (remediation) bits.push(`remediation=${remediation}`);
  return bits.join('; ');
}

function codegraphRemediation(result: CodegraphCheckResult): string | null {
  if (result.status === 'present') return null;

  const raw = result.raw as Record<string, any>;
  if (result.resolution.source === 'missing') {
    return String(raw.install_command ?? 'bash scripts/ensure-codegraph.sh');
  }
  if (result.resolution.globalFallbackUsed) {
    return String(raw.install_command ?? 'bun install');
  }
  if (raw.mcp_hosts?.codex?.status !== 'configured' || raw.mcp_hosts?.claude?.status !== 'configured') {
    return String(raw.mcp_install_command ?? 'local-repo-harness tools configure codegraph --target both --location global');
  }
  if (raw.project_index?.status === 'not-initialized') {
    return String(raw.init_command ?? 'bash scripts/ensure-codegraph.sh --init');
  }
  if (raw.project_index?.status === 'stale') {
    return String(raw.sync_command ?? 'bash scripts/ensure-codegraph.sh --sync');
  }
  return String(raw.ensure_command ?? raw.sync_command ?? 'bash scripts/ensure-codegraph.sh --check');
}

function codegraphMcpRemediation(result: CodegraphCheckResult, host: 'codex' | 'claude'): string {
  const raw = result.raw as Record<string, any>;
  const command = String(
    raw.mcp_install_command ??
      'local-repo-harness tools configure codegraph --target <codex|claude|both> --location global',
  );
  return command.replace('<codex|claude|both>', host);
}

interface CodegraphProbe {
  result?: CodegraphCheckResult;
  error?: Error;
}

function probeCodegraph(cwd: string): CodegraphProbe {
  try {
    return { result: checkCodegraph({ repoRoot: cwd, host: 'both' }) };
  } catch (err) {
    return { error: err as Error };
  }
}

function checkCodegraphReadiness(probe: CodegraphProbe): DoctorCheckResult {
  const id = 'codegraph-readiness';
  const describe = 'CodeGraph CLI, MCP, and project index readiness';
  if (probe.result) {
    return {
      id,
      describe,
      status: doctorStatusForCodegraph(probe.result.status),
      detail: formatCodegraphDetail(probe.result),
    };
  }
  return {
    id,
    describe,
    status: 'fail',
    detail: `error checking CodeGraph readiness: ${probe.error?.message ?? 'unknown error'}`,
  };
}

function checkCodegraphMcpHost(probe: CodegraphProbe, host: 'codex' | 'claude'): DoctorCheckResult {
  const id = `${host}-codegraph-mcp`;
  const describe = `${host === 'codex' ? 'Codex' : 'Claude Code'} CodeGraph MCP config`;
  if (!probe.result) {
    return {
      id,
      describe,
      status: 'fail',
      detail: `error checking CodeGraph MCP config: ${probe.error?.message ?? 'unknown error'}`,
    };
  }

  const raw = probe.result.raw as Record<string, any>;
  const entry = raw.mcp_hosts?.[host];
  if (entry?.status === 'configured') {
    return { id, describe, status: 'ok', detail: entry.reason ?? 'configured' };
  }
  return {
    id,
    describe,
    status: 'warn',
    detail: `${entry?.reason ?? 'missing'}; remediation=${codegraphMcpRemediation(probe.result, host)}`,
  };
}

function checkCodegraphIndex(probe: CodegraphProbe): DoctorCheckResult {
  const id = 'codegraph-index';
  const describe = 'CodeGraph project index';
  if (!probe.result) {
    return {
      id,
      describe,
      status: 'fail',
      detail: `error checking CodeGraph index: ${probe.error?.message ?? 'unknown error'}`,
    };
  }

  const raw = probe.result.raw as Record<string, any>;
  const indexStatus = raw.project_index?.status ?? 'unknown';
  const status: CheckStatus = indexStatus === 'up-to-date'
    ? 'ok'
    : indexStatus === 'stale' || indexStatus === 'unknown'
      ? 'warn'
      : 'fail';
  const remediation = indexStatus === 'not-initialized'
    ? raw.init_command
    : indexStatus === 'stale'
      ? raw.sync_command
      : raw.ensure_command;
  return {
    id,
    describe,
    status,
    detail: `index=${indexStatus}${remediation ? `; remediation=${remediation}` : ''}`,
  };
}

function checkSecurityConfig(report: SecurityScanReport): DoctorCheckResult {
  const id = 'security-config';
  const describe = 'Local hook and VS Code automatic task security scan';
  if (report.status === 'ok') {
    return {
      id,
      describe,
      status: 'ok',
      detail: `scope=${report.scope}; scanned ${report.scannedFiles.length} files; no findings`,
    };
  }

  const high = report.findings.filter((finding) => finding.severity === 'high').length;
  const fail = report.findings.filter((finding) => finding.severity === 'fail').length;
  const warn = report.findings.filter((finding) => finding.severity === 'warn').length;
  const first = report.findings[0];
  return {
    id,
    describe,
    status: report.status === 'fail' ? 'fail' : 'warn',
    detail: `scope=${report.scope}; ${report.findings.length} finding(s): ${high} high, ${warn} warn, ${fail} fail; first=${first.ruleId} at ${first.filePath}`,
  };
}

function securityScopeForStatus(statusReport: StatusReport): SecurityScanScope {
  if (hasProjectHookIntent(statusReport)) {
    return 'project';
  }
  return 'all';
}

function checkHookScriptDrift(cwd: string): DoctorCheckResult {
  const id = 'repo-hook-scripts';
  const describe = 'Active hook runtime scripts match the route registry';
  const repoRoot = resolveRepoRoot(cwd);
  if (!repoRoot) {
    return { id, describe, status: 'na', detail: 'not in a git repository' };
  }
  if (!isOptIn(repoRoot)) {
    return {
      id,
      describe,
      status: 'na',
      detail: 'repo is not opted in (.ai/harness/workflow-contract.json missing)',
    };
  }

  const resolved = resolveHooksDir(repoRoot);
  const expected = new Set<string>();
  const missing: string[] = [];
  for (const route of ROUTES) {
    for (const script of route.scripts) {
      expected.add(script);
      if (!fs.existsSync(path.join(resolved.dir, script)) && !missing.includes(script)) {
        missing.push(script);
      }
    }
  }

  if (missing.length === 0) {
    return {
      id,
      describe,
      status: 'ok',
      detail: `all ${expected.size} route scripts present (source=${resolved.source}, dir=${resolved.dir})`,
    };
  }

  const remediation =
    resolved.source === 'packaged'
      ? 'npm install -g local-repo-harness@latest'
      : `local-repo-harness adopt --repo ${repoRoot}`;
  return {
    id,
    describe,
    status: 'warn',
    detail: `missing from ${resolved.dir} (source=${resolved.source}): ${missing.join(', ')}; remediation=${remediation}`,
  };
}

export function runDoctor(cwd: string = process.cwd()): DoctorReport {
  const checks: DoctorCheckResult[] = [];
  const statusReport = runStatus(cwd);
  const codegraphProbe = probeCodegraph(cwd);
  const securityReport = runSecurityScan({ cwd, scope: securityScopeForStatus(statusReport) });
  checks.push(checkPath(statusReport));
  checks.push(checkVersion());
  checks.push(checkCliUpdate());
  for (const target of ALL_TARGETS) {
    if (target.supportsLocation('global')) {
      checks.push(checkTargetInstall(target, statusReport));
    }
  }
  checks.push(checkHookScopeIntent(statusReport));
  checks.push(checkProjectAdapter(statusReport, 'codex'));
  checks.push(checkProjectAdapter(statusReport, 'claude'));
  checks.push(checkMixedScopeAdapters(statusReport));
  checks.push(checkProjectHookRuntime(statusReport));
  checks.push(checkProjectSkills(statusReport));
  checks.push(checkThirdPartyTooling(statusReport));
  checks.push(checkCodexTrustState());
  checks.push(checkCodegraphReadiness(codegraphProbe));
  checks.push(checkCodegraphMcpHost(codegraphProbe, 'codex'));
  checks.push(checkCodegraphMcpHost(codegraphProbe, 'claude'));
  checks.push(checkCodegraphIndex(codegraphProbe));
  checks.push(checkSecurityConfig(securityReport));
  checks.push(checkHookScriptDrift(cwd));
  for (const plugin of REGISTERED_CHECKS) {
    const r = plugin.run();
    checks.push({ id: plugin.id, describe: plugin.describe, ...r });
  }
  const summary = { ok: 0, warn: 0, fail: 0, na: 0 };
  for (const c of checks) summary[c.status]++;
  return { checks, summary };
}

export function formatDoctor(report: DoctorReport, asJson = false): string {
  if (asJson) return JSON.stringify(report, null, 2);
  const lines: string[] = [];
  for (const c of report.checks) {
    const icon = c.status === 'ok' ? '✓' : c.status === 'warn' ? '!' : c.status === 'fail' ? '✗' : '-';
    lines.push(`${icon} ${c.id}: ${c.detail}`);
  }
  lines.push('');
  lines.push(
    `Summary: ${report.summary.ok} ok, ${report.summary.warn} warn, ${report.summary.fail} fail, ${report.summary.na} n/a`,
  );
  return lines.join('\n');
}
