# Codex Retained Smoke Certification Synthesis

Both retained-smoke experts converged on the same release criterion: certification is only meaningful when the artifact tree preserves real Codex host evidence and runtime-owned validation artifacts together.

Observed retained evidence:

- Runtime prompt-build artifacts exist for `certifier` and `skeptic` under `prompts/r001/response/`.
- Real Codex `swarm-expert` agent ids are preserved in `transport/r001/response/spawn-order.json` and `transport/r001/response/host-step.json`.
- The raw `wait_agent` batch is retained in `transport/r001/response/wait-batches.jsonl`.
- Runtime `transport-collect` normalized both experts into `transport/r001/response/collect-result.json`.
- Runtime `append-message` minted `r1-msg-001` through `r1-msg-003`, and `finalize-round` promoted `rounds/001.json`.

Recommendation: certify this retained smoke if the local runtime gates and adapter certification script pass on the retained tree.
