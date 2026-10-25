#!/usr/bin/env python
"""Convenience launcher for the MusicBee OpenRouter tagging agent.

Run from the repository root::

    python go.py
    python go.py <job_id> --max-batches 1

Any arguments are forwarded to ``scripts/openrouter_agent_loop.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    from scripts.openrouter_agent_loop import main as agent_main

    if argv is not None:
        sys.argv = [sys.argv[0]] + list(argv)
    return agent_main()


if __name__ == "__main__":
    raise SystemExit(main())