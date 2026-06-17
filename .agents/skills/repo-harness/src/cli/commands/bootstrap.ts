import { spawnSync } from "child_process";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from "fs";
import { dirname, join, resolve } from "path";
import type { InstallTargetSpec } from "./install";
import type { RuntimeSelection } from "../installer/hook-command";
import type { InstallScope } from "../installer/types";
import type { ToolingScope } from "../skills/project-skills";
import type { InitBrainMode } from "./init";

const HARNESS_PACKAGE = "local-repo-harness";
export const HARNESS_TOOL_DIR_REL = ".ai/harness/tools/local-repo-harness";
export const HARNESS_TOOL_BIN_REL = `${HARNESS_TOOL_DIR_REL}/node_modules/.bin/local-repo-harness`;
export const HARNESS_SHIM_REL = ".ai/harness/bin/local-repo-harness";

export interface BootstrapOptions {
  repo?: string;
  target?: InstallTargetSpec;
  syncSkill?: boolean;
  skillScope?: ToolingScope;
  hostAdapters?: boolean;
  hostAdapterScope?: InstallScope;
  runtime?: RuntimeSelection;
  externalSkills?: boolean;
  externalToolScope?: ToolingScope;
  verify?: boolean;
  codegraph?: boolean;
  codegraphMcpScope?: ToolingScope;
  syncCodegraph?: boolean;
  brainMode?: InitBrainMode;
  packageSpec?: string;
  version?: string;
  channel?: string;
  json?: boolean;
  env?: NodeJS.ProcessEnv;
}

export interface BootstrapStep {
  step: string;
  status: "ok" | "skipped" | "failed";
  exitCode?: number | null;
  command?: string[];
  detail?: string;
  stdout?: string;
  stderr?: string;
}

export interface BootstrapDelegation {
  status: number | null;
  command: string[];
  stdout: string;
  stderr: string;
}

export interface BootstrapResult {
  exitCode: number;
  repoRoot: string;
  packageSpec: string;
  dependencySpec: string;
  toolRoot: string;
  shim: string;
  steps: BootstrapStep[];
  delegated?: BootstrapDelegation;
  lines: string[];
}

function trimOutput(value: string | undefined): string {
  return (value ?? "").trim();
}

function renderStep(step: BootstrapStep): string[] {
  const lines = [`[bootstrap] ${step.status}: ${step.step}${step.detail ? ` - ${step.detail}` : ""}`];
  if (step.status === "failed" && step.stderr?.trim()) lines.push(step.stderr.trim());
  return lines;
}

function runProcess(command: string, args: string[], cwd: string, env?: NodeJS.ProcessEnv): BootstrapStep {
  const result = spawnSync(command, args, {
    cwd,
    encoding: "utf-8",
    env: { ...process.env, ...(env ?? {}) },
  });
  return {
    step: "",
    status: result.status === 0 && !result.error ? "ok" : "failed",
    exitCode: result.status,
    command: [command, ...args],
    stdout: trimOutput(result.stdout),
    stderr: trimOutput(result.stderr || (result.error ? String(result.error) : "")),
  };
}

function readJson(path: string): Record<string, any> | null {
  try {
    const parsed = JSON.parse(readFileSync(path, "utf-8"));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function samePath(a: string, b: string): boolean {
  try {
    return realpathSync(a) === realpathSync(b);
  } catch {
    return resolve(a) === resolve(b);
  }
}

function homeDir(env?: NodeJS.ProcessEnv): string | null {
  return env?.HOME ?? process.env.HOME ?? process.env.USERPROFILE ?? null;
}

function isGitWorkTree(repoRoot: string, env?: NodeJS.ProcessEnv): boolean {
  const result = spawnSync("git", ["-C", repoRoot, "rev-parse", "--is-inside-work-tree"], {
    encoding: "utf-8",
    env: { ...process.env, ...(env ?? {}) },
  });
  return result.status === 0 && result.stdout.trim() === "true";
}

function validateBootstrapTarget(
  repoRoot: string,
  explicitRepo: boolean,
  env?: NodeJS.ProcessEnv,
): BootstrapStep | null {
  const home = homeDir(env);
  if (home && samePath(repoRoot, home)) {
    return {
      step: "validate repo target",
      status: "failed",
      detail:
        `refusing to bootstrap local-repo-harness into HOME (${repoRoot}); pass --repo <git-repo> for an intended project`,
    };
  }
  if (!explicitRepo && !isGitWorkTree(repoRoot, env)) {
    return {
      step: "validate repo target",
      status: "failed",
      detail:
        `cwd is not inside a git work tree (${repoRoot}); pass --repo <project-path> explicitly for non-git scaffolds`,
    };
  }
  return null;
}

function managedHarnessToolRoot(repoRoot: string): string {
  return join(repoRoot, HARNESS_TOOL_DIR_REL);
}

function managedHarnessShimPath(repoRoot: string): string {
  return join(repoRoot, HARNESS_SHIM_REL);
}

function resolveHarnessPackageSpec(opts: BootstrapOptions): string {
  if (opts.packageSpec?.trim()) return opts.packageSpec.trim();
  if (opts.version?.trim()) return `${HARNESS_PACKAGE}@${opts.version.trim()}`;
  if (opts.channel?.trim()) return `${HARNESS_PACKAGE}@${opts.channel.trim()}`;
  return `${HARNESS_PACKAGE}@latest`;
}

function dependencySpecFromPackageSpec(packageSpec: string): string {
  if (packageSpec === HARNESS_PACKAGE) return "latest";
  if (packageSpec.startsWith(`${HARNESS_PACKAGE}@`)) {
    return packageSpec.slice(HARNESS_PACKAGE.length + 1) || "latest";
  }
  return packageSpec;
}

function writeManagedHarnessShim(repoRoot: string): void {
  const shimPath = managedHarnessShimPath(repoRoot);
  mkdirSync(dirname(shimPath), { recursive: true });
  writeFileSync(
    shimPath,
    [
      "#!/usr/bin/env bash",
      "set -euo pipefail",
      'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
      'REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"',
      `BIN="$REPO_ROOT/${HARNESS_TOOL_BIN_REL}"`,
      'if [[ ! -x "$BIN" ]]; then',
      '  echo "local-repo-harness project runtime is missing; run: bunx --bun local-repo-harness@latest bootstrap --repo \\"$REPO_ROOT\\"" >&2',
      "  exit 127",
      "fi",
      'exec "$BIN" "$@"',
      "",
    ].join("\n"),
  );
  chmodSync(shimPath, 0o755);
}

function ensureManagedHarnessPackage(
  repoRoot: string,
  packageSpec: string,
  env?: NodeJS.ProcessEnv,
): BootstrapStep {
  const toolRoot = managedHarnessToolRoot(repoRoot);
  const packagePath = join(toolRoot, "package.json");
  const dependencySpec = dependencySpecFromPackageSpec(packageSpec);

  mkdirSync(toolRoot, { recursive: true });
  writeManagedHarnessShim(repoRoot);

  const current = existsSync(packagePath) ? readJson(packagePath) : {};
  if (existsSync(packagePath) && !current) {
    return {
      step: "install managed local-repo-harness",
      status: "failed",
      command: ["bun", "install"],
      stderr: `${packagePath} is not valid JSON; refusing to overwrite the managed local-repo-harness package boundary.`,
    };
  }

  const next = {
    ...(current ?? {}),
    private: true,
    dependencies: {
      ...((current?.dependencies && typeof current.dependencies === "object") ? current.dependencies : {}),
      [HARNESS_PACKAGE]: dependencySpec,
    },
  };
  writeFileSync(packagePath, `${JSON.stringify(next, null, 2)}\n`);

  const step = runProcess("bun", ["install"], toolRoot, env);
  return {
    ...step,
    step: "install managed local-repo-harness",
    detail: `toolRoot=${toolRoot}; package=${packageSpec}`,
  };
}

function buildAdoptArgs(opts: Required<Pick<
  BootstrapOptions,
  "target" | "syncSkill" | "skillScope" | "hostAdapters" | "hostAdapterScope" | "runtime" |
  "externalSkills" | "externalToolScope" | "verify" | "codegraph" | "codegraphMcpScope" |
  "syncCodegraph" | "brainMode" | "json"
>> & { repoRoot: string }): string[] {
  const args = [
    "adopt",
    "--repo",
    opts.repoRoot,
    "--target",
    opts.target,
  ];

  if (!opts.syncSkill) args.push("--no-sync-skill");
  args.push("--skill-scope", opts.skillScope);

  if (!opts.hostAdapters) args.push("--no-host-adapters");
  args.push("--host-adapter-scope", opts.hostAdapterScope);
  args.push("--runtime", opts.runtime);

  if (!opts.externalSkills) args.push("--no-external-skills");
  args.push("--external-tool-scope", opts.externalToolScope);

  args.push("--codegraph-mcp-scope", opts.codegraphMcpScope);
  if (!opts.codegraph) args.push("--no-codegraph");
  if (opts.syncCodegraph) args.push("--sync-codegraph");
  if (!opts.verify) args.push("--no-verify");
  args.push("--brain-mode", opts.brainMode);
  if (opts.json) args.push("--json");

  return args;
}

export function runBootstrap(opts: BootstrapOptions = {}): BootstrapResult {
  const repoRoot = resolve(opts.repo ?? process.cwd());
  const packageSpec = resolveHarnessPackageSpec(opts);
  const dependencySpec = dependencySpecFromPackageSpec(packageSpec);
  const toolRoot = managedHarnessToolRoot(repoRoot);
  const shim = managedHarnessShimPath(repoRoot);
  const steps: BootstrapStep[] = [];

  const targetError = validateBootstrapTarget(repoRoot, opts.repo !== undefined, opts.env);
  if (targetError) {
    steps.push(targetError);
    return {
      exitCode: 2,
      repoRoot,
      packageSpec,
      dependencySpec,
      toolRoot,
      shim,
      steps,
      lines: steps.flatMap(renderStep),
    };
  }

  const installStep = ensureManagedHarnessPackage(repoRoot, packageSpec, opts.env);
  steps.push(installStep);
  if (installStep.status !== "ok") {
    return {
      exitCode: 1,
      repoRoot,
      packageSpec,
      dependencySpec,
      toolRoot,
      shim,
      steps,
      lines: steps.flatMap(renderStep),
    };
  }

  const adoptArgs = buildAdoptArgs({
    repoRoot,
    target: opts.target ?? "both",
    syncSkill: opts.syncSkill !== false,
    skillScope: opts.skillScope ?? "project",
    hostAdapters: opts.hostAdapters !== false,
    hostAdapterScope: opts.hostAdapterScope ?? "project",
    runtime: opts.runtime ?? "project-vendored-bun",
    externalSkills: opts.externalSkills !== false,
    externalToolScope: opts.externalToolScope ?? "project",
    verify: opts.verify !== false,
    codegraph: opts.codegraph !== false,
    codegraphMcpScope: opts.codegraphMcpScope ?? "project",
    syncCodegraph: opts.syncCodegraph === true,
    brainMode: opts.brainMode ?? "manifest-only",
    json: opts.json === true,
  });
  const delegatedStep = runProcess(shim, adoptArgs, repoRoot, opts.env);
  steps.push({
    ...delegatedStep,
    step: "delegate adopt",
    detail: `via ${shim}`,
  });
  const delegated = {
    status: delegatedStep.exitCode ?? (delegatedStep.status === "ok" ? 0 : 1),
    command: [shim, ...adoptArgs],
    stdout: delegatedStep.stdout ?? "",
    stderr: delegatedStep.stderr ?? "",
  };
  const exitCode = delegated.status ?? (delegatedStep.status === "ok" ? 0 : 1);

  return {
    exitCode,
    repoRoot,
    packageSpec,
    dependencySpec,
    toolRoot,
    shim,
    steps,
    delegated,
    lines: steps.flatMap(renderStep),
  };
}
