"""MCP tool groups, registered by the small server entrypoint."""

from .inspection import register_inspection_tools
from .musicbrainz import register_musicbrainz_tools
from .tags import register_tag_tools
from .text import register_text_tools


def register_tools(app) -> None:
    register_inspection_tools(app)
    register_musicbrainz_tools(app)
    register_tag_tools(app)
    register_text_tools(app)
