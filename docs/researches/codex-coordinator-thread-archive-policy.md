# Codex Coordinator Thread Archive Policy

> **Status**: Evidence recorded
> **Date**: 2026-06-20
> **Sprint row**: `coordinator-thread-archive-policy`
> **Worktree**: `/Users/syfq/dev/harness/swarm-discussion-codex-wt-coordinator-thread-archive-policy`

## Question

Should completed Codex coordinator threads be archived automatically after the
retained artifact tree and certification evidence are recorded?

This row answers only the product policy. It does not implement archive behavior
in the parent skill, does not change the wrapper/runtime boundary, and does not
archive or unarchive any existing Codex thread.

## Decision

Decision: use a `success-only` coordinator thread archive policy after retained
evidence exists.

Successful coordinator threads may be archived by the parent/operator after the
adapter has retained enough durable evidence to recover and audit the run:

- explicit coordinator `threadId`;
- retained `discussionDir`;
- trace/evidence/synthesis artifact paths;
- certification or local gate summary with required gates passing.

Failed, timed-out, partial, or evidence-missing coordinator threads should stay
visible for recovery. In those cases the visible thread is useful operational
state, and hiding it before durable evidence exists would make diagnosis harder.

Archiving is sidebar hygiene, not persistence. The retained runtime artifact
tree is the source of truth; raw thread messages and final coordinator prose are
secondary evidence.

## Evidence

### Product and workflow contracts

`docs/spec.md` defines the v1 topology as parent thread to dedicated coordinator
thread to no-tools expert persona, with runtime artifacts as authoritative
evidence. The spec open question for this row is whether completed coordinator
threads should be archived after retained artifacts and certification evidence
are recorded.

The source PRD keeps the wrapper/runtime out of host thread lifecycle and lists
coordinator auto-archive as an unresolved product policy. The parent skill owns
brief collection, coordinator creation/wakeup/read, and final relay. The wrapper
must remain a runtime command surface.

`bin/swarm_runtime_wrapper.py doctor --smoke-fixture` reports
`wrapperManagesThreads=false`, `topology=thread-coordinator`, and
`threadLifecycleOwner=skills/swarm-discussion/SKILL.md`. That boundary makes the
parent/operator the only acceptable place for a future archive action.

### Retained smoke evidence

The retained smoke discussion provides the first concrete success case:

```text
coordinator threadId: 019ee1bb-5223-7532-9571-1b7fa006a8f4
discussionDir:        smoke/discussions/smoke-retained-20260620-051524
manifest status:      completed
manifest mode:        release-smoke
```

`tasks/reviews/20260620-0509-retained-smoke-certification.review.md` records a
terminal pass and a retained smoke path. Its certification summary reports these
required gates as true:

```text
runtime-contract
vendor-manifest
adapter-smoke
validate-loop
validate-discussion
```

`smoke/discussions/smoke-retained-20260620-051524/certification/adapter-certification.json`
also records `ok=true`, the retained discussion path, the same required gate
summary, and real expert agent ids. That makes this run eligible for archiving
under the success-only policy, though this row intentionally performs no archive
action.

### Host archive surface

The current Codex Desktop host exposes `set_thread_archived` with an `archived`
boolean and an optional `threadId`. If `threadId` is omitted, the tool targets
the calling thread. A future implementation must therefore pass the explicit
coordinator `threadId` every time:

```text
set_thread_archived(threadId=<coordinator thread id>, archived=true)
```

The parent/operator must not omit `threadId`; doing so could archive the parent
thread instead of the completed coordinator thread. A future implementation
should re-check this host schema before adding automatic behavior, because UI
thread lifecycle behavior is outside the runtime protocol.

## Policy Matrix

| Coordinator result | Required evidence | Archive action |
|---|---|---|
| Completed success | `threadId`, `discussionDir`, retained artifacts, passing gates | May archive the coordinator thread |
| Completed with failed gates | `threadId` and returned artifact paths if available | Keep visible |
| Timeout or partial completion | `threadId` plus any partial state | Keep visible |
| Thread creation failed before artifacts | error text only | Nothing to archive |
| Missing retained evidence | incomplete or absent artifact tree | Keep visible |

## Invocation Rules

1. Archive only after a successful coordinator result and retained evidence.
2. Pass the explicit coordinator `threadId` to `set_thread_archived`.
3. Treat archive as reversible host lifecycle state; it must not delete,
   rewrite, or replace runtime artifacts.
4. Record the archived coordinator `threadId` alongside the retained artifact
   path in notes/review evidence when an implementation row later performs the
   action.
5. Keep failed or incomplete coordinator threads visible until the operator has
   enough evidence to diagnose the issue.

## Non-Goals

- Do not make the wrapper/runtime manage Codex thread lifecycle.
- Do not make raw Codex thread messages the primary audit record.
- Do not add a native custom-agent thread-selection assumption.
- Do not change retained smoke artifacts for this policy row.
- Do not close the `docs/spec.md` open question in this row; the later spec
  closeout row should decide how to reflect this policy in stable product truth.

## Failure Handling

If a future archive attempt fails after the retained artifacts and certification
summary already exist, the run should still be treated as successfully retained.
The parent/operator can report the archive failure as sidebar cleanup debt and
leave the coordinator thread visible. If the archive action accidentally targets
the wrong thread, the host lifecycle state should be reversed by unarchiving that
thread and the implementation should be treated as failed until the invocation
requires explicit coordinator `threadId`.

## Verification

This policy is verified by checking that the document contains the decision,
names the retained smoke evidence, identifies the host archive surface, requires
explicit `threadId`, keeps the wrapper boundary at `wrapperManagesThreads=false`,
and rejects success claims before retained artifacts and gate evidence exist.
