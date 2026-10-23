"""MusicBrainz recording search and forensic candidate ranking."""

from typing import Any, Dict, List, Optional

from .musicbrainz_api import musicbrainzngs
from .musicbrainz_scoring import calculate_duration_score, classify_release


def search_recordings_forensic(
    artist: str,
    title: str,
    duration_sec: Optional[float] = None,
    clue: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Search recordings and rank matches by service score and duration."""
    parts = []
    if artist:
        parts.append(f'artist:"{artist}"')
    if title:
        parts.append(f'recording:"{title}"')
    if clue:
        parts.append(f'"{clue}"')
    query = " AND ".join(parts) if parts else title

    try:
        results = musicbrainzngs.search_recordings(query=query, limit=limit)
    except Exception as error:
        return [{"error": f"MusicBrainz query error: {error}"}]

    candidates = []
    for recording in results.get("recording-list", []):
        length = recording.get("length")
        duration_score, duration_note = calculate_duration_score(
            duration_sec, int(length) if length else None
        )
        releases = []
        for release in recording.get("release-list", []):
            media = release.get("medium-list", [])
            tracks = media[0].get("track-list", []) if media else []
            releases.append({
                "release_id": release.get("id"),
                "album_title": release.get("title"),
                "date": release.get("date", ""),
                "country": release.get("country"),
                "track_number": tracks[0].get("number") if tracks else None,
                "classification": classify_release(release),
            })
        candidates.append({
            "recording_id": recording.get("id"),
            "title": recording.get("title", ""),
            "artist": recording.get("artist-credit-phrase", ""),
            "duration_seconds": round(int(length) / 1000, 2) if length else None,
            "forensic_score": float(recording.get("ext:score", 50)) + duration_score,
            "duration_match_note": duration_note,
            "releases": releases,
        })
    candidates.sort(key=lambda candidate: candidate["forensic_score"], reverse=True)
    return candidates
