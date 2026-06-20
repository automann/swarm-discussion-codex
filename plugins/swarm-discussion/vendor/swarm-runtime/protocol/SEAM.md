# Transport seam

Everything transport-specific in `swarm-discussion` collapses onto **six methods**. The protocol body
(`PROTOCOL.md`) calls only these; the runtime mapping implements them with the primitives available in this
environment. **Durability policy and anti-anchoring live ABOVE the seam** — the seam is only the raw
spawn/collect/lifecycle surface.

## Contract

| Method | Required behavior |
|---|---|
| `spawnTeam(id)` | create the discussion namespace and `{discussionsRoot}/{id}` directory |
| `spawnPersona(name, prompt, {bg})` | start one ephemeral worker with a fully-composed prompt |
| `collectResult(...)` | get each worker's structured output and normalize results to spawn order |
| `postToLog(entry)` | append a record to the in-memory round |
| `checkpoint(round, state, commit?)` | persist round state durably; `commit` promotes `{round}.json.partial` to `{round}.json` |
| `teardown()` | end the run and release runtime resources |

## Invariants the seam must preserve

- **Anti-anchoring is not a seam method.** At the position-declaration phase the body composes the prompt
  with **no peer content** and passes the finished string to `spawnPersona`. The seam never sees the policy.
- **`postToLog` / `checkpoint` are file I/O for the native blackboard strategy.** They are *in* the seam so an
  alternate coordinator can override them without touching the protocol.
- **`collectResult` must preserve spawn order.** If collection returns opaque worker IDs or batched results,
  maintain a spawn-time worker-to-persona map, with each persona's `name`/`token` only as a fallback. Never bind
  by arrival order, or message IDs and the argument graph can silently corrupt (see `durability.md` fan-in).

## Runtime mapping rule

A runtime mapping is *only* these six methods plus runtime config such as `discussionsRoot`. If the mapping
needs to add discussion logic, that logic is in the wrong place — it belongs in the protocol.
