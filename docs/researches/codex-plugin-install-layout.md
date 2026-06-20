# Codex Plugin Install Layout Probe

> **Status**: Evidence recorded
> **Date**: 2026-06-20
> **Sprint row**: `plugin-install-layout-probe`
> **Worktree**: `/Users/syfq/dev/harness/swarm-discussion-codex-wt-plugin-install-layout-probe`

## Question

What exact Codex local-development plugin install layout exposes the
`swarm-discussion-codex` adapter surfaces:

- `agents/swarm-coordinator.toml`
- `agents/swarm-expert.toml`
- `skills/swarm-discussion/SKILL.md`
- `bin/swarm_runtime_wrapper.py`
- `vendor/swarm-runtime/runtime/swarm_rt.py`

This row only answers the install layout question. Installed agent namespacing
and coordinator thread archive policy remain separate sprint rows.

## Current Repo Inputs

The source checkout uses these canonical adapter paths:

| Surface | Source path | Role |
|---|---|---|
| Coordinator contract | `agents/swarm-coordinator.toml` | Canonical coordinator contract; `agents/` is the source path |
| Expert contract | `agents/swarm-expert.toml` | No-tools leaf persona contract |
| Parent skill | `skills/swarm-discussion/SKILL.md` | Parent-thread lifecycle; starts/wakes one coordinator thread |
| Wrapper | `bin/swarm_runtime_wrapper.py` | Thin runtime wrapper; discovers plugin root from `bin/..` |
| Runtime CLI | `vendor/swarm-runtime/runtime/swarm_rt.py` | Vendored runtime command surface |

`agents/swarm-coordinator.toml` explicitly says `agents/` is the canonical
adapter source path and `.codex/agents/` is a later runtime install/projection
concern. This probe therefore does not create or depend on `.codex/agents/`
mirrors.

## Official Layout Inputs

- Codex plugins use `.codex-plugin/plugin.json` as the required plugin entry
  point.
- Plugin manifest component paths such as `skills`, `mcpServers`, `apps`, and
  `hooks` resolve relative to the plugin root and should start with `./`.
- Codex custom agents are documented as standalone TOML files under
  `~/.codex/agents/` for personal agents or `.codex/agents/` for
  project-scoped agents. That answers where Codex currently documents custom
  agent files, but not whether a plugin-level `agents/` directory is projected
  into those locations.

References:

- <https://developers.openai.com/codex/plugins/build>
- <https://developers.openai.com/codex/subagents>

## Tool Versions

```text
codex-cli 0.137.0
local-repo-harness 0.5.16
```

## Isolation Boundary

The successful probe used an isolated Codex home and local marketplace fixture:

```text
TMP_ROOT=/tmp/codex-plugin-layout-probe.xVyO1z
CODEX_HOME=/tmp/codex-plugin-layout-probe.xVyO1z/codex-home
MARKET=/tmp/codex-plugin-layout-probe.xVyO1z/marketplace
PLUGIN_FIXTURE=/tmp/codex-plugin-layout-probe.xVyO1z/marketplace/plugins/swarm-discussion
```

The fixture copied these source directories into
`plugins/swarm-discussion/`:

```text
agents/
skills/
bin/
vendor/swarm-runtime/
.codex-plugin/plugin.json
```

The temporary `.codex-plugin/plugin.json` used `skills: "./skills/"`. No
manifest field was added for `agents/`; the point of this row is to observe
whether keeping `agents/` in the plugin root is enough for adapter-relative
contract references and wrapper diagnostics.

The local marketplace entry used:

```json
{
  "name": "swarm-discussion-local",
  "plugins": [
    {
      "name": "swarm-discussion",
      "source": { "source": "local", "path": "./plugins/swarm-discussion" },
      "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
      "category": "Developer Tools"
    }
  ]
}
```

An initial fixture using `"authentication": "NONE"` failed with:

```text
unknown variant `NONE`, expected `ON_INSTALL` or `ON_USE`
```

That failure establishes the local marketplace schema constraint used by the
successful probe.

## Commands And Results

### Marketplace Add

```bash
CODEX_HOME="$CODEX_HOME" codex plugin marketplace add "$MARKET"
```

Result:

```text
Added marketplace `swarm-discussion-local` from /private/tmp/codex-plugin-layout-probe.xVyO1z/marketplace.
Installed marketplace root: /private/tmp/codex-plugin-layout-probe.xVyO1z/marketplace
```

### Available Plugin Listing

```bash
CODEX_HOME="$CODEX_HOME" codex plugin list --available --json
```

Relevant result:

```json
{
  "pluginId": "swarm-discussion@swarm-discussion-local",
  "name": "swarm-discussion",
  "marketplaceName": "swarm-discussion-local",
  "version": "0.0.0-local-probe",
  "installed": false,
  "enabled": false,
  "source": {
    "source": "local",
    "path": "/private/tmp/codex-plugin-layout-probe.xVyO1z/marketplace/plugins/swarm-discussion"
  },
  "installPolicy": "AVAILABLE",
  "authPolicy": "ON_INSTALL"
}
```

### Plugin Add

```bash
CODEX_HOME="$CODEX_HOME" codex plugin add swarm-discussion --marketplace swarm-discussion-local
```

Result:

```text
Added plugin `swarm-discussion` from marketplace `swarm-discussion-local`.
Installed plugin root: /private/tmp/codex-plugin-layout-probe.xVyO1z/codex-home/plugins/cache/swarm-discussion-local/swarm-discussion/0.0.0-local-probe
```

### Installed Plugin Listing

```bash
CODEX_HOME="$CODEX_HOME" codex plugin list --json
```

Relevant result:

```json
{
  "pluginId": "swarm-discussion@swarm-discussion-local",
  "name": "swarm-discussion",
  "marketplaceName": "swarm-discussion-local",
  "version": "0.0.0-local-probe",
  "installed": true,
  "enabled": true,
  "source": {
    "source": "local",
    "path": "/private/tmp/codex-plugin-layout-probe.xVyO1z/marketplace/plugins/swarm-discussion"
  },
  "installPolicy": "AVAILABLE",
  "authPolicy": "ON_INSTALL"
}
```

## Observed Installed Root

The installed plugin root reported by `codex plugin add` was:

```text
/private/tmp/codex-plugin-layout-probe.xVyO1z/codex-home/plugins/cache/swarm-discussion-local/swarm-discussion/0.0.0-local-probe
```

The filesystem path is the same directory as:

```text
/tmp/codex-plugin-layout-probe.xVyO1z/codex-home/plugins/cache/swarm-discussion-local/swarm-discussion/0.0.0-local-probe
```

## Required Path Table

The installed cache root exposed every required adapter path:

| Required path | Observed in installed cache root |
|---|---|
| `.codex-plugin/plugin.json` | present |
| `agents/swarm-coordinator.toml` | present |
| `agents/swarm-expert.toml` | present |
| `skills/swarm-discussion/SKILL.md` | present |
| `bin/swarm_runtime_wrapper.py` | present |
| `vendor/swarm-runtime/runtime/swarm_rt.py` | present |
| `vendor/swarm-runtime/vendor-manifest.json` | present |

The installed cache root contained 60 files in this fixture.

## Wrapper Doctor From Installed Root

Command:

```bash
python3 "$PLUGIN_ROOT/bin/swarm_runtime_wrapper.py" doctor --smoke-fixture
```

Summary:

```json
{
  "ok": true,
  "pluginRoot": "/private/tmp/codex-plugin-layout-probe.xVyO1z/codex-home/plugins/cache/swarm-discussion-local/swarm-discussion/0.0.0-local-probe",
  "runtimeSource": "vendored",
  "vendorManifestOk": true,
  "fixtureSmokeOk": true,
  "coordinatorContract": {
    "exists": true,
    "path": "agents/swarm-coordinator.toml",
    "sprintRow": "coordinator-and-expert-agent-contracts",
    "status": "present"
  },
  "threadLifecycleOwner": {
    "exists": true,
    "path": "skills/swarm-discussion/SKILL.md",
    "sprintRow": "parent-skill-thread-lifecycle",
    "status": "present"
  }
}
```

This confirms `bin/swarm_runtime_wrapper.py` can continue using
`Path(__file__).resolve().parents[1]` as the plugin root in the installed cache
layout.

## User-Level Non-Dependence

Before and after the isolated probe:

```text
present /Users/syfq/.codex/agents/swarm-expert.toml
absent  /Users/syfq/.codex/agents/swarm-coordinator.toml
absent  /Users/syfq/.codex/plugins/cache/swarm-discussion
```

The pre-existing `~/.codex/agents/swarm-expert.toml` is a user-level custom
agent file and is not proof of plugin installation. The successful evidence in
this row comes from the isolated `CODEX_HOME` cache root and the installed-root
wrapper doctor result.

## Conclusion

For Codex CLI `0.137.0`, a local marketplace install copies the plugin into:

```text
$CODEX_HOME/plugins/cache/<marketplace>/<plugin>/<version>/
```

Within that installed cache root, the adapter can expose:

```text
agents/
skills/
bin/
vendor/swarm-runtime/
.codex-plugin/plugin.json
```

The current wrapper root discovery works in this layout, and `doctor
--smoke-fixture` succeeds from the installed cache root. Therefore row 1 can
treat `agents/`, `skills/`, `bin/`, and `vendor/swarm-runtime/` as plugin-root
relative surfaces for local development installs.

What remains unresolved for row 2: whether Codex projects plugin-level
`agents/` into spawnable custom-agent names, or whether the adapter must provide
an explicit `.codex/agents/` projection for installed `swarm-coordinator` and
`swarm-expert` namespacing.

## Cleanup

The probe was intentionally run under `/tmp/codex-plugin-layout-probe.xVyO1z`.
The first failed schema probe used `/tmp/codex-plugin-layout-probe.H21Zcm`.
Both temporary directories were deleted after the durable evidence above was
recorded.
