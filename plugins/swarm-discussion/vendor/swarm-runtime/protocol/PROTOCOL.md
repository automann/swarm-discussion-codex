# swarm-discussion — protocol

The orchestration body for a discussion. Follow this file and call runtime primitives **only** through
[`SEAM.md`](SEAM.md). Persistence is in
[`durability.md`](durability.md), context windowing in [`windowing.md`](windowing.md), the on-disk shape in
[`SCHEMA.md`](SCHEMA.md), and every prompt builder in [`prompts.md`](prompts.md).

> The transport surface is isolated to the six [`SEAM.md`](SEAM.md) methods; everything else here is
> discussion protocol. Per-persona context is composed per phase; the windowed projection is
> `sliceForPersona` (`window.py`); round state is persisted by a per-step write-ahead log via `checkpoint`
> (`wal.py`). Generous windowing defaults keep Standard-mode slices ≈ the full chronological log.

---

## Modes

| Mode | Experts | Rounds | Calls/Round | Use when |
|------|---------|--------|-------------|----------|
| **Deep** | 3-4 dynamic + 4 fixed | 3-5 | 8-12 | Unprecedented problems, high-stakes decisions |
| **Standard** (default) | 2-3 dynamic + 4 fixed | 2-3 | 5-8 | Typical design decisions, tradeoff analysis |
| **Lightweight** | 2 dynamic + 2 fixed (Moderator, Contrarian) | 1-2 | 3-5 | Quick sanity checks, idea validation |

Parse the mode from the invocation (`--mode deep|standard|lightweight`); default **Standard**.

## Roles

**Fixed roles** (Lightweight uses only Moderator + Contrarian):

| Role | Responsibility | Quality function |
|------|----------------|------------------|
| **Moderator** | Facilitate, enforce quality gates, judge convergence | Prevents premature consensus |
| **Historian** | Build the argument graph, synthesize, write resumable records | Maintains traceability |
| **Contrarian** | Stress-test the strongest consensus | Prevents echo chambers |
| **Cross-Domain** | Analogies from other fields | Prevents domain-locked thinking |

**Dynamic experts** (2-4, generated per topic). Persona schema (saved to `personas/{id}.json`):

```json
{ "id": "kebab-id", "name": "Role Name", "expertise": ["…"], "thinkingStyle": "pragmatic",
  "bias": "…", "replyTendency": "…", "stakes": "what they lose if wrong", "blindSpots": ["…"] }
```

`stakes` and `blindSpots` drive genuine engagement and give other experts something to target.

### Tension map (required)

When generating personas the Moderator MUST design a tension map — pairs with structurally opposing
incentives — so debate is genuine, not "I agree, and also…":

```json
{ "tensionMap": [ { "between": ["expert-a", "expert-b"], "axis": "what they fundamentally disagree on",
                    "description": "why both sides have a valid point" } ] }
```

Each dynamic expert should appear in ≥1 tension. Tensions must be **structural** (from differing
roles/stakes), not arbitrary preference.

## Structured disagreement protocol

1. **Mandatory position declaration** — before debate, each expert declares `{position, confidence,
   conditions, wouldChangeIf, keyRisk}` **blind** (without seeing peers). `wouldChangeIf` forbids
   unfalsifiable positions.
2. **Steel-manning** — before disagreeing, restate the opposing view at its strongest, then counter.
3. **Disagreement budget** — the Moderator tracks a 0-10 score: < 2 (too much agreement) → direct the
   Contrarian at the strongest agreement; > 8 → find shared premises.
4. **Position-shift tracking** — the Historian records `{expert, from, to, trigger, reasoning}` whenever an
   expert changes stance, with the triggering message ID.

---

## Phase 1 — Initialization

```
discussionId = slugify(topic)
mode         = parseMode(input)                  // default "standard"
seam.spawnTeam(discussionId)                      // creates {discussionsRoot}/{discussionId}/ + runtime team (if any)

analysis = generatePersonasAndTensions(topic, mode)   // → { experts[], tensionMap[], problemDefinition }  (see prompts.md)
fixed    = (mode == "lightweight") ? [moderator, contrarian]
                                   : [moderator, historian, contrarian, cross-domain]
allExperts = analysis.experts ++ fixed

AskUserQuestion("Start with these experts & tensions?", options: Start | Modify | Change Mode)   // confirmation gate

write manifest.json { id, title, created, status:"active", mode, currentPhase:"initial",
                      currentRound:0, schemaVersion, personas: allExperts,   // FULL persona records (objects), not just ids
                      tensionMap: analysis.tensionMap, problemDefinition: analysis.problemDefinition }
for expert in allExperts: write personas/{expert.id}.json
```

## Phase 2 — Round execution

Report progress to the user after each step (and append to `progress.md`) — never run silently. Format:
`### Round {N} — Step {k}: {name}` + 1-3 sentence summary + **Key takeaway**.

IDs are `r{round}-msg-{nnn}` (see SCHEMA.md). The runtime mapping seeds an in-context counter from `wal.py max-seq`
at each step entry (durable across reaps), mints sequentially within the step, then flushes — so a reaped
orchestrator resumes at the right id, never restarting at 001 (see `durability.md`). `references[]` are parsed from each message and
become `argumentGraph` edges (`extractReferences` regex `/r\d+-msg-\d{3}/g`).

```
function executeRound(round, roundTopic):
  allMessages = []   ;   argumentGraph = []   ;   positionShifts = []

  // ── Step 1: Position declarations (BLIND — anti-anchoring) ─────────────────
  // Built with NO peer content: pass only (persona, topic). This withholding is the anti-anchoring
  // mechanism and lives HERE in the body, never in the seam (do NOT call sliceForPersona at this step).
  for expert in dynamicExperts (parallel):
      seam.spawnPersona(expert.id, buildPositionDeclarationPrompt(expert, roundTopic), {bg:true})
  for expert in dynamicExperts:
      decl = seam.collectResult(expert.id)                 // { position, confidence, conditions, wouldChangeIf, keyRisk }
      m = postToLog({ from:expert.id, type:"position_declaration", content:decl })
  seam.checkpoint(round, state)                            // per-step WAL flush (wal.py)
  reportProgress(1, "Position Declarations", …)

  // ── Step 2: Moderator framing ─────────────────────────────────────────────
  opening = ask("moderator", buildModeratorOpeningPrompt(roundTopic, positionDeclarations, tensionMap, prevSummary))
  postToLog({ from:"moderator", type:"opening", content:opening })   // frames real fault lines + 2-3 targeted Qs + budget
  seam.checkpoint(round, state)                            // flush — the framing must survive a reap too
  reportProgress(2, "Moderator Framing", …)

  // ── Step 3: Argumentation (cited + steel-manned) ──────────────────────────
  // Argumentation passes positionDeclarations + moderatorOpening explicitly (NOT a full-log projection);
  // the windowed projection is applied only from the response phase on (Step 5+).
  for expert in dynamicExperts (parallel):
      seam.spawnPersona(expert.id, buildExpertPrompt(expert, {phase:"argumentation", topic:roundTopic,
          positionDeclarations, moderatorOpening, tensionMap,
          instruction: "Cite ≥1 peer by message ID; steel-man before countering; be concrete; state wouldChangeIf."}), {bg:true})
  for expert in dynamicExperts:
      arg = seam.collectResult(expert.id)
      m = postToLog({ from:expert.id, type:"argument", content:arg, references: extractReferences(arg) })
      for ref in m.references: argumentGraph.push({ from:m.id, to:ref.targetId, relation:ref.type })
  seam.checkpoint(round, state)
  reportProgress(3, "Expert Arguments", …)

  // ── Step 4: Contrarian stress test (targets the STRONGEST consensus) ──────
  con = ask("contrarian", buildContrarianPrompt(roundTopic, allMessages, argumentGraph))
  postToLog({ from:"contrarian", type:"stress_test", content:con, references: extractReferences(con) })
  seam.checkpoint(round, state)                            // flush
  reportProgress(4, "Contrarian Stress Test", …)

  // ── Step 5: Responses + position-shift tracking ───────────────────────────
  // The response phase uses the windowed projection (window.py) and records the per-id
  // VISIBILITY map so the provenance gate can tell "shown in full" from "only gisted".
  for expert in dynamicExperts (parallel):
      proj = sliceForPersona(allMessages, expert, "response")    // {sliceText, injectedIds, visibility}
      personaContextLog[expert.id] = proj.visibility            // {id: full|gist}
      seam.spawnPersona(expert.id, buildExpertPrompt(expert, {phase:"response", topic:roundTopic, slice:proj.sliceText, contrarianId,
          instruction: "Respond to the stress test. Report {positionShift, currentPosition, previousPosition,
                         shiftReason, shiftTriggerIds:[ids you were SHOWN that actually moved you]}."}), {bg:true})
  for expert in dynamicExperts:
      resp = seam.collectResult(expert.id)
      m = postToLog({ from:expert.id, type:"response", content:resp, references: extractReferences(resp) })
      if resp.positionShift != "none":
          positionShifts.push({ type:"position_shift", expert:expert.id, from:resp.previousPosition,
                                to:resp.currentPosition, trigger:resp.shiftTriggerIds, reasoning:resp.shiftReason })
  // shift-provenance gate (window.py provenance): every shift must name ≥1 trigger id the persona was shown
  // IN FULL (per personaContextLog visibility) — else fail the round + re-inject. Real triggers, not the contrarian's id.
  seam.checkpoint(round, state)
  reportProgress(5, "Responses & Position Shifts", …)

  // ── Step 6: Cross-domain (Standard/Deep only) ─────────────────────────────
  if mode != "lightweight":
      cd = ask("cross-domain", buildCrossDomainPrompt(roundTopic, allMessages, positionShifts))
      postToLog({ from:"cross-domain", type:"analogy", content:cd, references: extractReferences(cd) })
      reportProgress(6, "Cross-Domain Perspective", …)   // report ONLY when it ran — lightweight skips this step
  seam.checkpoint(round, state)                            // flush the step boundary (a no-op flush in lightweight)

  // ── Step 7: Quality gate + convergence ────────────────────────────────────
  // Lightweight scores convergence INLINE (the orchestrator already holds the round — no spawn);
  // Standard/Deep spawn the Moderator for an independent gate.
  gate = (mode == "lightweight") ? scoreConvergence(allMessages, argumentGraph, positionShifts)   // inline, same shape
                                 : ask("moderator", buildQualityGatePrompt(allMessages, argumentGraph, positionShifts))
  // → { qualityScore{genuineDisagreement,evidenceQuality,steelManning,novelInsights,positionEvolution,overall},
  //     summary, agreements[], activeDisagreements[], insights[], openQuestions[], recommendation, recommendationReason }
  seam.checkpoint(round, state)                            // flush the gate result before the commit
  reportProgress(7, "Quality Gate", …)

  // ── Step 8: Record (the round commit) ─────────────────────────────────────
  // Round record: roundId, topic, mode, timestamp, messages,
  // argumentGraph, positionShifts, synthesis, metadata{messageCount, participants, referenceCount}. timestamp
  // is taken from the runtime clock at write time.
  roundRecord = { roundId:round, topic:roundTopic, mode, timestamp, messages:allMessages, argumentGraph,
                  positionShifts, synthesis:gate,
                  metadata:{ messageCount:count(allMessages), participants:distinct(allMessages.from), referenceCount:count(argumentGraph) } }
  if mode != "lightweight": ask("historian", buildHistorianRoundPrompt(roundRecord))   // updates the running argument map
  seam.checkpoint(round, roundRecord)                   // flush the FINAL record (incl. synthesis) first ...
  seam.checkpoint(round, roundRecord, commit:true)      // ... then commit: promote .partial -> rounds/{NNN}.json (wal.py)

  // ── Step 9: Confirm next action ───────────────────────────────────────────
  AskUserQuestion("Round {round} complete (quality {gate.overall}/5, {positionShifts.length} shifts). Next?",
      options: Follow recommendation | Deep dive | Different angle | Inject constraint | Synthesis | Pause)
  return roundRecord
```

Helper `ask(role, prompt)` = `seam.spawnPersona` + `seam.collectResult` for a single fixed-role agent.

## Phase 3 — Synthesis

```
allRounds = loadAllRounds(discussionId)
// Lightweight synthesizes INLINE (no Historian spawn) and writes only a concise, message-id-cited synthesis.md.
// Standard/Deep spawn the Historian for the full audited synthesis + the artifact set.
if mode == "lightweight":
    write artifacts/synthesis.md          // executive summary, key agreements / active disagreements, recommendation — cite message ids
else:
    final = ask("historian", buildSynthesisPrompt(allRounds, fullArgumentGraph, allPositionShifts, problemDefinition))
    // Rules: every insight cites message IDs; "resolved by argument" ≠ "resolved by majority"; confidence reflects
    // evidence quality not vote count; preserve a minority report for un-refuted dissent.
    write artifacts/synthesis.json, synthesis.md, open-questions.md, argument-graph.json, position-evolution.md
```

## Phase 4 — Checkpoint / Termination

```
// ALWAYS write the resume context at the end of a round — on completion AND on a mid-discussion pause,
// every mode. Do NOT skip it: it is what makes a discussion resumable and inspectable.
resumeContext = (mode == "lightweight") ? composeResumeContextInline(...)         // lightweight: inline, no spawn
                                        : ask("historian", buildResumeContextPrompt(...))   // theme, progress, current positions, open tensions
write context/summary.md
updateManifest( done ? {status:"completed", currentPhase:"synthesis"} : {status:"paused", currentPhase:"checkpoint"} )
seam.teardown()                                                    // release any runtime resources

// Resume: `wal.py resume` prefers a rounds/{NNN}.json.partial over the last completed round; `load`
// re-hydrates and `max-seq` re-seeds the counter, then re-open with the Moderator (see durability.md).
```

---

## Important notes

- **Cost:** Lightweight 3-5 calls/round, Standard 5-8, Deep 8-12. Reserve Deep for high-stakes.
- **Quality over quantity:** 2 rounds of genuine disagreement beat 5 of polite agreement. If a round's
  overall quality < 3, the Moderator intervenes (re-aim the Contrarian, demand specifics, ask "what would
  change your mind?").
- **Position shifts are the strongest signal** of a productive discussion; track them faithfully.
- **Evidence & traceability:** every message has a unique ID; every claim references the message it answers;
  the argument graph + position evolution make conclusions auditable.

### Anti-patterns

- "I agree, and also…" — if everyone agrees, the Contrarian isn't doing its job.
- Generic analogies — Cross-Domain must cite specific cases, and say where the analogy breaks.
- Unfalsifiable positions — every position needs a `wouldChangeIf`.
- Authority arguments — "best practice says…" is not evidence; show *why*.
- Premature synthesis — don't synthesize before real disagreements are explored.

---

## Helpers

The transport is isolated to the six methods in `SEAM.md`. Two protocol helpers sit above it:
`sliceForPersona` (`window.py`) windows the per-persona context — self-history never windowed, peers gisted
over budget, ids always kept; and `checkpoint` (`wal.py`) is the per-step write-ahead log — durable ids,
atomic flush, resume-from-partial. See `windowing.md` and `durability.md`.

**Core behavior:** modes, roles, persona schema, tension map, the disagreement protocol, prompt builders, the
round step sequence, the synthesis spec, progress reporting, and the anti-patterns.
