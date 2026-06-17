# local-repo-harness

> **Project statement:** `local-repo-harness` is an independent npm package
> based on the original [`repo-harness@0.5.0`](https://github.com/Ancienttwo/repo-harness).
> It preserves the upstream workflow model, uses `local-repo-harness` as the
> public CLI command, and adds project-scoped install support so a downstream
> project can install the harness, hooks, skills, and external tooling inside
> that project instead of relying on user-level hook registration.

<p align="center">
  <img src="docs/images/image.png" alt="One next button joining Claude and Codex under local-repo-harness workflow rules" width="760">
</p>

`local-repo-harness` turns Claude/Codex coding sessions into a repeatable repo-local
workflow. It ships a CLI plus skill/runtime hooks that write context, plans,
handoffs, checks, and review evidence back into the project, so the next agent
session can continue from files instead of chat memory.

Use it to:

- adopt an existing repo with a tasks-first agent contract
- keep Claude and Codex aligned on the same plans, checks, handoffs, and context
  boundaries
- spend fewer tokens rediscovering structure by using CodeGraph and progressive
  context loading

Give the agent a complete PRD or Sprint; after that, your loop is just review
and `next`, or start `/goal` and go AFK.

Repository: `https://github.com/automann/local-repo-harness`

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Français](README.fr.md) | [Español](README.es.md)

## Why local-repo-harness

- **File-backed sessions, not chat memory.** Separate agent sessions — Claude and
  Codex, now and later — stay coordinated through the repo, not a thread.
  `.ai/hooks/session-start-context.sh` injects the prior session's resume packet
  (`.ai/harness/handoff/resume.md`, `tasks/current.md`) when a new session starts;
  `finalize-handoff.sh` and `post-edit-guard.sh` write the next handoff back on stop
  and after edits. A session can end mid-task and the next one resumes the exact next
  step, blockers, and changed files without re-deriving them.
- **Token-lean by design.** Instead of grep-and-read loops that re-scan the repo every
  session, the harness leans on a pre-built CodeGraph index for structural queries
  (callers, callees, definitions) and on progressive context loading via
  `.ai/context/context-map.json` and `capabilities.json`: a small, stable root context
  (~12KB) plus capability blocks loaded only when the files you touch need them. Agents
  read a 1KB capability contract or query the index instead of spending thousands of
  tokens rediscovering structure.

In an adopted repo, the surface area is intentionally small:

| Surface | Purpose |
| --- | --- |
| `docs/spec.md` and `docs/reference-configs/` | Shared standards and stable product intent that every agent session can read. |
| `plans/`, `plans/prds/`, and `plans/sprints/` | Decision-complete work packages before implementation starts. |
| `tasks/contracts/`, `tasks/reviews/`, and `.ai/harness/checks/` | Scope, verification, and review evidence for proving the work is done. |
| `.ai/harness/handoff/` and `tasks/current.md` | Session journal and resumable status, derived from workflow artifacts instead of chat memory. |

## What's New in 0.5.0

- **Clean command boundary.** `local-repo-harness update` now refreshes only the
  user-level CLI/runtime surface, while `local-repo-harness adopt` owns repo-local
  workflow install, refresh, and migration.
- **Package-dispatched helper runtime.** Generated `scripts/*` wrappers can
  delegate through `local-repo-harness run <helper>`, so adopted repos do not need to
  vendor every helper implementation when the installed package already owns it.
- **Eight managed hook routes.** The README now documents the exact hook route
  matrix that Claude and Codex adapters install: session context, edit guards,
  delegated-agent routing, post-edit and post-bash observers, always-on trace,
  prompt routing, and stop closeout.
- **Release-ready install examples.** The first-run and refresh commands now
  show the split between machine bootstrap, user-level updates, read-only setup
  audit, and repo-local adoption.

## What local-repo-harness Does

`local-repo-harness` turns AI-assisted development from chat-memory coordination into
repo-local workflow state. It installs a small, file-backed contract into a
target repository so Claude, Codex, and humans can agree on:

- what product intent is stable
- which plan is approved for execution
- what the current sprint contract allows
- which checks and review evidence prove the work is done
- how hooks should warn, block, trace, and hand off work across sessions

It is not an agent gateway, product runtime, database service, or MCP server.
The product boundary is deliberately boring: inspect a repo, install or refresh
workflow files, route host events through repo-local hooks, and verify that the
workflow surfaces stay consistent.

## How It Works

The design has three layers:

1. **Source package**: this repository owns the CLI, CLI-backed command facades,
   templates, hook assets, workflow contract, tests, and release gate.
2. **Target repo contract**: `local-repo-harness adopt` or migration writes repo-local
   files such as `docs/spec.md`, `plans/`, `tasks/`, `.ai/context/`,
   `.ai/harness/`, helper scripts, and `.ai/hooks/`.
3. **Host adapters**: by default, user-level `~/.claude/settings.json` and
   `~/.codex/hooks.json` route Claude/Codex events into `local-repo-harness-hook`.
   Projects that need repo-local isolation can instead install project-scoped
   `.claude/settings.json` and `.codex/hooks.json` with
   `local-repo-harness install --target both --scope project` or
   `local-repo-harness update --host-adapter-scope project`. The hook entrypoint
   exits silently for non-opt-in repos. For opted-in repos, it resolves hooks
   central-first through the packaged install or `~/.repo-harness/hooks/`, with
   repo policy able to pin self-host development back to `.ai/hooks/*`.

For `UserPromptSubmit`, the public adapter contract stays
`local-repo-harness-hook UserPromptSubmit --route default`. The CLI route registry
dispatches that route to `.ai/hooks/prompt-guard.sh`. The shell hook remains the
repo-local adapter for host JSON parsing, workflow file reads, capture side
effects, and host-safe stdout/stderr. It pipes the prompt text into
`local-repo-harness-hook prompt-guard-decide`, where every prompt-text intent
classifier (Unicode-aware, `src/cli/hook/prompt-intents.ts`) and the
`intent x plan state` decision table live; the engine returns one verdict JSON
line with the action, the classified intent facts, and derived strings. The
shell keeps no duplicate classifier or fallback decision table — when the
engine is unreachable the prompt layer degrades to a one-shot advisory.

Prompt-layer plan/spec/contract gates are advisory routing. Hard enforcement
lives at the edit boundary: `pre-edit-guard.sh` blocks implementation edits
unless the active plan is Approved/Executing (policy
`.guards.edit_plan_gate`: enforce | advice | off). Done-claim gates keep
blocking because they verify file-backed completion evidence, not language.

The core invariant is that durable truth lives in the repo, not in a chat
thread. Hooks are accelerators and guardrails; the authority remains the
file-backed plan, contract, review, checks, and handoff artifacts.

## Task Workflow: Plan to Closeout

The diagram below assumes the harness is already installed in the repo. It shows
the normal lifecycle from a program sprint backlog down to one contract task:
draft or select the task, project it into execution files, check out the
contract worktree when policy requires it, implement under hooks, verify, review,
complete the sprint task when applicable, and close out. The 0.4.x loop-system
surfaces add scheduled heartbeat discovery, state-snapshot/eval evidence for
routing changes, architecture queue freshness, and optional contract-run
delegation without changing the file-backed authority model.

```mermaid
flowchart TD
  Program["Program goal or release theme"] --> Sprint{"Sprint layer needed?"}
  Sprint -->|yes| PRD["Upper-layer PRD<br/>plans/prds/*.prd.md"]
  PRD --> SprintDoc["Sprint backlog<br/>plans/sprints/*.sprint.md"]
  SprintDoc --> NextTask["Select next sprint task<br/>sprint-backlog.sh next"]
  Sprint -->|no| UserTask["User task or planning prompt"]
  Heartbeat["Heartbeat triage<br/>scripts/heartbeat-triage.sh<br/>.ai/harness/triage/"] --> UserTask
  NextTask --> UserTask

  UserTask --> Discovery["Due diligence<br/>P1 map, P2 trace, P3 decision"]
  Discovery --> LoopEvidence["Loop evidence when routing changes<br/>state-snapshot --json<br/>route-nl-vs-ts / cutover gate"]
  LoopEvidence --> PlanDraft["Draft plan<br/>plans/plan-*.md"]
  PlanDraft --> PlanReview{"Plan ready for execution?"}
  PlanReview -->|no| Refine["Refine plan, scope, evidence contract"]
  Refine --> PlanDraft
  PlanReview -->|yes| Approve["Approved plan<br/>Status: Approved"]

  Approve --> Project["Project plan into execution<br/>capture-plan.sh --execute<br/>or plan-to-todo.sh --plan"]
  Project --> Active["Active markers<br/>.ai/harness/active-plan<br/>.ai/harness/active-worktree"]
  Project --> SprintActive["Sprint projection<br/>active-sprint marker<br/>tasks/current.md"]
  Project --> Contract["Sprint contract<br/>tasks/contracts/YYYYMMDD-HHMM-task-slug.contract.md"]
  Project --> ReviewFile["Review file<br/>tasks/reviews/YYYYMMDD-HHMM-task-slug.review.md"]
  Project --> Notes["Task notes<br/>tasks/notes/YYYYMMDD-HHMM-task-slug.notes.md"]

  Contract --> Delegation["Delegation contract<br/>budget / permission_scope / roles"]
  Delegation --> Delegate{"Use contract-run delegation?"}
  Delegate -->|yes| ContractRun["Worker/verifier child run<br/>scripts/contract-run.ts"]
  Delegate -->|no| WorktreePolicy{"Contract worktree required?"}
  WorktreePolicy -->|yes| Checkout["Checkout isolated worktree<br/>contract-worktree.sh start --plan<br/>branch codex/task-slug"]
  WorktreePolicy -->|no| CurrentTree["Use current worktree<br/>small or explicitly allowed slice"]
  Checkout --> Implement
  CurrentTree --> Implement
  ContractRun --> Changes

  Implement["Edit and run commands"] --> PreHooks["Pre-edit guards<br/>PlanStatusGuard, ContractScopeGuard, WorktreeGuard"]
  PreHooks -->|blocked| ScopeFix["Fix plan, contract, worktree, or scope"]
  ScopeFix --> Implement
  PreHooks -->|allowed| Changes["Code, docs, tests, or config changes"]
  Changes --> PostHooks["Post-edit and post-bash hooks<br/>trace, drift request, handoff, check evidence"]
  PostHooks --> ArchQueue["Architecture queue<br/>architecture-queue.sh record/reindex<br/>check-architecture-sync.sh"]
  ArchQueue --> Verify["Run verification<br/>tests plus repo workflow checks"]

  Verify --> Checks["Structured evidence<br/>.ai/harness/checks/latest.json<br/>.ai/harness/runs/*.json"]
  Checks --> CheckReview["Evaluator review<br/>Waza /check -> review file"]
  CheckReview --> External["External acceptance advice<br/>or explicit manual override"]
  External --> DoneGate{"Contract, checks, review, and acceptance pass?"}
  DoneGate -->|no| Repair["Repair failing evidence or implementation"]
  Repair --> Implement
  DoneGate -->|yes| SprintComplete{"Sprint task active?"}
  SprintComplete -->|yes| MarkSprint["Mark backlog item complete<br/>sprint-backlog.sh complete-task"]
  SprintComplete -->|no| Closeout["Closeout<br/>scripts/contract-worktree.sh finish"]
  MarkSprint --> Closeout

  Closeout --> Commit["Commit contract branch"]
  Commit --> Merge["Fast-forward target branch"]
  Merge --> Archive["Archive plan/todo and refresh handoff"]
  Archive --> Cleanup["Cleanup merged worktree<br/>contract-worktree.sh cleanup"]
  Cleanup --> Done["Reviewable completed task"]
```

## Long-Running Product Loops

For Greenfield and Brownfield work, front-load discovery and engineering-plan
judgment in Claude-Fable before asking Codex to loop on execution:

1. In Claude-Fable, use gstack `office-hours` for product discovery or
   `plan-eng-review` for engineering plan review. The output should be the
   development documents that lock product intent, architecture, risks, and the
   evidence contract.
2. Turn those documents into an upper-layer PRD under `plans/prds/`, then into
   an ordered sprint backlog under `plans/sprints/` with detailed sub-plans for
   each execution slice.
3. In Codex, create a Goal that points at that sprint file. The harness can then
   project each sprint item through the normal plan -> contract -> worktree ->
   verification flow.

That handoff keeps long-running loops precise: Claude-Fable owns the broad
front-loaded judgment, the PRD remains the upper source of truth, the sprint
backlog is the durable execution queue, and Codex Goal mode resumes against a
concrete sprint instead of reinterpreting the original chat.

## First 5 Minutes

This is the fastest path for an AI tooling owner evaluating whether the workflow is
safe to adopt in a real repo. Start with the repo-local contract and keep host
runtime writes off until the dry-run output looks right. When you want a
project-only install, use `bootstrap`: it seeds a project-managed CLI under
`.ai/harness/tools/local-repo-harness/` and does not require the target repo to
have a root `package.json`.

### 1. Preview the repo-local contract only

```bash
bunx --bun local-repo-harness@latest adopt --dry-run \
  --host-adapter-scope none \
  --skill-scope none \
  --external-tool-scope none \
  --codegraph-mcp-scope none
```

This is the lowest-impact inspection path. It should not write user hooks,
user skills, user MCP config, or brain root state. It only reports the repo
workflow contract that would be created or refreshed.

### 2. Apply the repo-local contract only

```bash
bunx --bun local-repo-harness@latest bootstrap \
  --repo "$PWD" \
  --host-adapter-scope none \
  --skill-scope none \
  --external-tool-scope none \
  --codegraph-mcp-scope none \
  --brain-mode skip \
  --no-codegraph
```

This installs the file-backed workflow surface without registering Codex or
Claude adapters and without installing external skills. It also writes
`.ai/harness/bin/local-repo-harness`, so follow-up repo-local commands can use the
project-managed shim directly. Existing repos use `local-repo-harness adopt`; new
projects or modules use `repo-harness-scaffold`.

### 3. Enable project hooks and project skills

```bash
bunx --bun local-repo-harness@latest bootstrap \
  --repo "$PWD" \
  --host-adapter-scope project \
  --runtime project-vendored-bun \
  --skill-scope project \
  --external-tool-scope none \
  --codegraph-mcp-scope none \
  --brain-mode manifest-only \
  --no-codegraph
```

Project Codex skills live under `.agents/skills`; project Claude skills live
under `.claude/skills`. Project adapters live under `.codex/hooks.json` and
`.claude/settings.json`, and project runtime lives under `.ai/harness/bin/` plus
`.ai/harness/runtime/`. The project-managed CLI package lives under
`.ai/harness/tools/local-repo-harness/`. Codex still requires trusting the
project hooks file in Codex Settings before hooks run.

Keep `--external-tool-scope none` until you deliberately want project copies of
Waza/Mermaid. Project Waza/Mermaid installs use the skills CLI without `-g`.
Keep `--codegraph-mcp-scope none` unless you want project MCP config in
`.codex/config.toml` and `.mcp.json`. gbrain remains manual or manifest-only in
project-only mode.

After bootstrap, run refreshes through the project shim:

```bash
./.ai/harness/bin/local-repo-harness adopt --repo "$PWD" --dry-run
```

### 4. Optional CLI install

No Node.js required for the default path: the installer uses Bun as the runtime.
If Bun is missing, it installs Bun first, then installs the `local-repo-harness` CLI.

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/automann/local-repo-harness/main/install.sh | sh

# Windows (PowerShell)
irm https://raw.githubusercontent.com/automann/local-repo-harness/main/install.ps1 | iex
```

<details>
<summary>Already have Bun or Node? Use package managers instead</summary>

```bash
# Bun
bun add -g local-repo-harness
local-repo-harness adopt --dry-run

# Node/npm, with Bun already on PATH because the CLI runs on Bun
local-repo-harness adopt --dry-run
```

</details>

### 5. Optional user-level bootstrap

```bash
npx -y local-repo-harness init
```

`init` is the broad-impact machine bootstrap path. It installs the current npm
package as the global CLI, refreshes user skill aliases, writes user-level
Codex/Claude hook adapters, installs Waza/Mermaid runtime skills into user
skill roots, persists a brain root under `~/.repo-harness/config.json`, and
configures user-level CodeGraph MCP. Use it when you intentionally want
local-repo-harness available across repos on the machine.

For an Agent-owned, read-only bootstrap audit, run `npx -y local-repo-harness setup
check --json` or add `--check-updates` for version advisories. `setup check` is
not a runtime hook: it does not write user-level files, install updates, or
register adapters. It emits `agent_actions` with the reason, risk, target files,
optional command, and verification surface for the Agent to execute deliberately.
`local-repo-harness init-hook` remains a legacy shortcut for `setup check`.

### Install and refresh examples

```bash
# First machine bootstrap after installing the CLI: skills, host adapters, Waza, brain, CodeGraph.
local-repo-harness init

# Refresh user-level CLI/runtime pieces after a package update.
local-repo-harness update

# Ask for read-only repair guidance without writing files.
local-repo-harness update --check

# Refresh repo-local workflow files in an adopted repository.
local-repo-harness adopt --repo /path/to/repo
```

### 6. Prove the workflow

```bash
bash scripts/check-task-workflow.sh --strict
bun test
```

After apply, the repo should have a reviewable file-backed contract rather than
tool-specific chat setup. Agents should be able to find the stable intent in
`docs/spec.md`, execution state in `plans/` and `tasks/`, and resume state in
`.ai/harness/handoff/`.

Only maintainers editing the package need a source checkout:

```bash
git clone https://github.com/automann/local-repo-harness.git ~/Projects/local-repo-harness
cd ~/Projects/local-repo-harness
bun src/cli/index.ts update
```

Local path model:

- Source repo: `~/Projects/local-repo-harness`
- Claude skill alias: `~/.claude/skills/repo-harness`
- Codex discoverable skill alias: `~/.codex/skills/repo-harness`

The `~/Projects/local-repo-harness` repo is the only editable source of truth. Local
Claude/Codex paths are symlink-backed runtime entrypoints. Only
`~/.codex/skills/repo-harness` should expose `SKILL.md` and
`assets/skill-commands/`. The retired `repo-harness-skill` and
`project-initializer` directories under `~/.codex/skills` and
`~/.claude/skills` are deleted by `scripts/sync-codex-installed-copies.sh`.

### Minimum prerequisites

- Git working tree
- `bash`
- `bun` for follow-up verification and template assembly
- `jq` is optional for `--dry-run`, but recommended when applying settings merges

### Default project-safe shortcut

For an existing repo, run from the repo root:

```bash
local-repo-harness adopt --dry-run
```

Apply only after the dry-run report looks correct:

```bash
local-repo-harness adopt
```

For a new project or module, use the branch command `repo-harness-scaffold`. For
an existing repo, use `local-repo-harness adopt`; it installs or refreshes the harness
without creating an application stack.

### Success looks like this

The command should end with `=== Migration Report ===` and summarize:

- `Project hooks synced from:` to show where generated hook behavior comes from
- `Host hook config target:` to show whether no adapter, a project adapter, or a user adapter is selected
- `Host hook adapters default to user scope:` to remind the user to install user adapters deliberately or opt into project-scoped adapters and trust the matching Codex hooks file
- `Workflow migration:` to show the repo-local harness surfaces it will create or refresh
- `Helper runtime:` to show package-dispatched through `local-repo-harness run` with `scripts/*` compatibility wrappers after apply
- `--- External Tooling ---` to show default gstack/Waza/gbrain routing plus advisory install/update hints

If the dry-run output looks wrong, stop there and inspect
[`docs/reference-configs/hook-operations.md`](docs/reference-configs/hook-operations.md)
before applying anything.

## Hook Authority Map

- `.ai/hooks/` is the only shared hook implementation you should edit first.
- `~/.claude/settings.json` is the user-level Claude adapter that dispatches into opted-in repos.
- `~/.codex/hooks.json` is the user-level Codex adapter that dispatches into the same runner.
- Repo-local `.claude/settings.json` and `.codex/hooks.json` are supported project-scoped adapters for repos that should not register user-level hooks.
- `local-repo-harness adopt` owns repo-local workflow install/refresh/migration; pass `--host-adapter-scope project` for repo-local adapters or `--host-adapter-scope none` to skip adapter writes.
- `local-repo-harness init` and `local-repo-harness update` own user-level bootstrap/refresh paths and should be treated as broad-impact machine operations.
- Codex must mark the active hooks file (`~/.codex/hooks.json` or `<repo>/.codex/hooks.json`) as trusted in Codex Settings before those hooks run.
- Debug in this order: active adapter config -> `local-repo-harness-hook` (or fallback `local-repo-harness hook`) -> route registry -> `.ai/hooks/*`.
- If `local-repo-harness-hook` reports `.ai/hooks` drift, refresh the repo-local copy with `local-repo-harness adopt --repo <root>`.

The installed adapter owns eight managed hook routes. The route tuple
`event + routeId + matcher` is the stable contract; script names are the current
implementation under `assets/hooks/` or a repo-pinned `.ai/hooks/` copy.

| Route | Matcher | Scripts | Function |
| --- | --- | --- | --- |
| `SessionStart.default` | all sessions | `session-start-context.sh`, `security-sentinel.sh` | Injects prior handoff, sprint status, and read-only config-security findings before work starts. |
| `PreToolUse.edit` | `Edit|Write` | `worktree-guard.sh`, `pre-edit-guard.sh` | Enforces worktree policy and plan/contract readiness before implementation edits. |
| `PreToolUse.subagent` | `Task|Agent|SendUserMessage` | `subagent-return-channel-guard.sh` | Keeps delegated work returning through the parent session instead of leaking completion claims. |
| `PostToolUse.edit` | `Edit|Write` | `post-edit-guard.sh` | Records edit traces, refreshes handoff/task status, and queues architecture drift when controlled files change. |
| `PostToolUse.bash` | `Bash` | `post-bash.sh` | Observes command results and captures verification evidence without replacing the command runner. |
| `PostToolUse.always` | all tools | `post-tool-observer.sh` | Provides low-noise always-on trace and runtime observation; stale pinned copies soft-skip with a refresh hint. |
| `UserPromptSubmit.default` | all prompts | `prompt-guard.sh` | Classifies prompt intent, routes planning/check/hunt hints, and renders host-safe workflow guidance. |
| `Stop.default` | session stop | `stop-orchestrator.sh` | Finalizes handoff and guards against ending with unresolved draft-plan or completion evidence gaps. |

`SessionStart` resolves hooks central-first, then runs two ordered scripts before
work begins:

```mermaid
flowchart LR
  SessionStart["Claude/Codex SessionStart"] --> Adapter["active adapter<br/>user or project"]
  Adapter --> Entry["local-repo-harness-hook SessionStart --route default"]
  Entry --> Source{"hook source"}
  Source -->|central default| Central["packaged hooks<br/>or ~/.repo-harness/hooks"]
  Source -->|repo policy pin| Repo["repo .ai/hooks<br/>self-host development"]
  Central --> Ctx["session-start-context.sh<br/>resume + sprint + handoff context"]
  Repo --> Ctx
  Ctx --> Sec["security-sentinel.sh<br/>read-only config scan, fingerprint-gated"]
  Sec --> SSOut["SessionStart additionalContext<br/>prior-session state + SecurityConfig findings"]
```

`SessionStart` and `Stop` hooks are advisory for missing repo-local scripts: stale
repos get a drift warning instead of a startup failure. Required guard routes,
including edit and prompt gates, still fail closed when their scripts are
missing.

Prompt guard has one extra internal step:

```mermaid
flowchart LR
  Host["Claude/Codex UserPromptSubmit"] --> Adapter["active adapter<br/>user or project"]
  Adapter --> CLI["local-repo-harness-hook UserPromptSubmit --route default"]
  CLI --> Route["route registry"]
  Route --> Shell[".ai/hooks/prompt-guard.sh"]
  Shell -->|"stdin {prompt}"| Decision["local-repo-harness-hook prompt-guard-decide<br/>TypeScript classifiers + decision table"]
  Decision -->|"verdict JSON<br/>action + intent facts + derived"| Shell
  Shell --> RouteHint["Waza route hint<br/>explicit think/planning matched first → /think"]
  Shell --> HostOutput["host-safe advice, done gate, or capture output"]
```

The shell layer owns filesystem authority and side effects. TypeScript owns all
prompt-text classification plus the `intent x plan state` decision table.
Plan-state blocks render at the PreToolUse edit layer, not here.

## Hook Failure Playbook

When a hook blocks work, start with the structured output in the terminal. The core
fields are `guard`, `reason`, `fix`, `failure_class`, and `run_id`.

- Failure log: `.ai/harness/failures/latest.jsonl`
- Trace log: `.claude/.trace.jsonl`
- Deep guide: [`docs/reference-configs/hook-operations.md`](docs/reference-configs/hook-operations.md)

Most common guards:

- `PlanStatusGuard` (edit layer): an implementation edit was attempted with no active plan, or the plan is not ready to execute; the prompt layer emits the same guard name as advisory guidance
- `ContractGuard`: approved execution has not yet produced the contract/review/notes scaffold
- `ContractGuard`: completion was claimed before the task contract passed
- `WorktreeGuard`: writes were attempted in the primary worktree while linked worktrees are enforced

## Repo Workflow

- Root routing docs: `CLAUDE.md`, `AGENTS.md`
- Shared hook layer: `.ai/hooks/`
- Adapter layer: default user-scoped `~/.claude/settings.json`, `~/.codex/hooks.json`; optional project-scoped `.claude/settings.json`, `.codex/hooks.json`
- Active execution surface: `tasks/`
- Plan source of truth: `plans/`
- Durable progress: `tasks/workstreams/`
- Release history: `docs/CHANGELOG.md`

## Current Release

- npm package: `local-repo-harness@0.5.8`
- Generated workflow stamp: `local-repo-harness@0.5.8+template@0.5.8`
- GitHub repository: `automann/local-repo-harness`
- Release history: [`docs/CHANGELOG.md`](docs/CHANGELOG.md)

## Current Model

- Question flow uses **12 grouped decision points** with harness defaults inferred first.
- Plan menu is tiered:
  - **Core Plans (A-F)** first.
  - **Custom Presets (G-K)** only when needed.
- Skill routing is inspection-first:
  - `scripts/inspect-project-state.ts`
  - `scripts/migrate-workflow-docs.ts`
  - `assets/workflow-contract.v1.json`
- Runtime mode is configurable with template vars:
  - `{{RUNTIME_MODE}}`
  - `{{RUNTIME_PROFILE}}`
  - `{{RECOVERY_PROFILE}}`
  - `{{STATE_PROFILE}}`
- Question-pack source of truth is in:
  - `assets/initializer-question-pack.v4.json`
- Generated repos default to the repo-local harness flow:
  - `docs/spec.md -> plans/ -> tasks/contracts/ -> tasks/reviews/ -> .ai/context/context-map.json -> .ai/harness/*`
- Generated and self-hosted repos install:
  - `.ai/harness/workflow-contract.json`
  - `.ai/harness/policy.json`
- Generated and migrated repos default `external_tooling` to:
  - `complex -> gstack`
  - `simple -> Waza` with Codex-first user runtime copies in `~/.codex/skills`,
    or project copies in `.agents/skills` when project scope is selected
  - `knowledge -> gbrain`
- `local-repo-harness init` bootstraps the Codex/Claude runtime pieces needed for the
  default workflow:
  - refreshes `repo-harness` skill aliases
  - installs global Codex/Claude hook adapters
  - installs Waza skills (`think`, `hunt`, `check`, `health`) and Mermaid through the skills CLI
  - persists the brain root in `~/.repo-harness/config.json`
  - configures CodeGraph MCP for selected host agents
- Other external tooling stays advisory-only:
  - `bash scripts/check-agent-tooling.sh --host both --check-updates`
  - Waza update checks compare upstream `tw93/Waza` `SKILL.md` hashes without running `npx skills check`
  - no automatic gstack, gbrain MCP, CodeGraph daemon, or provider setup in
    project-only mode
- Manual distillation stays repo-local:
  - repeated corrections -> `tasks/lessons.md`
  - deep findings and hidden contracts -> topic-scoped `docs/researches/*.md`
  - sprint verification evidence -> `tasks/reviews/*.review.md`
  - durable capability progress -> `tasks/workstreams/`
  - release history -> `docs/CHANGELOG.md`

## Acknowledgements and Workflow Influences

`local-repo-harness` is built around a small set of external skills, repos, and agent
runtimes that
proved useful while this project was being designed, debugged, and released.
They are acknowledged here because they shaped the workflow contract, but they
are not ordinary bundled product dependencies.

| Tool or repo | Used for | Dependency shape |
| --- | --- | --- |
| [Hylarucoder](https://x.com/hylarucoder) / Geju | P1/P2/P3 due-diligence method and Geju practice that shaped the planning, tracing, and decision-rationale discipline in this workflow | Methodology contribution and acknowledgement; not a bundled dependency |
| Waza by [TW93](https://x.com/HiTw93), including `think`, `hunt`, `check`, and `health` | Daily planning, bug hunts, verification, health checks, and Codex-first skill sync | Installed through the skills CLI into host skill roots |
| gstack skills and `gbrain` by [Garry Tan](https://x.com/garrytan) | Product discovery, plan review, design review, post-ship documentation hygiene, knowledge sync, handoff retrieval, and long-form repo memory | External operator workflow plus optional external CLI/index; advisory by default |
| `mermaid` | Human-readable architecture and system-flow diagrams when Mermaid is not enough | Runtime-referenced skill, not vendored into generated repos |
| CodeGraph (`@colbymchenry/codegraph`) | Symbol-aware navigation, impact tracing, and readiness checks for this self-host repo | Dev dependency in this repo; generated repos can use project MCP/local index when policy opts in |
| OpenAI Codex | Primary execution agent for repo-local implementation, verification, and GitHub contributor attribution when a commit materially includes Codex-authored work | External agent runtime; attribution is an explicit commit trailer, not hidden hook automation |

### GitHub Contributor Attribution

When Codex materially contributes to a commit, use GitHub's standard co-author
trailer format at the end of the commit message:

```text
Co-authored-by: codex <codex@openai.com>
```

Keep this opt-in and visible per commit. Do not bake it into downstream
local-repo-harness commit scripts or hooks unless that repo explicitly adopts the same
policy.

## Action Command Skills

Source-owned command facades live in `assets/skill-commands/`. They keep host
skill discovery compatible while the CLI and hooks own execution:

- Planning and review: `repo-harness-plan`, `repo-harness-review`, `repo-harness-autoplan`
- Product planning layer: `repo-harness-prd` (upper-layer PRDs in `plans/prds/`, evidence-marked unknowns, sprint-consumable sections)
- Sprint program layer: `repo-harness-sprint` (ordered sprint backlogs in `plans/sprints/`, each row expanded with `$think` before the contract flow)
- Repo workflow actions: `repo-harness-ship`, `repo-harness-init`, `repo-harness-migrate`, `repo-harness-upgrade`, `repo-harness-capability`, `repo-harness-architecture`, `repo-harness-handoff`, `repo-harness-deploy`, `repo-harness-repair`, `repo-harness-check`
- Branch project creation command: `repo-harness-scaffold`

`local-repo-harness adopt` is for an existing repo; `repo-harness-scaffold` creates a
new project or module scaffold as a side command. `hooks-init`, `docs-init`, and
`create-project-dirs` are internal steps, not public commands.

`repo-harness-scaffold` keeps the A-K plan catalog as the project-type authority
and adds AI-native app structure through an optional `ai_native_profile` overlay.
The default profile is `none`, so existing scaffold output remains unchanged.
When selected, profiles such as `runtime-console`, `product-copilot`, and
`sidecar-kernel` document the AG-UI event boundary, assistant-ui or CopilotKit
UI runtime, Bun/Hono gateway, shared contracts, observability, and MCP/HTTP
sidecar rules without installing model providers or making Python, Go, Rust, or
A2UI mandatory defaults.

Webapp rendering is a separate overlay. Client-only Vite remains Plan B, while
React webapps that need public SEO/SSR plus an authenticated workspace should
use Plan C: one TanStack Start + Vite app deployed as a Cloudflare Worker under
`apps/web`, with `/` SSR/prerender-capable and `/app` client-only. The scaffold
does not default to separate `apps/marketing` and `apps/web` frontend deploys.

Use `repo-harness-capability` when the harness already exists and only selected
capability boundaries should be added. It updates `.ai/context/capabilities.json`,
syncs the requested local `AGENTS.md` / `CLAUDE.md` contract files, and validates
the registry without running a full init, migrate, or upgrade pass.

Use `repo-harness-architecture`, `repo-harness-handoff`, and `repo-harness-deploy`
for focused architecture documentation, rollover, and deploy/ops readiness
passes. These commands call existing repo-local helpers and keep their scope
narrow instead of refreshing the full harness.

Codex installed-copy rule: only `~/.codex/skills/repo-harness` exposes the root
skill and `repo-harness-*` command facades. The retired `repo-harness-skill`
and `project-initializer` directories under `~/.codex/skills` and
`~/.claude/skills` are removed during sync.

After cloning or moving this source repo, rebuild the local runtime aliases with:

```bash
bash scripts/sync-codex-installed-copies.sh
```

By default, the script keeps local Claude/Codex runtime paths linked back to the
source repo. Set `AGENTIC_DEV_LINK_INSTALLED_COPIES=0` for copy-based staging,
and set `CODEX_SKILLS_ROOT` or `CLAUDE_SKILLS_ROOT` to stage under alternate
runtime roots.

## Maintainer Reference

### Self-check this repository's workflow contract

```bash
bash scripts/check-task-sync.sh
bash scripts/check-task-workflow.sh --strict
bun scripts/inspect-project-state.ts --repo . --format text
bash scripts/migrate-project-template.sh --repo . --dry-run
```

### Runtime reference docs

Generic local-repo-harness runtime/reference docs live in the installed package under
`assets/reference-configs/` and are resolved through the CLI:

```bash
local-repo-harness docs list
local-repo-harness docs path harness-overview
local-repo-harness docs show harness-overview
```

Generated and migrated repos still keep `docs/reference-configs/*.md`, but
those files are deterministic pointer stubs. Repo-local workflow state,
policy, checks, runs, handoff packets, context maps, and helper snapshots stay
under `.ai/`.

### Explicit template assembly

```bash
bun scripts/assemble-template.ts --plan C --name "MyProject"
bun scripts/assemble-template.ts --target agents --plan C --name "MyProject"
```

### Local benchmark skeleton

```bash
bun run benchmark:skills --dry-run
```

Dry-run benchmark output is a wiring smoke only. Release or readiness evidence
needs a non-dry-run eval with grader output.

### Run one eval across both Claude and Codex

```bash
bun run benchmark:skills --eval repair-agents-task-sync
```

## Key Files

- Skill spec: `SKILL.md`
- Root routing docs: `CLAUDE.md`, `AGENTS.md`
- Plan mapping: `assets/plan-map.json`
- Question-pack: `assets/initializer-question-pack.v4.json`
- Shared hooks: `assets/hooks/`
- Runtime reference docs: `assets/reference-configs/` via `local-repo-harness docs`
- Workflow contract: `assets/workflow-contract.v1.json`
- Source repo reference docs: `docs/reference-configs/*.md`
- Template assembler: `scripts/assemble-template.ts`
- Question inference helper: `scripts/initializer-question-pack.ts`
- State inspector: `scripts/inspect-project-state.ts`
- Legacy-doc migrator: `scripts/migrate-workflow-docs.ts`
- External tooling detector: `scripts/check-agent-tooling.sh`
- Scaffolding scripts:
  - `scripts/init-project.sh`
  - `scripts/create-project-dirs.sh`

## Generated vs Self-Hosted Hook Parity

- Downstream hook behavior is defined by generated output from `assets/hooks/` plus
  `assets/reference-configs/`.
- This repo dogfoods the same contract, but self-host behavior is not magically in
  sync with generated repos unless a change explicitly updates both surfaces.
- Every hook change should say whether it affects `self-host`, `generated`, or `both`.

## Package Manager Defaults

- General default priority: `bun > pnpm > npm`
- **Plan G/H** (Python-centric) default to **`uv`** as primary package manager.

## Runtime Profiles

- `Plan-only (recommended)` (default)
- `Plan + Permissionless`
- `Standard (ask before each action)`

Configured in `assets/initializer-question-pack.v4.json` and consumed by `scripts/initializer-question-pack.ts`.

## Verification

```bash
bun test
bash scripts/check-task-sync.sh
bash scripts/check-task-workflow.sh --strict
bun scripts/inspect-project-state.ts --repo . --format text
bash scripts/migrate-project-template.sh --repo . --dry-run
bash scripts/check-agent-tooling.sh --host both --check-updates
bun run benchmark:skills --eval route-workflow-check
```
