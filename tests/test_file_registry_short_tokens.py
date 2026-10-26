"""Regression tests for short-token resolution in the file registry."""
import json
import uuid
from pathlib import Path

from musicbee_tagger_mcp.file_registry import FileRegistry


def test_resolve_accepts_unique_short_prefix(tmp_path):
    reg = FileRegistry(directory=tmp_path / "reg")
    reg.directory.mkdir()
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"\x00")
    token = reg.register(str(audio))["token"]

    assert reg.resolve(token[:6]) == reg.resolve(token)


def test_resolve_rejects_ambiguous_or_unknown_short_prefix(tmp_path):
    reg = FileRegistry(directory=tmp_path / "reg")
    reg.directory.mkdir()
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"\x00")
    reg.register(str(audio))

    # Too short to be treated as a prefix.
    try:
        reg.resolve("abc")
    except KeyError:
        pass
    else:
        raise AssertionError("short prefix should not resolve")

    # Unknown prefix.
    try:
        reg.resolve("zzzzzz")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown prefix should not resolve")
