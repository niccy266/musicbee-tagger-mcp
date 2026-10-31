"""Tests for the secure token-based pipeline.

Verifies:
1. The local registry returns tokens, never paths, and persists registrations.
2. Unregistered tokens raise KeyError (not silently pass).
3. stage_tag_changes returns a stage_id, never a path.
4. list_staged_changes never exposes paths.
5. apply_staged is not importable as an MCP tool from server.
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from musicbee_tagger_mcp.file_registry import FileRegistry
from musicbee_tagger_mcp.staging import StagingManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry():
    return FileRegistry()


@pytest.fixture
def tmp_audio(tmp_path):
    """A file that exists on disk — content irrelevant for registry/staging tests."""
    f = tmp_path / "test_track.ogg"
    f.write_bytes(b"\x00" * 64)
    return f


@pytest.fixture
def staging(tmp_path):
    staging_dir = tmp_path / "staged"
    staging_dir.mkdir()
    return StagingManager(staging_dir=staging_dir)


FAKE_PREVIEW_DIFF = {
    "album": {"before": None, "after": "Test Album", "changed": True},
    "artist": {"before": "Test Artist", "after": "Test Artist", "changed": False},
}


# ---------------------------------------------------------------------------
# FileRegistry tests
# ---------------------------------------------------------------------------

def test_register_returns_token_not_path(registry, tmp_audio):
    result = registry.register(str(tmp_audio))
    assert "token" in result
    assert "display_name" in result
    # display_name must be just the filename, never a directory path
    assert os.sep not in result["display_name"]
    assert str(tmp_audio.parent) not in result["display_name"]


def test_register_display_name_is_filename_only(registry, tmp_audio):
    result = registry.register(str(tmp_audio))
    assert result["display_name"] == tmp_audio.name


def test_resolve_returns_path_internally(registry, tmp_audio):
    result = registry.register(str(tmp_audio))
    resolved = registry.resolve(result["token"])
    assert resolved == tmp_audio.resolve()


def test_persistent_registry_resolves_token_after_restart(tmp_path, tmp_audio):
    data_directory = tmp_path / "registered"
    first_process_registry = FileRegistry(data_directory)

    result = first_process_registry.register(str(tmp_audio))
    restarted_process_registry = FileRegistry(data_directory)

    assert restarted_process_registry.resolve(result["token"]) == tmp_audio.resolve()
    assert restarted_process_registry.list_tokens() == [{
        "token": result["token"],
        "display_name": tmp_audio.name,
    }]
    assert str(tmp_audio) not in json.dumps(result)
    assert str(tmp_audio) not in json.dumps(restarted_process_registry.list_tokens())


def test_batch_brief_sanitizes_metadata_errors(tmp_path, tmp_audio, monkeypatch):
    from musicbee_tagger_mcp.tools import inspection

    registry = FileRegistry()
    token = registry.register(str(tmp_audio))["token"]
    monkeypatch.setattr(inspection, "get_registry", lambda: registry)

    def fail_read(path):
        raise RuntimeError(f"failed to read {path}")

    monkeypatch.setattr(
        inspection, "read_audio_metadata", fail_read
    )

    result = inspection.get_batch_brief([token])

    assert result == [{
        "token": token,
        "error_code": "E_INTERNAL",
        "error": "internal error",
        "function": "get_batch_brief",
    }]
    assert str(tmp_path) not in json.dumps(result)


def test_preview_errors_do_not_expose_registered_paths(tmp_audio, monkeypatch):
    from musicbee_tagger_mcp.tools import tags

    registry = FileRegistry()
    token = registry.register(str(tmp_audio))["token"]
    monkeypatch.setattr(tags, "get_registry", lambda: registry)

    def fail_preview(path, new_tags):
        raise RuntimeError(f"failed to preview {path}")

    monkeypatch.setattr(tags, "preview_tag_changes", fail_preview)

    result = tags.preview_tags(token, {"title": "New title"})

    assert result == {
        "error_code": "E_AUDIO_READ_FAILED",
        "error": "access denied by filesystem",
        "function": "preview_tags",
    }
    assert str(tmp_audio.parent) not in json.dumps(result)


def test_stage_errors_do_not_expose_registered_paths(tmp_audio, monkeypatch):
    from musicbee_tagger_mcp.tools import tags

    registry = FileRegistry()
    token = registry.register(str(tmp_audio))["token"]
    monkeypatch.setattr(tags, "get_registry", lambda: registry)

    class FailedStageManager:
        def stage(self, **kwargs):
            raise RuntimeError(f"failed to stage {kwargs['absolute_path']}")

    monkeypatch.setattr(
        tags, "get_staging_manager", lambda: FailedStageManager()
    )

    result = tags.stage_tag_changes(token, {"title": "New title"})

    assert result == {
        "error_code": "E_STAGING_FAILED",
        "error": "unable to stage tag changes",
        "function": "stage_tag_changes",
    }
    assert str(tmp_audio.parent) not in json.dumps(result)


def test_unknown_token_raises_key_error(registry):
    with pytest.raises(KeyError, match="Unknown file token"):
        registry.resolve("not-a-real-token")


def test_nonexistent_file_raises_file_not_found(registry, tmp_path):
    with pytest.raises(FileNotFoundError):
        registry.register(str(tmp_path / "ghost.mp3"))


def test_list_tokens_no_paths(registry, tmp_audio):
    registry.register(str(tmp_audio))
    listing = registry.list_tokens()
    for entry in listing:
        assert "token" in entry
        assert "display_name" in entry
        assert os.sep not in entry["display_name"]


def test_revoke_removes_token(registry, tmp_audio):
    result = registry.register(str(tmp_audio))
    token = result["token"]
    registry.revoke(token)
    with pytest.raises(KeyError):
        registry.resolve(token)


# ---------------------------------------------------------------------------
# StagingManager tests (preview_tag_changes mocked — no real audio needed)
# ---------------------------------------------------------------------------

def test_stage_returns_stage_id_not_path(staging, tmp_audio):
    with patch("musicbee_tagger_mcp.staging.preview_tag_changes",
               return_value={"diff": FAKE_PREVIEW_DIFF}):
        result = staging.stage(
            absolute_path=tmp_audio,
            display_name=tmp_audio.name,
            proposed_tags={"title": "Test Title"},
        )
    assert "stage_id" in result
    assert "display_name" in result
    assert "message" in result
    assert result["diff_summary"] == [
        {"field": "album", "old": None, "new": "Test Album"}
    ]
    # The absolute path must NOT appear anywhere in the returned dict
    result_str = json.dumps(result)
    assert str(tmp_audio.parent) not in result_str


def test_stage_manifest_written_to_disk(staging, tmp_audio):
    with patch("musicbee_tagger_mcp.staging.preview_tag_changes",
               return_value={"diff": FAKE_PREVIEW_DIFF}):
        result = staging.stage(
            absolute_path=tmp_audio,
            display_name=tmp_audio.name,
            proposed_tags={"album": "Test Album"},
        )
    manifest_path = staging.staging_dir / f"{result['stage_id']}.json"
    assert manifest_path.exists(), "Manifest file must be written to disk"


def test_list_pending_no_paths(staging, tmp_audio):
    with patch("musicbee_tagger_mcp.staging.preview_tag_changes",
               return_value={"diff": FAKE_PREVIEW_DIFF}):
        staging.stage(
            absolute_path=tmp_audio,
            display_name=tmp_audio.name,
            proposed_tags={"year": "1965"},
        )
    pending = staging.list_pending()
    assert len(pending) >= 1
    for entry in pending:
        assert str(tmp_audio.parent) not in json.dumps(entry), \
            "list_pending() must never expose the absolute path"


# ---------------------------------------------------------------------------
# Server surface test
# ---------------------------------------------------------------------------

def test_apply_staged_not_in_mcp_server():
    """apply_staged / apply_tags must NOT be registered as MCP tools."""
    import musicbee_tagger_mcp.server as server
    from musicbee_tagger_mcp.server import app

    tool_names = [t for t in dir(server) if not t.startswith("_")]
    registered_tool_names = set(app._tool_manager._tools)
    assert "apply_staged" not in tool_names
    assert "apply_tags" not in tool_names
    assert "apply_tags_to_file" not in tool_names
    assert "apply_tags_to_file" not in registered_tool_names
    assert registered_tool_names == {
        "next_batch",
        "preview_batch",
        "complete_batch",
        "release_batch",
        "job_status",
        "list_jobs",
        "read_track_metadata",
        "extract_filename_clues",
        "get_batch_brief",
        "resolve_track_token",
        "get_release_tracklist",
        "identify_acrcloud",
        "repair_mojibake",
        "search_canonical_release",
        "verify_mbid",
        "enqueue_batch_operation",
        "list_batch_operations",
        "update_batch_operation",
        "preview_tags",
        "web_search",
        "stage_tag_changes",
        "list_staged_changes",
        "get_staged_change",
        "amend_staged_changes",
        "withdraw_staged_change",
        "propose_artist_split",
        "search_musicbrainz_artist",
        "verify_artists_on_recording",
        "flag_suspicious_artists",
    }
    # Registration is CLI-only (musicbee-tagger-register-playlist creates the
    # job locally). No MCP tool accepts a path or location of any kind.
    assert "register_files" not in registered_tool_names
