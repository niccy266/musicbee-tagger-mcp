"""MCP application assembly and stdio entrypoint."""

import os
import sys

from mcp.server.mcpserver import MCPServer

from . import __version__
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


def main() -> None:
    """Run the MCP server over stdio for local desktop clients."""
    print(
        f"musicbee-tagger-mcp {__version__} starting; "
        f"data_dir={os.environ.get('MUSICBEE_TAGGER_DATA_DIR', '(default)')}",
        file=sys.stderr,
        flush=True,
    )
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
