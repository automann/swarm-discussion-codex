# swarm-discussion-codex

Codex root plugin adapter for the `swarm-discussion` runtime family.

This repository is the installable Codex plugin root. The parent Codex thread
stays thin: it collects the user's brief, creates temporary discussion-scoped
expert custom agents, starts one dedicated coordinator thread, and relays only a
compact result index. The coordinator thread owns the runtime loop and uses the
vendored `swarm-discussion-runtime` for prompts, transport capture, WAL updates,
validation, trace, evidence, and retained artifacts.

## Current Release And Stress Readiness

| Field | Value |
|---|---|
| Plugin manifest version | `0.4.1` |
| Latest release tag | `v0.4.1` |
| Tagged runtime sha | `c84393111158674e743e1dc082271f467043f496` |
| Runtime 009 readiness sha | `c84393111158674e743e1dc082271f467043f496` |
| Runtime compatibility | `swarm-runtime-v2-alpha` |
| Runtime 009 files | `60` vendored files |
| Retained projected smoke | `smoke/discussions/smoke-projected-20260621-2359` |
| Retained stress smoke | `smoke/discussions/smoke-stress-20260623-0404` |
| Stress evidence profile | `stress-minimal-v2` |
| Stress smoke mode | `mode=deep`, `stressPolicy=required` |
| Required certification mode | `--require-projection --require-stress` |
| Aggregator distribution | `automann/swarm-discussion` pins this repo at `v0.4.1` |

The published tag is `v0.4.1`; the top-level aggregator pins this repo at `v0.4.1`,
vendoring runtime `c843931` and certifying both the projected and the retained
stress smoke with `--require-projection --require-stress`. The retained projected smoke proves the v0.3.0 topology:
parent-created discussion-scoped `.codex/agents/` expert files,
coordinator-owned runtime execution, projected expert invocation,
runtime-owned `agentDescriptor` and `transport.customAgentProjection`
provenance, terminal parent cleanup, and zero remaining run-scoped projected
agent files.

The runtime 009 readiness line is stress-certified by the retained
`stress-minimal-v2` Codex smoke at
`smoke/discussions/smoke-stress-20260623-0404`. It uses `mode=deep` and
`stressPolicy=required`, records the runtime-owned `stress-check` decision, and
passes certification with both `--require-projection` and `--require-stress`.
This proves structural disagreement: challenge edges, a real stress pass when
required, and a cited response to the stress message. It does not claim that
the disagreement was substantively good; retained real-host artifacts and
review remain the evidence for that host-truth question.

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
is only the distribution catalog. Runtime 009 stress readiness on `main` is not
distributed by the aggregator until a later tag and aggregator pin update.

## Usage

Once installed through the [aggregator marketplace](https://github.com/automann/swarm-discussion), just ask
in plain language in your Codex thread:

```text
Use swarm-discussion to decide: should the orders service adopt event sourcing?
```

Bring the questions where a lone model would just nod along — architecture & design trade-offs, one-way-door
calls, adversarial reviews, open questions where easy consensus would be suspicious. **What comes back** is a
compact index: a **recommendation**, the **strongest surviving counter-argument**, the **open questions**, and
pointers to the traceable artifacts (cited argument graph, synthesis, trace/evidence). The debate runs in a
dedicated coordinator thread, so the parent thread stays small.

**Two knobs, set together.** `mode` controls *breadth & cost* (how many experts, how many rounds);
`stressPolicy` controls *how hard they must disagree* (whether a mandatory anti-consensus stress pass
runs before synthesis). They're orthogonal — combine them freely:

```text
/swarm-discussion [--mode lightweight|standard|deep] [--stressPolicy auto|required|off] <your question>
```

`stressPolicy` **defaults from `mode`** (`lightweight → off`, `standard → auto`, `deep → required`), so
usually you set neither — pick a mode by stakes, or just describe the problem (*"go **deep** and don't let
them agree too fast"* ≈ `--mode deep --stressPolicy required`). Pass `--stressPolicy` only to override that
default:

| Invocation | What runs |
|---|---|
| `/swarm-discussion Should we adopt event sourcing?` | inferred mode + its default stress policy |
| `/swarm-discussion --mode standard --stressPolicy auto <topic>` | 2–3 experts; stress pass *only if* they converge with no real disagreement |
| `/swarm-discussion --mode deep <topic>` | full panel + a `required` stress pass (deep's default) |
| `/swarm-discussion --mode lightweight --stressPolicy required <topic>` | cheap 2-expert panel, but still force one stress pass |

Both knobs are detailed below; it defaults to **standard** when you say nothing.

## Modes

Pick a tier by stakes and budget (default **Standard**):

| Mode | Panel | Rounds | Calls/round | Use when |
|------|-------|--------|-------------|----------|
| `lightweight` | 2 dynamic experts + Moderator & Contrarian | 1–2 | 3–5 | quick sanity check, idea validation |
| `standard` *(default)* | 2–3 dynamic experts + 4 fixed roles | 2–3 | 5–8 | typical design decision, trade-off analysis |
| `deep` | 3–4 dynamic experts + 4 fixed roles | 3–5 | 8–12 | unprecedented problems, high-stakes calls |

> **Quality over quantity:** two rounds of *genuine* disagreement beat five rounds of polite agreement.

### Stress policy — engineering the disagreement

Orthogonal to `mode`, **`stressPolicy`** controls whether the panel must run an anti-consensus
**stress pass** (the Contrarian attacks the *strongest* agreement; the challenged experts answer
and may shift position) before it synthesizes:

| `stressPolicy` | Behavior | Default for |
|---|---|---|
| `required` | always run the stress pass, however smooth the round looks | `deep` |
| `auto` | run it only if the round reached consensus with no real disagreement | `standard` |
| `off` | no stress pass — fast convergence | `lightweight` |

You rarely set it (it defaults from the `mode`), but you can ask in plain language:
*"stress-test this"* / *"don't converge too fast"* → `required`. The runtime **certifies** that a
`required`/`auto` discussion actually engineered disagreement (a stress pass answered by a cited
response, or a recorded decision that none was needed) — a checked contract, not a suggestion.

Every panel runs **dynamic experts** generated per topic — each with explicit *stakes* and *blind spots* —
plus **fixed roles** that keep the debate honest:

| Role | Keeps the debate honest by… |
|------|------------------------------|
| 🧭 **Moderator** | framing the real fault lines and running the quality gate — *prevents premature consensus* |
| 🥊 **Contrarian** | stress-testing the *strongest* point of agreement — *prevents echo chambers* |
| 🔭 **Cross-Domain** *(standard / deep)* | bringing analogies from other fields — *prevents domain-locked thinking* |
| 📜 **Historian** *(standard / deep)* | building the cited argument graph and synthesis — *keeps it traceable* |

The full mode / role / round protocol lives in the runtime's
[`protocol/PROTOCOL.md`](https://github.com/automann/swarm-discussion-runtime/blob/main/protocol/PROTOCOL.md).

## Stress Policy

Runtime 009 treats depth and stress as two separate controls:

| Field | Values | Purpose |
|---|---|---|
| `mode` | `lightweight`, `standard`, `deep` | Cost, panel size, and round depth. |
| `stressPolicy` | `off`, `auto`, `required` | Whether an anti-consensus stress pass is skipped, data-triggered, or mandatory. |

When the user does not specify a stress policy, defaults are derived from mode:
`lightweight -> off`, `standard -> auto`, and `deep -> required`.

The coordinator contract is intentionally bounded:
`declaration -> argumentation -> stress-check -> contrarian -> response -> synthesis`.
After argumentation, the coordinator calls runtime `stress-check`, records the
runtime-owned `stressRequired` and `argumentDigest`, then runs the contrarian
stress pass and cited expert response only when the runtime decision requires
it. The adapter does not re-derive the quality signal or write a parallel
quality store.

The `--require-stress` gate proves structural disagreement: challenge edges, a
real stress pass when required, and a cited response. It does not prove that
the disagreement was substantively good; retained real-host smoke evidence and
review still carry that host-truth burden.

## How It Runs

1. The parent skill in `skills/swarm-discussion/SKILL.md` receives the user
   brief and keeps the parent thread small.
2. Before creating the coordinator thread, the parent derives one temporary
   custom-agent file per expert from `agents/swarm-expert.toml` and writes those
   run-scoped files under the current workspace's `.codex/agents/`.
3. The parent starts one independent Codex coordinator thread and gives it the
   brief, canonical `mode`, `stressPolicy`, projected expert roster, cleanup
   policy, and the coordinator contract from `agents/swarm-coordinator.toml`.
4. The coordinator uses `bin/swarm_runtime_wrapper.py` or the vendored runtime
   to run `context-build`, `prompt-build`, transport initialization, raw host
   collection, fan-in, `stress-check`, validation, trace, and evidence.
5. The coordinator invokes only the pre-created projected expert custom agents.
   It prefers `@<projected-agent-name>` when that route gives precise host
   evidence, and can fall back to explicit spawn with the projected custom-agent
   name when certification evidence requires it.
6. The coordinator returns only a compact final index: `ok`, `discussionDir`,
   synthesis or failure summary, trace path, evidence path, and local gate
   summaries.
7. The parent removes only the run-scoped `.codex/agents/<expert-name>.toml`
   files it created for that discussion, then requires the final workflow to
   regenerate trace/evidence against the clean projection manifest before
   reporting projection-certified success.

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
| `smoke/discussions/smoke-stress-20260623-0404/` | Retained runtime 009 `stress-minimal-v2` smoke evidence with `mode=deep` and `stressPolicy=required`. |
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
  --require-stress \
  --discussion smoke/discussions/smoke-stress-20260623-0404 \
  --vendored vendor/swarm-runtime \
  --runtime vendor/swarm-runtime/runtime/swarm_rt.py
```

For the older `v0.3.0` projection-only tag, replay
`smoke/discussions/smoke-projected-20260621-2359` with
`--require-projection` only.

After the retained stress smoke, this zero-residue check should print no
run-scoped projected expert files:

```bash
test ! -d .codex/agents || find .codex/agents -maxdepth 1 -name 'swarm-smoke-stress-20260623-0404-*.toml' -print
```

## Release Maintenance

For a new adapter release:

1. Re-vendor the runtime from `swarm-discussion-runtime`; do not edit vendored
   runtime files in place.
2. Update `.codex-plugin/plugin.json` and `vendor/swarm-runtime/vendor-manifest.json`
   only when the version or runtime pin actually changes.
3. Run wrapper doctor and projected adapter certification with
   `--require-projection` and, for runtime 009 stress-certified releases,
   `--require-stress` (the local install smoke under `scripts/` is optional).
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
