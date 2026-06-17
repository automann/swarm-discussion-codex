#!/usr/bin/env bun
/**
 * local-repo-harness CLI entry.
 *
 * Wires commander.js to the global runtime bootstrap, repo-local update,
 * hook adapter, status, doctor, migrate, security, and tool command bodies.
 */

import { Command } from 'commander';
import { runInstall, runUninstall, type InstallTargetSpec } from './commands/install';
import { runInit, runInteractiveInit, type InitBrainMode } from './commands/init';
import { runHook } from './commands/hook';
import { CLI_VERSION, formatStatus, runStatus } from './commands/status';
import { formatDoctor, runDoctor } from './commands/doctor';
import { buildInitHookCommand, buildSetupCommand, formatInitHook, runInitHook } from './commands/init-hook';
import { formatMigratePlan, runMigrate } from './commands/migrate';
import { buildToolsCommand } from './commands/tools';
import { buildBrainCommand } from './commands/brain';
import { buildCapabilityContextCommand } from './commands/capability-context';
import { buildDocsCommand } from './commands/docs';
import { buildRunCommand } from './commands/run';
import { formatSecurityScan, runSecurityScan, SECURITY_SCAN_SCOPES, type SecurityScanScope } from './commands/security';
import { runGlobalRuntimeSetup } from './commands/global-runtime';
import { runBootstrap } from './commands/bootstrap';
import { runPromptGuardDecideCli } from './commands/prompt-guard-decision';
import { runRuntimeReclaim, runRuntimeRollback } from './repo-adoption/reclaim-runtime';
import type { InstallScope, Location } from './installer/types';
import { isRuntimeSelection, type RuntimeSelection } from './installer/hook-command';
import type { HookEvent, RouteId } from './hook/route-registry';
import type { ToolingScope } from './skills/project-skills';

export const SUBCOMMANDS = [
  'init',
  'init-hook',
  'install',
  'uninstall',
  'hook',
  'status',
  'doctor',
  'migrate',
  'security',
  'update',
  'bootstrap',
  'adopt',
  'run',
  'setup',
  'tools',
  'brain',
  'capability-context',
  'docs',
] as const;
export type Subcommand = (typeof SUBCOMMANDS)[number];

const VALID_TARGETS: readonly InstallTargetSpec[] = ['codex', 'claude', 'both'];
const VALID_LOCATIONS: readonly Location[] = ['global', 'local'];
const VALID_SCOPES: readonly InstallScope[] = ['user', 'project', 'none'];
const VALID_RUNTIMES: readonly RuntimeSelection[] = ['auto', 'global-path', 'project-vendored-bun'];

export function buildProgram(): Command {
  const program = new Command();
  program
    .name('local-repo-harness')
    .description('Make Claude/Codex work resumable, reviewable, and repo-local')
    .version(CLI_VERSION)
    .exitOverride();

  program
    .command('init')
    .description('Install the local-repo-harness CLI, global hook adapters, and required runtime dependencies')
    .option('--target <target>', `Host target for adapters and runtime skills: ${VALID_TARGETS.join('|')}`, 'both')
    .option('--no-cli', 'Skip installing the local-repo-harness CLI globally')
    .option('--no-sync-skill', 'Skip refreshing repo-harness skill aliases under host skill roots')
    .option('--no-hooks', 'Skip global hook adapter installation')
    .option('--no-external-skills', 'Skip Waza, Mermaid, and cross-review (codex-review/claude-review) skill bootstrap')
    .option('--no-codegraph', 'Skip CodeGraph CLI/MCP configuration')
    .option('--brain-root <path>', 'Brain vault root to persist for local-repo-harness brain commands')
    .option('--refresh', 'Refresh the idempotent user-level runtime after a CLI package update')
    .option('--json', 'Output JSON instead of human-readable text')
    .action((rawOpts: {
      target: string;
      cli?: boolean;
      syncSkill?: boolean;
      hooks?: string | false;
      externalSkills?: boolean;
      codegraph?: boolean;
      brainRoot?: string;
      refresh?: boolean;
      json?: boolean;
    }) => {
      if (!VALID_TARGETS.includes(rawOpts.target as InstallTargetSpec)) {
        console.error(
          `local-repo-harness init: invalid --target "${rawOpts.target}" (expected: ${VALID_TARGETS.join(', ')})`,
        );
        process.exit(2);
      }
      const result = runGlobalRuntimeSetup({
        target: rawOpts.target as InstallTargetSpec,
        installCli: rawOpts.cli !== false,
        syncSkill: rawOpts.syncSkill !== false,
        hostAdapters: rawOpts.hooks !== false,
        externalSkills: rawOpts.externalSkills !== false,
        codegraph: rawOpts.codegraph !== false,
        brainRoot: rawOpts.brainRoot,
      });
      if (rawOpts.json === true) {
        console.log(JSON.stringify(result, null, 2));
      } else {
        for (const line of result.lines) console.log(line);
      }
      process.exit(result.exitCode);
    });

  program
    .command('update')
    .description('Update the global local-repo-harness CLI and user-level managed runtime')
    .option('--target <target>', `Host target for adapters and runtime skills: ${VALID_TARGETS.join('|')}`, 'both')
    .option('--version <version>', 'Install a specific local-repo-harness package version')
    .option('--channel <channel>', 'Install package channel: latest|next')
    .option('--check', 'Run the read-only setup check without refreshing runtime')
    .option('--check-updates', 'Include network-backed version update advisories in setup check output')
    .option('--no-runtime-refresh', 'Skip runtime refresh and run the read-only setup check only')
    .option('--no-cli', 'Skip installing the local-repo-harness CLI globally')
    .option('--no-sync-skill', 'Skip refreshing repo-harness skill aliases under host skill roots')
    .option('--no-hooks', 'Skip global hook adapter installation')
    .option('--with-external-skills', 'Also bootstrap third-party Waza, Mermaid, and cross-review skills')
    .option('--no-external-skills', 'Compatibility no-op; update no longer bootstraps third-party skills by default')
    .option('--configure-codegraph', 'Also configure CodeGraph CLI/MCP during runtime refresh')
    .option('--no-codegraph', 'Compatibility no-op; update no longer configures CodeGraph by default')
    .option('--brain-root <path>', 'Brain vault root for manifest sync')
    .option('--repo <path>', 'Deprecated: use local-repo-harness adopt --repo <path>')
    .option('--dry-run', 'Deprecated: use local-repo-harness adopt --dry-run for repo-level planning')
    .option('--interactive', 'Deprecated: use local-repo-harness adopt --interactive for repo-level planning')
    .option('--json', 'Output JSON instead of human-readable text')
    .action((rawOpts: {
      repo?: string;
      dryRun?: boolean;
      target: string;
      version?: string;
      channel?: string;
      check?: boolean;
      checkUpdates?: boolean;
      runtimeRefresh?: boolean;
      cli?: boolean;
      syncSkill?: boolean;
      hooks?: string | false;
      withExternalSkills?: boolean;
      externalSkills?: boolean;
      codegraph?: boolean;
      configureCodegraph?: boolean;
      brainRoot?: string;
      interactive?: boolean;
      json?: boolean;
    }) => {
      if (!VALID_TARGETS.includes(rawOpts.target as InstallTargetSpec)) {
        console.error(
          `local-repo-harness update: invalid --target "${rawOpts.target}" (expected: ${VALID_TARGETS.join(', ')})`,
        );
        process.exit(2);
      }
      if (rawOpts.channel !== undefined && !['latest', 'next'].includes(rawOpts.channel)) {
        console.error('local-repo-harness update: invalid --channel (expected: latest, next)');
        process.exit(2);
      }
      if (rawOpts.repo || rawOpts.dryRun || rawOpts.interactive) {
        console.error(
          'local-repo-harness update no longer refreshes repositories. For repo-level refresh, run: local-repo-harness adopt --repo <path>',
        );
        process.exit(2);
      }
      if (rawOpts.check === true || rawOpts.runtimeRefresh === false) {
        const report = runInitHook({
          target: rawOpts.target as InstallTargetSpec,
          checkUpdates: rawOpts.checkUpdates === true,
        });
        console.log(formatInitHook(report, rawOpts.json === true));
        process.exit(report.status === 'blocked' ? 1 : 0);
      }
      const installSpec = rawOpts.version
        ? `local-repo-harness@${rawOpts.version}`
        : rawOpts.channel
          ? `local-repo-harness@${rawOpts.channel}`
          : 'local-repo-harness@latest';
      const result = runGlobalRuntimeSetup({
        target: rawOpts.target as InstallTargetSpec,
        installCli: rawOpts.cli !== false,
        installSpec,
        syncSkill: rawOpts.syncSkill !== false,
        hostAdapters: rawOpts.hooks !== false,
        externalSkills: rawOpts.withExternalSkills === true,
        codegraph: rawOpts.configureCodegraph === true,
        brainRoot: rawOpts.brainRoot,
      });
      if (rawOpts.json === true) {
        console.log(JSON.stringify(result, null, 2));
      } else {
        for (const line of result.lines) console.log(line);
      }
      process.exit(result.exitCode);
    });

  program
    .command('bootstrap')
    .description('Install local-repo-harness into a repo-managed tool root, then delegate to project adopt')
    .option('--repo <path>', 'Target repository path (defaults to cwd)')
    .option('--target <target>', `Host target for adapters and runtime skills: ${VALID_TARGETS.join('|')}`, 'both')
    .option('--package <spec>', 'Package spec to install into the project-managed runtime')
    .option('--version <version>', 'Install a specific local-repo-harness package version into the project-managed runtime')
    .option('--channel <channel>', 'Install package channel: latest|next')
    .option('--no-sync-skill', 'Skip repo-harness skill alias installation during delegated adopt')
    .option('--skill-scope <scope>', `repo-harness-owned skill scope: ${VALID_SCOPES.join('|')}`, 'project')
    .option('--no-host-adapters', 'Skip writing Codex/Claude hook adapters during delegated adopt')
    .option('--host-adapter-scope <scope>', `Hook adapter scope: ${VALID_SCOPES.join('|')}`, 'project')
    .option('--runtime <runtime>', `Hook runtime mode: ${VALID_RUNTIMES.join('|')}`, 'project-vendored-bun')
    .option('--no-external-skills', 'Skip Waza and Mermaid third-party skill bootstrap during delegated adopt')
    .option('--external-tool-scope <scope>', `Third-party tooling scope: ${VALID_SCOPES.join('|')}`, 'project')
    .option('--no-verify', 'Skip repo workflow verification during delegated adopt')
    .option('--no-codegraph', 'Skip building the CodeGraph index and MCP readiness check during delegated adopt')
    .option('--codegraph-mcp-scope <scope>', `CodeGraph MCP scope: ${VALID_SCOPES.join('|')}`, 'project')
    .option('--sync-codegraph', 'Sync the CodeGraph index after ensure during delegated adopt')
    .option('--brain-mode <mode>', 'Repo-local brain mode: skip|manifest-only', 'manifest-only')
    .option('--json', 'Output JSON instead of human-readable text')
    .action((rawOpts: {
      repo?: string;
      target: string;
      package?: string;
      version?: string;
      channel?: string;
      syncSkill?: boolean;
      skillScope?: string;
      hostAdapters?: boolean;
      hostAdapterScope?: string;
      runtime?: string;
      externalSkills?: boolean;
      externalToolScope?: string;
      verify?: boolean;
      codegraph?: boolean;
      codegraphMcpScope?: string;
      syncCodegraph?: boolean;
      brainMode?: string;
      json?: boolean;
    }) => {
      if (!VALID_TARGETS.includes(rawOpts.target as InstallTargetSpec)) {
        console.error(
          `local-repo-harness bootstrap: invalid --target "${rawOpts.target}" (expected: ${VALID_TARGETS.join(', ')})`,
        );
        process.exit(2);
      }
      if (rawOpts.channel !== undefined && !['latest', 'next'].includes(rawOpts.channel)) {
        console.error('local-repo-harness bootstrap: invalid --channel (expected: latest, next)');
        process.exit(2);
      }
      if ([rawOpts.package, rawOpts.version, rawOpts.channel].filter((value) => value !== undefined).length > 1) {
        console.error('local-repo-harness bootstrap: use only one of --package, --version, or --channel');
        process.exit(2);
      }
      if (!['skip', 'manifest-only'].includes(rawOpts.brainMode ?? 'manifest-only')) {
        console.error('local-repo-harness bootstrap: invalid --brain-mode (expected: skip, manifest-only)');
        process.exit(2);
      }
      if (!VALID_SCOPES.includes(rawOpts.hostAdapterScope as InstallScope)) {
        console.error(
          `local-repo-harness bootstrap: invalid --host-adapter-scope "${rawOpts.hostAdapterScope}" (expected: ${VALID_SCOPES.join(', ')})`,
        );
        process.exit(2);
      }
      for (const [flag, value] of [
        ['--skill-scope', rawOpts.skillScope],
        ['--external-tool-scope', rawOpts.externalToolScope],
        ['--codegraph-mcp-scope', rawOpts.codegraphMcpScope],
      ] as const) {
        if (value && !VALID_SCOPES.includes(value as InstallScope)) {
          console.error(`local-repo-harness bootstrap: invalid ${flag} "${value}" (expected: ${VALID_SCOPES.join(', ')})`);
          process.exit(2);
        }
      }
      if (!isRuntimeSelection(rawOpts.runtime ?? 'project-vendored-bun')) {
        console.error(
          `local-repo-harness bootstrap: invalid --runtime "${rawOpts.runtime}" (expected: ${VALID_RUNTIMES.join(', ')})`,
        );
        process.exit(2);
      }
      const result = runBootstrap({
        repo: rawOpts.repo,
        target: rawOpts.target as InstallTargetSpec,
        packageSpec: rawOpts.package,
        version: rawOpts.version,
        channel: rawOpts.channel,
        syncSkill: rawOpts.syncSkill !== false,
        skillScope: rawOpts.skillScope as ToolingScope | undefined,
        hostAdapters: rawOpts.hostAdapters !== false,
        hostAdapterScope: rawOpts.hostAdapterScope as InstallScope,
        runtime: rawOpts.runtime as RuntimeSelection,
        externalSkills: rawOpts.externalSkills !== false,
        externalToolScope: rawOpts.externalToolScope as ToolingScope | undefined,
        verify: rawOpts.verify !== false,
        codegraph: rawOpts.codegraph !== false,
        codegraphMcpScope: rawOpts.codegraphMcpScope as ToolingScope | undefined,
        syncCodegraph: rawOpts.syncCodegraph === true,
        brainMode: rawOpts.brainMode as InitBrainMode,
        json: rawOpts.json === true,
      });
      if (rawOpts.json === true) {
        console.log(JSON.stringify(result, null, 2));
      } else {
        for (const line of result.lines) console.log(line);
      }
      process.exit(result.exitCode);
    });

  program
    .command('adopt')
    .description('Install or refresh the repo-local harness workflow in an existing repo')
    .argument('[action]', 'Optional action: rollback')
    .option('--repo <path>', 'Target repository path (defaults to cwd)')
    .option('--archive <path>', 'Runtime reclaim archive to restore when action is rollback')
    .option('--dry-run', 'Plan repo harness changes without applying them')
    .option('--target <target>', `Host target for readiness checks and optional global bootstrap: ${VALID_TARGETS.join('|')}`, 'both')
    .option('--no-sync-skill', 'Skip repo-harness skill alias installation')
    .option('--skill-scope <scope>', `repo-harness-owned skill scope: ${VALID_SCOPES.join('|')} (default: none)`, 'none')
    .option('--no-host-adapters', 'Skip writing Codex/Claude hook adapters')
    .option('--host-adapter-scope <scope>', `Hook adapter scope: ${VALID_SCOPES.join('|')} (default: none)`, 'none')
    .option('--runtime <runtime>', `Hook runtime mode: ${VALID_RUNTIMES.join('|')} (default: auto)`, 'auto')
    .option('--no-external-skills', 'Skip Waza and Mermaid third-party skill bootstrap')
    .option('--external-tool-scope <scope>', `Third-party tooling scope: ${VALID_SCOPES.join('|')} (default: none)`, 'none')
    .option('--no-verify', 'Skip repo workflow verification after apply')
    .option('--no-codegraph', 'Skip building the CodeGraph index and MCP readiness check')
    .option('--reclaim-runtime', 'Reclaim generated repo-local hook/helper runtime copies after replacement paths verify')
    .option('--compact', 'Compact repo surface; includes --reclaim-runtime plus package script rewrite')
    .option('--mode <mode>', 'Adoption mode: minimal|standard|self-host', 'standard')
    .option('--configure-codegraph', 'Deprecated: user-level MCP config belongs to local-repo-harness update/setup')
    .option('--codegraph-mcp-scope <scope>', `CodeGraph MCP scope: ${VALID_SCOPES.join('|')} (default: none)`, 'none')
    .option('--sync-codegraph', 'Sync the CodeGraph index after ensure')
    .option('--brain-root <path>', 'Deprecated: user-level brain config belongs to local-repo-harness update/setup')
    .option('--brain-mode <mode>', 'Repo-local brain mode: skip|manifest-only', 'skip')
    .option('--interactive', 'Run the numbered interactive install planner')
    .option('--json', 'Output JSON instead of human-readable text')
    .action(async (action: string | undefined, rawOpts: {
      repo?: string;
      archive?: string;
      dryRun?: boolean;
      target: string;
      syncSkill?: boolean;
      skillScope?: string;
      hostAdapters?: boolean;
      hostAdapterScope?: string;
      runtime?: string;
      externalSkills?: boolean;
      externalToolScope?: string;
      verify?: boolean;
      codegraph?: boolean;
      reclaimRuntime?: boolean;
      compact?: boolean;
      mode?: string;
      configureCodegraph?: boolean;
      codegraphMcpScope?: string;
      syncCodegraph?: boolean;
      brainRoot?: string;
      brainMode?: string;
      interactive?: boolean;
      json?: boolean;
    }) => {
      if (action) {
        if (action !== 'rollback') {
          console.error(`local-repo-harness adopt: unknown action "${action}"`);
          process.exit(2);
        }
        if (!rawOpts.archive) {
          console.error('local-repo-harness adopt rollback: --archive is required');
          process.exit(2);
        }
        const rollback = runRuntimeRollback({ repo: rawOpts.repo, archive: rawOpts.archive });
        if (rawOpts.json === true) {
          console.log(JSON.stringify(rollback, null, 2));
        } else {
          console.log(`[adopt] ${rollback.status}: rollback runtime archive ${rollback.archive}`);
          for (const restored of rollback.restored) console.log(`[adopt] restored: ${restored}`);
          for (const missing of rollback.missing) console.log(`[adopt] missing: ${missing}`);
        }
        process.exit(rollback.status === 'ok' ? 0 : 1);
      }
      if (!VALID_TARGETS.includes(rawOpts.target as InstallTargetSpec)) {
        console.error(
          `local-repo-harness adopt: invalid --target "${rawOpts.target}" (expected: ${VALID_TARGETS.join(', ')})`,
        );
        process.exit(2);
      }
      if (!['skip', 'manifest-only', 'install-gbrain-cli'].includes(rawOpts.brainMode ?? 'skip')) {
        console.error('local-repo-harness adopt: invalid --brain-mode (expected: skip, manifest-only, install-gbrain-cli)');
        process.exit(2);
      }
      if (!['minimal', 'standard', 'self-host'].includes(rawOpts.mode ?? 'standard')) {
        console.error('local-repo-harness adopt: invalid --mode (expected: minimal, standard, self-host)');
        process.exit(2);
      }
      if (rawOpts.configureCodegraph === true) {
        console.error('local-repo-harness adopt: --configure-codegraph writes user-level MCP config; run local-repo-harness update instead');
        process.exit(2);
      }
      if (rawOpts.brainRoot || rawOpts.brainMode === 'install-gbrain-cli') {
        console.error('local-repo-harness adopt: user-level brain configuration belongs to local-repo-harness update/init');
        process.exit(2);
      }
      if (!VALID_SCOPES.includes(rawOpts.hostAdapterScope as InstallScope)) {
        console.error(
          `local-repo-harness adopt: invalid --host-adapter-scope "${rawOpts.hostAdapterScope}" (expected: ${VALID_SCOPES.join(', ')})`,
        );
        process.exit(2);
      }
      for (const [flag, value] of [
        ['--skill-scope', rawOpts.skillScope],
        ['--external-tool-scope', rawOpts.externalToolScope],
        ['--codegraph-mcp-scope', rawOpts.codegraphMcpScope],
      ] as const) {
        if (value && !VALID_SCOPES.includes(value as InstallScope)) {
          console.error(`local-repo-harness adopt: invalid ${flag} "${value}" (expected: ${VALID_SCOPES.join(', ')})`);
          process.exit(2);
        }
      }
      if (!isRuntimeSelection(rawOpts.runtime ?? 'auto')) {
        console.error(
          `local-repo-harness adopt: invalid --runtime "${rawOpts.runtime}" (expected: ${VALID_RUNTIMES.join(', ')})`,
        );
        process.exit(2);
      }
      const common = {
        repo: rawOpts.repo,
        apply: rawOpts.dryRun !== true,
        target: rawOpts.target as InstallTargetSpec,
        syncSkill: rawOpts.syncSkill !== false,
        skillScope: rawOpts.skillScope as ToolingScope | undefined,
        hostAdapters: rawOpts.hostAdapters !== false,
        hostAdapterScope: rawOpts.hostAdapterScope as InstallScope,
        runtime: rawOpts.runtime as RuntimeSelection,
        externalSkills: rawOpts.externalSkills !== false,
        externalToolScope: rawOpts.externalToolScope as ToolingScope | undefined,
        verify: rawOpts.verify !== false,
        codegraph: rawOpts.codegraph !== false,
        configureCodegraphMcp: false,
        codegraphMcpScope: rawOpts.codegraphMcpScope as ToolingScope | undefined,
        syncCodegraph: rawOpts.syncCodegraph === true,
        brainRoot: rawOpts.brainRoot,
        brainMode: rawOpts.brainMode as InitBrainMode,
      };
      const result = rawOpts.interactive === true
        ? await runInteractiveInit({
            ...common,
            output: rawOpts.json === true ? process.stderr : process.stdout,
          })
        : runInit(common);
      const shouldReclaim = rawOpts.reclaimRuntime === true || rawOpts.compact === true;
      const reclaim = shouldReclaim && (result.exitCode === 0 || rawOpts.dryRun === true)
        ? runRuntimeReclaim({
            repo: result.repoRoot,
            apply: rawOpts.dryRun !== true,
            compact: rawOpts.compact === true,
            verify: rawOpts.verify !== false,
            mode: rawOpts.mode as 'minimal' | 'standard' | 'self-host',
          })
        : null;
      if (rawOpts.json === true) {
        console.log(JSON.stringify(reclaim ? { adopt: result, runtime_reclaim: reclaim } : result, null, 2));
      } else {
        for (const line of result.lines) console.log(line);
        if (reclaim) {
          console.log(`[adopt] ${reclaim.status}: reclaim runtime - files=${reclaim.runtime_reclaim.files.length}`);
          if (reclaim.runtime_reclaim.archive) console.log(`[adopt] archive: ${reclaim.runtime_reclaim.archive}`);
          for (const blocked of reclaim.runtime_reclaim.blocked) console.log(`[adopt] blocked: ${blocked}`);
        }
      }
      process.exit(result.exitCode || (reclaim?.status === 'blocked' ? 1 : 0));
    });

  program
    .command('install')
    .description('Install hook adapters into Codex and/or Claude host config')
    .requiredOption('--target <target>', `Target host: ${VALID_TARGETS.join('|')}`)
    .option('--location <location>', `Install location: ${VALID_LOCATIONS.join('|')}`)
    .option('--scope <scope>', `Install scope: ${VALID_SCOPES.join('|')}`)
    .option('--runtime <runtime>', `Hook runtime mode: ${VALID_RUNTIMES.join('|')} (default: auto)`, 'auto')
    .action((rawOpts: { target: string; location?: string; scope?: string; runtime?: string }) => {
      if (!VALID_TARGETS.includes(rawOpts.target as InstallTargetSpec)) {
        console.error(
          `local-repo-harness install: invalid --target "${rawOpts.target}" (expected: ${VALID_TARGETS.join(', ')})`,
        );
        process.exit(2);
      }
      if (rawOpts.location && rawOpts.scope) {
        console.error('local-repo-harness install: use either --location or --scope, not both');
        process.exit(2);
      }
      if (!rawOpts.location && !rawOpts.scope) {
        console.error('local-repo-harness install: one of --location or --scope is required');
        process.exit(2);
      }
      if (rawOpts.location && !VALID_LOCATIONS.includes(rawOpts.location as Location)) {
        console.error(
          `local-repo-harness install: invalid --location "${rawOpts.location}" (expected: ${VALID_LOCATIONS.join(', ')})`,
        );
        process.exit(2);
      }
      if (rawOpts.scope && !VALID_SCOPES.includes(rawOpts.scope as InstallScope)) {
        console.error(
          `local-repo-harness install: invalid --scope "${rawOpts.scope}" (expected: ${VALID_SCOPES.join(', ')})`,
        );
        process.exit(2);
      }
      if (!isRuntimeSelection(rawOpts.runtime ?? 'auto')) {
        console.error(
          `local-repo-harness install: invalid --runtime "${rawOpts.runtime}" (expected: ${VALID_RUNTIMES.join(', ')})`,
        );
        process.exit(2);
      }
      const result = runInstall({
        target: rawOpts.target as InstallTargetSpec,
        location: rawOpts.location as Location | undefined,
        scope: rawOpts.scope as InstallScope | undefined,
        runtime: rawOpts.runtime as RuntimeSelection,
      });
      for (const line of result.lines) console.log(line);
      process.exit(result.exitCode);
    });

  program
    .command('uninstall')
    .description('Remove repo-harness-managed hook adapters from Codex and/or Claude host config')
    .requiredOption('--target <target>', `Target host: ${VALID_TARGETS.join('|')}`)
    .option('--location <location>', `Install location: ${VALID_LOCATIONS.join('|')}`)
    .option('--scope <scope>', `Install scope: ${VALID_SCOPES.join('|')}`)
    .action((rawOpts: { target: string; location?: string; scope?: string }) => {
      if (!VALID_TARGETS.includes(rawOpts.target as InstallTargetSpec)) {
        console.error(
          `local-repo-harness uninstall: invalid --target "${rawOpts.target}" (expected: ${VALID_TARGETS.join(', ')})`,
        );
        process.exit(2);
      }
      if (rawOpts.location && rawOpts.scope) {
        console.error('local-repo-harness uninstall: use either --location or --scope, not both');
        process.exit(2);
      }
      if (!rawOpts.location && !rawOpts.scope) {
        console.error('local-repo-harness uninstall: one of --location or --scope is required');
        process.exit(2);
      }
      if (rawOpts.location && !VALID_LOCATIONS.includes(rawOpts.location as Location)) {
        console.error(
          `local-repo-harness uninstall: invalid --location "${rawOpts.location}" (expected: ${VALID_LOCATIONS.join(', ')})`,
        );
        process.exit(2);
      }
      if (rawOpts.scope && !VALID_SCOPES.includes(rawOpts.scope as InstallScope)) {
        console.error(
          `local-repo-harness uninstall: invalid --scope "${rawOpts.scope}" (expected: ${VALID_SCOPES.join(', ')})`,
        );
        process.exit(2);
      }
      const result = runUninstall({
        target: rawOpts.target as InstallTargetSpec,
        location: rawOpts.location as Location | undefined,
        scope: rawOpts.scope as InstallScope | undefined,
      });
      for (const line of result.lines) console.log(line);
      process.exit(result.exitCode);
    });

  program
    .command('hook')
    .description('Dispatch a hook event to opt-in repo .ai/hooks/<script>')
    .argument('<event>', 'Hook event name')
    .requiredOption('--route <route>', 'Route id (default, edit, bash, always)')
    .action((event: string, rawOpts: { route: string }) => {
      const result = runHook({
        event: event as HookEvent,
        routeId: rawOpts.route as RouteId,
      });
      process.exit(result.exitCode);
    });

  program
    .command('status')
    .description('Show CLI version, host install status, route coverage, and repo opt-in state')
    .option('--json', 'Output JSON instead of human-readable text')
    .action((rawOpts: { json?: boolean }) => {
      const report = runStatus();
      console.log(formatStatus(report, rawOpts.json === true));
      process.exit(0);
    });

  program
    .command('doctor')
    .description('Run read-only readiness diagnostics (PATH, version, hosts, trust state)')
    .option('--json', 'Output JSON instead of human-readable text')
    .action((rawOpts: { json?: boolean }) => {
      const report = runDoctor();
      console.log(formatDoctor(report, rawOpts.json === true));
      process.exit(report.summary.fail > 0 ? 1 : 0);
    });

  program.addCommand(buildInitHookCommand());
  program.addCommand(buildSetupCommand());

  program
    .command('migrate')
    .description('Remove retired project-level hook adapters while preserving managed project/user adapters')
    .option('--apply', 'Commit changes (default is dry-run)')
    .option('--json', 'Output JSON plan')
    .action((rawOpts: { apply?: boolean; json?: boolean }) => {
      const plan = runMigrate({ apply: rawOpts.apply === true });
      console.log(formatMigratePlan(plan, rawOpts.json === true));
      process.exit(0);
    });

  const security = program
    .command('security')
    .description('Read-only security checks for local hook and editor task configs');
  security
    .command('scan')
    .description('Scan Claude/Codex hook configs and VS Code folder-open tasks')
    .option('--json', 'Output JSON instead of human-readable text')
    .option('--scope <scope>', `Scan scope: ${SECURITY_SCAN_SCOPES.join('|')}`, 'all')
    .option('--strict', 'Exit non-zero when high-risk or failed findings are present')
    .action((rawOpts: { json?: boolean; scope?: string; strict?: boolean }) => {
      const scope = rawOpts.scope ?? 'all';
      if (!SECURITY_SCAN_SCOPES.includes(scope as SecurityScanScope)) {
        console.error(`local-repo-harness security scan: invalid --scope "${scope}" (expected: ${SECURITY_SCAN_SCOPES.join(', ')})`);
        process.exit(2);
      }
      const report = runSecurityScan({ scope: scope as SecurityScanScope });
      console.log(formatSecurityScan(report, rawOpts.json === true));
      const strictFailure = report.findings.some((finding) => finding.severity === 'high' || finding.severity === 'fail');
      process.exit(rawOpts.strict === true && strictFailure ? 1 : 0);
    });

  program.addCommand(buildToolsCommand());
  program.addCommand(buildBrainCommand());
  program.addCommand(buildCapabilityContextCommand());
  program.addCommand(buildDocsCommand());
  program.addCommand(buildRunCommand());
  program
    .command('prompt-guard-decide', { hidden: true })
    .description('Internal prompt-guard intent/state decision engine')
    .action(() => {
      console.log(runPromptGuardDecideCli());
      process.exit(0);
    });

  return program;
}

if (import.meta.main) {
  try {
    await buildProgram().parseAsync(process.argv);
  } catch (err) {
    const e = err as { exitCode?: number; message?: string };
    if (typeof e.exitCode === 'number') process.exit(e.exitCode);
    if (e.message) console.error(e.message);
    process.exit(1);
  }
}
