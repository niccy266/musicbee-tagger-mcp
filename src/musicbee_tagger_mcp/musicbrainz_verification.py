"""MusicBrainz recording match evaluation scoring function."""

from typing import Any, Dict, List, Optional

from .musicbrainz_api import musicbrainzngs
from .match_store import record_match
from .musicbrainz_scoring import classify_release, string_similarity

_FORENSIC_SCORE_ALIASES = (
    "forensic_score",
    "mb_forensic_score",
    "musicbrainz_forensic_score",
    "search_forensic_score",
    "mb_score",
    "score",
)


def _coerce_forensic_score(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_match(
    recording_id: str,
    expected_artist: Optional[str] = None,
    expected_title: Optional[str] = None,
    duration_sec: Optional[float] = None,
    forensic_score: Optional[float] = None,
    release_id: Optional[str] = None,
    acoustid_score: Optional[Any] = None,
    acoustid_match: Optional[Any] = None,
    acoustid_recording_id: Optional[str] = None,
    acoustid_result: Optional[Any] = None,
    fingerprint_score: Optional[Any] = None,
    fingerprint_match: Optional[Any] = None,
    fingerprint_recording_id: Optional[str] = None,
    fingerprint_result: Optional[Any] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Compare an identified recording with expected tags and local duration."""
    if forensic_score is None:
        for alias in _FORENSIC_SCORE_ALIASES:
            if alias in kwargs and kwargs.get(alias) is not None:
                forensic_score = kwargs.get(alias)
                break
    forensic_score = _coerce_forensic_score(forensic_score)
    # Collect AcoustID/fingerprint evidence from explicit args and aliases.
    if acoustid_score is None:
        for alias in ("acoustid_score", "acoustid_confidence", "acoustid_similarity"):
            if alias in kwargs and kwargs.get(alias) is not None:
                acoustid_score = kwargs.get(alias)
                break
    if fingerprint_score is None:
        for alias in ("fingerprint_score", "fingerprint_confidence", "fingerprint_similarity"):
            if alias in kwargs and kwargs.get(alias) is not None:
                fingerprint_score = kwargs.get(alias)
                break
    if acoustid_score is None and fingerprint_score is not None:
        acoustid_score = fingerprint_score
    if fingerprint_score is None and acoustid_score is not None:
        fingerprint_score = acoustid_score

    if acoustid_match is None:
        for alias in ("acoustid_match", "acoustid_verified", "acoustid_matched"):
            if alias in kwargs and kwargs.get(alias) is not None:
                acoustid_match = kwargs.get(alias)
                break
    if fingerprint_match is None:
        for alias in ("fingerprint_match", "fingerprint_verified", "fingerprint_matched"):
            if alias in kwargs and kwargs.get(alias) is not None:
                fingerprint_match = kwargs.get(alias)
                break
    if acoustid_match is None and fingerprint_match is not None:
        acoustid_match = fingerprint_match
    if fingerprint_match is None and acoustid_match is not None:
        fingerprint_match = acoustid_match

    if acoustid_recording_id is None:
        for alias in ("acoustid_recording_id", "acoustid_mbid", "acoustid_recording"):
            if alias in kwargs and kwargs.get(alias) is not None:
                acoustid_recording_id = kwargs.get(alias)
                break
    if fingerprint_recording_id is None:
        for alias in ("fingerprint_recording_id", "fingerprint_mbid", "fingerprint_recording"):
            if alias in kwargs and kwargs.get(alias) is not None:
                fingerprint_recording_id = kwargs.get(alias)
                break
    if acoustid_recording_id is None and fingerprint_recording_id is not None:
        acoustid_recording_id = fingerprint_recording_id
    if fingerprint_recording_id is None and acoustid_recording_id is not None:
        fingerprint_recording_id = acoustid_recording_id

    for result_obj in (acoustid_result, fingerprint_result, kwargs.get("acoustid"), kwargs.get("fingerprint")):
        if isinstance(result_obj, dict):
            if acoustid_score is None:
                for key in ("score", "confidence"):
                    if result_obj.get(key) is not None:
                        raw_score = result_obj.get(key)
                        try:
                            numeric = float(raw_score)
                            if key == "confidence" and numeric > 1.0:
                                numeric = numeric / 100.0
                            acoustid_score = numeric
                            break
                        except (TypeError, ValueError):
                            pass
            if acoustid_recording_id is None:
                for key in ("musicbrainz_recording_id", "mb_recording_id", "recording_id"):
                    if result_obj.get(key) is not None:
                        acoustid_recording_id = result_obj.get(key)
                        break
            if acoustid_match is None and result_obj.get("status") in ("matched", "ok"):
                acoustid_match = True
    try:
        data = musicbrainzngs.get_recording_by_id(
            recording_id, includes=["artists", "releases", "tags"]
        )
    except Exception as error:
        _h = record_match(recording_id, confidence=0.0)
        return {
            "verified": False,
            "confidence": 0.0,
            "error": f"Failed to fetch MBID {recording_id}: {error}",
            "match_handle": _h,
            "mbid_handle": _h,
            "handle": _h,
            "verified_match": _h,
            "recording_id": recording_id,
        }

    recording = data.get("recording", {})
    from .musicbrainz_search import _genres

    release_tags = [tag for release in recording.get("release-list", [])
                    for tag in release.get("tag-list", [])]
    genres = _genres(recording.get("tag-list"), release_tags)
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
            duration_match = 0.2
            mismatches.append(
                f"Duration mismatch: local is {duration_sec}s, MB is {duration}s "
                f"(diff {duration_diff}s)"
            )
    if expected_title and title_similarity < 0.5:
        mismatches.append(
            f"Title similarity is low ({title_similarity:.2f}): "
            f"expected '{expected_title}', got '{title}'"
        )
    if expected_artist and artist_similarity < 0.45:
        mismatches.append(
            f"Artist similarity is low ({artist_similarity:.2f}): "
            f"expected '{expected_artist}', got '{artist}'"
        )

    if duration_sec is not None and duration is not None:
        confidence = title_similarity * 40 + artist_similarity * 30 + duration_match * 30
    else:
        confidence = title_similarity * 55 + artist_similarity * 45

    high_forensic = forensic_score is not None and forensic_score >= 90.0
    if high_forensic and (duration_diff is None or duration_diff <= 15.0):
        mismatches = []
        confidence = max(confidence, 90.0)
        confidence = min(confidence, 100.0)

    if release_id:
        _early_release_match = any(
            release.get("id") == release_id
            for release in recording.get("release-list", [])
        )
    else:
        _early_release_match = None
    # AcoustID fingerprint evidence is supporting only...
    # reported confidence slightly, but it never clears mismatches or makes
    # a candidate verified on its own.
    fingerprint_recording_matches = (
        acoustid_recording_id is not None
        and str(acoustid_recording_id) == str(recording_id)
    )
    fingerprint_evidence = bool(fingerprint_recording_matches or acoustid_match is True)
    try:
        fingerprint_score_value = (
            float(acoustid_score) if acoustid_score is not None else None
        )
    except (TypeError, ValueError):
        fingerprint_score_value = None
    if fingerprint_score_value is not None:
        if fingerprint_score_value > 1.0:
            fingerprint_score_value = fingerprint_score_value / 100.0
        if fingerprint_score_value >= 0.8:
            fingerprint_evidence = True
    pre_fingerprint_verified = (
        confidence >= 50.0
        and (duration_diff is None or duration_diff <= 15.0)
        and (_early_release_match is not False)
    )
    if fingerprint_evidence:
        confidence = min(100.0, confidence + 5.0)

    parsed_releases = []
    top_release = None
    release_match = None
    if release_id:
        release_match = any(
            release.get("id") == release_id
            for release in recording.get("release-list", [])
        )
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

    if release_id and release_match is False:
        mismatches.append(
            f"Recording is not part of release {release_id}"
        )

    _match_release_id = release_id
    if _match_release_id is None and top_release:
        _match_release_id = top_release.get("release_id")
    _match_handle = record_match(recording_id, release_id=_match_release_id, confidence=round(confidence, 1), genre="; ".join(genres))
    return {
        "verified": pre_fingerprint_verified,
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
        "genre": "; ".join(genres),
        "mismatches": mismatches,
        "forensic_score": forensic_score,
        "acoustid_score": fingerprint_score_value,
        "acoustid_match": bool(fingerprint_evidence),
        "fingerprint_match": bool(fingerprint_evidence),
        "acoustid_recording_id": acoustid_recording_id,
        "fingerprint_evidence": fingerprint_evidence,
        "release_match": release_match,
        "match_handle": _match_handle,
        "mbid_handle": _match_handle,
        "handle": _match_handle,
        "verified_match": _match_handle,
    }


# Backward-compatible alias.
verify_recording_mbid = evaluate_match
