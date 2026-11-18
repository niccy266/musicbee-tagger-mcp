"""MCP tools for Last.fm canonical title resolution."""

from typing import Any, Dict, List, Optional

from ..error_codes import E_PROVIDER_NOT_CONFIGURED, make_error
from ..lastfm import (
    LastFmConfig,
    build_search_passes,
    lastfm_track_get_info,
    lastfm_track_search,
    resolve_lastfm,
    should_skip_lastfm,
)


def resolve_lastfm_title(
    title: Optional[str] = None,
    artist: Optional[str] = None,
    display_name: Optional[str] = None,
    folder_context: Optional[List[str]] = None,
    confidence: Optional[float] = None,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve the most popular Last.fm title/artist form for a track."""
    return resolve_lastfm(
        title=title,
        artist=artist,
        filename=filename if filename is not None else display_name,
        folder_context=folder_context,
        confidence=confidence,
    )


def lastfm_track_search_tool(
    track: str,
    artist: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search Last.fm tracks (ranked by listeners)."""
    return lastfm_track_search(track, artist, limit=limit)


def register_lastfm_tools(app) -> None:
    app.tool()(resolve_lastfm_title)
    app.tool()(lastfm_track_search_tool)
