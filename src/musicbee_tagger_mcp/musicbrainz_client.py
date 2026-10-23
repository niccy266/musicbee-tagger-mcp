"""MusicBrainz client with forensic release resolution and scrobble classification."""

from typing import List, Dict, Any, Optional
import difflib
import musicbrainzngs

USER_AGENT_APP = "musicbee-tagger-mcp"
USER_AGENT_VERSION = "0.1.0"
USER_AGENT_CONTACT = "https://github.com/niccy266/musicbee-tagger-mcp"

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

    category = "Unknown"
    if is_live:
        category = "Live Release"
    elif is_compilation:
        category = "Compilation"
    elif is_single:
        category = "Single / EP"
    elif primary_type == "Album":
        category = "Studio Album"

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


def string_similarity(a: Optional[str], b: Optional[str]) -> float:
    """Calculate normalized character & token similarity between two strings."""
    if not a or not b:
        return 0.0
    import re
    s_a = a.strip().lower()
    s_b = b.strip().lower()
    if s_a == s_b:
        return 1.0

    # Clean bracketed fluff from both for comparison
    clean_a = re.sub(r"[\(\[\{\【\（\「].*?[\)\]\}\】\）\」]", "", s_a).strip()
    clean_b = re.sub(r"[\(\[\{\【\（\「].*?[\)\]\}\】\）\」]", "", s_b).strip()
    if clean_a and clean_b and clean_a == clean_b:
        return 0.95

    base_ratio = difflib.SequenceMatcher(None, s_a, s_b).ratio()
    clean_ratio = difflib.SequenceMatcher(None, clean_a or s_a, clean_b or s_b).ratio()
    return round(max(base_ratio, clean_ratio), 3)


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


def verify_recording_mbid(
    recording_id: str,
    expected_artist: Optional[str] = None,
    expected_title: Optional[str] = None,
    duration_sec: Optional[float] = None
) -> Dict[str, Any]:
    """
    Verification / Eval Gate: Retrieve recording details directly by MBID and
    verify against expected title, artist, and audio duration.
    """
    try:
        data = musicbrainzngs.get_recording_by_id(
            recording_id,
            includes=["artists", "releases"]
        )
    except Exception as e:
        return {
            "verified": False,
            "confidence": 0.0,
            "error": f"Failed to fetch MBID {recording_id}: {str(e)}"
        }

    rec = data.get("recording", {})
    mb_title = rec.get("title", "")
    mb_artist = rec.get("artist-credit-phrase", "")
    mb_length_ms = rec.get("length")
    mb_sec = round(int(mb_length_ms) / 1000, 2) if mb_length_ms else None

    # Calculate metrics
    title_sim = string_similarity(expected_title, mb_title) if expected_title else 1.0
    artist_sim = string_similarity(expected_artist, mb_artist) if expected_artist else 1.0

    mismatches: List[str] = []
    dur_diff = None
    dur_match_pct = 1.0

    if duration_sec is not None and mb_sec is not None:
        dur_diff = round(abs(duration_sec - mb_sec), 2)
        if dur_diff <= 2.5:
            dur_match_pct = 1.0
        elif dur_diff <= 6.0:
            dur_match_pct = 0.85
        elif dur_diff <= 15.0:
            dur_match_pct = 0.5
            mismatches.append(f"Duration difference is notable ({dur_diff}s)")
        else:
            dur_match_pct = 0.0
            mismatches.append(f"Duration mismatch: local is {duration_sec}s, MB is {mb_sec}s (diff {dur_diff}s)")

    if expected_title and title_sim < 0.65:
        mismatches.append(f"Title similarity is low ({title_sim:.2f}): expected '{expected_title}', got '{mb_title}'")

    if expected_artist and artist_sim < 0.60:
        mismatches.append(f"Artist similarity is low ({artist_sim:.2f}): expected '{expected_artist}', got '{mb_artist}'")

    # Weighted confidence score (0-100)
    # Title: 40%, Artist: 30%, Duration: 30%
    if duration_sec is not None and mb_sec is not None:
        confidence = (title_sim * 40.0) + (artist_sim * 30.0) + (dur_match_pct * 30.0)
    else:
        confidence = (title_sim * 55.0) + (artist_sim * 45.0)

    # Classify releases
    releases = rec.get("release-list", [])
    top_release = None
    parsed_releases = []
    for rel in releases:
        cl = classify_release(rel)
        rel_info = {
            "release_id": rel.get("id"),
            "album_title": rel.get("title"),
            "date": rel.get("date", ""),
            "country": rel.get("country", ""),
            "classification": cl,
        }
        parsed_releases.append(rel_info)
        # Prioritize earliest Studio Album
        if not top_release and cl["category"] == "Studio Album":
            top_release = rel_info

    if not top_release and parsed_releases:
        top_release = parsed_releases[0]

    verified = (confidence >= 75.0) and (dur_diff is None or dur_diff <= 6.0)

    return {
        "verified": verified,
        "confidence": round(confidence, 1),
        "recording_id": recording_id,
        "mb_title": mb_title,
        "mb_artist": mb_artist,
        "mb_duration_seconds": mb_sec,
        "duration_diff_seconds": dur_diff,
        "title_similarity": title_sim,
        "artist_similarity": artist_sim,
        "top_release": top_release,
        "release_count": len(parsed_releases),
        "mismatches": mismatches,
    }
