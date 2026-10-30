"""Compatibility alias for the generic agent loop."""

from __future__ import annotations

from .agent_loop import *  # noqa: F401,F403
from .agent_loop import main, run

__all__ = ["main", "run"]
