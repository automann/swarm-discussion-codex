# Product Spec: swarm-discussion-codex

> **Status**: Draft
> **Last Updated**: 2026-06-17
> **Owner**: Codex Adapter

## Product Outcome

`swarm-discussion-codex` delivers the Codex host adapter for the
`swarm-discussion` runtime family.

The stable product outcome is a Codex-native adapter where the parent thread
stays thin: the user provides a compact brief in the current thread and receives
only a synthesis plus artifact paths. For each discussion, the adapter creates a
dedicated Codex coordinator thread. That coordinator owns the runtime loop,
spawns persona experts, records Codex host transport, writes the discussion
artifact tree, and returns a compact completion summary.

The adapter is a thin host shell around the vendored
`swarm-discussion-runtime`. Runtime commands remain the authority for prompt
construction, fan-in collection, WAL mutation, validation, trace, and evidence.
Codex thread tools provide coordinator isolation and wakeup; they do not become
a separate AgentBus in v1.

## Success Criteria

- Primary workflow: a Codex parent thread collects a brief, creates one
  dedicated coordinator thread in the same project checkout, observes that
  coordinator with Codex thread tools, and relays the final synthesis after the
  runtime artifact gates pass.
- Quality bar: at least one real Codex-driven smoke discussion is retained under
  `smoke/discussions/<id>` and passes the runtime adapter certification gates:
  `runtime-contract`, `vendor-manifest`, `adapter-smoke`, `validate-loop`, and
  `validate-discussion`.
- Out of scope: a CTU-style AgentBus, persistent cross-discussion registry,
  autonomous P2P thread network, full standard/deep protocol coverage in the
  first smoke, or protocol/runtime logic copied into Codex adapter files.

## Constraints

- Technical: vendor the runtime at `vendor/swarm-runtime/` and never edit
  vendored files in place. The wrapper may discover the vendored runtime, run
  `doctor --smoke-fixture`, report host capabilities, and delegate runtime
  commands; it must not manage Codex threads or implement discussion mechanics.
- Technical: `skills/swarm-discussion/SKILL.md` owns parent-thread lifecycle:
  collect the brief, create or wake the coordinator thread, poll/read
  coordinator completion, and present the result. Thread lifecycle is host
  behavior, not runtime behavior.
- Technical: ship `agents/swarm-coordinator.toml` as the canonical coordinator
  contract. In v1 the parent skill injects or references that contract in the
  new thread's initial prompt. If Codex later supports creating threads with a
  native agent type, the adapter may switch to native `swarm-coordinator`
  instantiation without changing the product contract.
- Technical: ship `agents/swarm-expert.toml` as a no-tools leaf persona.
  Experts receive runtime-produced prompt text and return only the requested
  JSON. They must not manage threads, spawn agents, mutate artifacts, or call
  runtime helpers.
- Technical: `doctor` reports host nesting capability for diagnostics, but v1
  always uses the thread-coordinator topology. Native nested-subagent
  orchestration is a future explicit compatibility mode, not an automatic
  topology switch.
- Compliance: raw Codex transcripts and coordinator final messages are secondary
  evidence. Runtime artifacts and certification gates are the source of truth.
- Delivery: normal user discussions default to `.swarm/discussions/<id>` in the
  current workspace. Release/certification smoke discussions are retained under
  `smoke/discussions/<id>`.

## Acceptance Scenarios

- Given the adapter has a vendored runtime bundle,
  When `python3 bin/swarm_runtime_wrapper.py doctor --smoke-fixture` runs,
  Then it resolves the vendored runtime, validates the
  `swarm-runtime-v2-alpha` contract, reports host capability diagnostics, and
  passes the bundled fixture smoke without mutating the user's workspace.

- Given a user asks for a swarm discussion in Codex,
  When the parent skill starts the workflow,
  Then it creates one dedicated coordinator thread in the current project local
  checkout and gives it the brief plus the canonical coordinator contract.

- Given the coordinator thread is running,
  When it executes a minimal host-native smoke discussion,
  Then it uses runtime `context-build` and `prompt-build`, spawns real
  `swarm-expert` personas, records returned Codex `agent_id` values, appends
  every raw `wait_agent` batch through runtime transport helpers, collects
  results through `transport-collect`, and writes WAL state only through runtime
  commands.

- Given the coordinator completes,
  When it returns to the parent thread,
  Then its final message is only an index: `ok`, `discussionDir`, synthesis,
  trace, evidence, and local gate summaries. The parent or release operator
  still treats the retained artifact tree and certification command as the
  authoritative verdict.

- Given a retained smoke discussion under `smoke/discussions/<id>`,
  When the runtime repo runs:
  ```bash
  python3 conformance/certify_adapter.py \
    --discussion <dir> \
    --vendored <repo>/vendor/swarm-runtime \
    --runtime <repo>/vendor/swarm-runtime/runtime/swarm_rt.py
  ```
  Then all certification checks pass and the result is recorded for release or
  aggregator listing.

## Open Questions

- What exact Codex plugin install layout should expose `agents/`, `skills/`,
  `bin/`, and `vendor/swarm-runtime/` for a local development install?
- What is the Codex namespacing behavior for installed `swarm-expert` and
  `swarm-coordinator` agent contracts?
- Should completed coordinator threads be archived automatically after the
  retained artifact tree and certification evidence are recorded?
