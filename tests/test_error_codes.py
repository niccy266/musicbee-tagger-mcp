"""Tests for the standardized MCP error code system.

Covers:
* Error codes map Python exception types to stable codes.
* Error dicts include ``error_code``, ``error``, and optional ``function``.
* No filesystem path leaks into error messages.
* ``extract_filename_clues`` reports filesystem access errors with its function name.
* All MCP tool error paths return path-free, code-labelled responses.
"""

import json
import re

import pytest

from musicbee_tagger_mcp.error_codes import (
    E_AUDIO_READ_FAILED,
    E_FILE_NOT_FOUND,
    E_INTERNAL,
    E_PARSE_ERROR,
    E_PERMISSION_DENIED,
    E_PROVIDER_FAILED,
    E_STAGING_FAILED,
    E_UNKNOWN_TOKEN,
    E_UNSUPPORTED_FORMAT,
    error_from_exception,
    make_error,
)


# ---------------------------------------------------------------------------
# make_error / error_from_exception
# ---------------------------------------------------------------------------

def test_make_error_includes_code_message_and_function():
    result = make_error(
        E_FILE_NOT_FOUND,
        "file not found",
        function="read_track_metadata",
    )
    assert result == {
        "error_code": E_FILE_NOT_FOUND,
        "error": "file not found",
        "function": "read_track_metadata",
    }


def test_make_error_without_function():
    result = make_error(E_INTERNAL, "internal error")
    assert result == {"error_code": E_INTERNAL, "error": "internal error"}
    assert "function" not in result


def test_error_from_exception_maps_types():
    assert error_from_exception(FileNotFoundError("nope"))["error_code"] == E_FILE_NOT_FOUND
    assert error_from_exception(PermissionError("nope"))["error_code"] == E_PERMISSION_DENIED
    assert error_from_exception(ValueError("nope"))["error_code"] == E_UNSUPPORTED_FORMAT
    assert error_from_exception(KeyError("nope"))["error_code"] == E_UNKNOWN_TOKEN
    assert error_from_exception(RuntimeError("nope"))["error_code"] == E_INTERNAL


def test_error_from_exception_includes_function():
    result = error_from_exception(
        PermissionError("denied"),
        function="extract_filename_clues",
    )
    assert result["error_code"] == E_PERMISSION_DENIED
    assert result["function"] == "extract_filename_clues"


# ---------------------------------------------------------------------------
# Path-free guarantee
# ---------------------------------------------------------------------------

def test_make_error_strips_windows_paths():
    result = make_error(
        E_FILE_NOT_FOUND,
        "could not open C:\\\\Music\\\\Artist\\\\track.flac",
        function="read_track_metadata",
    )
    assert "C:" not in result["error"]
    assert "Music" not in result["error"]
    assert "[path]" in result["error"]


def test_make_error_strips_posix_paths():
    result = make_error(
        E_FILE_NOT_FOUND,
        "could not open /home/user/Music/track.flac",
        function="read_track_metadata",
    )
    assert "/home" not in result["error"]
    assert "[path]" in result["error"]


def test_error_from_exception_strips_paths_from_messages():
    exc = FileNotFoundError("could not open K:\\\\Music\\\\track.flac")
    result = error_from_exception(exc, function="extract_filename_clues",
                                  default_message="could not open K:\\\\Music\\\\track.flac")
    assert "K:" not in result["error"]
    assert "Music" not in result["error"]
    assert "[path]" in result["error"]


# ---------------------------------------------------------------------------
# extract_filename_clues error reporting
# ---------------------------------------------------------------------------

def test_extract_filename_clues_unknown_token_returns_code_and_function(tmp_path, monkeypatch):
    from musicbee_tagger_mcp.file_registry import FileRegistry
    from musicbee_tagger_mcp.tools import inspection

    registry = FileRegistry(directory=tmp_path / "reg")
    registry.directory.mkdir()
    monkeypatch.setattr(inspection, "get_registry", lambda: registry)

    result = inspection.extract_filename_clues("not-a-real-token")

    assert result["error_code"] == E_UNKNOWN_TOKEN
    assert result["function"] == "extract_filename_clues"
    assert "error" in result


def test_extract_filename_clues_permission_error_reports_function_name(tmp_path, monkeypatch):
    from musicbee_tagger_mcp.file_registry import FileRegistry
    from musicbee_tagger_mcp.tools import inspection

    registry = FileRegistry(directory=tmp_path / "reg")
    registry.directory.mkdir()
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"\\x00" * 16)
    token = registry.register(str(audio))["token"]
    monkeypatch.setattr(inspection, "get_registry", lambda: registry)

    monkeypatch.setattr(
        inspection,
        "extract_clues_from_filename",
        lambda _name: (_ for _ in ()).throw(PermissionError("access denied")),
    )

    result = inspection.extract_filename_clues(token)

    assert result["error_code"] == E_PERMISSION_DENIED
    assert result["function"] == "extract_filename_clues"
    assert "access denied" in result["error"]
    # No path may appear in the response
    assert str(tmp_path) not in json.dumps(result)
    assert "song.flac" not in json.dumps(result)


# ---------------------------------------------------------------------------
# All error codes are stable strings
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", [
    E_UNKNOWN_TOKEN,
    E_FILE_NOT_FOUND,
    E_PERMISSION_DENIED,
    E_UNSUPPORTED_FORMAT,
    E_PARSE_ERROR,
    E_STAGING_FAILED,
    E_AUDIO_READ_FAILED,
    E_PROVIDER_FAILED,
    E_INTERNAL,
])
def test_error_codes_are_nonempty_strings(code):
    assert isinstance(code, str)
    assert code.startswith("E_")
    assert len(code) > 3