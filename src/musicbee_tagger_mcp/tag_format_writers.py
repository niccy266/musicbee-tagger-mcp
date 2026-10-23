"""Format-specific tag mutation routines used only by the CLI applier."""

from typing import Any, Dict

from mutagen.flac import FLAC
from mutagen.id3 import ID3, TALB, TDOR, TDRC, TIT2, TPE1, TPE2, TRCK, TXXX, UFID
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis


def write_id3(audio: Any, new_tags: Dict[str, Any]) -> None:
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    frames = {
        "title": ("TIT2", TIT2),
        "artist": ("TPE1", TPE1),
        "album": ("TALB", TALB),
        "album_artist": ("TPE2", TPE2),
        "year": ("TDRC", TDRC),
        "original_year": ("TDOR", TDOR),
        "track_number": ("TRCK", TRCK),
    }
    for field, (frame_id, frame_type) in frames.items():
        if new_tags.get(field):
            tags.setall(frame_id, [frame_type(encoding=3, text=[str(new_tags[field])])])
    if new_tags.get("musicbrainz_track_id"):
        tags.setall("UFID:http://musicbrainz.org", [
            UFID(owner="http://musicbrainz.org",
                 data=str(new_tags["musicbrainz_track_id"]).encode("ascii"))
        ])
    if new_tags.get("musicbrainz_release_id"):
        tags.setall("TXXX:MusicBrainz Album Id", [
            TXXX(encoding=3, desc="MusicBrainz Album Id",
                 text=[str(new_tags["musicbrainz_release_id"])])
        ])
    audio.save(v2_version=4)


def write_vorbis(audio: FLAC | OggVorbis, new_tags: Dict[str, Any]) -> None:
    mapping = {
        "title": "TITLE",
        "artist": "ARTIST",
        "album": "ALBUM",
        "album_artist": "ALBUMARTIST",
        "year": "DATE",
        "original_year": "ORIGINALDATE",
        "track_number": "TRACKNUMBER",
        "musicbrainz_track_id": "MUSICBRAINZ_TRACKID",
        "musicbrainz_release_id": "MUSICBRAINZ_ALBUMID",
    }
    for field, key in mapping.items():
        if field in new_tags and new_tags[field] is not None:
            audio[key] = [str(new_tags[field])]
    audio.save()


def write_mp4(audio: MP4, new_tags: Dict[str, Any]) -> None:
    mapping = {
        "title": "\xa9nam",
        "artist": "\xa9ART",
        "album": "\xa9alb",
        "album_artist": "aART",
        "year": "\xa9day",
    }
    for field, key in mapping.items():
        if new_tags.get(field):
            audio[key] = [str(new_tags[field])]
    if new_tags.get("track_number") is not None:
        audio["trkn"] = [(int(new_tags["track_number"]), 0)]
    audio.save()
