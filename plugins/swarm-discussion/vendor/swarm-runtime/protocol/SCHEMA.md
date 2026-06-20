# On-disk data contract

This schema records the durable discussion state. It is **not** a live transport. Frozen here so on-disk
discussions remain readable across plugin releases.

**`schemaVersion`: `2`** — bump on any breaking change; record in `manifest.json`. Public plugin releases
follow SemVer and must declare the `schemaVersion` they read/write.

## Directory layout — `{discussionsRoot}/{id}/`

```
manifest.json           # id, title, mode, schemaVersion, personas (FULL records, not ids), tensionMap, status, currentRound
progress.md             # live progress log (appended per step)
personas/{persona}.json # generated persona definitions (stakes, blindSpots, …)
rounds/{NNN}.json        # committed round record (see below)
rounds/{NNN}.json.partial# in-flight round (write-ahead log; durability.md)
artifacts/              # Standard/Deep: synthesis.json/.md, open-questions.md, argument-graph.json, position-evolution.md — Lightweight: synthesis.md only
context/summary.md      # resume context
tmp/                    # transient scratch (helper payloads piped to wal.py/window.py); safe to delete
```

**Default `discussionsRoot`: `./.swarm/discussions`.** Discussion artifacts belong to the project by default,
so plugin install is enough and no user-scope config is required. This is workspace-local rather than
worktree-proof; do not rely on it after deleting a transient worktree. **All writes — including transient
scratch — stay under `{discussionsRoot}/{id}/`: build helper payloads in `{id}/tmp/`, never user-scope `/tmp`.**

## Round record — `rounds/{NNN}.json`

```jsonc
{
  "roundId": 1, "topic": "…", "mode": "standard", "timestamp": "<runtime-clock ISO-8601>",
  "messages": [ { "id": "r1-msg-001", "from": "<persona>", "type": "position_declaration|opening|argument|stress_test|response|analogy", "content": {…}, "references": [ {"targetId":"r1-msg-00X","relation":"supports|counters|extends|questions"} ] } ],
  "argumentGraph": [ { "from": "r1-msg-005", "to": "r1-msg-001", "relation": "counters" } ],
  "positionShifts": [ { "type": "position_shift", "expert": "…", "from": "…", "to": "…",
                        "trigger": ["r1-msg-006"], "reasoning": "…" } ],   // trigger = validated shiftTriggerIds (real cited ids)
  "synthesis": { /* quality-gate output: qualityScore, agreements, activeDisagreements, insights, recommendation */ },
  "metadata": { "messageCount": <n>, "participants": ["…"], "referenceCount": <n> }
}
```
**schemaVersion 2**: `positionShifts[].trigger` holds the validated `shiftTriggerIds` (an array of the real
cited ids); the per-shift magnitude (`none|minor|major`) is carried inside the response `content`.
The `.partial` variant adds the durability fields `phase` and `personaContextLog` (`durability.md`), where
`personaContextLog[persona]` is the **visibility map** `{messageId: "full" | "gist"}` of what that persona
was shown (the provenance gate needs full-vs-gist, not just presence). On `commit` it is renamed to
`{NNN}.json`; retaining `personaContextLog` aids post-hoc shift-provenance audits.

## Invariants

- Message-ID grammar: **`r{round}-msg-{nnn}`** (3-digit, gapless, monotonic per round, globally unique).
- Reference regex: **`/r\d+-msg-\d{3}/g`** must resolve every citation to a present ID.
- Write cadence: **flush after every message-producing step** to `.partial`, then **flush-the-final-record
  + commit** to `{NNN}.json` (the final flush persists synthesis before the rename). Live round shape
  preserved (no field dropped); see schemaVersion 2 above for the two additive deltas.
- **Discussion-id grammar:** `^[a-z0-9][a-z0-9-]{0,99}$` — one slug segment, no separators or `..`. Runtimes
  MUST validate via `wal.py valid_discussion_id` before building `{discussionsRoot}/{id}` and ensure the
  resolved path stays under `discussionsRoot` (path containment for the allow-listed write root).
