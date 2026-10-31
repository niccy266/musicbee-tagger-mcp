"""MCP tool groups, registered by the small server entrypoint."""

from .inspection import register_inspection_tools
from .musicbrainz import register_musicbrainz_tools, register_split_tools
from .queue import register_queue_tools
from .tags import register_tag_tools
from .playlists import register_playlist_tools
from .text import register_text_tools
from .genre_cleanup import register_genre_cleanup_tools
from .acrcloud import register_acrcloud_tools
from .review import register_review_tools


def register_tools(app) -> None:
    register_inspection_tools(app)
    register_musicbrainz_tools(app)
    register_split_tools(app)
    register_queue_tools(app)
    register_tag_tools(app)
    register_playlist_tools(app)
    register_text_tools(app)
    register_genre_cleanup_tools(app)
    register_acrcloud_tools(app)
    register_review_tools(app)
