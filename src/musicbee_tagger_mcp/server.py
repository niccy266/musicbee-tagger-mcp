"""MCP application assembly and stdio entrypoint."""

import argparse
import asyncio
import os
import sys

from mcp.server.mcpserver import MCPServer

from . import __version__
from .job_store import get_job_store
from .tools import register_tools
from .tools.inspection import (
    extract_filename_clues,
    get_batch_brief,
    read_track_metadata,
)
from .tools.musicbrainz import search_canonical_release, verify_mbid
from .tools.tags import (
    amend_staged_changes,
    get_staged_change,
    list_staged_changes,
    preview_tags,
    stage_tag_changes,
    withdraw_staged_change,
)
from .tools.text import repair_mojibake

app = MCPServer("musicbee-tagger")
register_tools(app)


def _print_tools() -> None:
    tools = asyncio.run(app.list_tools())
    print(f"musicbee-tagger-mcp {__version__} MCP tools:")
    for tool in tools:
        description = (tool.description or "").strip()
        print(f"  {tool.name}: {description}")


def _print_jobs() -> None:
    try:
        jobs = get_job_store().list_jobs()
    except RuntimeError as error:
        print(f"Unable to list playlist jobs: {error}")
        return
    if not jobs:
        print("No playlist jobs with pending work.")
        return
    # All possible statuses from job_store.py
    STATUSES = ("pending", "in_progress", "done", "failed", "skipped", "unresolved", "needs_review", "partial")

    # Print table header
    header = f"{'Job ID':<36} {'Playlist':<20} " + " ".join(f"{s:>12}" for s in STATUSES) + "  Total"
    print(header)
    print("-" * len(header))

    for job in jobs:
        counts = job.get("counts", {})
        # Count each status
        row_counts = {}
        total = 0
        for status in STATUSES:
            count = counts.get(status, 0)
            row_counts[status] = count
            total += count

        job_id = job.get("job_id", "")[:35]
        playlist = job.get("playlist_name", "")[:19]

        # Format row
        row = f"{job_id:<36} {playlist:<20} " + " ".join(f"{row_counts[s]:>12}" for s in STATUSES) + f"  {total:>5}"
        print(row)


def main() -> None:
    """Run the MCP server over stdio or print user-facing help."""
    parser = argparse.ArgumentParser(
        prog="musicbee-tagger-mcp",
        description=(
            "MusicBee Tagger MCP server. Run without arguments to start the "
            "stdio MCP server; use the options below for user-facing help."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"musicbee-tagger-mcp {__version__}"
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List the MCP tools available to agents.",
    )
    parser.add_argument(
        "--list-jobs",
        action="store_true",
        help="List playlist jobs with pending work.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("help", "list-jobs", "list-tools"),
        help="Optional help command.",
    )

    args = parser.parse_args()

    if args.command == "list-tools" or args.list_tools:
        _print_tools()
        return
    if args.command == "list-jobs" or args.list_jobs:
        _print_jobs()
        return
    if args.command == "help":
        _print_tools()
        print()
        _print_jobs()
        return

    print(
        f"musicbee-tagger-mcp {__version__} starting; "
        f"data_dir={os.environ.get('MUSICBEE_TAGGER_DATA_DIR', '(default)')}",
        file=sys.stderr,
        flush=True,
    )
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
