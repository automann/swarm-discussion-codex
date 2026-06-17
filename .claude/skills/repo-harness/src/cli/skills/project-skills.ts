import {
  chmodSync,
  copyFileSync,
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  readlinkSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "fs";
import { dirname, join, relative, resolve } from "path";
import type { InstallTargetSpec } from "../commands/install";

export type ToolingScope = "project" | "user" | "none";
export type SkillHost = "codex" | "claude";

export interface SkillInstallStep {
  step: string;
  status: "ok" | "skipped" | "failed";
  detail?: string;
  stdout?: string;
  stderr?: string;
}

export interface SkillRootOptions {
  scope: ToolingScope;
  host: SkillHost;
  repoRoot: string;
  env?: NodeJS.ProcessEnv;
}

export interface RepoHarnessSkillInstallOptions {
  sourceRoot: string;
  repoRoot: string;
  target: InstallTargetSpec;
  scope: ToolingScope;
  env?: NodeJS.ProcessEnv;
}

const ROOT_EXCLUDES = new Set([
  ".git",
  ".codegraph",
  ".agents",
  "_ops",
  "_ref",
  "dev-plans",
  "node_modules",
  ".codex",
]);

const RELATIVE_EXCLUDES = new Set([
  ".DS_Store",
  "evals/benchmark.md",
  ".claude/skills",
  ".claude/settings.local.json",
  ".claude/.atomic_pending",
  ".claude/.session-id",
  ".claude/.trace.jsonl",
  ".claude/.session-handoff.md",
  ".claude/.task-state.json",
  ".claude/.task-handoff.md",
  ".ai/harness/checks/latest.json",
  ".ai/harness/events.jsonl",
  ".ai/harness/failures/latest.jsonl",
  ".ai/harness/handoff/current.md",
  ".ai/harness/handoff/resume.md",
  ".ai/harness/architecture/events.jsonl",
]);

const RELATIVE_PREFIX_EXCLUDES = [
  ".claude/skills/",
  ".claude/.plan-state/",
  ".ai/harness/archive/",
  ".ai/harness/codegraph-runtime/",
  ".ai/harness/runs/",
  ".ai/harness/worktrees/",
];

const INSTALLED_COPY_MARKER = ".repo-harness-installed-copy";

function homeDir(env?: NodeJS.ProcessEnv): string | null {
  return env?.HOME ?? process.env.HOME ?? null;
}

export function skillHostsForTarget(target: InstallTargetSpec): SkillHost[] {
  if (target === "codex") return ["codex"];
  if (target === "claude") return ["claude"];
  return ["codex", "claude"];
}

export function skillRootFor(opts: SkillRootOptions): string | null {
  if (opts.scope === "none") return null;
  if (opts.scope === "project") {
    return join(opts.repoRoot, opts.host === "codex" ? ".agents" : ".claude", "skills");
  }
  const home = homeDir(opts.env);
  if (!home) return null;
  return join(home, opts.host === "codex" ? ".codex" : ".claude", "skills");
}

function normalizeRel(value: string): string {
  return value.replaceAll("\\", "/");
}

function shouldCopyFromSource(sourceRoot: string, src: string): boolean {
  const rel = normalizeRel(relative(sourceRoot, src));
  if (!rel) return true;
  const first = rel.split("/")[0];
  if (ROOT_EXCLUDES.has(first)) return false;
  if (RELATIVE_EXCLUDES.has(rel)) return false;
  if (RELATIVE_PREFIX_EXCLUDES.some((prefix) => rel.startsWith(prefix))) return false;
  if (/^\.claude\/.*\.(tmp|bak)(\..*)?$/.test(rel)) return false;
  return true;
}

export function syncDirectory(source: string, dest: string, sourceRoot = source): void {
  if (existsSync(dest)) rmSync(dest, { recursive: true, force: true });
  mkdirSync(dirname(dest), { recursive: true });
  copyRecursive(source, dest, sourceRoot);
}

function copyRecursive(source: string, dest: string, sourceRoot: string): void {
  if (!shouldCopyFromSource(sourceRoot, source)) return;
  const stat = lstatSync(source);
  if (stat.isDirectory()) {
    mkdirSync(dest, { recursive: true });
    chmodSync(dest, stat.mode);
    for (const entry of readdirSync(source)) {
      copyRecursive(join(source, entry), join(dest, entry), sourceRoot);
    }
    return;
  }
  if (stat.isSymbolicLink()) {
    mkdirSync(dirname(dest), { recursive: true });
    symlinkSync(readlinkSync(source), dest);
    return;
  }
  mkdirSync(dirname(dest), { recursive: true });
  copyFileSync(source, dest);
  chmodSync(dest, stat.mode);
}

export function syncSkillDirectory(source: string, dest: string): SkillInstallStep {
  const sourceSkill = join(source, "SKILL.md");
  const destSkill = join(dest, "SKILL.md");
  if (!existsSync(sourceSkill)) {
    return { step: "", status: "skipped", detail: `bundled source not found at ${source}` };
  }

  if (
    existsSync(destSkill) &&
    readFileSync(destSkill, "utf-8") === readFileSync(sourceSkill, "utf-8")
  ) {
    return { step: "", status: "ok", detail: "already present" };
  }

  if (existsSync(dest)) rmSync(dest, { recursive: true, force: true });
  mkdirSync(dest, { recursive: true });
  cpSync(source, dest, { recursive: true, force: true });
  return { step: "", status: "ok", detail: `synced ${dest}` };
}

function installedCopyDescription(scope: ToolingScope): string {
  return scope === "project" ? "project-scoped" : "user-scoped";
}

export function writeRepoHarnessInstalledCopyBoundary(dest: string, scope: ToolingScope, host: SkillHost): void {
  const scopeDescription = installedCopyDescription(scope);
  writeFileSync(
    join(dest, INSTALLED_COPY_MARKER),
    [
      "kind=repo-harness-installed-copy",
      `scope=${scope}`,
      `host=${host}`,
      "generated_by=repo-harness",
      "edit_policy=generated-install-state-do-not-edit-for-product-development",
      "",
    ].join("\n"),
  );
  writeFileSync(
    join(dest, "AGENTS.md"),
    [
      "# Installed repo-harness Skill Copy",
      "",
      `This directory is an installed ${scopeDescription} copy of repo-harness.`,
      "It is not the canonical repo-harness product source.",
      "",
      "- Do not edit this directory to develop repo-harness itself.",
      "- For product changes, edit the source checkout or package that produced this install, then reinstall.",
      "- For using the skill, read `SKILL.md`; treat this tree as generated install state.",
      "",
    ].join("\n"),
  );
}

export function installRepoHarnessProjectSkills(opts: RepoHarnessSkillInstallOptions): SkillInstallStep[] {
  if (opts.scope === "none") {
    return [{ step: "sync repo-harness skills", status: "skipped", detail: "scope=none" }];
  }

  const steps: SkillInstallStep[] = [];
  for (const host of skillHostsForTarget(opts.target)) {
    const root = skillRootFor({
      scope: opts.scope,
      host,
      repoRoot: opts.repoRoot,
      env: opts.env,
    });
    const stepName = `sync repo-harness ${host} skill`;
    if (!root) {
      steps.push({
        step: stepName,
        status: "failed",
        detail: `${opts.scope} skill root could not be resolved`,
      });
      continue;
    }
    const dest = join(root, "repo-harness");
    try {
      syncDirectory(resolve(opts.sourceRoot), dest, resolve(opts.sourceRoot));
      writeRepoHarnessInstalledCopyBoundary(dest, opts.scope, host);
      steps.push({ step: stepName, status: "ok", detail: `scope=${opts.scope}; ${dest}` });
    } catch (error) {
      steps.push({
        step: stepName,
        status: "failed",
        stderr: String((error as Error).message ?? error),
      });
    }
  }
  return steps;
}
