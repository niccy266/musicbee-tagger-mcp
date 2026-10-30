#!/usr/bin/env python
"""Convenience launcher for the AI-supervised MusicBee OpenRouter tagging agent.

Run from repository root:
    python go_supervise.py
    python go_supervise.py <playlist.m3u>
    python go_supervise.py <job_id>
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from musicbee_tagger_mcp.file_registry import get_registry
from musicbee_tagger_mcp.job_store import get_job_store
from musicbee_tagger_mcp.tools.files import register_playlist


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    target = argv[0] if argv else ""
    remaining_args = argv[1:] if argv else []

    job_id = None
    if target:
        target_path = Path(target)
        if target_path.is_file() or target.lower().endswith((".m3u", ".m3u8")):
            # It's a playlist file! Register it first.
            print(f"Registering playlist file: {target}")
            playlist_name = target.replace("\\", "/").rsplit("/", 1)[-1]
            job_id = str(uuid.uuid4())
            get_job_store().create_job([], playlist_name=playlist_name, skipped=0, job_id=job_id)
            result = register_playlist(
                target,
                get_registry(),
                get_job_store(),
                job_id,
            )
            if "error" in result:
                print(f"Error registering playlist: {result['error']}")
                return 1
            print(f"Successfully registered {len(result['registered'])} tracks as job {job_id}")
        else:
            # Treated as a job ID
            job_id = target

    # Now launch the AI-supervised agent loop
    from scripts import ai_supervised_agent_loop as supervised_agent

    script_argv = ["ai_supervised_agent_loop.py"]
    if job_id:
        script_argv.append(job_id)
    script_argv.extend(remaining_args)

    sys.argv = script_argv
    return supervised_agent.main()


if __name__ == "__main__":
    raise SystemExit(main())
