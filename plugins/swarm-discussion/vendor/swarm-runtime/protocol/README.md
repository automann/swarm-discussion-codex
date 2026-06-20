# Discussion Protocol (Host-Agnostic)

This directory is the single source of truth for swarm-discussion protocol
semantics: modes, roles, phases, structured disagreement, blind declarations,
steel-manning, argument graph, position shifts, quality gates, and persona
generation.

Provenance: imported verbatim from the published plugin line at
`swarm-discussion@96eb5f2`, where the Claude and Codex copies were
byte-identical. Host adapters must reference this package; they must not carry
their own forked copies of these documents.

## Ownership split: semantics vs mechanics

The *semantics* in these documents are normative. The *mechanics* they
describe (legacy per-plugin helper scripts) are superseded by runtime
commands. Where a document references a legacy helper, read it through this
mapping:

| Legacy helper (in docs) | Runtime command (normative) |
|---|---|
| `wal.py flush` | `swarm-rt checkpoint` |
| `wal.py commit` | `swarm-rt finalize-round` |
| `wal.py max-seq` / `wal.py next-id` | minted internally by `swarm-rt append-message` |
| `wal.py resume` | `swarm-rt resume-plan` |
| `wal.py valid_discussion_id` | adapter responsibility (path hygiene) + `swarm-rt validate-discussion` |
| `window.py slice` | `swarm-rt prompt-build` (visibility map in `prompt-build.json`) |
| `window.py provenance` | `swarm-rt validate-round` (shift provenance errors) |
| `collect.py` | `swarm-rt collect-merge` / `swarm-rt transport-collect` |
| `validate_round.py` | `swarm-rt validate-round` / `swarm-rt validate-discussion` |

Adapters call the runtime commands; they never reimplement the left column.

## Files

- `PROTOCOL.md` — modes, roles, phases, disagreement protocol, termination.
- `SCHEMA.md` — discussion directory and round record shapes (see also
  `schemas/` for machine-readable versions, which win on conflict).
- `SEAM.md` — the orchestrator/host seam the runtime now implements.
- `durability.md` — WAL semantics (mechanics superseded; see mapping).
- `windowing.md` — visibility/windowing semantics (mechanics superseded).
- `prompts.md` — phase prompt semantics consumed by `prompt-build`.
- `templates/persona-generator.md` — persona generation template.
- `templates/context-generator.md` — parent-brief authoring guide consumed by `context-build`.
