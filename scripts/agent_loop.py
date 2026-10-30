"""Generic agent loop entry point (compatibility alias)."""

from __future__ import annotations

from . import agent_loop_script as _script
from . import cline_agent, openrouter_agent


def main(argv=None):
    return _script.main(argv)


def run(job_id=None, *, agent="openrouter", **kwargs):
    if agent in ("openrouter", "openai"):
        return openrouter_agent.run(job_id)
    return cline_agent.run(job_id, **kwargs)


__all__ = ["main", "run", "agent_loop_script", "openrouter_agent", "cline_agent"]
