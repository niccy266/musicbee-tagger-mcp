"""MusicBrainz client with forensic release resolution and scrobble classification."""

from typing import List, Dict, Any, Optional
import musicbrainzngs

USER_AGENT_APP = "musicbee-tagger-mcp"
USER_AGENT_VERSION = "0.1.0"
USER_AGENT_CONTACT = "https://github.com/user/musicbee-tagger-mcp"

# Initialize musicbrainzngs
musicbrainzngs.set_useragent(USER_AGENT_APP, USER_AGENT_VERSION, USER_AGENT_CONTACT)

def classify_release(release: Dict[str, Any]) -> Dict[str, Any]:
    """
    Classify a release by primary type, secondary types, and live status.
    """
    title = release.get("title", "")
    rg = release.get("release-group", {})
    primary_type = rg.get("primary-type", "Unknown")
    secondary_types = rg.get("secondary-type-list", [])

    is_live = "Live" in secondary_types or "live" in title.lower()
    is_compilation = "Compilation" in secondary_types or "compilation" in title.lower()
    is_single = primary_type in ("Single", "EP")

    category = "Studio Album"
    if is_live:
        category = "Live Release"
    elif is_compilation:
        category = "Compilation"
    elif is_single:
        category = "Single / EP"

    return {
        "category": category,
        "is_live": is_live,
        "is_compilation": is_compilation,
        "primary_type": primary_type,
        "secondary_types": secondary_types,
    }

def calculate_duration_score(target_sec: Optional[float], mb_length_ms: Optional[int]) -> tuple[float, str]:
    """Compare track duration against MusicBrainz recording length."""
    if not target_sec or not mb_length_ms:
        return 0.0, "no_duration_data"

    mb_sec = mb_length_ms / 1000.0
    diff = abs(target_sec - mb_sec)

    if diff <= 2.5:
        return 30.0, f"exact_match (diff {diff:.1f}s)"
    elif diff <= 6.0:
        return 20.0, f"close_match (diff {diff:.1f}s)"
    elif diff <= 15.0:
        return 5.0, f"approximate (diff {diff:.1f}s)"
    else:
        return -25.0, f"duration_mismatch (diff {diff:.1f}s)"

def search_recordings_forensic(
    artist: str,
    title: str,
    duration_sec: Optional[float] = None,
    clue: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Search MusicBrainz for candidate recordings and return enriched release details.
    Uses duration and optional context clues (e.g., venue, album subtitle) to score results.
    """
    query_parts = []
    if artist:
        query_parts.append(f'artist:"{artist}"')
    if title:
        query_parts.append(f'recording:"{title}"')
    if clue:
        query_parts.append(f'"{clue}"')

    query = " AND ".join(query_parts) if query_parts else title

    try:
        results = musicbrainzngs.search_recordings(query=query, limit=limit)
    except Exception as e:
        return [{"error": f"MusicBrainz query error: {str(e)}"}]

    recordings = results.get("recording-list", [])
    ranked_candidates = []

    for rec in recordings:
        rec_id = rec.get("id")
        rec_title = rec.get("title", "")
        rec_artist = rec.get("artist-credit-phrase", "")
        rec_length = rec.get("length")  # in ms
        base_score = float(rec.get("ext:score", 50))

        # Check duration match
        dur_score, dur_note = calculate_duration_score(
            duration_sec, int(rec_length) if rec_length else None
        )
        total_score = base_score + dur_score

        # Collect releases this recording appeared on
        release_list = rec.get("release-list", [])
        enriched_releases = []

        for rel in release_list:
            classification = classify_release(rel)
            date = rel.get("date", "")
            media_list = rel.get("medium-list", [])
            
            track_num = None
            if media_list and "track-list" in media_list[0]:
                tracks = media_list[0]["track-list"]
                if tracks:
                    track_num = tracks[0].get("number")

            enriched_releases.append({
                "release_id": rel.get("id"),
                "album_title": rel.get("title"),
                "date": date,
                "country": rel.get("country"),
                "track_number": track_num,
                "classification": classification,
            })

        ranked_candidates.append({
            "recording_id": rec_id,
            "title": rec_title,
            "artist": rec_artist,
            "duration_seconds": round(int(rec_length) / 1000, 2) if rec_length else None,
            "forensic_score": total_score,
            "duration_match_note": dur_note,
            "releases": enriched_releases
        })

    # Sort by forensic score descending
    ranked_candidates.sort(key=lambda x: x.get("forensic_score", 0), reverse=True)
    return ranked_candidates
