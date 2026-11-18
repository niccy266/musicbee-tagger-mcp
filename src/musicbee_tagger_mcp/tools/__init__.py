"""MCP tool groups, registered by the small server entrypoint."""

import asyncio
import json

from .inspection import register_inspection_tools
from .musicbrainz import register_musicbrainz_tools, register_split_tools
from .queue import register_queue_tools
from .tags import register_tag_tools
from .playlists import register_playlist_tools
from .text import register_text_tools
from .genre_cleanup import register_genre_cleanup_tools
from .acrcloud import register_acrcloud_tools
from .acoustid import register_acoustid_tools
from .lastfm import register_lastfm_tools
from .review import register_review_tools


def register_schema_resources(app) -> None:
    async def tool_schema_handler(tool: str) -> str:
        tools = await app.list_tools()
        for t in tools:
            if t.name == tool:
                return json.dumps(t.input_schema, indent=2, sort_keys=True)
        return json.dumps({"error": f"unknown tool: {tool}"})

    app.resource(
        "schema/{tool}.json",
        name="tool_schema",
        title="MCP tool JSON schema",
        description="JSON schema for an MCP tool keyed by tool name",
        mime_type="application/json",
    )(tool_schema_handler)


def register_tools(app) -> None:
    register_inspection_tools(app)
    register_musicbrainz_tools(app)
    register_split_tools(app)
    register_queue_tools(app)
    register_tag_tools(app)
    register_playlist_tools(app)
    register_text_tools(app)
    register_genre_cleanup_tools(app)
    register_review_tools(app)
    register_acrcloud_tools(app)
    register_acoustid_tools(app)
    register_lastfm_tools(app)
    register_schema_resources(app)
