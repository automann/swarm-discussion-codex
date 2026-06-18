"""swarm-discussion runtime incubator package."""

from __future__ import annotations

__version__ = "0.0.0"


def planned_commands() -> list[str]:
    """Return the planned runtime command surface.

    Only a small subset exists in the skeleton. Keeping the target command list
    executable makes drift obvious as implementation begins.
    """
    return [
        "health",
        "planned-commands",
        "runtime-contract",
        "init",
        "context-build",
        "persona-plan",
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
        "validate-host-step",
        "capability-doctor",
        "validate-loop",
        "adapter-smoke",
    ]
