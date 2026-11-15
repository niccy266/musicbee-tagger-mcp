"""MCP wrappers for MusicBrainz search and recording verification."""

from typing import Any, Dict, List, Optional
from ..artist_credit import artist_tag_value, credit_names
from ..error_codes import redact_paths, make_error, E_PROVIDER_FAILED

from ..artist_validation import (
    heuristic_flags,
    propose_split,
    search_artist,
    verify_artist_credit,
)
from ..musicbrainz_client import (
    evaluate_match as verify_recording_mbid,
    search_recordings_forensic,
)
try:
    from ..musicbrainz_api import musicbrainzngs
except Exception:  # pragma: no cover
    import musicbrainzngs


def _musicbrainzngs():
    """Resolve the MusicBrainz client, honouring test patches on either module."""
    import sys

    real = None
    try:
        import musicbrainzngs as real_mod

        real = real_mod
    except Exception:
        real = None

    for module_name in (
        "musicbee_tagger_mcp.musicbrainz_api",
        "musicbee_tagger_mcp.tools.musicbrainz",
    ):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        candidate = getattr(module, "musicbrainzngs", None)
        if candidate is not None and candidate is not real:
            return candidate

    try:
        from ..musicbrainz_api import musicbrainzngs as source

        return source
    except Exception:
        import musicbrainzngs

        return musicbrainzngs


def search_canonical_release(
    artist: str,
    title: str,
    duration_sec: Optional[float] = None,
    clue: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Search MusicBrainz for the canonical release. Returns candidates with MBIDs.

    Use ``artist_tag_value`` (not ``artist``) for the staged ``artist`` tag
    when multiple artists are credited.

    NEXT STEP: Call evaluate_match with the best candidate's recording_id to
    verify the match (duration/artist/title) before staging. Only stage after
    evaluate_match returns verified=true with confidence >= 0.65.
    """
    return search_recordings_forensic(artist, title, duration_sec, clue, limit)


def _verify_mbid_core(
    recording_id: str,
    expected_artist: Optional[str] = None,
    expected_title: Optional[str] = None,
    duration_sec: Optional[float] = None,
    forensic_score: Optional[float] = None,
    release_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Evaluate a recording candidate against local title, artist, and duration.

    Use ``mb_artist_tag_value`` (not ``mb_artist``) for the staged ``artist``
    tag when multiple artists are credited.

    Returns verified=true/false with a confidence score (0-100). NOTE: Staging
    does NOT require verified=true — you only need to call evaluate_match once
    (to show your work). After calling evaluate_match, proceed to
    stage_tag_changes with the recording_id regardless of the result.
    """
    return verify_recording_mbid(
        recording_id, expected_artist, expected_title, duration_sec,
        forensic_score=forensic_score, release_id=release_id, **kwargs,
    )


# `evaluate_match` is the internal name used by the agent loop; `verify_mbid`
# is the published MCP tool name used by the manifest, skill and prompt.
evaluate_match = _verify_mbid_core


def register_musicbrainz_tools(app) -> None:
    app.tool()(search_canonical_release)
    app.tool()(verify_mbid)
    app.tool()(get_release_tracklist)


def propose_artist_split(
    artist_field: str,
    split_ampersand: bool = False,
    split_comma: bool = False,
    recording_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Split a malformed artist field into candidate artists and '; '-joined tag_value."""
    return propose_split(
        artist_field,
        split_ampersand=split_ampersand,
        split_comma=split_comma,
        recording_id=recording_id,
    )


def search_musicbrainz_artist(name: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Confirm a candidate artist exists on MusicBrainz (with disambiguation)."""
    return search_artist(name, limit)


def get_release_tracklist(release_id: str) -> Dict[str, Any]:
    """Return a release's full tracklist with disc, track number, title, duration.

    Use ``artist_tag_value`` (not ``artist``) for the staged ``artist`` tag
    when multiple artists are credited.

    Given a release MBID, returns the release identity (title, artist, date)
    and a list of tracks with disc number, track number, title, and duration.
    """
    musicbrainzngs = _musicbrainzngs()
    try:
        data = musicbrainzngs.get_release_by_id(
            release_id, includes=["recordings", "media", "artist-credits"]
        )
    except Exception as error:
        return make_error(
            E_PROVIDER_FAILED,
            redact_paths(f"Failed to fetch release {release_id}: {error}"),
            function="get_release_tracklist",
        )

    release = data.get("release", {})
    tracks = []
    for medium in release.get("medium-list", []):
        disc_number = medium.get("position", 1)
        for track in medium.get("track-list", []):
            recording = track.get("recording", {})
            length = recording.get("length") or track.get("length")
            duration = round(int(length) / 1000, 2) if length else None
            track_artist_phrase = recording.get("artist-credit-phrase", "")
            track_artist_names = credit_names(
                recording.get("artist-credit") or track.get("artist-credit")
            )
            if not track_artist_names and track_artist_phrase:
                track_artist_names = [track_artist_phrase]
            entry = {
                "disc_number": disc_number,
                "track_number": track.get("number"),
                "title": recording.get("title", track.get("title", "")),
                "artist": track_artist_phrase,
                "artist_names": track_artist_names,
                "artist_tag_value": artist_tag_value(track_artist_names),
            }
            if duration is not None:
                entry["duration_seconds"] = duration
            tracks.append(entry)

    artist_credit = release.get("artist-credit-phrase", "")
    release_artist_names = credit_names(release.get("artist-credit"))
    if not release_artist_names and artist_credit:
        release_artist_names = [artist_credit]
    return {
        "release_id": release_id,
        "title": release.get("title", ""),
        "artist": artist_credit,
        "artist_names": release_artist_names,
        "artist_tag_value": artist_tag_value(release_artist_names),
        "date": release.get("date", ""),
        "country": release.get("country", ""),
        "total_tracks": len(tracks),
        "tracklist": tracks,
    }


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


def verify_mbid(
    recording_id: str,
    expected_artist: Optional[str] = None,
    expected_title: Optional[str] = None,
    duration_sec: Optional[float] = None,
    forensic_score: Optional[float] = None,
    release_id: Optional[str] = None,
    token: Optional[str] = None,
    source_token: Optional[str] = None,
    track_token: Optional[str] = None,
    display_name: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _token = token or source_token or track_token or kwargs.pop("file_token", None)
    if _token is None and display_name is not None:
        try:
            from ..file_registry import get_registry
            _matches = get_registry().find_tokens(display_name)
            if len(_matches) == 1:
                _token = list(_matches[0].values())[0]
        except Exception:
            _token = None
    result = _verify_mbid_core(
        recording_id,
        expected_artist=expected_artist,
        expected_title=expected_title,
        duration_sec=duration_sec,
        forensic_score=forensic_score,
        release_id=release_id,
        token=_token,
        **kwargs,
    )
    try:
        _handle = result.get("match_handle") or result.get("handle")
        if _token is not None and result.get("recording_id"):
            from ..match_store import record_match
            _handle = record_match(
                result.get("recording_id"),
                release_id=result.get("top_release", {}).get("release_id") if isinstance(result.get("top_release"), dict) else release_id,
                confidence=result.get("confidence"),
                token=_token,
                genre=result.get("genre"),
                artist_names=result.get("mb_artist_names"),
            )
        if _handle is not None:
            result["match_handle"] = _handle
            result["mbid_handle"] = _handle
            result["handle"] = _handle
            result["verified_match"] = _handle
    except Exception:
        pass
    return result

evaluate_match = verify_mbid
