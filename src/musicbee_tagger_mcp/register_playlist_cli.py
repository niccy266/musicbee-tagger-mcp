"""Human-run local playlist registration command."""

import sys
from typing import TextIO

from .file_registry import get_registry
from .tools.files import register_playlist


def run(input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> int:
    """Prompt locally for a playlist and print path-free token handoff details."""
    print(
        "This local command registers playlist entries without sending paths to "
        "the MCP agent.",
        file=output_stream,
    )
    print(
        "Run this command in a separate terminal, not through the agent.",
        file=output_stream,
    )
    print("Playlist path (.m3u or .m3u8): ", end="", file=output_stream, flush=True)
    playlist_path = input_stream.readline().strip().strip('"')
    if not playlist_path:
        print("No playlist path was entered.", file=output_stream)
        return 1

    result = register_playlist(playlist_path, get_registry())
    if "error" in result:
        print(f"Unable to register playlist: {result['error']}.", file=output_stream)
        return 1

    registered = result["registered"]
    print(
        f"Registered {len(registered)} audio file(s). Copy these tokens to the "
        "agent; no playlist path was sent in an MCP request.",
        file=output_stream,
    )
    for entry in registered:
        print(
            f"- {entry['token']} ({entry['display_name']})",
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
    """Run the interactive playlist registration command."""
    raise SystemExit(run())


if __name__ == "__main__":
    main()
