---
name: swarm-discussion
description: Start a Codex-hosted swarm discussion by creating one independent coordinator thread that owns the runtime loop and returns a compact artifact index.
when_to_use: "swarm-discussion, swarm discussion, multi-expert discussion, expert panel, run a coordinator discussion, 让多个专家讨论, 多专家讨论, 群体讨论"
---

# swarm-discussion

Use this skill when the user wants a multi-expert discussion inside the current
Codex checkout. The current thread stays thin: it collects a compact brief,
starts or wakes one dedicated coordinator thread, waits for the coordinator's
final index, and relays only the synthesis plus artifact paths.

The parent thread does not run the discussion itself. It delegates discussion
execution to the coordinator contract at `agents/swarm-coordinator.toml`.

## Parent Thread Responsibilities

1. Collect a brief that is complete enough for a discussion.
   - Ask only for missing discussion-critical inputs.
   - Preserve the user's original wording when possible.
   - Do not expand the brief into expert prompts in the parent thread.
2. Resolve the current workspace root.
   - Use the current repository checkout as the execution context.
   - Treat normal discussion output as a coordinator-owned artifact tree under
     `.swarm/discussions/<id>`.
   - Pass the intended `discussionDir` to the coordinator when the user or host
     already selected one; otherwise let the coordinator allocate the concrete
     id and return it.
3. Create or wake exactly one independent coordinator thread for the discussion.
   - Use the Codex thread-management tool surface available in the host.
   - Apply the coordinator contract by referencing or embedding
     `agents/swarm-coordinator.toml` in the coordinator's initial prompt.
   - Do not create expert threads or persona agents from the parent thread.
4. Read or poll the coordinator until it returns a terminal result.
   - A terminal success result includes `ok: true`, `discussionDir`, synthesis,
     trace path, evidence path, and local gate summaries.
   - A terminal failure result includes `ok: false`, `discussionDir` when one
     exists, failure summary, available trace or evidence paths, and gate
     summaries.
5. Relay a compact result to the user.
   - Show the synthesis or failure summary.
   - Show `discussionDir`, trace path, evidence path, and local gate summaries.
   - Do not paste raw transport logs, expert transcripts, or intermediate WAL
     content unless the user explicitly asks to inspect artifacts.

## Coordinator Handoff Packet

When starting or waking the coordinator thread, send a concise packet with these
fields:

```text
Task: run one swarm discussion as the dedicated coordinator.
Workspace root: <absolute path to the current checkout>
Brief: <user brief, including any constraints or acceptance criteria>
Mode: normal discussion unless the user explicitly requests release smoke
discussionDir: <existing or requested discussion directory, or "allocate">
Coordinator contract: agents/swarm-coordinator.toml
Return shape: ok, discussionDir, synthesis or failure summary, trace path,
evidence path, local gate summaries.
```

The packet should make clear that the coordinator owns runtime execution,
expert fan-out, host transport capture, artifact writes, validation, trace, and
evidence generation. The parent thread only manages the lifecycle around the
coordinator thread.

## Failure Handling

- If Codex thread-management tools are unavailable, stop and report that the
  host cannot start a coordinator thread. Do not fall back to running experts
  directly in the parent thread.
- If coordinator thread creation fails before an artifact tree exists, report
  the failure without inventing `discussionDir`, trace, or evidence paths.
- If the coordinator times out, report the timeout and any thread identifier or
  partial artifact path that is actually known.
- If the coordinator returns failed gates, report the coordinator's failure
  index and artifact paths. Do not present the synthesis as accepted.

## Boundaries

- The parent thread must not spawn expert personas directly.
- The parent thread must not write discussion artifacts, WAL state, trace, or
  evidence files.
- The parent thread must not run runtime transport, merge, validation, or prompt
  construction commands.
- The parent thread must not treat raw Codex messages as the source of truth.
  Runtime artifacts and the coordinator's local gate summaries are authoritative.
- The coordinator is an independent Codex thread, not a nested subagent created
  by an expert or persona.

## Completion Checklist

Before answering the user, confirm that the coordinator returned:

- `ok`
- `discussionDir`
- synthesis or failure summary
- trace path
- evidence path
- local gate summaries

If any field is missing, ask or wake the coordinator for the missing terminal
index instead of guessing.
