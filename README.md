# swarm-discussion-codex

Codex host adapter and repo marketplace for the `swarm-discussion` runtime
family.

The adapter keeps the parent Codex thread thin. The parent skill collects a
brief, starts or wakes one dedicated coordinator thread, and reports only the
final synthesis plus artifact paths. The coordinator thread owns runtime
execution, expert fan-out, transport capture, validation, and retained
discussion artifacts through the vendored `swarm-discussion-runtime`.

## Install From This Repo

Add this checkout or GitHub clone as a Codex plugin marketplace:

```bash
codex plugin marketplace add <path-or-url-to-this-repo>
```

Then install the plugin from the marketplace:

```bash
codex plugin add swarm-discussion --marketplace swarm-discussion-codex
```

The repo marketplace catalog lives at `.agents/plugins/marketplace.json`. It
publishes one local plugin entry named `swarm-discussion` whose source path is
`./plugins/swarm-discussion`.

## Repository Shape

This repository has two layers:

| Layer | Path | Purpose |
|---|---|---|
| Marketplace catalog | `.agents/plugins/marketplace.json` | Lets Codex discover the installable plugin from this repo. |
| Installable plugin payload | `plugins/swarm-discussion/` | The slim payload copied into the Codex plugin cache. |
| Maintainer source and evidence | repository root | Runtime certification smoke, conformance, plans, tasks, and research retained for maintainers. |

The installable payload intentionally contains only the plugin-root surfaces
needed by Codex:

```text
plugins/swarm-discussion/.codex-plugin/plugin.json
plugins/swarm-discussion/agents/
plugins/swarm-discussion/skills/
plugins/swarm-discussion/bin/
plugins/swarm-discussion/vendor/swarm-runtime/
```

Root-only maintainer material such as `smoke/`, `conformance/`, `docs/`,
`plans/`, `tasks/`, and `.ai/` is not part of the installed plugin payload.

## Verification

Run the local marketplace install smoke from the repository root:

```bash
bash scripts/check-codex-marketplace-install.sh
```

The smoke uses an isolated temporary `CODEX_HOME`, adds this repository as a
Codex marketplace, installs `swarm-discussion`, checks the installed cache root,
and runs:

```bash
python3 <installed-plugin-root>/bin/swarm_runtime_wrapper.py doctor --smoke-fixture
```

This tracked smoke script is the public verification entrypoint for the
marketplace package shape. Maintainer-only workflow context may exist in local
checkouts, but it is not required to install or verify the plugin payload.
