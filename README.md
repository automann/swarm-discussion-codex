# swarm-discussion-codex

Codex root plugin adapter for the `swarm-discussion` runtime family.

This repository is the installable Codex plugin root. The parent Codex thread
stays thin: it collects the user's brief, creates temporary discussion-scoped
expert custom agents, starts one dedicated coordinator thread, and relays only a
compact result index. The coordinator thread owns the runtime loop and uses the
vendored `swarm-discussion-runtime` for prompts, transport capture, WAL updates,
validation, trace, evidence, and retained artifacts.

## Current Release

| Field | Value |
|---|---|
| Plugin version | `0.3.0` |
| Release tag | `v0.3.0` |
| Runtime sha | `04f4974f26f5d3f8da55cc3b1c2f9068a83d4cf5` |
| Runtime compatibility | `swarm-runtime-v2-alpha` |
| Runtime files | `58` vendored files |
| Retained projected smoke | `smoke/discussions/smoke-projected-20260621-2359` |
| Required certification mode | `--require-projection` |
| Aggregator distribution | `automann/swarm-discussion` pins this repo at `v0.3.0` |

The retained projected smoke proves the v0.3.0 topology: parent-created
discussion-scoped `.codex/agents/` expert files, coordinator-owned runtime
execution, projected expert invocation, runtime-owned `agentDescriptor` and
`transport.customAgentProjection` provenance, terminal parent cleanup, and zero
remaining run-scoped projected agent files.

## Install

End users should install through the top-level `swarm-discussion` aggregator
marketplace:

```bash
codex plugin marketplace add automann/swarm-discussion
codex plugin add swarm-discussion --marketplace swarm-discussion
```

The aggregator entry points at
`https://github.com/automann/swarm-discussion-codex.git` and pins the
`v0.3.0` ref. This adapter repo remains the root plugin payload; the aggregator
is only the distribution catalog.

## How It Runs

1. The parent skill in `skills/swarm-discussion/SKILL.md` receives the user
   brief and keeps the parent thread small.
2. Before creating the coordinator thread, the parent derives one temporary
   custom-agent file per expert from `agents/swarm-expert.toml` and writes those
   run-scoped files under the current workspace's `.codex/agents/`.
3. The parent starts one independent Codex coordinator thread and gives it the
   brief, projected expert roster, cleanup policy, and the coordinator contract
   from `agents/swarm-coordinator.toml`.
4. The coordinator uses `bin/swarm_runtime_wrapper.py` or the vendored runtime
   to run `context-build`, `prompt-build`, transport initialization, raw host
   collection, fan-in, validation, trace, and evidence.
5. The coordinator invokes only the pre-created projected expert custom agents.
   It prefers `@<projected-agent-name>` when that route gives precise host
   evidence, and can fall back to explicit spawn with the projected custom-agent
   name when certification evidence requires it.
6. The coordinator returns only a compact final index: `ok`, `discussionDir`,
   synthesis or failure summary, trace path, evidence path, and local gate
   summaries.
7. The parent removes only the run-scoped `.codex/agents/<expert-name>.toml`
   files it created for that discussion, then reports the final index.

The parent does not run experts directly, write discussion artifacts, merge
transport batches, or validate the discussion. Those responsibilities belong to
the coordinator plus runtime.

## Repository Shape

| Path | Purpose |
|---|---|
| `.codex-plugin/plugin.json` | Codex plugin manifest for the root plugin. |
| `skills/swarm-discussion/SKILL.md` | Parent-thread entrypoint and lifecycle contract. |
| `agents/swarm-coordinator.toml` | Canonical coordinator thread contract. |
| `agents/swarm-expert.toml` | Template for temporary projected expert custom agents. |
| `bin/swarm_runtime_wrapper.py` | Thin diagnostic and command wrapper around the vendored runtime. |
| `vendor/swarm-runtime/` | Pinned runtime bundle used for prompt, transport, WAL, validation, trace, and evidence. |
| `smoke/discussions/smoke-projected-20260621-2359/` | Retained v0.3.0 projected smoke evidence. |
| `docs/spec.md` | Stable product truth for this adapter. |
| `docs/researches/` | Decision evidence for Codex plugin layout, agent namespacing, projection, and thread policy. |

During an actual run, `.codex/agents/swarm-<run-id>-*.toml` files are temporary
host state created by the parent. They are not source contracts and should not
be left behind after a terminal coordinator result.

Local development checkouts may also contain ignored repo-harness, planning,
research, and operator files. Those files are useful maintainer context but are
not part of the public plugin verdict.

## Runtime Boundary

The Codex adapter is a host shell around the runtime. Codex thread tools provide
coordinator isolation and custom-agent invocation. The vendored runtime remains
the authority for:

- context construction
- prompt construction
- spawn-order and host transport normalization
- raw wait batch persistence
- fan-in collection and merge behavior
- WAL mutation
- discussion validation
- trace and evidence generation
- adapter certification

Wrapper diagnostics can report host capabilities and run fixture smoke checks,
but they do not replace runtime certification gates. Do not copy protocol or
discussion mechanics into adapter files; re-vendor from
`swarm-discussion-runtime` instead.

## Verification

Check readiness with the wrapper doctor (runtime contract, bundled-fixture
gates, and host diagnostics):

```bash
python3 bin/swarm_runtime_wrapper.py doctor --smoke-fixture
```

A root plugin install smoke lives under `scripts/` as a maintainer-local tool;
it is intentionally untracked and not part of the published plugin payload.

Replay release certification with a checkout of
`swarm-discussion-runtime` available locally:

```bash
RUNTIME_REPO=/path/to/swarm-discussion-runtime
PYTHONDONTWRITEBYTECODE=1 python3 "$RUNTIME_REPO/conformance/certify_adapter.py" \
  --require-projection \
  --discussion smoke/discussions/smoke-projected-20260621-2359 \
  --vendored vendor/swarm-runtime \
  --runtime vendor/swarm-runtime/runtime/swarm_rt.py
```

After the retained smoke, this zero-residue check should print no run-scoped
projected expert files:

```bash
test ! -d .codex/agents || find .codex/agents -maxdepth 1 -name 'swarm-20260621-2359-*.toml' -print
```

## Release Maintenance

For a new adapter release:

1. Re-vendor the runtime from `swarm-discussion-runtime`; do not edit vendored
   runtime files in place.
2. Update `.codex-plugin/plugin.json` and `vendor/swarm-runtime/vendor-manifest.json`
   only when the version or runtime pin actually changes.
3. Run wrapper doctor and projected adapter certification with
   `--require-projection` (the local install smoke under `scripts/` is optional).
4. Retain the certification discussion under `smoke/discussions/<id>` when it is
   release evidence.
5. Tag this repository.
6. Update the top-level `swarm-discussion` aggregator to pin the certified tag.

## What This Repo Is Not

- It is not the top-level marketplace aggregator. That repo is
  `automann/swarm-discussion`.
- It is not the runtime source repository. Runtime source and conformance gates
  live in `swarm-discussion-runtime`.
- It is not a CTU-style AgentBus, persistent expert registry, or P2P thread
  network.
- It does not make experts ordinary top-level Codex threads. Expert workers are
  discussion-scoped custom agents projected before the coordinator thread
  starts.
