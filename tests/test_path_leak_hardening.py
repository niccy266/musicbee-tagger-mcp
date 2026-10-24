"""Regression tests for the path-leak audit and the threat model decision.

Covers the remaining gaps from issue #2/#3:
- Missing/unreadable registered audio returns path-free MCP errors.
- Missing/unreadable playlist inputs return path-free errors.
- Windows-style absolute paths survive registry serialization round-trips.
- No MCP tool accepts or returns a filesystem path.
"""

import json

import pytest

from musicbee_tagger_mcp.file_registry import FileRegistry
from musicbee_tagger_mcp.tools.files import register_playlist
from musicbee_tagger_mcp.tools import inspection, tags


@pytest.fixture
def registry(tmp_path, monkeypatch):
    reg = FileRegistry(directory=tmp_path / "reg")
    reg.directory.mkdir()
    for mod in ("musicbee_tagger_mcp.file_registry",
                "musicbee_tagger_mcp.tools.files",
                "musicbee_tagger_mcp.tools.inspection",
                "musicbee_tagger_mcp.tools.tags"):
        monkeypatch.setattr(f"{mod}.get_registry", lambda: reg)
    return reg


def _m3u(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def test_missing_registered_audio_returns_path_free_error(registry, tmp_path):
    audio = tmp_path / "vanished.flac"
    audio.write_bytes(b"\x00")
    token = registry.register(str(audio))["token"]
    audio.unlink()
    result = inspection.read_track_metadata(token)
    assert "error" in result
    assert "that-vanished" not in json.dumps(result)
    assert "C:\\" not in json.dumps(result)


def test_batch_brief_handles_unreadable_audio(registry, tmp_path, monkeypatch):
    audio = tmp_path / "song.ogg"
    audio.write_bytes(b"\x00" * 8)
    token = registry.register(str(audio))["token"]
    monkeypatch.setattr(
        inspection, "read_audio_metadata",
        lambda _p: (_ for _ in ()).throw(RuntimeError(f"boom {audio}")),
    )
    briefs = inspection.get_batch_brief([token])
    assert briefs[0]["token"] == token
    assert "error" in briefs[0]
    assert str(tmp_path) not in json.dumps(briefs)


def test_missing_playlist_returns_path_free_error(registry):
    result = register_playlist(str(registry.__class__ and "definitely-not-here.m3u"))
    assert "error" in result
    assert "definitely-not-here" not in json.dumps(result)


def test_unreadable_playlist_entries_are_skipped_without_paths(registry, tmp_path):
    playlist = _m3u(tmp_path, "missing.m3u", ["C:\\Music\\nowhere.mp3", "# comment"])
    result = register_playlist(str(playlist))
    assert result["registered"] == []
    assert all("error" in e for e in result["skipped"])
    assert "nowhere" not in json.dumps(result)


def test_windows_absolute_path_survives_registry_round_trip(tmp_path):
    """A Windows-style absolute path survives disk persistence byte-for-byte."""
    from unittest.mock import patch
    reg = FileRegistry(directory=tmp_path / "reg")
    win_path = "K:\\Music\\Artist\\Album\\01 - Track.flac"
    token = "12345678-1234-5678-1234-567812345678"
    (tmp_path / "reg").mkdir()
    (tmp_path / "reg" / f"{token}.json").write_text(
        json.dumps({"token": token, "path": win_path}), encoding="utf-8"
    )
    with patch("pathlib.Path.is_absolute", return_value=True):
        entry = reg.resolve(token)
    assert str(entry) == win_path


def test_no_mcp_tool_takes_a_path_parameter():
    """No tool registered on the MCP server accepts a path-like parameter."""
    import inspect

    class FakeApp:
        def __init__(self):
            self.tools = []

        def tool(self, *a, **k):
            def deco(fn):
                self.tools.append(fn)
                return fn
            return deco

    from musicbee_tagger_mcp.tools import register_tools
    app = FakeApp()
    register_tools(app)

    path_words = ("path", "file", "playlist", "dir", "directory")
    for fn in app.tools:
        for pname in inspect.signature(fn).parameters:
            assert not any(w in pname.lower() for w in path_words), \
                f"{fn.__name__} exposes path-like parameter {pname!r}"
