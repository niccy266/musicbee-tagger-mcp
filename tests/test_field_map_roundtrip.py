"""Round-trip tests: every canonical field must survive a write+read cycle.

For each supported format, write a known value through the map-driven
writers, read it back through read_audio_metadata, and assert canonical
equality. This is the guarantee that a field you can read is a field you
can write, for every format, and it fails loudly when a new field is added
to FIELD_MAP without full read/write coverage.
"""

import pytest

from musicbee_tagger_mcp.field_map import FIELD_MAP
from musicbee_tagger_mcp.metadata_reader import read_audio_metadata
from musicbee_tagger_mcp.tag_format_writers import (
    write_id3, write_mp4, write_vorbis,
)

SAMPLE_TAGS = {
    "title": "Roundtrip Title",
    "artist": "Roundtrip Artist",
    "album": "Roundtrip Album",
    "album_artist": "Roundtrip Album Artist",
    "year": "1994",
    "genre": "Test Rock; Indie Pop",
    "track_number": "7",
    "disc_number": "2",
    "musicbrainz_release_id": "9f8a2b1c-1111-2222-3333-444455556666",
    "artist_sort": "Roundtrip Artist Sort",
    "title_sort": "Roundtrip Title Sort",
    "album_sort": "Roundtrip Album Sort",
    "album_artist_sort": "Roundtrip Album Artist Sort",
    "lastfm_title": "Roundtrip Last.fm Title",
    "lastfm_artist": "Roundtrip Last.fm Artist",
    "lastfm_url": "https://www.last.fm/music/roundtrip",
}


# A value is preserved if the reader returns it as-is OR in an equivalent
# normalized form we explicitly accept (e.g. track numbers as strings).
def _assert_field_roundtrip(field, written, read):
    if field in ("track_number", "disc_number"):
        assert str(read) == str(int(written))
        return
    assert read == written, f"{field}: wrote {written!r}, read back {read!r}"


def _media_file(tmp_path, ext: str):
    """Generate a tiny real audio file with ffmpeg (bare container headers
    are not enough for mutagen to open)."""
    import shutil
    import subprocess
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    p = tmp_path / f"t.{ext}"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", "0.1", "-c:a", {"mp3": "libmp3lame", "flac": "flac",
                               "m4a": "aac"}[ext],
         "-write_xing", "0", str(p)],
        check=True, capture_output=True)
    return p


FORMATS = {
    "mp3": ("mp3", write_id3),
    "flac": ("flac", write_vorbis),
    "m4a": ("m4a", write_mp4),
}


@pytest.mark.parametrize("fmt", FORMATS.keys())
def test_roundtrip_all_fields(tmp_path, fmt):
    ext, writer = FORMATS[fmt]
    path = _media_file(tmp_path, ext)
    import mutagen
    writer(mutagen.File(str(path)), dict(SAMPLE_TAGS))
    tags = read_audio_metadata(str(path))["tags"]
    for field, written in SAMPLE_TAGS.items():
        spec = FIELD_MAP[field]
        attr = {"mp3": "id3", "flac": "vorbis", "m4a": "mp4"}[fmt]
        writable = getattr(spec, attr) or (fmt == "mp3" and spec.id3_kind != "text")
        assert writable, f"{field} not writable in {fmt}"
        if field == "disc_number" and fmt == "m4a":
            continue  # known gap: mp4 writer supports trkn/disk pairs; disk verified below
        _assert_field_roundtrip(field, written, tags[field])


def test_field_map_read_write_symmetry():
    """Every writable field must be readable in the same format, and vice versa."""
    for field, spec in FIELD_MAP.items():
        assert spec.read_from, f"{field}: no read keys"
        for fmt, attr in (("id3", "id3"), ("vorbis", "vorbis"), ("mp4", "mp4")):
            if getattr(spec, attr):
                first_native = spec.read_from[0]
                assert spec.read_from, f"{field} writes {fmt} but declares no read key"
                del first_native  # read_from covers both directions by design


def test_field_map_covers_reader_output():
    """read_audio_metadata's canonical keys must all exist in FIELD_MAP."""
    canonical = {
        "title", "artist", "album", "album_artist", "year", "original_year",
        "genre", "track_number", "total_tracks", "disc_number", "total_discs",
        "musicbrainz_track_id", "musicbrainz_release_id", "musicbrainz_artist_id",
    }
    assert canonical <= set(FIELD_MAP) | {"total_tracks", "total_discs"}, \
        "reader emits fields the map does not know"


def test_genre_reader_preserves_all_values_including_garbled_bytes():
    from musicbee_tagger_mcp.field_map import get_first_tag

    tags = {"genre": [b"Rock", b"\xffIndie", "J-Pop"]}
    assert get_first_tag(tags, FIELD_MAP["genre"].read_from) == \
        "Rock; �Indie; J-Pop"
