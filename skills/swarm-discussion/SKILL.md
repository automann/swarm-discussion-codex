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
execution to the coordinator contract at `agents/swarm-coordinator.toml`. The
parent does own the host lifecycle around that coordinator, including temporary
project-scoped custom-agent projection for the expert workers.

## Parent Thread Responsibilities

1. Collect a brief that is complete enough for a discussion.
   - Ask only for missing discussion-critical inputs.
   - Preserve the user's original wording when possible.
   - Do not expand the brief into expert prompts in the parent thread.
   - Map user depth wording to a canonical runtime `Mode`:
     `lightweight`, `standard`, or `deep`. Default to `standard`.
   - Map user stress wording to an explicit `stressPolicy`: `off`, `auto`, or
     `required`. Default by mode when the user does not specify one:
     `lightweight -> off`, `standard -> auto`, `deep -> required`.
   - Do not pass free-text modes such as `normal` to the coordinator.
2. Resolve the current workspace root.
   - Use the current repository checkout as the execution context.
   - Treat normal discussion output as a coordinator-owned artifact tree under
     `.swarm/discussions/<id>`.
   - Treat release/certification smoke output as a coordinator-owned artifact
     tree under `smoke/discussions/<id>` only when the user or release workflow
     explicitly requests smoke certification.
   - Pass the intended `discussionDir` to the coordinator when the user or host
     already selected one; otherwise let the coordinator allocate the concrete
     id under the selected normal or smoke root and return it.
3. Project discussion-scoped expert custom agents before starting the
   coordinator.
   - Derive every projected expert from `agents/swarm-expert.toml`.
   - Write one uniquely named project-scoped custom agent per discussion expert
     under `.codex/agents/`.
   - Use stable names that include the discussion id or another collision-safe
     run id, plus a role slug.
   - Record projection-manifest.json fields for the run: `runId`,
     `createdPaths[{path, sha256}]`, `deletionStatus`, `removedPaths`, and
     `remainingPaths`. The parent owns file creation and cleanup; runtime gates
     validate the manifest shape and descriptor consistency.
   - Treat the projected files as temporary host state. The coordinator records
     their names, prompt references, hashes, invocation form, and host ids in
     runtime artifacts; the parent removes the files after the coordinator
     reaches a terminal result or after coordinator creation fails.
   - Do not run the experts from the parent thread.
4. Create or wake exactly one independent coordinator thread for the discussion.
   - Use the Codex thread-management tool surface available in the host.
   - Apply the coordinator contract by referencing or embedding
     `agents/swarm-coordinator.toml` in the coordinator's initial prompt.
   - Include the projected expert roster, projected `.codex/agents/` paths,
     projection-manifest.json path, cleanup policy, canonical `Mode`, and
     `stressPolicy` in the coordinator packet.
   - State the runtime phase order explicitly:
     `declaration -> argumentation -> stress-check -> contrarian -> response -> synthesis`.
   - Require the coordinator to use runtime `stress-check` and later
     `validate-loop --require-stress` when retained stress certification is in
     scope; the parent must not re-derive the quality signal.
   - Do not create ordinary expert threads or run persona agents from the parent
     thread.
5. Read or poll the coordinator until it returns a terminal result.
   - A terminal success result includes `ok: true`, `discussionDir`, synthesis,
     trace path, evidence path, and local gate summaries.
   - A terminal failure result includes `ok: false`, `discussionDir` when one
     exists, failure summary, available trace or evidence paths, and gate
     summaries.
6. Clean up projected expert files.
   - Remove only the run-scoped `.codex/agents/<expert-name>.toml` files that
     this parent thread created for this discussion.
   - Update projection-manifest.json with terminal cleanup fields when a
     discussion artifact tree exists.
   - After terminal cleanup is recorded as clean, wake or instruct the
     coordinator to regenerate trace/evidence so runtime projection gates see
     the final `projection-manifest.json` instead of stale pending cleanup
     state.
   - Do not remove user-authored or plugin-installed custom agents.
   - If cleanup fails, report the exact paths that remain.
7. Relay a compact result to the user.
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
Mode: <lightweight|standard|deep>; default standard
stressPolicy: <off|auto|required>; default by mode unless explicitly requested
Artifact root: .swarm/discussions/<id> for normal discussions; smoke/discussions/<id> for explicitly requested release smoke
discussionDir: <existing or requested discussion directory, or "allocate">
Coordinator contract: agents/swarm-coordinator.toml
Projected experts: <list of .codex/agents/<expert-name>.toml files, exact names,
template source agents/swarm-expert.toml, sha256 values, and cleanup owner parent>
Projection manifest: projection-manifest.json with runId, createdPaths,
deletionStatus, removedPaths, and remainingPaths
Phase contract: declaration -> argumentation -> stress-check -> contrarian -> response -> synthesis
Stress contract: coordinator calls runtime stress-check after argumentation,
records quality.stressRequired and quality.argumentDigest, and uses
validate-loop --require-stress when stress certification is required
Preferred invocation: @<projected-agent-name> with invocationForm at_mention
when it preserves agentDescriptor-compatible host evidence; fallback
invocationForm explicit_spawn when @mention evidence is insufficient
Cleanup freshness: after the parent finalizes projected-agent cleanup,
regenerate trace/evidence before claiming --require-projection success
Return shape: ok, discussionDir, synthesis or failure summary, trace path,
evidence path, local gate summaries.
```

The packet should make clear that the coordinator owns runtime execution,
expert fan-out, host transport capture, artifact writes, validation, trace, and
evidence generation. The parent thread only manages the lifecycle around the
coordinator thread and the temporary `.codex/agents/` projection that makes the
expert custom agents visible before the coordinator starts. The coordinator
must record runtime `agentDescriptor` entries and
`transport.customAgentProjection`; release smoke certification uses
`--require-projection`. Runtime 009 retained stress certification also uses
`--require-stress`; that gate proves structural disagreement only, while the
retained artifact tree remains the host truth for substantive quality.

## Failure Handling

- If Codex thread-management tools are unavailable, stop and report that the
  host cannot start a coordinator thread. Do not fall back to running experts
  directly in the parent thread.
- If coordinator thread creation fails before an artifact tree exists, report
  the failure without inventing `discussionDir`, trace, or evidence paths, then
  remove any projected expert files created for that failed start.
- If the coordinator times out, report the timeout and any thread identifier or
  partial artifact path that is actually known. Clean up only after the
  coordinator reaches a terminal result or the user explicitly abandons the run.
- If the coordinator returns failed gates, report the coordinator's failure
  index and artifact paths. Do not present the synthesis as accepted. Remove the
  projected expert files after the failure index has been captured.

## Boundaries

- The parent thread must not spawn expert personas directly.
- The parent thread may create temporary `.codex/agents/` custom-agent files for
  the discussion before the coordinator starts, but it must not run those
  experts itself.
- The parent thread must not write discussion artifacts, WAL state, trace, or
  evidence files.
- The parent thread must not create `.swarm/discussions/<id>` or
  `smoke/discussions/<id>` itself; it passes path intent and reports only paths
  returned by the coordinator.
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
