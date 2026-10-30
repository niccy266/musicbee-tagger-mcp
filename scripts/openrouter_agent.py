"""OpenRouter-backed agent implementation."""
from __future__ import annotations


def run(job_id=None, **kwargs) -> None:
    from . import openrouter_agent_loop as loop

    main = getattr(loop, "main", None)
    if main is None:
        return None
    if job_id is not None:
        try:
            return main([str(job_id)])
        except TypeError:
            pass
    try:
        return main()
    except TypeError:
        return main(None)
