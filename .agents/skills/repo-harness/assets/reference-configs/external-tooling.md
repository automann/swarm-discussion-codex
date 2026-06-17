# External Tooling

Generated repos route external tooling by host/runtime shape. Task-level
skill routing lives in `docs/reference-configs/agentic-development-flow.md`.

- `gstack` supplies `office-hours`, `plan-eng-review`, and `plan-design-review`
- `Waza` supplies `/think`, `/hunt`, and `/check` for daily small/medium work
- Codex automation can use `health`, `check`, and `mermaid` from project
  `.agents/skills` or user `~/.codex/skills`
- `gbrain` supports knowledge capture, repo sync, and handoff retrieval
- `CodeGraph` is required agent readiness for code navigation and impact tracing

Waza is Codex-first in this contract. `~/.codex/skills` is the Codex runtime
source, while `~/.agents/skills` is only the skills CLI staging/cache path used
to receive upstream `tw93/Waza` updates before syncing verified copies into
Codex. In project-scoped mode, the skills CLI writes Codex skills to
`.agents/skills` and Claude Code skills to `.claude/skills`; do not use
`.codex/skills` as the repo-local Codex target.

`local-repo-harness init` is allowed to bootstrap the workflow-owned global runtime in
one pass: the `local-repo-harness` CLI, local-repo-harness runtime aliases, user-level
Codex/Claude hook adapters, Waza (`think`, `hunt`, `check`, `health`), brain
root persistence, Mermaid, and CodeGraph CLI/MCP configuration. It must not
silently install unrelated toolchains or Claude marketplace plugins.

`local-repo-harness update` refreshes only the CLI and local-repo-harness-owned user-level
runtime by default. Third-party tooling and CodeGraph registration stay
readiness findings from `local-repo-harness setup check` unless the update command is
run with an explicit opt-in such as `--with-external-skills` or
`--configure-codegraph`.

`local-repo-harness adopt` owns repo-local project-scoped adoption. Explicit scope
flags can isolate hook adapters, skills, external tooling, and MCP config to the
current repo:

```bash
local-repo-harness adopt \
  --host-adapter-scope project \
  --skill-scope project \
  --external-tool-scope project \
  --codegraph-mcp-scope project
```

Project scope must not write Waza, Mermaid, cross-review, CodeGraph MCP, or
brain state into user-level roots. If a third-party project install cannot be
completed, report that failure instead of falling back to global writes.

The cross-review skills are **harness-owned and self-contained** — their source
lives in `assets/skills/<skill>/` and they wrap the peer CLI (`codex exec` /
`claude -p`) in a read-only sandbox with no gstack dependency, so installing them
is a workflow-owned runtime concern, not an unrelated toolchain. They install
host-aware during `local-repo-harness init`, explicit external-skill refreshes, or
project-scoped `local-repo-harness adopt`:
`codex-review` only into `~/.claude/skills` (a Claude session asking
Codex for an independent review) and `claude-review` only into `~/.codex/skills`
(a Codex session asking Claude). When gstack is present, its `/codex` and
`gstack-claude` skills are a more featureful superset; the harness skills are the
zero-dependency baseline that always ships with `init` and the peer acceptance
gate surface for `## External Acceptance Advice`.

In project scope, cross-review skills install to host project skill roots:
`codex-review` goes to `.claude/skills`, and `claude-review` goes to
`.agents/skills`.

The review scope is the current reviewable diff, not just committed branch
history: branch diff against the default base, staged changes, unstaged tracked
changes, and untracked files are all in scope. A timeout or missing peer CLI is
reported as unavailable review evidence, not as a pass.

The Codex automation profile is a runtime reference, not a vendored copy. It
requires Waza `health`, Waza `check`, and the standalone `mermaid` skill to
exist under the active Codex skill root; the skill bodies stay owned by their
original installations.

## Detect Safely

Use `bash scripts/check-agent-tooling.sh` for a read-only tooling report.
Init and migration reports run the detector without update checks by default;
set `REPO_HARNESS_CHECK_TOOLING_UPDATES=1` when that advisory pass should
also compare upstream versions.

Supported flags:

- `--host claude|codex|both`
- `--json`
- `--check-updates`
- `--strict-readiness`

The detector intentionally avoids side-effecting commands. It does not run:

- `gstack setup`
- `npx skills check`
- `npx skills update`
- `gbrain serve`
- `gbrain sync`
- `codegraph init`
- `codegraph sync`
- `codegraph install`

With `--check-updates`, Waza update checks fetch upstream GitHub raw
`SKILL.md` and shared `rules/` files, then compare versions/hashes against each
host path. The detector also compares each host's Waza skill directories and
shared rules against the `~/.agents` staging cache so helper files under
`references/`, `scripts/`, `agents/`, and cross-skill `rules/` links cannot
silently drift. Network failures are reported as `unknown`; the detector never
updates skills.

## Install

### gstack

Claude Code:

```bash
git clone --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
cd ~/.claude/skills/gstack && ./setup
```

Codex:

```bash
test -d ~/.claude/skills/gstack || git clone --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
cd ~/.claude/skills/gstack && ./setup --host codex
```

### Waza

Both hosts:

```bash
npx -y skills add tw93/Waza -g -a claude-code codex -s think hunt check health -y
```

Single host:

```bash
npx -y skills add tw93/Waza -g -a claude-code -s think hunt check health -y
```

Replace `claude-code` with `codex` when installing for Codex only.

Project-scoped install is owned by `local-repo-harness adopt` so the detector
can keep Codex skills under `.agents/skills` and Claude Code skills under
`.claude/skills`:

```bash
local-repo-harness adopt --repo . --skill-scope project --external-tool-scope project
bash scripts/check-agent-tooling.sh --json --host both
```

In JSON reports, project-scoped Waza should show `effective_scope: "project"`,
project paths such as `.agents/skills` and `.claude/skills`, and
`stage_command: "not-applicable-project-scope"`. The legacy user-scope staging
commands remain under `user_scope_commands` only as reference material.

For user-scoped installs or upgrades, verify Codex has its own runtime copy:

```bash
for d in think hunt check health; do
  rsync -a --delete ~/.agents/skills/$d/ ~/.codex/skills/$d/
done
mkdir -p ~/.codex/rules
for f in anti-patterns.md chinese.md durable-context.md english.md; do
  cp ~/.agents/rules/$f ~/.codex/rules/$f
done
for d in think hunt check health; do
  diff -qr ~/.agents/skills/$d ~/.codex/skills/$d
done
for f in anti-patterns.md chinese.md durable-context.md english.md; do
  cmp -s ~/.agents/rules/$f ~/.codex/rules/$f
done
```

### gbrain

```bash
bun add -g gbrain
```

### CodeGraph

`CodeGraph` is required readiness for agent code navigation. It speeds up
Codex and Claude exploration for indexed TypeScript and other supported languages, but it
does not replace `.ai/context/capabilities.json`, workflow checks, tests,
architecture drift events, or shell-script review.

This self-host repo vendors CodeGraph as a dev dependency so `bun install`
materializes `node_modules/.bin/codegraph`; its source-only
`scripts/ensure-codegraph.sh` can manage the local index. Generated downstream
repos with project CodeGraph intent use a harness-managed tool root at
`.ai/harness/tools/codegraph/` and a stable MCP shim at
`.ai/harness/bin/codegraph`, so the target repo root does not need to declare
`@colbymchenry/codegraph`.

Read-only check:

```bash
codegraph status .
```

Local index mutation:

```bash
codegraph init -i .
codegraph sync .
```

Project-local CodeGraph setup should first ensure the managed tool root, then
write host project config:

```bash
local-repo-harness tools ensure codegraph --repo .
local-repo-harness tools configure codegraph --target both --location local
```

Expected project-level config files are `.codex/config.toml` for Codex and
`.mcp.json` for Claude Code. Their MCP command should be
`./.ai/harness/bin/codegraph`. This mode must not edit
`~/.codex/config.toml`, `~/.claude.json`, or `~/.claude/settings.json`.

Do not ask users to copy MCP TOML or Claude JSON by hand. The user-facing path
is one terminal command, or explicit authorization for their agent to run the
same command:

```bash
npm install -g @colbymchenry/codegraph && mkdir -p ~/.local/bin && ln -sfn "$(npm config get prefix)/bin/codegraph" ~/.local/bin/codegraph && PATH="$HOME/.local/bin:$PATH" local-repo-harness tools configure codegraph --target codex --location global
```

Use the global npm command only for user-level MCP setup. For project-level
setup, prefer the managed root command above. Restart Codex after the installer
finishes so the MCP server is discovered; Claude Code should pick up its config
according to its own settings reload behavior. Do not make the user hand-edit
MCP config as the fallback.

For troubleshooting only, inspect host config snippets without writing:

```bash
codegraph install --print-config codex
codegraph install --print-config claude
```

Project-local indexes are ignored runtime state:

```bash
codegraph init -i .
codegraph status .
```

Before non-trivial code work, agents should sync the local index and use it for
P1/P2 discovery:

```bash
codegraph sync .
codegraph context "<task>"
codegraph query <symbol> --json
codegraph callers <symbol> --json
codegraph callees <symbol> --json
codegraph impact <symbol> --json
```

For this repo, do not treat `codegraph affected` as an authoritative test
selector. Many tests execute scripts by path or subprocess rather than import
edges, so run the repo verification commands instead.

### Bash Output Evidence and RTK

`repo-harness` treats Bash output as runtime evidence, not durable task state.
`PostToolUse:Bash` records command metadata in `.ai/harness/checks/` and stores
large or failed command output under ignored `.ai/harness/runs/bash-output/` with
the byte count, SHA-256 digest, and relative evidence path.

RTK can be useful as a user-level compression tool for noisy successful shell
commands, but it is optional and advisory-only. Hooks may suggest `rtk` when it
is already on `PATH`, the command is broad, and the command succeeded; hooks must
not rewrite Bash commands, require RTK, or suggest compression for failed
commands. Failed command output stays raw so test, build, and review evidence is
not hidden by a compressor.

## Update

### gstack

Claude Code:

```bash
cd ~/.claude/skills/gstack && git pull && ./setup
```

Codex:

```bash
cd ~/.claude/skills/gstack && git pull && ./setup --host codex
```

### Waza

```bash
npx -y skills update
for d in think hunt check health; do
  rsync -a --delete ~/.agents/skills/$d/ ~/.codex/skills/$d/
done
mkdir -p ~/.codex/rules
for f in anti-patterns.md chinese.md durable-context.md english.md; do
  cp ~/.agents/rules/$f ~/.codex/rules/$f
done
for d in think hunt check health; do
  diff -qr ~/.agents/skills/$d ~/.codex/skills/$d
done
for f in anti-patterns.md chinese.md durable-context.md english.md; do
  cmp -s ~/.agents/rules/$f ~/.codex/rules/$f
done
```

For project-scoped Waza upgrades, rerun the project refresh instead:

```bash
local-repo-harness adopt --repo . --skill-scope project --external-tool-scope project
bash scripts/check-agent-tooling.sh --json --host both
```

### gbrain

```bash
gbrain check-update --json
gbrain upgrade
```

### CodeGraph

```bash
npm install -g @colbymchenry/codegraph@latest && mkdir -p ~/.local/bin && ln -sfn "$(npm config get prefix)/bin/codegraph" ~/.local/bin/codegraph && PATH="$HOME/.local/bin:$PATH" codegraph sync . && PATH="$HOME/.local/bin:$PATH" codegraph status .
```

## Manual Knowledge Sync

`gbrain` stays advisory-first in this contract. Manual repo sync is allowed:

```bash
gbrain sync --repo <path>
```

In project-scoped repo-harness mode, keep gbrain manual or manifest-only. Do not
auto-install `gbrain`, register gbrain MCP, or write remote tokens while applying
project-only harness changes.

## Default Brain Vault

Long-lived external knowledge should land in the default brain file vault before
or alongside `gbrain` import:

```text
brain/<project>/*
```

For this repo, use:

```text
brain/repo-harness/*
```

The legacy repo-harness-skill and project-initializer paths are retired and
removed by installed-copy sync; do not use them as sync targets.

Keep runtime contracts, hooks, scripts, checks, evidence, and migration state in
the repo. The default brain stores reusable explanations, runbooks, decisions,
and patterns only.

Repo stubs that point to default brain pages are indexed in
`.ai/harness/brain-manifest.json`. Valuable repo-authored docs can opt into
one-way mirroring by adding a manifest entry with:

```json
{
  "id": "project-decision-log",
  "repo_path": "docs/decisions.md",
  "brain_path": "brain/<project>/decisions/project-decision-log.md",
  "gbrain_slug": "decisions/project-decision-log",
  "sync": { "direction": "repo-to-brain" }
}
```

After that, PostEdit hooks sync only that source file. Manual sync and drift
checks are also available:

```bash
bash scripts/check-brain-manifest.sh
bash scripts/sync-brain-docs.sh --all
bash scripts/sync-brain-docs.sh --check
```

## Why gbrain MCP Stays Off by Default

- `gbrain` is useful even when only the CLI is healthy.
- Local MCP endpoints are more failure-prone than the CLI health path.
- The policy keeps `gbrain` as a candidate MCP entry, not a required runtime dependency.
- Re-enable MCP only after the local host config is explicitly updated and `gbrain doctor --json` is healthy enough for your workflow.
