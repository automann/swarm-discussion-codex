"""Private shared helpers for the swarm runtime package.

Not part of the adapter-facing API — adapters call the CLI, not this module.
This module exists to hold helpers that previously had to be kept in lockstep
across modules (notably the message-id grammar).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Canonical message-id grammar: rN-msg-NNN where the sequence is 3+ digits.
MESSAGE_ID = re.compile(r"^r(\d+)-msg-(\d{3,})$")


def fsync_dir(path: Path) -> None:
    """Best-effort directory fsync for durability after an atomic rename."""
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass
