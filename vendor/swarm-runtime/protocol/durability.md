# Durability — the write-ahead-log contract

The orchestrator's in-memory round state is ephemeral: the runtime can reap the idle orchestrator during the
between-round `AskUserQuestion` pause. So **the `rounds/{NNN}.json.partial` file is the system of record; the
orchestrator's memory is a cache.** Implemented as [`wal.py`](wal.py), behind the `checkpoint` seam method —
pure file I/O with no live transport dependency.

## `wal.py` CLI

```
wal.py flush   --dir D --round N --phase P   <state.json on stdin>   # atomic: .tmp, fsync, replace -> .partial, fsync dir
wal.py commit  --dir D --round N                                     # atomic rename .partial -> .json (renames only)
wal.py max-seq --dir D --round N                                     # highest seq in round STATE files -> seed the counter
wal.py next-id --dir D --round N                                     # max-seq+1, collision-guarded -> "rN-msg-nnn"
wal.py resume  --dir D                                               # {round, phase, maxId, source: partial|final|none}
wal.py load    --dir D --round N                                     # current .partial (else .json) state JSON
```

## Partial round file — `rounds/{NNN}.json.partial`

```jsonc
{ "round": 1, "phase": "responses",            // resume cursor
  "messages": [...], "argumentGraph": [...], "positionShifts": [...],
  "personaContextLog": { "<persona>": { "r1-msg-001": "full", "r1-msg-002": "gist" } } }   // VISIBILITY map (windowing.md)
```

## Orchestrator flow

1. **Step entry:** `wal.py max-seq` → seed the in-context counter (0 on a fresh round; the real max after a
   resume, so ids never restart at 001). IDs derive from the round STATE files (`.partial`/`.json`) ONLY —
   `progress.md` is an append-only *informational* log, never an authoritative id source.
2. Mint sequentially in-context within the step.
3. **Flush after every message-producing step** — positions, framing, arguments, contrarian, responses,
   cross-domain, quality gate — via `wal.py flush` (atomic: `.tmp` → fsync → `os.replace` → fsync parent dir).
4. **End of round: flush the FINAL record (incl. `synthesis`) THEN `wal.py commit`.** `commit` only renames
   the existing partial, so the final state must be flushed first. The `checkpoint(..., commit:true)` mapping is
   *flush-then-commit*.
5. **Resume:** `wal.py resume` chooses the **highest round across partials + finals**, preferring a partial
   only when the top round has one (a stale lower-round partial never rolls a newer committed round backward).
   `load` re-hydrates; `max-seq` re-seeds the counter; the interrupted step re-runs deterministically.

Guarantees: atomic flush (no torn files; parent dir fsync'd), durable monotonic IDs (max-in-state + 1),
collision guard, highest-round resume.

## Deterministic fan-in

Fan-in can return results by opaque worker ID, persona name, or completion batches depending on the runtime
surface. The orchestrator records a spawn-time **worker → persona** map and demuxes on it (with each persona's
`name`/`token` as a fallback) — never by completion order. Sort by stable spawn index **before** minting ids so
reference extraction remains deterministic. This is a mapping discipline, not an architecture change.
