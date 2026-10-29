"""OpenRouter-backed agent implementation."""
from __future__ import annotations


def run(job_id=None) -> None:
    from . import openrouter_agent_loop as loop

    loop.main() if hasattr(loop, "main") else None
