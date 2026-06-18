# Windowing — `sliceForPersona` + provenance

`sliceForPersona` is a stateless projection of the canonical log into what one persona may cite this step.
Used from the response phase onward — never at the position-declaration phase (anti-anchoring; it returns an
empty slice there defensively) and not at argumentation (which passes `positionDeclarations` +
`moderatorOpening`).

## `window.py`

```
window.py slice --persona ID --phase P [--budget N]   < {"messages":[...]}  -> {sliceText, injectedIds, visibility}
window.py provenance   < {"positionShifts":[...], "personaContextLog":{persona: {id: full|gist}}}  -> {"violations":[...]}
```

`sliceForPersona` rules:
- **Self never windowed** — every message whose `from == persona` is rendered in full (identity spine).
- **Pinned never windowed** — fixed-role framing (`moderator` / `contrarian` / `cross-domain`) in full.
- **Peers windowed** — other dynamic experts' bodies, full newest-first up to the char `budget`; the rest
  become `"[id] from (type): <gist>  (elided)"` with the gist **body ≤ 120 chars including the marker**.
  **IDs are never dropped.**
- Returns `injectedIds` (every id rendered, full or gist) **and** `visibility` (`{id: "full" | "gist"}`). The
  orchestrator persists **`visibility`** into `partial.personaContextLog[persona]` — provenance needs
  full-vs-gist, not mere presence.
- **Default budget is generous** (100k chars): Standard-mode slices ≈ the full chronological log; windowing
  engages mainly in **deep mode** / long rounds.

## Shift-provenance gate

`provenance(positionShifts, personaContextLog)` flags a shift when it (a) **names no trigger id**, (b) cites
an id **absent** from the persona's slice, or (c) cites an id the persona saw **only as a gist**. PROTOCOL.md
Step 5 records the real `shiftTriggerIds` the response named and runs this gate; a violation → fail the round
+ re-inject. This guards against re-hydration amnesia or hallucinated citations masquerading as genuine shifts.
