"""MCP application assembly and stdio entrypoint."""

from mcp.server.mcpserver import MCPServer

from .tools import register_tools
from .tools.files import register_files, register_playlist
from .tools.inspection import (
    extract_filename_clues,
    get_batch_brief,
    read_track_metadata,
)
from .tools.musicbrainz import search_canonical_release, verify_mbid
from .tools.tags import list_staged_changes, preview_tags, stage_tag_changes
from .tools.text import repair_mojibake

app = MCPServer("musicbee-tagger")
register_tools(app)


def main() -> None:
    """Run the MCP server over stdio for local desktop clients."""
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
