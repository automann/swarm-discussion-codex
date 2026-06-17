#!/usr/bin/env bun
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const sourceRoot =
  process.env.REPO_HARNESS_SOURCE_ROOT ||
  process.env.AGENTIC_DEV_ROOT ||
  process.env.AGENTIC_DEV_SKILL_ROOT;
const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = basename(scriptDir) === "repo-harness" ? resolve(scriptDir, "..", "..") : resolve(scriptDir, "..");
const projectCli = join(repoRoot, ".ai", "harness", "bin", "local-repo-harness");
const command = sourceRoot && existsSync(join(sourceRoot, "src", "cli", "index.ts"))
  ? ["bun", join(sourceRoot, "src", "cli", "index.ts"), "run", "architecture-event"]
  : existsSync(projectCli)
    ? [projectCli, "run", "architecture-event"]
  : ["local-repo-harness", "run", "architecture-event"];

const result = spawnSync(command[0], [...command.slice(1), ...process.argv.slice(2)], {
  cwd: process.cwd(),
  env: process.env,
  stdio: "inherit",
});

if (result.error) {
  console.error(`Missing local-repo-harness CLI for helper architecture-event: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
