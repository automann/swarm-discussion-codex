import { spawnSync } from "child_process";
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const CLAUDE_CODEGRAPH_ALLOWED_TOOLS_PATTERN = "mcp__codegraph__*";
const CLAUDE_CODEGRAPH_SERVER_NAME = "codegraph";
const CODEGRAPH_PACKAGE = "@colbymchenry/codegraph";
const CODEGRAPH_PACKAGE_VERSION = "1.0.1";
const CODEGRAPH_SCOPED_MCP_ARGS = ["serve", "--mcp", "--path", "."] as const;
const CODEGRAPH_SCOPED_MCP_TOML_ARGS = `[${CODEGRAPH_SCOPED_MCP_ARGS.map((arg) => JSON.stringify(arg)).join(", ")}]`;
const CODEGRAPH_RUNTIME_DIR_REL = ".ai/harness/codegraph-runtime";
const CODEGRAPH_TOOL_DIR_REL = ".ai/harness/tools/codegraph";
const CODEGRAPH_TOOL_BIN_REL = `${CODEGRAPH_TOOL_DIR_REL}/node_modules/.bin/codegraph`;
const CODEGRAPH_SHIM_REL = ".ai/harness/bin/codegraph";
const CODEGRAPH_TELEMETRY_ENV = {
  CODEGRAPH_TELEMETRY: "0",
  DO_NOT_TRACK: "1",
} as const;
const CODEGRAPH_PROJECT_MCP_ENV = {
  ...CODEGRAPH_TELEMETRY_ENV,
  CODEGRAPH_INSTALL_DIR: CODEGRAPH_RUNTIME_DIR_REL,
  CODEGRAPH_NO_DAEMON: "1",
} as const;

export type CodegraphSource = "local" | "global" | "missing";
export type CodegraphStatus = "present" | "warning" | "partial" | "missing";
export type CodegraphActionStatus = "changed" | "unchanged" | "failed" | "skipped";
export type CodegraphHostTarget = "codex" | "claude" | "both";
export type CodegraphConfigureLocation = "global" | "local";

export interface CodegraphResolveOptions {
  repoRoot: string;
  env?: NodeJS.ProcessEnv;
  host?: CodegraphHostTarget;
}

export interface CodegraphEnsureOptions extends CodegraphResolveOptions {
  checkOnly?: boolean;
  init?: boolean;
  sync?: boolean;
  installDeps?: boolean;
}

export interface CodegraphConfigureOptions extends CodegraphResolveOptions {
  target: CodegraphHostTarget;
  location: CodegraphConfigureLocation;
}

export interface CodegraphResolution {
  source: CodegraphSource;
  binPath: string | null;
  version: string | null;
  localBinPath: string | null;
  globalBinPath: string | null;
  globalFallbackUsed: boolean;
  drift: { local: string | null; global: string | null; using: string } | null;
}

export interface CodegraphCheckResult {
  status: CodegraphStatus;
  reason: string;
  resolution: CodegraphResolution;
  raw: Record<string, unknown>;
}

export interface CodegraphEnsureResult extends CodegraphCheckResult {
  changed: boolean;
  readOnly: boolean;
  actions: CodegraphAction[];
}

export interface CodegraphConfigureResult extends CodegraphCheckResult {
  target: CodegraphHostTarget;
  location: CodegraphConfigureLocation;
  changed: boolean;
  readOnly: false;
  actions: CodegraphAction[];
}

export interface CodegraphAction {
  action: string;
  status: CodegraphActionStatus;
  command: string[];
  stdout?: string;
  stderr?: string;
}

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(SCRIPT_DIR, "..", "..", "..");

function runJson(command: string, args: string[], repoRoot: string, env?: NodeJS.ProcessEnv) {
  const result = spawnSync(command, args, {
    cwd: repoRoot,
    encoding: "utf8",
    env: { ...process.env, ...(env ?? {}) },
  });

  if (result.status !== 0 || result.error) {
    throw new Error(result.stderr || result.stdout || String(result.error));
  }

  return JSON.parse(result.stdout);
}

function codegraphRuntimeEnv(repoRoot: string, env?: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  return {
    ...(env ?? {}),
    ...CODEGRAPH_TELEMETRY_ENV,
    CODEGRAPH_INSTALL_DIR:
      env?.REPO_HARNESS_CODEGRAPH_INSTALL_DIR ??
      process.env.REPO_HARNESS_CODEGRAPH_INSTALL_DIR ??
      join(repoRoot, CODEGRAPH_RUNTIME_DIR_REL),
  };
}

function codegraphMcpEnv(location: CodegraphConfigureLocation): Record<string, string> {
  return location === "local"
    ? { ...CODEGRAPH_PROJECT_MCP_ENV }
    : { ...CODEGRAPH_TELEMETRY_ENV };
}

function renderTomlInlineEnv(env: Record<string, string>): string {
  return `{ ${Object.entries(env)
    .map(([key, value]) => `${key} = ${JSON.stringify(value)}`)
    .join(", ")} }`;
}

function run(command: string, args: string[], cwd: string, env?: NodeJS.ProcessEnv) {
  const result = spawnSync(command, args, {
    cwd,
    encoding: "utf8",
    env: { ...process.env, ...(env ?? {}) },
  });

  return {
    ok: result.status === 0 && !result.error,
    status: result.status ?? 1,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    error: result.error ? String(result.error.message || result.error) : "",
  };
}

function trimOutput(value: string) {
  if (value.length <= 4096) return value;
  return `${value.slice(0, 4096)}\n[output truncated]`;
}

function readJson(path: string) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (_error) {
    return null;
  }
}

function readToolingReport(repoRoot: string, env?: NodeJS.ProcessEnv, host: CodegraphHostTarget = "codex") {
  const checker = join(REPO_ROOT, "scripts", "check-agent-tooling.sh");
  const report = runJson("bash", [checker, "--json", "--host", host], repoRoot, codegraphRuntimeEnv(repoRoot, env));
  return report.tools.codegraph;
}

function hasCodegraphDependency(repoRoot: string) {
  const pkg = readJson(join(repoRoot, "package.json"));
  return Boolean(
    pkg?.devDependencies?.[CODEGRAPH_PACKAGE] ||
      pkg?.dependencies?.[CODEGRAPH_PACKAGE] ||
      pkg?.optionalDependencies?.[CODEGRAPH_PACKAGE]
  );
}

function managedCodegraphPackageDir(repoRoot: string): string {
  return join(repoRoot, CODEGRAPH_TOOL_DIR_REL);
}

function managedCodegraphShimPath(repoRoot: string): string {
  return join(repoRoot, CODEGRAPH_SHIM_REL);
}

function writeManagedCodegraphShim(repoRoot: string): void {
  const shimPath = managedCodegraphShimPath(repoRoot);
  mkdirSync(dirname(shimPath), { recursive: true });
  writeFileSync(
    shimPath,
    [
      "#!/usr/bin/env bash",
      "set -euo pipefail",
      'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
      'REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"',
      `BIN="$REPO_ROOT/${CODEGRAPH_TOOL_BIN_REL}"`,
      'if [[ ! -x "$BIN" ]]; then',
      '  echo "CodeGraph project binary is missing; run: local-repo-harness tools ensure codegraph --repo \\"$REPO_ROOT\\"" >&2',
      "  exit 127",
      "fi",
      'export CODEGRAPH_TELEMETRY="${CODEGRAPH_TELEMETRY:-0}"',
      'export DO_NOT_TRACK="${DO_NOT_TRACK:-1}"',
      `export CODEGRAPH_INSTALL_DIR="\${CODEGRAPH_INSTALL_DIR:-$REPO_ROOT/${CODEGRAPH_RUNTIME_DIR_REL}}"`,
      'exec "$BIN" "$@"',
      "",
    ].join("\n"),
  );
  chmodSync(shimPath, 0o755);
}

function ensureManagedCodegraphPackage(repoRoot: string, env?: NodeJS.ProcessEnv): CodegraphAction {
  const toolDir = managedCodegraphPackageDir(repoRoot);
  const packagePath = join(toolDir, "package.json");
  const command = ["bun", "install"];

  mkdirSync(toolDir, { recursive: true });
  writeManagedCodegraphShim(repoRoot);

  if (existsSync(packagePath) && !readJson(packagePath)) {
    return {
      action: "install-managed-deps",
      status: "failed",
      command,
      stderr: `${packagePath} is not valid JSON; refusing to overwrite the managed CodeGraph package boundary.`,
    };
  }

  if (!existsSync(packagePath)) {
    writeFileSync(
      packagePath,
      `${JSON.stringify(
        {
          private: true,
          dependencies: {
            [CODEGRAPH_PACKAGE]: CODEGRAPH_PACKAGE_VERSION,
          },
        },
        null,
        2,
      )}\n`,
    );
  }

  const result = run("bun", ["install"], toolDir, env);
  return {
    action: "install-managed-deps",
    status: result.ok ? "changed" : "failed",
    command,
    stdout: trimOutput(result.stdout),
    stderr: trimOutput(result.stderr || result.error),
  };
}

function appendAction(
  actions: CodegraphAction[],
  action: string,
  command: string[],
  result: ReturnType<typeof run>
): boolean {
  actions.push({
    action,
    status: result.ok ? "changed" : "failed",
    command,
    stdout: trimOutput(result.stdout),
    stderr: trimOutput(result.stderr || result.error),
  });
  return result.ok;
}

function appendCodegraphInstallAction(
  actions: CodegraphAction[],
  action: string,
  command: string[],
  result: ReturnType<typeof run>
): boolean {
  const unsupportedLocal =
    result.ok &&
    /skipped.*does not support --location=local|does not support --location=local.*skipped/i.test(
      `${result.stdout}\n${result.stderr}`
    );
  actions.push({
    action,
    status: result.ok ? (unsupportedLocal ? "skipped" : "changed") : "failed",
    command,
    stdout: trimOutput(result.stdout),
    stderr: unsupportedLocal
      ? "CodeGraph installer reported that this target does not support --location=local; repo-harness will write supported project config when available."
      : trimOutput(result.stderr || result.error),
  });
  return result.ok;
}

function normalize(raw: Record<string, any>): CodegraphCheckResult {
  return {
    status: raw.status,
    reason: raw.reason,
    resolution: {
      source: raw.source,
      binPath: raw.bin_path,
      version: raw.version,
      localBinPath: raw.local_bin_path,
      globalBinPath: raw.global_bin_path,
      globalFallbackUsed: Boolean(raw.global_fallback_used),
      drift: raw.drift,
    },
    raw,
  };
}

export function checkCodegraph(opts: CodegraphResolveOptions): CodegraphCheckResult {
  return normalize(readToolingReport(opts.repoRoot, opts.env, opts.host));
}

export function resolveCodegraph(opts: CodegraphResolveOptions): CodegraphResolution {
  return checkCodegraph(opts).resolution;
}

export function ensureCodegraph(opts: CodegraphEnsureOptions): CodegraphEnsureResult {
  const actions: CodegraphAction[] = [];

  if (opts.checkOnly) {
    return {
      ...checkCodegraph(opts),
      changed: false,
      readOnly: true,
      actions,
    };
  }

  let codegraph = readToolingReport(opts.repoRoot, opts.env, opts.host);
  const projectMcpIntent = codegraph.mcp_intent === "project";
  if (opts.installDeps !== false && !codegraph.local_bin_path && projectMcpIntent) {
    actions.push(ensureManagedCodegraphPackage(opts.repoRoot, opts.env));
    codegraph = readToolingReport(opts.repoRoot, opts.env, opts.host);
  } else if (opts.installDeps !== false && hasCodegraphDependency(opts.repoRoot) && !codegraph.local_bin_path) {
    appendAction(actions, "install-deps", ["bun", "install"], run("bun", ["install"], opts.repoRoot, opts.env));
    codegraph = readToolingReport(opts.repoRoot, opts.env, opts.host);
  }

  const binPath = codegraph.bin_path;
  if (binPath && opts.init && codegraph.project_index?.status === "not-initialized") {
    appendAction(actions, "init-index", [binPath, "init", "-i", "."], run(binPath, ["init", "-i", "."], opts.repoRoot, codegraphRuntimeEnv(opts.repoRoot, opts.env)));
    codegraph = readToolingReport(opts.repoRoot, opts.env, opts.host);
  }

  if (binPath && opts.sync) {
    mkdirSync(join(opts.repoRoot, ".codegraph"), { recursive: true });
    appendAction(actions, "sync-index", [binPath, "sync", "."], run(binPath, ["sync", "."], opts.repoRoot, codegraphRuntimeEnv(opts.repoRoot, opts.env)));
    codegraph = readToolingReport(opts.repoRoot, opts.env, opts.host);
  }

  const normalized = normalize(codegraph);
  return {
    ...normalized,
    changed: actions.some((entry) => entry.status === "changed"),
    readOnly: false,
    actions,
  };
}

function configureTargets(target: CodegraphHostTarget): Array<"codex" | "claude"> {
  return target === "both" ? ["codex", "claude"] : [target];
}

function isMcpHostConfigured(raw: Record<string, unknown>, target: "codex" | "claude"): boolean {
  const hosts = (raw as { mcp_hosts?: Record<string, { status?: string }> }).mcp_hosts ?? {};
  return hosts[target]?.status === "configured";
}

function appendSkippedAction(actions: CodegraphAction[], action: string, command: string[], reason: string): void {
  actions.push({
    action,
    status: "skipped",
    command,
    stderr: reason,
  });
}

function claudeSettingsPath(env?: NodeJS.ProcessEnv): string | null {
  const home = env?.HOME ?? process.env.HOME ?? process.env.USERPROFILE;
  return home ? join(home, ".claude", "settings.json") : null;
}

function claudeRootConfigPath(env?: NodeJS.ProcessEnv): string | null {
  const home = env?.HOME ?? process.env.HOME ?? process.env.USERPROFILE;
  return home ? join(home, ".claude.json") : null;
}

function codexConfigPath(location: CodegraphConfigureLocation, repoRoot: string, env?: NodeJS.ProcessEnv): string | null {
  if (location === "local") return join(repoRoot, ".codex", "config.toml");
  const home = env?.HOME ?? process.env.HOME ?? process.env.USERPROFILE;
  return home ? join(home, ".codex", "config.toml") : null;
}

function codegraphArgsAreScoped(args: unknown): boolean {
  return Array.isArray(args) &&
    args.length === CODEGRAPH_SCOPED_MCP_ARGS.length &&
    args.every((arg, index) => arg === CODEGRAPH_SCOPED_MCP_ARGS[index]);
}

function configureCodexProjectPath(
  actions: CodegraphAction[],
  repoRoot: string,
  location: CodegraphConfigureLocation,
  env?: NodeJS.ProcessEnv,
): void {
  const path = codexConfigPath(location, repoRoot, env);
  const command = ["codex-config", "scope-codegraph-mcp", path ?? "<HOME>/.codex/config.toml"];

  if (!path) {
    actions.push({
      action: "codex-project-path",
      status: "skipped",
      command,
      stderr: "HOME environment variable not set; cannot locate ~/.codex/config.toml.",
    });
    return;
  }

  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch (_error) {
    if (location === "local") {
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, renderCodexCodegraphConfig(repoRoot, location));
      actions.push({
        action: "codex-project-path",
        status: "changed",
        command,
      });
      return;
    }
    actions.push({
      action: "codex-project-path",
      status: "skipped",
      command,
      stderr: `${path} not found; CodeGraph did not create a Codex MCP config.`,
    });
    return;
  }

  const sectionMatch = raw.match(/(^\[mcp_servers\.codegraph\]\n)([\s\S]*?)(?=^\[|(?![\s\S]))/m);
  if (!sectionMatch) {
    if (location === "local") {
      const next = `${raw.trimEnd()}${raw.trimEnd() ? "\n\n" : ""}${renderCodexCodegraphConfig(repoRoot, location)}`;
      writeFileSync(path, next);
      actions.push({
        action: "codex-project-path",
        status: "changed",
        command,
      });
      return;
    }
    actions.push({
      action: "codex-project-path",
      status: "skipped",
      command,
      stderr: "Codex CodeGraph MCP server entry was not found; run codegraph install first.",
    });
    return;
  }

  const [section, header, body] = sectionMatch;
  const desiredArgsLine = `args = ${CODEGRAPH_SCOPED_MCP_TOML_ARGS}`;
  const desiredCommandLine = `command = ${JSON.stringify(localCodegraphCommand(repoRoot))}`;
  const desiredEnvLine = `env = ${renderTomlInlineEnv(codegraphMcpEnv(location))}`;
  const commandLine = body.match(/^command\s*=\s*(.+)$/m)?.[1]?.trim();
  const argsLine = body.match(/^args\s*=\s*(.+)$/m)?.[1]?.trim();
  const envLine = body.match(/^env\s*=\s*(.+)$/m)?.[1]?.trim();
  if (
    argsLine === CODEGRAPH_SCOPED_MCP_TOML_ARGS &&
    envLine === renderTomlInlineEnv(codegraphMcpEnv(location)) &&
    (location !== "local" || commandLine === JSON.stringify(localCodegraphCommand(repoRoot)))
  ) {
    actions.push({
      action: "codex-project-path",
      status: "unchanged",
      command,
    });
    return;
  }

  let nextBody = body;
  if (location === "local") {
    if (/^command\s*=/m.test(nextBody)) {
      nextBody = nextBody.replace(/^command\s*=.*$/m, desiredCommandLine);
    } else {
      nextBody = `${desiredCommandLine}\n${nextBody}`;
    }
  }
  if (/^args\s*=/m.test(body)) {
    nextBody = nextBody.replace(/^args\s*=.*$/m, desiredArgsLine);
  } else if (/^command\s*=/m.test(nextBody)) {
    nextBody = nextBody.replace(/^(command\s*=.*)$/m, `$1\n${desiredArgsLine}`);
  } else {
    nextBody = `${desiredArgsLine}\n${nextBody}`;
  }
  if (/^env\s*=/m.test(nextBody)) {
    nextBody = nextBody.replace(/^env\s*=.*$/m, desiredEnvLine);
  } else if (/^args\s*=/m.test(nextBody)) {
    nextBody = nextBody.replace(/^(args\s*=.*)$/m, `$1\n${desiredEnvLine}`);
  } else {
    nextBody = `${nextBody.trimEnd()}\n${desiredEnvLine}\n`;
  }

  const next = raw.replace(section, `${header}${nextBody}`);
  try {
    writeFileSync(path, next);
  } catch (error) {
    actions.push({
      action: "codex-project-path",
      status: "failed",
      command,
      stderr: `Failed to write ${path}: ${String((error as Error).message ?? error)}`,
    });
    return;
  }

  actions.push({
    action: "codex-project-path",
    status: "changed",
    command,
  });
}

function localCodegraphCommand(_repoRoot: string): string {
  return `./${CODEGRAPH_SHIM_REL}`;
}

function renderCodexCodegraphConfig(repoRoot: string, location: CodegraphConfigureLocation): string {
  return [
    "[mcp_servers.codegraph]",
    `command = ${JSON.stringify(localCodegraphCommand(repoRoot))}`,
    `args = ${CODEGRAPH_SCOPED_MCP_TOML_ARGS}`,
    `env = ${renderTomlInlineEnv(codegraphMcpEnv(location))}`,
    "",
  ].join("\n");
}

function renderClaudeCodegraphConfig(repoRoot: string, location: CodegraphConfigureLocation): Record<string, unknown> {
  return {
    mcpServers: {
      [CLAUDE_CODEGRAPH_SERVER_NAME]: {
        type: "stdio",
        command: location === "local" ? localCodegraphCommand(repoRoot) : "codegraph",
        args: [...CODEGRAPH_SCOPED_MCP_ARGS],
        env: codegraphMcpEnv(location),
      },
    },
  };
}

function writeClaudeMcpJson(
  actions: CodegraphAction[],
  path: string,
  command: string[],
  parsed: Record<string, any>,
  raw = "",
): void {
  const trailingNewline = raw.endsWith("\n") ? "\n" : "";
  try {
    writeFileSync(path, `${JSON.stringify(parsed, null, 2)}${trailingNewline || "\n"}`);
  } catch (error) {
    actions.push({
      action: "claude-project-path",
      status: "failed",
      command,
      stderr: `Failed to write ${path}: ${String((error as Error).message ?? error)}`,
    });
    return;
  }

  actions.push({
    action: "claude-project-path",
    status: "changed",
    command,
  });
}

function configureClaudeProjectPath(
  actions: CodegraphAction[],
  repoRoot: string,
  location: CodegraphConfigureLocation,
  env?: NodeJS.ProcessEnv,
): void {
  const path = location === "local" ? join(repoRoot, ".mcp.json") : claudeRootConfigPath(env);
  const command = [
    location === "local" ? "claude-project-config" : "claude-root-config",
    "scope-codegraph-mcp",
    path ?? "<HOME>/.claude.json",
  ];

  if (!path) {
    actions.push({
      action: "claude-project-path",
      status: "skipped",
      command,
      stderr: "HOME environment variable not set; cannot locate ~/.claude.json.",
    });
    return;
  }

  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch (_error) {
    if (location === "local") {
      mkdirSync(dirname(path), { recursive: true });
      writeClaudeMcpJson(actions, path, command, renderClaudeCodegraphConfig(repoRoot, location));
      return;
    }
    actions.push({
      action: "claude-project-path",
      status: "skipped",
      command,
      stderr: `${path} not found; CodeGraph did not create a Claude ${location} MCP config.`,
    });
    return;
  }

  let parsed: any;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    actions.push({
      action: "claude-project-path",
      status: "failed",
      command,
      stderr: `Failed to parse ${path} as JSON: ${String((error as Error).message ?? error)}`,
    });
    return;
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    actions.push({
      action: "claude-project-path",
      status: "failed",
      command,
      stderr: `${path} is not a JSON object; refusing to mutate.`,
    });
    return;
  }

  const mcpServers =
    location === "global"
      ? parsed?.mcpServers
      : parsed?.mcpServers;
  if (
    location === "local" &&
    (!parsed.mcpServers || typeof parsed.mcpServers !== "object" || Array.isArray(parsed.mcpServers))
  ) {
    parsed.mcpServers = {};
  }
  const server = parsed.mcpServers?.[CLAUDE_CODEGRAPH_SERVER_NAME] ?? mcpServers?.[CLAUDE_CODEGRAPH_SERVER_NAME];
  if (!server || typeof server !== "object" || Array.isArray(server)) {
    if (location === "local") {
      parsed.mcpServers[CLAUDE_CODEGRAPH_SERVER_NAME] = (
        renderClaudeCodegraphConfig(repoRoot, location) as { mcpServers: Record<string, unknown> }
      ).mcpServers[CLAUDE_CODEGRAPH_SERVER_NAME];
      writeClaudeMcpJson(actions, path, command, parsed, raw);
      return;
    }
    actions.push({
      action: "claude-project-path",
      status: "skipped",
      command,
      stderr: `Claude ${location} CodeGraph MCP server entry was not found; run codegraph install first.`,
    });
    return;
  }

  if (codegraphArgsAreScoped(server.args)) {
    const desiredEnv = codegraphMcpEnv(location);
    const existingEnv = server.env && typeof server.env === "object" && !Array.isArray(server.env)
      ? server.env
      : {};
    const desiredCommand = location === "local" ? localCodegraphCommand(repoRoot) : server.command;
    const envMatches = Object.entries(desiredEnv).every(([key, value]) => existingEnv[key] === value);
    const commandMatches = location !== "local" || server.command === desiredCommand;
    if (envMatches && commandMatches) {
      actions.push({
        action: "claude-project-path",
        status: "unchanged",
        command,
      });
      return;
    }
  }

  server.args = [...CODEGRAPH_SCOPED_MCP_ARGS];
  server.env = {
    ...(server.env && typeof server.env === "object" && !Array.isArray(server.env) ? server.env : {}),
    ...codegraphMcpEnv(location),
  };
  if (location === "local") {
    server.command = localCodegraphCommand(repoRoot);
  }
  writeClaudeMcpJson(actions, path, command, parsed, raw);
}

function configureClaudeAlwaysLoad(
  actions: CodegraphAction[],
  repoRoot: string,
  location: CodegraphConfigureLocation,
  env?: NodeJS.ProcessEnv,
): void {
  if (location === "local") {
    actions.push({
      action: "claude-always-load",
      status: "skipped",
      command: ["claude-project-config", "set-codegraph-always-load", join(repoRoot, ".mcp.json")],
      stderr: "Project-local Claude MCP config does not require user-level alwaysLoad mutation.",
    });
    return;
  }
  const path = claudeRootConfigPath(env);
  const command = ["claude-root-config", "set-codegraph-always-load", path ?? "<HOME>/.claude.json"];

  if (!path) {
    actions.push({
      action: "claude-always-load",
      status: "skipped",
      command,
      stderr: "HOME environment variable not set; cannot locate ~/.claude.json.",
    });
    return;
  }

  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch (_error) {
    actions.push({
      action: "claude-always-load",
      status: "skipped",
      command,
      stderr: `${path} not found; CodeGraph did not create a Claude root MCP config.`,
    });
    return;
  }

  let parsed: any;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    actions.push({
      action: "claude-always-load",
      status: "failed",
      command,
      stderr: `Failed to parse ${path} as JSON: ${String((error as Error).message ?? error)}`,
    });
    return;
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    actions.push({
      action: "claude-always-load",
      status: "failed",
      command,
      stderr: `${path} is not a JSON object; refusing to mutate.`,
    });
    return;
  }

  const mcpServers =
    location === "global"
      ? parsed.mcpServers
      : parsed.projects?.[repoRoot]?.mcpServers;
  const server = mcpServers?.[CLAUDE_CODEGRAPH_SERVER_NAME];
  if (!server || typeof server !== "object" || Array.isArray(server)) {
    actions.push({
      action: "claude-always-load",
      status: "skipped",
      command,
      stderr: `Claude ${location} CodeGraph MCP server entry was not found; run codegraph install first.`,
    });
    return;
  }

  if (server.alwaysLoad === true) {
    actions.push({
      action: "claude-always-load",
      status: "unchanged",
      command,
    });
    return;
  }

  server.alwaysLoad = true;
  const trailingNewline = raw.endsWith("\n") ? "\n" : "";
  const serialized = `${JSON.stringify(parsed, null, 2)}${trailingNewline}`;

  try {
    writeFileSync(path, serialized);
  } catch (error) {
    actions.push({
      action: "claude-always-load",
      status: "failed",
      command,
      stderr: `Failed to write ${path}: ${String((error as Error).message ?? error)}`,
    });
    return;
  }

  actions.push({
    action: "claude-always-load",
    status: "changed",
    command,
  });
}

function configureClaudeAllowedTools(actions: CodegraphAction[], env?: NodeJS.ProcessEnv): void {
  // Hosts claude_settings_path is shown only as a path token; the pattern itself
  // travels via writeFile, not via the command echo. This keeps host-agnostic
  // invariants intact for consumers that grep CLI stdout for concrete tool
  // call syntax such as codegraph_context(...).
  const path = claudeSettingsPath(env);
  const command = ["claude-settings", "register-allowed-tools", path ?? "<HOME>/.claude/settings.json"];

  if (!path) {
    actions.push({
      action: "claude-allowed-tools",
      status: "skipped",
      command,
      stderr: "HOME environment variable not set; cannot locate ~/.claude/settings.json.",
    });
    return;
  }

  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch (_error) {
    actions.push({
      action: "claude-allowed-tools",
      status: "skipped",
      command,
      stderr: `${path} not found; Claude Code is not installed for this user. Skipping eager-load registration.`,
    });
    return;
  }

  let parsed: any;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    actions.push({
      action: "claude-allowed-tools",
      status: "failed",
      command,
      stderr: `Failed to parse ${path} as JSON: ${String((error as Error).message ?? error)}`,
    });
    return;
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    actions.push({
      action: "claude-allowed-tools",
      status: "failed",
      command,
      stderr: `${path} is not a JSON object; refusing to mutate.`,
    });
    return;
  }

  const existing = Array.isArray(parsed.allowedTools) ? (parsed.allowedTools as unknown[]) : [];
  if (existing.includes(CLAUDE_CODEGRAPH_ALLOWED_TOOLS_PATTERN)) {
    actions.push({
      action: "claude-allowed-tools",
      status: "unchanged",
      command,
    });
    return;
  }

  parsed.allowedTools = [...existing, CLAUDE_CODEGRAPH_ALLOWED_TOOLS_PATTERN];
  const trailingNewline = raw.endsWith("\n") ? "\n" : "";
  const serialized = `${JSON.stringify(parsed, null, 2)}${trailingNewline}`;

  try {
    writeFileSync(path, serialized);
  } catch (error) {
    actions.push({
      action: "claude-allowed-tools",
      status: "failed",
      command,
      stderr: `Failed to write ${path}: ${String((error as Error).message ?? error)}`,
    });
    return;
  }

  actions.push({
    action: "claude-allowed-tools",
    status: "changed",
    command,
  });
}

export function configureCodegraph(opts: CodegraphConfigureOptions): CodegraphConfigureResult {
  const actions: CodegraphAction[] = [];
  const initial = checkCodegraph({ repoRoot: opts.repoRoot, env: opts.env, host: opts.target });
  const binPath = initial.resolution.binPath;

  for (const target of configureTargets(opts.target)) {
    const command = [binPath ?? "codegraph", "install", "--target", target, "--location", opts.location, "--yes"];
    const actionName = `configure-${target}`;

    if (!binPath) {
      actions.push({
        action: actionName,
        status: opts.location === "local" ? "skipped" : "failed",
        command,
        stderr: opts.location === "local"
          ? "CodeGraph CLI is missing; writing project MCP config only. Install the managed project tool with: local-repo-harness tools ensure codegraph --repo ."
          : "CodeGraph CLI is missing; run local-repo-harness tools ensure codegraph first.",
      });
      if (opts.location === "local" && target === "codex") {
        configureCodexProjectPath(actions, opts.repoRoot, opts.location, opts.env);
      }
      if (opts.location === "local" && target === "claude") {
        configureClaudeProjectPath(actions, opts.repoRoot, opts.location, opts.env);
        configureClaudeAlwaysLoad(actions, opts.repoRoot, opts.location, opts.env);
      } else if (target === "claude") {
        configureClaudeAllowedTools(actions, opts.env);
      }
      continue;
    }

    if (target === "claude" && opts.location === "global" && isMcpHostConfigured(initial.raw, target)) {
      appendSkippedAction(actions, actionName, command, "Claude CodeGraph MCP is already configured.");
    } else {
      appendCodegraphInstallAction(actions, actionName, command, run(binPath, command.slice(1), opts.repoRoot, codegraphRuntimeEnv(opts.repoRoot, opts.env)));
    }

    if (target === "codex") {
      configureCodexProjectPath(actions, opts.repoRoot, opts.location, opts.env);
    }

    if (target === "claude") {
      configureClaudeProjectPath(actions, opts.repoRoot, opts.location, opts.env);
      configureClaudeAlwaysLoad(actions, opts.repoRoot, opts.location, opts.env);
      if (opts.location === "global") configureClaudeAllowedTools(actions, opts.env);
    }
  }

  let refreshed = initial;
  if (actions.some((entry) => entry.status === "changed")) {
    try {
      refreshed = checkCodegraph({ repoRoot: opts.repoRoot, env: opts.env, host: opts.target });
    } catch (_error) {
      refreshed = initial;
    }
  }

  return {
    ...refreshed,
    target: opts.target,
    location: opts.location,
    changed: actions.some((entry) => entry.status === "changed"),
    readOnly: false,
    actions,
  };
}
