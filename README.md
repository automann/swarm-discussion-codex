# swarm-discussion-codex

Codex host adapter and root plugin repo for the `swarm-discussion` runtime
family.

The adapter keeps the parent Codex thread thin. The parent skill collects a
brief, starts or wakes one dedicated coordinator thread, and reports only the
final synthesis plus artifact paths. The coordinator thread owns runtime
execution, expert fan-out, transport capture, validation, and retained
discussion artifacts through the vendored `swarm-discussion-runtime`.

## Distribution

This repository is the Codex plugin root. The plugin manifest lives at
`.codex-plugin/plugin.json`, and all paths declared by the manifest are
relative to this repository root.

End-user discovery should be mediated by the top-level `swarm-discussion`
aggregator after it adds a Codex entry that points at this repository as a root
plugin source. Until that aggregator entry exists, release operators should use
the root install smoke below to prove the tracked public tree installs cleanly
from an isolated Codex home.

## Repository Shape

The tracked public tree is the installable plugin payload:

| Layer | Path | Purpose |
|---|---|---|
| Plugin manifest | `.codex-plugin/plugin.json` | Declares the `swarm-discussion` Codex plugin and its component paths. |
| Coordinator and expert contracts | `agents/` | Defines the host-visible coordinator and leaf expert prompts. |
| Parent skill | `skills/swarm-discussion/` | Owns parent-thread entrypoint behavior and coordinator handoff. |
| Runtime wrapper | `bin/swarm_runtime_wrapper.py` | Locates the vendored runtime and exposes diagnostic/runtime commands. |
| Vendored runtime | `vendor/swarm-runtime/` | Provides prompt building, transport capture, WAL mutation, validation, and smoke fixtures. |
| Public smoke | `scripts/check-codex-root-plugin-install.sh` | Proves the tracked public tree installs as a root Codex plugin. |

Local development checkouts may also contain ignored repo-harness, planning,
research, and operator files. Those local-only files are not part of the public
plugin verdict; the public install shape is judged from the tracked files.

## Runtime Boundary

The Codex adapter is a host shell around the runtime. Codex thread tools create
and observe the coordinator thread; the runtime remains the authority for
context construction, prompt construction, transport collection, WAL updates,
validation, and retained artifact structure. Wrapper diagnostics can report
host capabilities, but they do not replace the runtime certification gates.

## Release Provenance

Current certified adapter metadata:

| Field | Value |
|---|---|
| Plugin version | `0.2.2` |
| Runtime sha | `fb7f869d82fe3ba69dc9bfec148f8d833d687e8a` |
| Runtime compatibility | `swarm-runtime-v2-alpha` |
| Retained certification discussion | `smoke/discussions/smoke-retained-20260621-021426` |
| Certification verdict | `certified: true` |
| Certification completed | `2026-06-20T18:20:19.857Z` |
| Release tag | `v0.2.2` |

The top-level aggregator source pin is a separate repository follow-through
step. This repository records the certified runtime pin, retained discussion
evidence, and release tag so the aggregator can pin an auditable adapter
release.

## Verification

Run the root plugin install smoke from the repository root:

```bash
bash scripts/check-codex-root-plugin-install.sh
```

The smoke uses `git ls-files` to snapshot the tracked public tree, installs
that snapshot through an isolated temporary `CODEX_HOME`, verifies the
versioned plugin cache root, and runs installed-root wrapper doctor.

You can also run the wrapper doctor directly during local development:

```bash
python3 bin/swarm_runtime_wrapper.py doctor --smoke-fixture
```

The top-level aggregator update is intentionally separate from this adapter
repo. This repository must first prove that its tracked root plugin payload is
stable, then the aggregator can add a release-pinned Codex source entry.
