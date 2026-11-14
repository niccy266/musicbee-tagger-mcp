"""Tests for JobStore fallback in metadata inspection tools."""

import json
import pytest

from musicbee_tagger_mcp.file_registry import FileRegistry
from musicbee_tagger_mcp.job_store import JobStore
from musicbee_tagger_mcp.tools import inspection


def test_job_store_get_track_by_token(tmp_path):
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    store = JobStore(directory=job_dir)

    token1 = "11111111-1111-1111-1111-111111111111"
    token2 = "22222222-2222-2222-2222-222222222222"
    job_id = "33333333-3333-3333-3333-333333333333"

    job_data = {
        "job_id": job_id,
        "playlist_name": "Test Playlist.m3u",
        "tracks": [
            {
                "token": token1,
                "display_name": "Artist - Title 1.mp3",
                "status": "pending",
                "duration_seconds": 180.0,
                "format": "mp3",
                "tags": {"artist": "Artist", "title": "Title 1"},
            },
            {
                "token": token2,
                "display_name": "Artist - Title 2.flac",
                "status": "done",
                "duration_seconds": 240.0,
                "format": "flac",
                "tags": {"artist": "Artist", "title": "Title 2"},
            },
        ],
    }
    (job_dir / f"{job_id}.json").write_text(json.dumps(job_data), encoding="utf-8")

    # Match exact token
    track1 = store.get_track_by_token(token1)
    assert track1 is not None
    assert track1["display_name"] == "Artist - Title 1.mp3"
    assert track1["status"] == "pending"

    # Match second token
    track2 = store.get_track_by_token(token2)
    assert track2 is not None
    assert track2["format"] == "flac"

    # Non-existent token
    assert store.get_track_by_token("99999999-9999-9999-9999-999999999999") is None
    # Invalid token types
    assert store.get_track_by_token(None) is None
    assert store.get_track_by_token(123) is None


def test_read_track_metadata_job_store_fallback(tmp_path, monkeypatch):
    reg = FileRegistry(directory=tmp_path / "reg")
    reg.directory.mkdir()
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    store = JobStore(directory=job_dir)

    monkeypatch.setattr(inspection, "get_registry", lambda: reg)
    monkeypatch.setattr(inspection, "get_job_store", lambda: store)

    token = "44444444-4444-4444-4444-444444444444"
    job_id = "55555555-5555-5555-5555-555555555555"

    job_data = {
        "job_id": job_id,
        "playlist_name": "Favorites.m3u",
        "tracks": [
            {
                "token": token,
                "display_name": "01 - Jimmy Takeuchi - Drum.mp3",
                "status": "pending",
                "duration_seconds": 210.5,
                "format": "mp3",
                "tags": {"artist": "Jimmy Takeuchi", "title": "Drum"},
            }
        ],
    }
    (job_dir / f"{job_id}.json").write_text(json.dumps(job_data), encoding="utf-8")

    # Token is NOT in file registry, but IS in job store
    result = inspection.read_track_metadata(token)
    assert result["token"] == token
    assert result["display_name"] == "01 - Jimmy Takeuchi - Drum.mp3"
    assert result["duration_seconds"] == 210.5
    assert result["tags"]["artist"] == "Jimmy Takeuchi"
    assert "error" in result
    assert "file_path" not in result
    assert str(tmp_path) not in json.dumps(result)


def test_extract_filename_clues_job_store_fallback(tmp_path, monkeypatch):
    reg = FileRegistry(directory=tmp_path / "reg")
    reg.directory.mkdir()
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    store = JobStore(directory=job_dir)

    monkeypatch.setattr(inspection, "get_registry", lambda: reg)
    monkeypatch.setattr(inspection, "get_job_store", lambda: store)

    token = "66666666-6666-6666-6666-666666666666"
    job_id = "77777777-7777-7777-7777-777777777777"

    job_data = {
        "job_id": job_id,
        "playlist_name": "Test.m3u",
        "tracks": [
            {
                "token": token,
                "display_name": "03 - Jimmy Takeuchi - Drum Drum Drum (1970).mp3",
                "status": "pending",
            }
        ],
    }
    (job_dir / f"{job_id}.json").write_text(json.dumps(job_data), encoding="utf-8")

    clues = inspection.extract_filename_clues(token)
    assert clues["track_number_guess"] == 3
    assert clues["year_guess"] == "1970"
    assert any(
        c["artist"] == "Jimmy Takeuchi" for c in clues["artist_title_candidates"]
    )
    assert str(tmp_path) not in json.dumps(clues)


def test_get_batch_brief_with_fallback(tmp_path, monkeypatch):
    reg = FileRegistry(directory=tmp_path / "reg")
    reg.directory.mkdir()
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    store = JobStore(directory=job_dir)

    # 1. Registered file
    audio_file = tmp_path / "real_song.ogg"
    audio_file.write_bytes(b"\x00" * 32)
    reg_token = reg.register(str(audio_file))["token"]

    monkeypatch.setattr(
        inspection,
        "read_audio_metadata",
        lambda _p: {"duration_seconds": 120.0, "format": "ogg", "tags": {"title": "Real"}},
    )
    monkeypatch.setattr(inspection, "get_registry", lambda: reg)
    monkeypatch.setattr(inspection, "get_job_store", lambda: store)

    # 2. Fallback token (only in JobStore)
    job_token = "88888888-8888-8888-8888-888888888888"
    job_id = "99999999-9999-9999-9999-999999999999"
    job_data = {
        "job_id": job_id,
        "playlist_name": "List.m3u",
        "tracks": [
            {
                "token": job_token,
                "display_name": "02 - Artist - Track.mp3",
                "duration_seconds": 200.0,
                "format": "mp3",
                "tags": {"title": "Track"},
            }
        ],
    }
    (job_dir / f"{job_id}.json").write_text(json.dumps(job_data), encoding="utf-8")

    # 3. Completely unknown token
    unknown_token = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    briefs = inspection.get_batch_brief([reg_token, job_token, unknown_token])
    assert len(briefs) == 3

    # Check 1: Real registered file
    assert briefs[0]["token"] == reg_token
    assert briefs[0]["display_name"] == "real_song.ogg"
    assert briefs[0]["format"] == "ogg"

    # Check 2: Fallback from JobStore
    assert briefs[1]["token"] == job_token
    assert briefs[1]["display_name"] == "02 - Artist - Track.mp3"
    assert briefs[1]["format"] == "mp3"
    assert "note" in briefs[1]
    assert briefs[1]["filename_clues"]["track_number_guess"] == 2

    # Check 3: Unknown token
    assert briefs[2]["token"] == unknown_token
    assert briefs[2]["display_name"] is None
    assert briefs[2]["error_code"] == "E_UNKNOWN_TOKEN"

    # Path leak safety assertion
    assert str(tmp_path) not in json.dumps(briefs)
