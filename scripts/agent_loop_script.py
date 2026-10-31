"""Shared entry point for looping agentic music tagging.

The entry point is backend-agnostic: it can drive the built-in OpenRouter /
OpenAI-style function-calling loop or delegate to a locally installed Cline
CLI.  Select the backend with ``--agent`` (aliases: ``--agent-type``,
``--backend``).
"""

from __future__ import annotations

import argparse


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Looping agentic music tagger")
    parser.add_argument(
        "--agent", "--agent-type", "--backend",
        dest="agent",
        choices=("openrouter", "openai", "cline"),
        default="openrouter",
        help="Agent backend to use",
    )
    parser.add_argument("--provider", default=None, help="Provider override for Cline")
    parser.add_argument("--model", default=None, help="Model override for Cline")
    parser.add_argument("--cline-bin", default=None, help="Path to the Cline executable")
    parser.add_argument("job_id", nargs="?")
    args = parser.parse_args(argv)

    backend = "openrouter" if args.agent == "openai" else args.agent
    if backend == "openrouter":
        from . import openrouter_agent

        openrouter_agent.run(args.job_id)
        return 0

    from . import cline_agent

    return cline_agent.run(
        args.job_id,
        provider=args.provider,
        model=args.model,
        cline_bin=args.cline_bin,
    )


if __name__ == "__main__":
    raise SystemExit(main())
