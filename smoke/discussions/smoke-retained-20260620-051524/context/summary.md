# Context Summary

## Topic

Codex retained smoke certification for swarm-discussion adapter

## Objective

Prove one retained release-smoke discussion can use the vendored runtime and real Codex swarm-expert transport artifacts.

## Operating Mode

release-smoke

## Discussion ID

smoke-retained-20260620-051524

## Constraints

- Keep the brief non-sensitive.
- Use runtime-owned context, prompt, transport, WAL, trace, evidence, and validation commands.
- Spawn at least one real Codex swarm-expert worker and preserve host ids.

## Known Facts

- This is a release/certification smoke run.
- The retained artifact tree must live under smoke/discussions.

## Success Criteria

- Transport has spawn-order, host-step, wait-batches, and collect-result artifacts.
- At least one prompt-build artifact exists under prompts/r001/response.
- Round 1 is finalized with runtime-minted message ids and synthesis.
- Trace, evidence, validate-host-step, adapter-smoke, validate-loop, validate-discussion, and adapter certification pass.

## Alignment Rule

Keep every contribution anchored to the topic, objective, constraints, known facts, and success criteria above.
