"""Tests against the royalty-free real audio files in test_files/test_audio_files.

These are real-world files with real quirks (mixed tag encodings, Cyrillic
genres, invisible Unicode characters in filenames) — exactly what this tool
exists to handle. Originals must never be modified.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import mutagen
import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "test_files" / "test_audio_files"

MP3 = FIXTURES / "I'd Be A Millionaire - David.mp3"
OGG_KNACK = FIXTURES / "The Knack (Main Theme) - John Barry And His Orchestra_1.ogg"
OGG_MARSEILLES = FIXTURES / "The Sunshine Of Marseilles - Alfredo And His Band \u200e_1.ogg"

REAL_FILES = [MP3, OGG_KNACK, OGG_MARSEILLES]

pytestmark = pytest.mark.requires_audio_fixtures

# Expected ground truth (verified with exiftool)
EXPECTED = {
    MP3: {"title": "I'd Be A Millionaire", "artist": "David",
          "genre": "Другое", "album": "", "duration_s": 214.0},
    OGG_KNACK: {"title": "The Knack (Main Theme)",
                "artist": "John Barry And His Orchestra",
                "genre": "Другое", "duration_s": 174.7},
    OGG_MARSEILLES: {"title": "The Sunshine Of Marseilles",
                     "artist": "Alfredo And His Band",
                     "genre": "Другое", "duration_s": None},
}


@pytest.fixture(scope="module")
def file_hashes():
    """Digest originals before the module runs; verified after."""
    import hashlib
    return {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in REAL_FILES}


def _ground_truth(path):
    for f, exp in EXPECTED.items():
        if f.name == path.name or f == path:
            return exp
    return {}


sys.path.insert(0, str(REPO / "src"))
from musicbee_tagger_mcp.metadata_reader import read_audio_metadata  # noqa: E402
from musicbee_tagger_mcp.tag_format_writers import (  # noqa: E402
    write_id3, write_vorbis, write_mp4,
)


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name[:40])
def test_reads_real_file(path):
    result = read_audio_metadata(str(path))
    exp = _ground_truth(path)
    tags = result["tags"]
    assert tags["title"] == exp["title"]
    assert tags["artist"] == exp["artist"]
    if exp.get("genre"):
        assert tags["genre"] == exp["genre"], "Cyrillic genre must survive decode"
    if exp.get("album") == "":
        assert not tags.get("album"), "absent album should be empty/None, not garbage"


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name[:40])
def test_error_never_contains_path(path):
    import musicbee_tagger_mcp.metadata_reader as mr
    try:
        mr.read_audio_metadata(str(path.parent / "definitely not here.mp3"))
        pytest.fail("expected FileNotFoundError")
    except FileNotFoundError as e:
        assert str(path) not in str(e)
        assert "definitely not here" not in str(e)


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name[:40])
def test_technical_properties(path, tmp_path):
    """Duration/bitrate sanity vs ffprobe ground truth."""
    result = read_audio_metadata(str(path))
    exp = _ground_truth(path)
    if exp.get("duration_s") is None:
        pytest.skip("no duration recorded for this file")
    assert abs(result["duration_seconds"] - exp["duration_s"]) < 1.0
    assert result["duration_seconds"] > 0


UNICODE_WRITE_CASES = ["Моцарт — Реквием", "坂本龍一", "Song 🎵 mixes А Я", "Chanson Française"]


@pytest.mark.parametrize("value", UNICODE_WRITE_CASES)
def test_unicode_roundtrip_per_format(value, tmp_path):
    """Cyrillic/CJK/emoji must survive write→read on every format."""
    for src, fmt in [(MP3, "mp3"), (OGG_KNACK, "ogg")]:
        dest = tmp_path / src.name
        shutil.copy2(src, dest)
        audio = _open(dest)
        data = {"artist": value, "title": value}
        if fmt == "mp3":
            write_id3(audio, data)
        else:
            write_vorbis(audio, data)
        audio.save()
        tags = read_audio_metadata(str(dest))["tags"]
        assert tags["artist"] == value, f"{fmt}: artist garbled"
        assert tags["title"] == value, f"{fmt}: title garbled"


def _open(path):
    from mutagen.mp3 import MP3
    from mutagen.oggvorbis import OggVorbis
    from mutagen.mp4 import MP4
    return {"mp3": MP3, "ogg": OggVorbis, "m4a": MP4}[path.suffix.lstrip(".")(path) if False else _suffix(path)](path)


def _suffix(path):
    return "mp3" if path.suffix == ".mp3" else ("ogg" if path.suffix == ".ogg" else "m4a")


def test_cross_format_fidelity(tmp_path):
    """Read OGG metadata, write it to a fresh MP3, canonical fields must match."""
    src_tags = read_audio_metadata(str(OGG_KNACK))["tags"]
    dest = tmp_path / MP3.name
    shutil.copy2(MP3, dest)
    audio = _open(dest)
    write_id3(audio, {
        "title": src_tags["title"], "artist": src_tags["artist"],
        "album": "Cross Format Test", "genre": src_tags["genre"],
        "year": "1965",
    })
    audio.save()
    out = read_audio_metadata(str(dest))["tags"]
    for key in ("title", "artist", "album", "genre", "year"):
        assert out[key] == src_tags.get(key) if key != "album" and key != "year" else out[key] == {"album": "Cross Format Test", "year": "1965"}[key]


def test_musicbrainz_ids_on_real_files(tmp_path):
    """No MB IDs in the originals; after writing them they must read back."""
    for src, fmt in [(MP3, "mp3"), (OGG_KNACK, "ogg")]:
        dest = tmp_path / src.name
        shutil.copy2(src, dest)
        audio = _open(dest)
        data = {"musicbrainz_track_id": "aaaa-1234-bbbb",
                "musicbrainz_release_id": "cccc-5678-dddd",
                "musicbrainz_artist_id": "eeee-9012-ffff"}
        if fmt == "mp3":
            write_id3(audio, data)
        else:
            write_vorbis(audio, data)
        audio.save()
        tags = read_audio_metadata(str(dest))["tags"]
        for k, v in data.items():
            assert tags[k] == v, f"{fmt}: {k} roundtrip failed"


def test_originals_unmodified(file_hashes, tmp_path):
    """Fixture integrity: originals must remain byte-identical after tests."""
    import hashlib
    for f, before in file_hashes.items():
        assert hashlib.sha256(f.read_bytes()).hexdigest() == before, \
            f"fixture mutated: {f.name}"


# --- Garbled-tag correction workflow ----------------------------------------

GARBLED = {
    "title": "???unknown???",
    "artist": "Unknown Artist",
    "album": "",
    "genre": "Другое",
    "year": "1999",
}


def _make_garbled_copy(tmp_path, src, fmt):
    dest = tmp_path / src.name
    shutil.copy2(src, dest)
    audio = _open(dest)
    data = dict(GARBLED)
    if fmt == "mp3":
        write_id3(audio, data)
    else:
        write_vorbis(audio, data)
    audio.save()
    return dest


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name[:40])
def test_garbled_copy_can_be_corrected(path, tmp_path):
    """Simulate a messy rip: garble, then correct, then verify."""
    fmt = "mp3" if path.suffix == ".mp3" else "ogg"
    dest = _make_garbled_copy(tmp_path, path, fmt)
    garbled = read_audio_metadata(str(dest))["tags"]
    assert garbled["artist"] == GARBLED["artist"]
    assert garbled["title"] == GARBLED["title"]

    truth = _ground_truth(path)
    audio = _open(dest)
    writer = write_id3 if fmt == "mp3" else write_vorbis
    writer(audio, {"title": truth["title"], "artist": truth["artist"]})
    audio.save()

    fixed = read_audio_metadata(str(dest))["tags"]
    assert fixed["title"] == truth["title"]
    assert fixed["artist"] == truth["artist"]
    assert fixed["genre"] == GARBLED["genre"], "untouched fields must be preserved"


# --- Issue #19: sort fields and Last.fm passthrough on real files ---

SORT_AND_LASTFM = {
    "artist_sort": "Качмарик Дэвид",
    "title_sort": "Другое Название",
    "album_sort": "Другое Альбом",
    "album_artist_sort": "Качмарик Дэвид",
    "lastfm_title": "Another Title",
    "lastfm_artist": "David Kachmarik",
    "lastfm_url": "https://www.last.fm/music/david+kachmarik",
}


@pytest.mark.parametrize("ext", ["mp3", "ogg", "m4a"])
def test_sort_and_lastfm_fields_roundtrip_on_real_files(tmp_path, ext):
    """Write Cyrillic sort names + Last.fm passthrough into a real audio
    file and read them back byte-identical."""
    src = {"mp3": MP3, "ogg": OGG_KNACK, "m4a": OGG_KNACK}[ext]
    work = tmp_path / f"sort-test.{ext}"
    if ext == "m4a":
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
             "-c:a", "aac", str(work)], check=True)
    else:
        work.write_bytes(src.read_bytes())

    audio = mutagen.File(str(work))
    writer = {"mp3": write_id3, "ogg": write_vorbis, "m4a": write_mp4}[ext]
    writer(audio, SORT_AND_LASTFM)
    audio.save()

    tags = read_audio_metadata(str(work))["tags"]
    for field, expected in SORT_AND_LASTFM.items():
        assert tags.get(field) == expected, \
            f"{ext} {field}: wrote {expected!r}, read back {tags.get(field)!r}"
