"""Human-run local cleanup for persisted playlist registrations."""

import argparse
import sys
from typing import TextIO

from .file_registry import get_registry


def run(input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> int:
    """Ask for confirmation before deleting local token-to-path mappings."""
    registry = get_registry()
    registrations = registry.list_tokens()
    if not registrations:
        print("There are no local file registrations to clear.", file=output_stream)
        return 0

    print(
        f"This will remove {len(registrations)} local file registration(s).",
        file=output_stream,
    )
    print(
        "It will not modify audio files or staged tag proposals.",
        file=output_stream,
    )
    print("Type YES to remove the registrations: ", end="", file=output_stream, flush=True)
    if input_stream.readline().strip() != "YES":
        print("Registration cleanup cancelled.", file=output_stream)
        return 0

    removed = registry.clear()
    print(f"Removed {removed} local file registration(s).", file=output_stream)
    return 0


def main() -> None:
    """Run the confirmation-gated registration cleanup command."""
    parser = argparse.ArgumentParser(
        prog="musicbee-tagger-clear-registrations",
        description="Remove local token-to-path registrations after confirmation.",
    )
    parser.parse_args()
    raise SystemExit(run())


if __name__ == "__main__":
    main()
