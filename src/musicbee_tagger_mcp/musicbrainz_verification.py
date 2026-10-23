"""Direct MusicBrainz recording-ID verification gate."""

from typing import Any, Dict, List, Optional

from .musicbrainz_api import musicbrainzngs
from .musicbrainz_scoring import classify_release, string_similarity


def verify_recording_mbid(
    recording_id: str,
    expected_artist: Optional[str] = None,
    expected_title: Optional[str] = None,
    duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """Compare an identified recording with expected tags and local duration."""
    try:
        data = musicbrainzngs.get_recording_by_id(
            recording_id, includes=["artists", "releases"]
        )
    except Exception as error:
        return {
            "verified": False,
            "confidence": 0.0,
            "error": f"Failed to fetch MBID {recording_id}: {error}",
        }

    recording = data.get("recording", {})
    title = recording.get("title", "")
    artist = recording.get("artist-credit-phrase", "")
    length = recording.get("length")
    duration = round(int(length) / 1000, 2) if length else None
    title_similarity = string_similarity(expected_title, title) if expected_title else 1.0
    artist_similarity = string_similarity(expected_artist, artist) if expected_artist else 1.0

    mismatches: List[str] = []
    duration_diff = None
    duration_match = 1.0
    if duration_sec is not None and duration is not None:
        duration_diff = round(abs(duration_sec - duration), 2)
        if duration_diff <= 2.5:
            duration_match = 1.0
        elif duration_diff <= 6.0:
            duration_match = 0.85
        elif duration_diff <= 15.0:
            duration_match = 0.5
            mismatches.append(f"Duration difference is notable ({duration_diff}s)")
        else:
            duration_match = 0.0
            mismatches.append(
                f"Duration mismatch: local is {duration_sec}s, MB is {duration}s "
                f"(diff {duration_diff}s)"
            )
    if expected_title and title_similarity < 0.65:
        mismatches.append(
            f"Title similarity is low ({title_similarity:.2f}): "
            f"expected '{expected_title}', got '{title}'"
        )
    if expected_artist and artist_similarity < 0.60:
        mismatches.append(
            f"Artist similarity is low ({artist_similarity:.2f}): "
            f"expected '{expected_artist}', got '{artist}'"
        )

    if duration_sec is not None and duration is not None:
        confidence = title_similarity * 40 + artist_similarity * 30 + duration_match * 30
    else:
        confidence = title_similarity * 55 + artist_similarity * 45

    parsed_releases = []
    top_release = None
    for release in recording.get("release-list", []):
        info = {
            "release_id": release.get("id"),
            "album_title": release.get("title"),
            "date": release.get("date", ""),
            "country": release.get("country", ""),
            "classification": classify_release(release),
        }
        parsed_releases.append(info)
        if top_release is None and info["classification"]["category"] == "Studio Album":
            top_release = info
    if top_release is None and parsed_releases:
        top_release = parsed_releases[0]

    return {
        "verified": confidence >= 75.0 and (duration_diff is None or duration_diff <= 6.0),
        "confidence": round(confidence, 1),
        "recording_id": recording_id,
        "mb_title": title,
        "mb_artist": artist,
        "mb_duration_seconds": duration,
        "duration_diff_seconds": duration_diff,
        "title_similarity": title_similarity,
        "artist_similarity": artist_similarity,
        "top_release": top_release,
        "release_count": len(parsed_releases),
        "mismatches": mismatches,
    }
