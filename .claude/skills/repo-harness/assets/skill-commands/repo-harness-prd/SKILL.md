---
name: repo-harness-prd
description: Generates an AI-implementation-friendly PRD from a product idea into plans/prds/, with tiered sections, evidence rules, and sprint-consumable structure.
when_to_use: "repo-harness-prd, generate PRD, write PRD, product requirements doc, PRD from idea, plans/prds, 产品需求文档, 需求文档"
---

# repo-harness-prd

Use this command to generate an upper-layer PRD under `plans/prds/`. The PRD is product intent and implementation guidance; it is not a Sprint backlog and does not start task execution.

## Protocol

1. Confirm the working repo with `git rev-parse --show-toplevel`; read `docs/spec.md`, `.ai/harness/policy.json`, and the PRD template from `.prds.template_file` when present, otherwise `.claude/templates/prd.template.md`.
2. Accept a one-line or vague product idea and default to writing the PRD. Ask only when the answer would materially change platform, safety, legal risk, budget, data ownership, or scope tier.
3. Choose `compact` by default. Use `standard` only for multi-module products, explicit user request, commercialization, or frontend/backend deepening.
4. Write a new `plans/prds/<YYYYMMDD>-<HHMM>-<slug>.prd.md`. Fill every core section; include optional sections only when tier or user request requires them. Keep section headings in English and write body content in the user's language.
5. Use evidence rules: do not invent competitor facts, API behavior, platform limits, model capabilities, package sizes, or current market facts. Mark unverifiable details as `[UNKNOWN]` or `[UNVERIFIED]`.
6. Inline response should include only the AI Quick-Read Card and the PRD file path, not the full document.
7. Verify with `bash scripts/check-task-workflow.sh --strict` when the helper exists; in this self-host source repo, `bash scripts/check-task-workflow.sh --strict` is also valid. If verification fails, stop and fix the PRD instead of bypassing the check.
8. Suggest `repo-harness-sprint plan from-prd <prd-file>` only after the PRD exists and the user wants an ordered Sprint backlog.

## Failure Modes

- If `plans/prds/` is missing, report the missing catalog and route the user to `repo-harness-init` or `repo-harness-repair`.
- If the idea is a single ambiguous word with no product category, ask for one clarifying sentence before writing.
- If strict workflow verification rejects the PRD, stop and revise the PRD file before suggesting Sprint generation.
- If a matching PRD filename already exists, preserve it and create a new timestamped file.

## Boundaries

- Does not create or approve a Sprint backlog; that belongs to `repo-harness-sprint`.
- Does not edit `docs/spec.md` or reinterpret repo product truth.
- Does not set `> **Status**: Approved`; the user must review and approve the PRD.
- Does not write outside `plans/prds/` except for verification artifacts produced by existing workflow checks.
- Never fabricates facts for `Adjacent Patterns`; use adjacent workflow patterns or mark claims `[UNVERIFIED]`.
