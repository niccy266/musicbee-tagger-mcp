"""Human-run local playlist registration command."""

import sys
from typing import TextIO

import uuid

from .playlist import parse_m3u_playlist
from .file_registry import get_registry
from .job_store import get_job_store
from .tools.files import register_playlist


def _progress_bar(output_stream: TextIO, current: int, total: int) -> None:
    """Render a compact, in-place registration progress bar."""
    if total <= 0:
        return
    width = 30
    filled = int(width * current / total)
    bar = "#" * filled + "-" * (width - filled)
    print(
        f"\rRegistering: [{bar}] {current}/{total}",
        end="",
        file=output_stream,
        flush=True,
    )
    if current >= total:
        print(file=output_stream, flush=True)
def run(
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    playlist_path: str = "",
) -> int:
    """Register a supplied playlist or prompt locally, then print path-free details."""
    print(
        "This local command registers playlist entries without sending paths to "
        "the MCP agent.",
        file=output_stream,
    )
    print(
        "Run this command in a separate terminal, not through the agent.",
        file=output_stream,
    )
    if not playlist_path:
        print(
            "Playlist path (.m3u or .m3u8): ",
            end="",
            file=output_stream,
            flush=True,
        )
        playlist_path = input_stream.readline().strip().strip('"')
    if not playlist_path:
        print("No playlist path was entered.", file=output_stream)
        return 1

    playlist_name = playlist_path.replace("\\", "/").rsplit("/", 1)[-1]
    job_id = str(uuid.uuid4())
    get_job_store().create_job([], playlist_name=playlist_name, skipped=0, job_id=job_id)
    print(
        f"Job id: {job_id} (registration in progress)",
        file=output_stream,
        flush=True,
    )

    result = register_playlist(
        playlist_path,
        get_registry(),
        get_job_store(),
        job_id,
        progress_callback=lambda current, total: _progress_bar(
            output_stream, current, total
        ),
    )
    if "error" in result:
        print(f"Unable to register playlist: {result['error']}.", file=output_stream)
        return 1

    registered_count = len(result["registered"])
    print(
        f"Registered {registered_count} audio file(s) as playlist job "
        f"{job_id}.",
        file=output_stream,
    )
    print(
        "Pass this job id to the agent loop or ask the agent for the next "
        "batch; the playlist path was never sent over MCP.",
        file=output_stream,
    )

    skipped = result["skipped"]
    if skipped:
        count = len(skipped)
        label = "entry" if count == 1 else "entries"
        print(f"Skipped {count} playlist {label}:", file=output_stream)
        for entry in skipped:
            print(f"- Line {entry['line']}: {entry['error']}", file=output_stream)

    return 0


def main() -> None:
    """Run playlist registration with an optional local path argument."""
    if len(sys.argv) > 2:
        print("Provide at most one playlist path (.m3u or .m3u8).")
        raise SystemExit(2)
    playlist_path = sys.argv[1] if len(sys.argv) == 2 else ""
    raise SystemExit(
        run(
            input_stream=sys.stdin,
            output_stream=sys.stdout,
            playlist_path=playlist_path,
        )
    )


if __name__ == "__main__":
    main()
