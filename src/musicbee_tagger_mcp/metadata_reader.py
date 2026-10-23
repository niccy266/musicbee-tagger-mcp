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

def get_first_tag(tags: Any, keys: list[str]) -> Optional[str]:
    """Retrieve the first matching tag value from a list of possible tag keys."""
    if not tags:
        return None
    for k in keys:
        if k in tags:
            v = tags[k]
            if isinstance(v, (list, tuple)) and len(v) > 0:
                return str(v[0]).strip()
            if v:
                return str(v).strip()
    return None

def read_audio_metadata(file_path: str) -> Dict[str, Any]:
    """
    Read comprehensive metadata and technical audio stream properties from an audio file.
    Supports MP3, FLAC, OGG, M4A, etc.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    audio = mutagen.File(file_path)
    if audio is None:
        raise ValueError(f"Unsupported audio format or corrupt file: {file_path}")

    # Technical stream info
    info = audio.info
    duration = getattr(info, "length", 0.0)
    bitrate = getattr(info, "bitrate", None)
    sample_rate = getattr(info, "sample_rate", None)
    channels = getattr(info, "channels", None)

    # Format-specific tag normalization
    tags = audio.tags or {}
    format_name = type(audio).__name__

    # Standardized fields extraction
    title = get_first_tag(tags, ["title", "TIT2", "\xa9nam", "TITLE"])
    artist = get_first_tag(tags, ["artist", "TPE1", "\xa9ART", "ARTIST"])
    album = get_first_tag(tags, ["album", "TALB", "\xa9alb", "ALBUM"])
    album_artist = get_first_tag(tags, ["albumartist", "album artist", "TPE2", "aART", "ALBUMARTIST"])
    year = get_first_tag(tags, ["date", "year", "TDRC", "TYER", "\xa9day", "DATE", "YEAR"])
    original_year = get_first_tag(tags, ["originaldate", "originalyear", "TDOR", "ORIGINALDATE", "ORIGINALYEAR"])
    genre = get_first_tag(tags, ["genre", "TCON", "\xa9gen", "GENRE"])

    # Track / Disc numbers
    track_raw = get_first_tag(tags, ["tracknumber", "TRCK", "trkn", "TRACKNUMBER"])
    track_num, total_tracks = normalize_track_number(track_raw)

    disc_raw = get_first_tag(tags, ["discnumber", "TPOS", "disk", "DISCNUMBER"])
    disc_num, total_discs = normalize_track_number(disc_raw)

    # MusicBrainz IDs
    mb_track_id = get_first_tag(tags, [
        "musicbrainz_trackid", 
        "UFID:http://musicbrainz.org",
        "MUSICBRAINZ_TRACKID"
    ])
    mb_release_id = get_first_tag(tags, [
        "musicbrainz_albumid", 
        "TXXX:MusicBrainz Album Id", 
        "MUSICBRAINZ_ALBUMID"
    ])
    mb_artist_id = get_first_tag(tags, [
        "musicbrainz_artistid", 
        "TXXX:MusicBrainz Artist Id", 
        "MUSICBRAINZ_ARTISTID"
    ])

    return {
        "file_path": str(path.resolve()),
        "file_name": path.name,
        "format": format_name,
        "duration_seconds": round(duration, 3),
        "bitrate_kbps": int(bitrate / 1000) if bitrate else None,
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "tags": {
            "title": title,
            "artist": artist,
            "album": album,
            "album_artist": album_artist,
            "track_number": track_num,
            "total_tracks": total_tracks,
            "disc_number": disc_num,
            "total_discs": total_discs,
            "year": year,
            "original_year": original_year,
            "genre": genre,
            "musicbrainz_track_id": mb_track_id,
            "musicbrainz_release_id": mb_release_id,
            "musicbrainz_artist_id": mb_artist_id,
        },
        "raw_tag_keys": list(tags.keys()) if hasattr(tags, "keys") else []
    }
