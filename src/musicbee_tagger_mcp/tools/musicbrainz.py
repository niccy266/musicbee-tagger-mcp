"""MCP wrappers for MusicBrainz search and recording verification."""

from typing import Any, Dict, List, Optional

from ..musicbrainz_client import evaluate_match as verify_recording_mbid, search_recordings_forensic


def search_canonical_release(
    artist: str,
    title: str,
    duration_sec: Optional[float] = None,
    clue: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Search and rank MusicBrainz recording candidates."""
    return search_recordings_forensic(artist, title, duration_sec, clue, limit)


def evaluate_match(
    recording_id: str,
    expected_artist: Optional[str] = None,
    expected_title: Optional[str] = None,
    duration_sec: Optional[float] = None,
    forensic_score: Optional[float] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Evaluate a recording candidate against local title, artist, and duration."""
    return verify_recording_mbid(
        recording_id, expected_artist, expected_title, duration_sec,
        forensic_score=forensic_score, **kwargs,
    )


def register_musicbrainz_tools(app) -> None:
    app.tool()(search_canonical_release)
    app.tool()(evaluate_match)


def propose_artist_split(
    artist_field: str,
    split_ampersand: bool = False,
    split_comma: bool = False,
) -> Dict[str, Any]:
    """Split a malformed artist field into candidate artists mechanically."""
    return propose_split(artist_field, split_ampersand, split_comma)


def search_musicbrainz_artist(name: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Confirm a candidate artist exists on MusicBrainz (with disambiguation)."""
    return search_artist(name, limit)


def verify_artists_on_recording(
    recording_id: str,
    candidate_artists: List[str],
) -> Dict[str, Any]:
    """Check candidates are credited on the MusicBrainz recording."""
    return verify_artist_credit(recording_id, candidate_artists)


def flag_suspicious_artists(candidate_artists: List[str]) -> List[Dict[str, str]]:
    """Heuristic garble/debris flags for candidate artists."""
    return heuristic_flags(candidate_artists)


def register_split_tools(app) -> None:
    app.tool()(propose_artist_split)
    app.tool()(search_musicbrainz_artist)
    app.tool()(verify_artists_on_recording)
    app.tool()(flag_suspicious_artists)


# Backward-compatible alias.
verify_mbid = evaluate_match

from ..artist_validation import (  # noqa: E402,F401
    propose_split,
    search_artist,
    verify_artist_credit,
    heuristic_flags,
)
