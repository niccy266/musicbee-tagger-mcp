"""Tests for the secure token-based pipeline.

Verifies:
1. register_files returns tokens, never paths.
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


FAKE_DIFF = [{"field": "album", "old": None, "new": "Test Album"}]


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


def test_unknown_token_raises_key_error(registry):
    with pytest.raises(KeyError, match="Unknown token"):
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
               return_value={"changes": FAKE_DIFF}):
        result = staging.stage(
            absolute_path=tmp_audio,
            display_name=tmp_audio.name,
            proposed_tags={"title": "Test Title"},
        )
    assert "stage_id" in result
    assert "display_name" in result
    assert "message" in result
    # The absolute path must NOT appear anywhere in the returned dict
    result_str = json.dumps(result)
    assert str(tmp_audio.parent) not in result_str


def test_stage_manifest_written_to_disk(staging, tmp_audio):
    with patch("musicbee_tagger_mcp.staging.preview_tag_changes",
               return_value={"changes": FAKE_DIFF}):
        result = staging.stage(
            absolute_path=tmp_audio,
            display_name=tmp_audio.name,
            proposed_tags={"album": "Test Album"},
        )
    manifest_path = staging.staging_dir / f"{result['stage_id']}.json"
    assert manifest_path.exists(), "Manifest file must be written to disk"


def test_list_pending_no_paths(staging, tmp_audio):
    with patch("musicbee_tagger_mcp.staging.preview_tag_changes",
               return_value={"changes": FAKE_DIFF}):
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
    tool_names = [t for t in dir(server) if not t.startswith("_")]
    assert "apply_staged" not in tool_names
    assert "apply_tags" not in tool_names
    assert "apply_tags_to_file" not in tool_names
