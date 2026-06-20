# Codex Installed Agent Namespacing Probe

> **Status**: Evidence recorded
> **Date**: 2026-06-20
> **Sprint row**: `installed-agent-namespacing-probe`
> **Worktree**: `/Users/syfq/dev/harness/swarm-discussion-codex-wt-installed-agent-namespacing-probe`

## Question

When the `swarm-discussion-codex` adapter is installed as a Codex plugin, what
names should be treated as the installed coordinator and expert agent names,
and what invocation surfaces currently make those names usable?

This row answers the namespacing and invocation question only. It does not add
`.codex/agents/` projections, change parent-skill behavior, start real
coordinator threads, or decide coordinator thread archive policy.

## Short Answer

The adapter source contracts name the agents:

| Source contract | Source path | Source name |
|---|---|---|
| Coordinator | `agents/swarm-coordinator.toml` | `swarm-coordinator` |
| Expert | `agents/swarm-expert.toml` | `swarm-expert` |

An isolated Codex plugin install keeps those files under the installed plugin
cache root at:

```text
$CODEX_HOME/plugins/cache/<marketplace>/swarm-discussion/<version>/agents/
```

Current official Codex subagent docs describe custom agents as TOML files under
personal `~/.codex/agents/` or project `.codex/agents/` locations, and say the
agent identity comes from the TOML `name field`. Current plugin docs describe
plugin identity through `.codex-plugin/plugin.json` and local marketplace
metadata. The observable docs and host tool schemas do not prove that a plugin
root `agents/` directory is projected into independent thread creation.

Therefore the current adapter contract is:

- Parent-to-coordinator: keep creating or resuming an independent coordinator
  thread by prompt contract that references or embeds
  `agents/swarm-coordinator.toml`; do not treat native coordinator custom-agent
  thread selection as established.
- Coordinator-to-expert: `swarm-expert` is the source and installed expert
  name. It can be used only on host surfaces that expose `agent_type` with that
  value, such as the current nested `spawn_agent` tool surface in this Codex
  session.
- User-level `~/.codex/agents` files are background state, not acceptance
  evidence for this plugin install row.

## Evidence

### Official Codex docs

References checked on 2026-06-20:

- <https://developers.openai.com/codex/subagents>
- <https://developers.openai.com/codex/plugins/build>

Relevant findings:

- The subagent custom-agent schema requires `name`, `description`, and
  `developer_instructions`; the docs describe `name` as the identity Codex uses
  when spawning or referring to an agent.
- The documented custom-agent file locations are personal
  `~/.codex/agents/` and project `.codex/agents/` TOML files.
- The plugin docs describe `.codex-plugin/plugin.json` as the required plugin
  manifest and say plugin `name` is the plugin identifier and component
  namespace.
- The plugin docs describe local repo marketplace metadata at
  `.agents/plugins/marketplace.json`, with plugin source paths resolved
  relative to the marketplace root.

Interpretation: these docs establish the custom-agent `name field` and plugin
layout contracts, but they do not establish a documented projection from a
plugin-root `agents/` directory into independent custom-agent thread creation.

### Source contracts

The current checkout contains:

```text
agents/swarm-coordinator.toml
agents/swarm-expert.toml
```

Observed TOML values:

```text
agents/swarm-coordinator.toml name = "swarm-coordinator"
agents/swarm-expert.toml      name = "swarm-expert"
```

`agents/swarm-coordinator.toml` also states that `agents/` is the canonical
adapter source path and that `.codex/agents/` is a runtime install/projection
concern, not a source-tree mirror used by these rows.

### Isolated plugin install

Probe environment:

```text
codex-cli 0.137.0
TMP_ROOT=/tmp/codex-agent-namespacing-probe.Inlysd
CODEX_HOME=/tmp/codex-agent-namespacing-probe.Inlysd/codex-home
MARKET=/tmp/codex-agent-namespacing-probe.Inlysd/marketplace
```

The probe built a temporary local marketplace fixture with:

```text
plugins/swarm-discussion/.codex-plugin/plugin.json
plugins/swarm-discussion/agents/
plugins/swarm-discussion/skills/
plugins/swarm-discussion/bin/
plugins/swarm-discussion/vendor/
```

Marketplace install summary:

```text
Added marketplace `swarm-discussion-namespacing-local`
Added plugin `swarm-discussion` from marketplace `swarm-discussion-namespacing-local`
Installed plugin root:
/private/tmp/codex-agent-namespacing-probe.Inlysd/codex-home/plugins/cache/swarm-discussion-namespacing-local/swarm-discussion/0.0.0-local-namespacing-probe
```

Available plugin listing showed:

```json
{
  "pluginId": "swarm-discussion@swarm-discussion-namespacing-local",
  "name": "swarm-discussion",
  "marketplaceName": "swarm-discussion-namespacing-local",
  "version": "0.0.0-local-namespacing-probe",
  "installed": false,
  "enabled": false,
  "installPolicy": "AVAILABLE",
  "authPolicy": "ON_INSTALL"
}
```

Installed plugin listing showed the same plugin as:

```json
{
  "pluginId": "swarm-discussion@swarm-discussion-namespacing-local",
  "name": "swarm-discussion",
  "marketplaceName": "swarm-discussion-namespacing-local",
  "version": "0.0.0-local-namespacing-probe",
  "installed": true,
  "enabled": true,
  "installPolicy": "AVAILABLE",
  "authPolicy": "ON_INSTALL"
}
```

Required installed-root paths were present:

| Installed cache-root path | Result |
|---|---|
| `.codex-plugin/plugin.json` | present |
| `agents/swarm-coordinator.toml` | present |
| `agents/swarm-expert.toml` | present |
| `skills/swarm-discussion/SKILL.md` | present |
| `bin/swarm_runtime_wrapper.py` | present |
| `vendor/swarm-runtime/runtime/swarm_rt.py` | present |

Agent values read from the installed cache root:

```text
AGENT_NAME agents/swarm-coordinator.toml swarm-coordinator
AGENT_NAME agents/swarm-expert.toml swarm-expert
```

User-level custom-agent state before and after the isolated install:

```text
before: swarm-expert=present, swarm-coordinator=absent
after:  swarm-expert=present, swarm-coordinator=absent
```

This confirms the isolated plugin install did not create or depend on real
user-level `~/.codex/agents` files. The pre-existing user-level
`swarm-expert` file remains background noise.

The temporary probe directory was deleted after evidence capture.

### CLI visibility

Commands:

```bash
codex --version
codex plugin --help
codex exec --help
codex debug prompt-input "probe agent visibility" | rg -n "swarm-coordinator|swarm-expert|Custom agent|Subagents|skill|plugin"
```

Observed:

- `codex --version` returned `codex-cli 0.137.0`.
- `codex plugin --help` exposes `add`, `list`, `marketplace`, and `remove`.
- `codex exec --help` does not expose an agent-selection option.
- `codex debug prompt-input` exposed skill and plugin context but did not expose
  a custom-agent registry listing for `swarm-coordinator` or `swarm-expert`.

Interpretation: CLI help and prompt-input debug output are useful negative
evidence for observable command surfaces, but they are not a full Codex runtime
registry API.

### Current host tool schema

Tool schema observed in the current Codex Desktop thread:

| Tool | Relevant fields | Namespacing implication |
|---|---|---|
| `codex_app.create_thread` | `prompt`, `target`, optional `model`, optional `thinking` | No field for selecting `swarm-coordinator` as the coordinator thread agent. |
| `codex_app.send_message_to_thread` | `threadId`, `prompt`, optional `model`, optional `thinking` | No field for changing an existing thread to `swarm-coordinator`. |
| `multi_agent_v1.spawn_agent` | optional `agent_type`; available roles include `swarm-expert`, `default`, `explorer`, `worker` | `swarm-expert` is currently spawnable as a nested subagent role in this session. |

This host schema distinction matters: `create_thread` creates an independent
user-visible Codex thread, while `spawn_agent` creates a nested subagent. The
presence of `swarm-expert` in `spawn_agent.agent_type` supports coordinator
fan-out to expert workers, but it does not establish native custom-agent
selection for the parent-created coordinator thread.

## Invocation

### Parent creates or resumes the coordinator thread

The parent skill should continue treating the coordinator as an independent
thread whose behavior is supplied by prompt contract:

```text
agent contract path: agents/swarm-coordinator.toml
agent source name:  swarm-coordinator
thread creation:    create_thread(prompt=..., target=...)
```

The parent may include or reference the coordinator TOML content in the
coordinator prompt. It should not assume the current `create_thread` tool can
select the coordinator by custom-agent name.

### Coordinator fans out to experts

The coordinator contract may treat `swarm-expert` as the expert source and
installed name:

```text
agent contract path: agents/swarm-expert.toml
agent source name:  swarm-expert
subagent surface:   spawn_agent(agent_type="swarm-expert", message=<runtime prompt>)
```

This is valid only on host surfaces where `spawn_agent` exposes
`agent_type="swarm-expert"`. If a future Codex host omits that role, the
coordinator must record the failed invocation and return a runtime-classified
failure rather than silently falling back to an untyped expert.

## Decisions

1. Treat `agents/` as the canonical adapter source path for
   `swarm-coordinator` and `swarm-expert`.
2. Treat installed plugin cache-root `agents/` as installed plugin evidence,
   not as proof of project or personal `.codex/agents/` projection.
3. Keep `swarm-coordinator` parent invocation prompt-driven until the
   thread-creation tool exposes an explicit custom-agent selection mechanism.
4. Treat `swarm-expert` as currently usable for nested fan-out because the host
   `spawn_agent` schema exposes that `agent_type`.
5. Keep real user-level `~/.codex/agents` state out of acceptance evidence.

## Residual Risk

Codex plugin and subagent surfaces may change. A later Codex release could add
thread creation with explicit custom-agent selection or documented plugin agent
projection. If that happens, update this research note and the parent skill
contract together; do not infer that behavior from plugin cache layout alone.

## Verification

Row acceptance:

```bash
test -f docs/researches/codex-installed-agent-namespacing.md && rg "swarm-coordinator" docs/researches/codex-installed-agent-namespacing.md && rg "swarm-expert" docs/researches/codex-installed-agent-namespacing.md && rg "Invocation" docs/researches/codex-installed-agent-namespacing.md && rg "Evidence" docs/researches/codex-installed-agent-namespacing.md
```

Additional contract checks:

```bash
rg "create_thread" docs/researches/codex-installed-agent-namespacing.md
rg "send_message_to_thread" docs/researches/codex-installed-agent-namespacing.md
rg "spawn_agent" docs/researches/codex-installed-agent-namespacing.md
rg "name field" docs/researches/codex-installed-agent-namespacing.md
```

Negative checks should return no matches for:

- any claim that independent `create_thread` currently accepts a custom-agent
  selector
- any claim that the user-level `swarm-expert` TOML under the home Codex agent
  directory is the evidence source for this row
