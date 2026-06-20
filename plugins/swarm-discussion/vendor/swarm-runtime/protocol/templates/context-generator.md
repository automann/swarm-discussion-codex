# Context Generator (Parent Brief)

This template tells the parent agent how to write the **brief** that the runtime
turns into `context/summary.md`. The flow is:

1. The parent agent fills the brief JSON below from the user's request.
2. `swarm-rt context-build --brief brief.json --out context/summary.md` renders
   it into a compact Markdown summary.
3. Every expert prompt injects that summary in **every phase** — so the brief
   **is** the alignment mechanism that keeps experts anchored to the parent's
   intent and stops mid-discussion drift.

Keep the brief compact: it is background for experts, not a transcript dump.

## Brief schema

The runtime's `build_context_summary` (see `runtime/swarm/context.py`, which is
authoritative if this table and the code ever disagree) reads:

| Field | Type | Required | Notes |
|---|---|---|---|
| `topic` | string | yes | Short title of what's being decided. |
| `objective` | string | yes | The single decision the parent needs, in one sentence. |
| `mode` | string | no | `lightweight` \| `standard` \| `deep`; defaults to `standard`. |
| `discussionId` | string | no | Stable slug for the discussion directory. |
| `parentContext` | string | no | Background an expert needs to avoid intent drift: problem origin, who is affected, what was already tried. |
| `constraints` | list of non-empty strings | no | Hard boundaries the recommendation must respect. |
| `knownFacts` | list of non-empty strings | no | Verified data points (ideally with their source). |
| `successCriteria` | list of non-empty strings | no | What a useful synthesis must answer. |

## Field-writing guidance

- **objective** — the decision, not a topic restatement. "Choose X or Y given Z",
  not "discuss X".
- **parentContext** — the few sentences that stop an expert from solving the
  wrong problem: why this came up, who it affects, what's already been tried.
- **constraints** — things that are non-negotiable; the experts must not propose
  violating them.
- **knownFacts** — established data so experts argue from the same baseline.
- **successCriteria** — the questions the synthesis is graded against.

## Worked example

```json
{
  "discussionId": "tabs-vs-spaces",
  "topic": "Tabs vs spaces in a shared codebase",
  "mode": "lightweight",
  "objective": "Choose a whitespace policy that reduces churn while preserving formatter determinism.",
  "parentContext": "The parent agent is advising on repository-wide style policy before making code changes.",
  "constraints": [
    "Do not rewrite unrelated files.",
    "Prefer existing project formatter behavior when it is already configured."
  ],
  "knownFacts": [
    "The repository already contains mixed historical style.",
    "The decision should be easy for future automation to verify."
  ],
  "successCriteria": [
    "Recommendation is actionable.",
    "Risks and migration costs are explicit."
  ]
}
```

Render it:

```bash
swarm-rt context-build --brief brief.json --out context/summary.md
```

## Error codes

`context-build` fails loud with these codes (adapters should surface them):

| Code | Meaning |
|---|---|
| `invalid_brief` | The brief is not a JSON object. |
| `missing_field` | `topic` or `objective` is missing or empty. |
| `invalid_list` | `constraints` / `knownFacts` / `successCriteria` is not a list of non-empty strings. |

## Re-alignment between rounds

The rendered summary ends with an **Alignment Rule** instructing every expert to
keep contributions anchored to the topic, objective, constraints, known facts,
and success criteria. If a discussion drifts or the parent's intent sharpens
between rounds, update the brief and re-run `context-build` — the new summary is
injected into the next round's prompts. That is the runtime's re-alignment
mechanism; there is no separate "drift check" command.
