"""Single source of truth mapping canonical tag fields to every format.

Each canonical field (the names used across the MCP surface, the staging
manifests and the diff previews) declares how to:

- READ it:    ``read_from`` lists the format-native keys probed in order.
- WRITE it:   per-format instructions (ID3 frame, Vorbis key, MP4 atom).

Adding a new field means adding one entry here — read and write become
available for every supported format at once, and the round-trip tests in
``tests/test_field_map_roundtrip.py`` enforce that both directions agree.

Canonical field names and read keys follow this precedence per format:
Vorbis-comment style keys, ID3 frame ids, MP4 atom names.
"""

from dataclasses import dataclass
import re

from typing import Any, Dict, Optional


@dataclass(frozen=True)
class FieldSpec:
    """How one canonical field maps to physical tags in each format."""

    read_from: tuple
    id3: Optional[str] = None          # ID3 frame id, None = not writable as text
    id3_kind: str = "text"             # "text" | "ufid" | "txxx"
    id3_desc: Optional[str] = None     # description for TXXX frames
    vorbis: Optional[str] = None       # Vorbis comment key
    mp4: Optional[str] = None          # MP4 atom name
    mp4_pair: bool = False             # MP4 atom takes (number, total) tuple


FIELD_MAP: Dict[str, FieldSpec] = {
    "title": FieldSpec(
        read_from=("title", "TIT2", "\xa9nam", "TITLE"),
        id3="TIT2", vorbis="TITLE", mp4="\xa9nam",
    ),
    "artist": FieldSpec(
        read_from=("artist", "TPE1", "\xa9ART", "ARTIST"),
        id3="TPE1", vorbis="ARTIST", mp4="\xa9ART",
    ),
    "album": FieldSpec(
        read_from=("album", "TALB", "\xa9alb", "ALBUM"),
        id3="TALB", vorbis="ALBUM", mp4="\xa9alb",
    ),
    "album_artist": FieldSpec(
        read_from=("albumartist", "album artist", "TPE2", "aART", "ALBUMARTIST"),
        id3="TPE2", vorbis="ALBUMARTIST", mp4="aART",
    ),
    "year": FieldSpec(
        read_from=("date", "year", "TDRC", "TYER", "\xa9day", "DATE", "YEAR"),
        id3="TDRC", vorbis="DATE", mp4="\xa9day",
    ),
    "original_year": FieldSpec(
        read_from=("originaldate", "originalyear", "TDOR", "ORIGINALDATE", "ORIGINALYEAR"),
        id3="TDOR", vorbis="ORIGINALDATE", mp4="----:com.apple.iTunes:ORIGINALDATE",
    ),
    "genre": FieldSpec(
        read_from=("genre", "TCON", "\xa9gen", "GENRE"),
        id3="TCON", vorbis="GENRE", mp4="\xa9gen",
    ),
    "track_number": FieldSpec(
        read_from=("tracknumber", "TRCK", "trkn", "TRACKNUMBER"),
        id3="TRCK", vorbis="TRACKNUMBER", mp4="trkn", mp4_pair=True,
    ),
    "disc_number": FieldSpec(
        read_from=("discnumber", "TPOS", "disk", "DISCNUMBER"),
        id3="TPOS", vorbis="DISCNUMBER", mp4="disk", mp4_pair=True,
    ),
    "musicbrainz_track_id": FieldSpec(
        read_from=(
                   "----:com.apple.iTunes:MusicBrainz Track Id",
                   "musicbrainz_trackid", "UFID:http://musicbrainz.org",
                   "MUSICBRAINZ_TRACKID"),
        id3_kind="ufid", vorbis="MUSICBRAINZ_TRACKID",
        mp4="----:com.apple.iTunes:MusicBrainz Track Id",
    ),
    "musicbrainz_release_id": FieldSpec(
        read_from=(
                   "----:com.apple.iTunes:MusicBrainz Album Id",
                   "musicbrainz_albumid", "TXXX:MusicBrainz Album Id",
                   "MUSICBRAINZ_ALBUMID"),
        id3_kind="txxx", id3_desc="MusicBrainz Album Id", vorbis="MUSICBRAINZ_ALBUMID",
        mp4="----:com.apple.iTunes:MusicBrainz Album Id",
    ),
    "musicbrainz_artist_id": FieldSpec(
        read_from=(
                   "----:com.apple.iTunes:MusicBrainz Artist Id",
                   "musicbrainz_artistid", "TXXX:MusicBrainz Artist Id",
                   "MUSICBRAINZ_ARTISTID"),
        id3_kind="txxx", id3_desc="MusicBrainz Artist Id", vorbis="MUSICBRAINZ_ARTISTID",
        mp4="----:com.apple.iTunes:MusicBrainz Artist Id",
    ),
}


_ID3_FRAME_CLASSES: Dict[str, Any] = {}


def id3_frame_class(frame_id: str) -> Any:
    """Lazily resolve the mutagen frame class for an ID3 frame id."""
    from mutagen.id3 import TALB, TCON, TDOR, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
    if not _ID3_FRAME_CLASSES:
        _ID3_FRAME_CLASSES.update({
            "TIT2": TIT2, "TPE1": TPE1, "TALB": TALB, "TPE2": TPE2,
            "TDRC": TDRC, "TDOR": TDOR, "TCON": TCON, "TRCK": TRCK,
            "TPOS": TPOS,
        })
    return _ID3_FRAME_CLASSES[frame_id]


# Invisible Unicode format characters (bidi marks, zero-width) that carry
# no visible content and break Last.fm/MusicBrainz matching.
_INVISIBLE_RE = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]"
)


def _tag_str(value: Any) -> Optional[str]:
    """Stringify a tag value, decoding MP4 freeform bytes."""
    if type(value).__name__ == "MP4FreeForm":
        value = bytes(value).decode("utf-8", errors="replace")
    return _INVISIBLE_RE.sub("", str(value)).strip()


def get_first_tag(tags: Any, keys) -> Optional[str]:
    """First matching tag value across candidate keys.

    Handles Vorbis comment dicts (OGG/FLAC) that raise ValueError on
    membership tests for keys containing uppercase characters.
    """
    if not tags:
        return None
    for key in keys:
        try:
            if key in tags:
                value = tags[key]
                # ID3 UFID frames are objects; the payload bytes are the ID
                if type(value).__name__ == "UFID":
                    return _tag_str(value.data.decode("utf-8", errors="replace"))
                if isinstance(value, (list, tuple)) and len(value) > 0:
                    if isinstance(value[0], tuple):
                        return value[0]  # MP4 (track, total) pairs stay structured
                    return _tag_str(value[0])
                if value:
                    return _tag_str(value)
        except (ValueError, KeyError):
            lower = key.lower()
            try:
                if lower in tags:
                    value = tags[lower]
                    if isinstance(value, (list, tuple)) and len(value) > 0:
                        if isinstance(value[0], tuple):
                            return value[0]
                        return _tag_str(value[0])
                    if value:
                        return _tag_str(value)
            except (ValueError, KeyError):
                continue
    return None
