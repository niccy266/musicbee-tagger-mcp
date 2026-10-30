"""Supervisor for long-running agent loops."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from openrouter_agent_loop_monitor import main as monitor_main


def supervise() -> None:
    """Supervise agent loop execution via monitor loop."""
    sys.exit(monitor_main())


if __name__ == "__main__":
    supervise()

