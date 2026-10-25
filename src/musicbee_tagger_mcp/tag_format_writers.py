"""Format-specific tag mutation routines used only by the CLI applier.

All field routing lives in ``field_map.FIELD_MAP``; these routines only
know how to physically set frames/comments/atoms for their format.
"""

from typing import Any, Dict

from mutagen.flac import FLAC
from mutagen.id3 import ID3, TXXX, UFID
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.oggvorbis import OggVorbis

from .field_map import FIELD_MAP, id3_frame_class


def _tag_value(value: Any) -> str:
    return str(value)


def _genre_values(value: Any) -> list[str]:
    """Split a canonical semicolon-delimited genre field into tag values."""
    return [part.strip() for part in _tag_value(value).split(";") if part.strip()]


def write_id3(audio: Any, new_tags: Dict[str, Any]) -> None:
    """Write canonical fields to an ID3 (MP3) tag."""
    if audio.tags is None:
        audio.add_tags()
    tags: ID3 = audio.tags
    for field, spec in FIELD_MAP.items():
        if spec.id3_kind == "text" and new_tags.get(field) is not None:
            frame_class = id3_frame_class(spec.id3)
            values = (_genre_values(new_tags[field]) if field == "genre"
                      else [_tag_value(new_tags[field])])
            tags.setall(spec.id3, [frame_class(encoding=3,
                                               text=values)])
        elif spec.id3_kind == "ufid" and new_tags.get(field) is not None:
            tags.setall("UFID:http://musicbrainz.org", [
                UFID(owner="http://musicbrainz.org",
                     data=_tag_value(new_tags[field]).encode("ascii"))])
        elif spec.id3_kind == "txxx" and new_tags.get(field) is not None:
            tags.setall(f"TXXX:{spec.id3_desc}", [
                TXXX(encoding=3, desc=spec.id3_desc,
                     text=[_tag_value(new_tags[field])])])
    audio.save(v2_version=4)


def write_vorbis(audio: FLAC | OggVorbis, new_tags: Dict[str, Any]) -> None:
    """Write canonical fields to a Vorbis comment tag (FLAC / OGG)."""
    for field, spec in FIELD_MAP.items():
        if spec.vorbis is not None and new_tags.get(field) is not None:
            audio[spec.vorbis] = (_genre_values(new_tags[field]) if field == "genre"
                                  else [_tag_value(new_tags[field])])
    audio.save()


def write_mp4(audio: MP4, new_tags: Dict[str, Any]) -> None:
    """Write canonical fields to an MP4 (m4a) tag."""
    for field, spec in FIELD_MAP.items():
        value = new_tags.get(field)
        if value is None or spec.mp4 is None:
            continue
        if spec.mp4_pair:
            total = new_tags.get(
                "total_tracks" if field == "track_number" else "total_discs")
            audio[spec.mp4] = [(int(value), int(total) if total else 0)]
        elif spec.mp4.startswith("----:"):
            audio[spec.mp4] = [MP4FreeForm(_tag_value(value).encode("utf-8"))]
        elif field == "genre":
            audio[spec.mp4] = _genre_values(value)
        else:
            audio[spec.mp4] = [_tag_value(value)]
    audio.save()
