"""swarm-discussion runtime incubator package."""

from __future__ import annotations

__version__ = "0.0.0"


def planned_commands() -> list[str]:
    """Return the canonical runtime command surface.

    Source of truth for the CLI command set: it must match the argparse
    subcommands in ``swarm_rt.build_parser()`` exactly, and the stable commands
    in ``runtime-contract.json`` must be a subset of it. A drift test pins all
    three together (see ``tests/test_skeleton_contract.py``).
    """
    return [
        "health",
        "planned-commands",
        "runtime-contract",
        "init",
        "context-build",
        "prompt-build",
        "collect-merge",
        "transport-init",
        "transport-append-batch",
        "transport-collect",
        "append-message",
        "checkpoint",
        "finalize-round",
        "resume-plan",
        "validate-round",
        "validate-discussion",
        "trace",
        "evidence",
        "stress-check",
        "validate-host-step",
        "capability-doctor",
        "validate-loop",
        "adapter-smoke",
    ]
