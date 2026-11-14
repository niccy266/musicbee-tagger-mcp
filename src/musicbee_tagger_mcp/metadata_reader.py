"""Audio metadata reader using Mutagen for universal format inspection."""

from pathlib import Path
from typing import Dict, Any, Optional
import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4

def normalize_track_number(val: Any) -> tuple[Optional[int], Optional[int]]:
    """Extract (track_number, total_tracks) from string or tuple."""
    if not val:
        return None, None
    if isinstance(val, (list, tuple)):
        val = val[0]
    val_str = str(val).strip()
    if "/" in val_str:
        parts = val_str.split("/", 1)
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return None, None
    try:
        return int(val_str), None
    except ValueError:
        return None, None

def read_audio_metadata(file_path: str) -> Dict[str, Any]:
    """
    Read comprehensive metadata and technical audio stream properties from an audio file.
    Supports MP3, FLAC, OGG, M4A, etc.
    """
    path = Path(file_path)
    if not path.is_file():
        # Path-free: this exception can reach MCP clients via tool wrappers.
        raise FileNotFoundError("Audio file not found")

    try:
        audio = mutagen.File(file_path)
    except Exception:
        # Mutagen parse errors may embed the full path.
        raise ValueError("Unsupported audio format or corrupt file") from None
    if audio is None:
        raise ValueError("Unsupported audio format or corrupt file")

    # Technical stream info
    info = audio.info
    duration = getattr(info, "length", 0.0)
    bitrate = getattr(info, "bitrate", None)
    sample_rate = getattr(info, "sample_rate", None)
    channels = getattr(info, "channels", None)

    # Format-specific tag normalization
    tags = audio.tags or {}
    format_name = type(audio).__name__

    # Canonical field extraction, driven by the shared field map
    from .field_map import FIELD_MAP, get_first_tag

    tags_by_field: Dict[str, Optional[str]] = {}
    for field, spec in FIELD_MAP.items():
        if field in ("track_number", "disc_number"):
            continue
        tags_by_field[field] = get_first_tag(tags, spec.read_from)

    # Track / Disc numbers (parsed into number + total)
    track_num, total_tracks = normalize_track_number(
        get_first_tag(tags, FIELD_MAP["track_number"].read_from))
    disc_num, total_discs = normalize_track_number(
        get_first_tag(tags, FIELD_MAP["disc_number"].read_from))

    return {
        "file_path": str(path.resolve()),
        "file_name": path.name,
        "format": format_name,
        "duration_seconds": round(duration, 3),
        "bitrate_kbps": int(bitrate / 1000) if bitrate else None,
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "tags": {
            "title": tags_by_field["title"],
            "artist": tags_by_field["artist"],
            "album": tags_by_field["album"],
            "album_artist": tags_by_field["album_artist"],
            "track_number": track_num,
            "total_tracks": total_tracks,
            "disc_number": disc_num,
            "total_discs": total_discs,
            "year": tags_by_field["year"],
            "original_year": tags_by_field["original_year"],
            "genre": tags_by_field["genre"],
            "musicbrainz_track_id": tags_by_field["musicbrainz_track_id"],
            "musicbrainz_release_id": tags_by_field["musicbrainz_release_id"],
            "musicbrainz_artist_id": tags_by_field["musicbrainz_artist_id"],
            "artist_sort": tags_by_field["artist_sort"],
            "title_sort": tags_by_field["title_sort"],
            "album_sort": tags_by_field["album_sort"],
            "album_artist_sort": tags_by_field["album_artist_sort"],
            "lastfm_title": tags_by_field["lastfm_title"],
            "lastfm_artist": tags_by_field["lastfm_artist"],
            "lastfm_url": tags_by_field["lastfm_url"],
        },
        "raw_tag_keys": list(tags.keys()) if hasattr(tags, "keys") else []
    }


def normalize_for_matching(text):
    import re, unicodedata
    if text is None:
        return ""
    value = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]", "", str(text))
    value = value.casefold()
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


normalize_match_key = normalize_for_matching
normalize_key = normalize_for_matching


def strip_invisible(text):
    import re
    if text is None:
        return ""
    return re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]", "", str(text))

normalize_for_match = normalize_for_matching
normalize_text_for_matching = normalize_for_matching
fold_for_matching = normalize_for_matching
match_key = normalize_for_matching
strip_invisible_chars = strip_invisible
