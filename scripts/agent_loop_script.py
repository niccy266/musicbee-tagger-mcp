"""Shared entry point for looping agentic music tagging."""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Looping agentic music tagger")
    parser.add_argument("--agent", choices=("openrouter", "cline"), default="openrouter")
    parser.add_argument("job_id", nargs="?")
    args = parser.parse_args()
    if args.agent == "openrouter":
        from . import openrouter_agent

        openrouter_agent.run(args.job_id)
    else:
        from . import cline_agent

        cline_agent.run(args.job_id)


if __name__ == "__main__":
    main()
