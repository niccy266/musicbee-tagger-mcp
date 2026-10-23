"""Compatibility facade for MusicBrainz services and shared scoring helpers."""

from .musicbrainz_scoring import (
    calculate_duration_score,
    classify_release,
    string_similarity,
)
from .musicbrainz_search import search_recordings_forensic
from .musicbrainz_verification import verify_recording_mbid

__all__ = [
    "calculate_duration_score",
    "classify_release",
    "search_recordings_forensic",
    "string_similarity",
    "verify_recording_mbid",
]
