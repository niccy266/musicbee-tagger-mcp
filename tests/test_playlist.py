import json

import pytest

from musicbee_tagger_mcp.file_registry import FileRegistry
from musicbee_tagger_mcp.playlist import parse_m3u_playlist


def test_parse_m3u_resolves_relative_entries_and_reports_skips(tmp_path):
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    track = music_dir / "track one.ogg"
    track.write_bytes(b"audio")

    playlist = tmp_path / "list.m3u8"
    playlist.write_text(
        "\ufeff#EXTM3U\n"
        "#EXTINF:120,Artist - Title\n"
        "Music/track one.ogg\n"
        f"{track}\n"
        "missing.mp3\n"
        "https://example.com/track.mp3\n"
        "notes.txt\n",
        encoding="utf-8",
    )

    entries = parse_m3u_playlist(str(playlist))

    assert entries == [
        (3, track, None),
        (4, track, None),
        (5, tmp_path / "missing.mp3", None),
        (6, None, "Remote playlist entries are not supported"),
        (7, None, "Unsupported audio format"),
    ]


def test_register_playlist_returns_tokens_without_paths(tmp_path, monkeypatch):
    from musicbee_tagger_mcp.tools import files as file_tools

    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    track = music_dir / "song.mp3"
    track.write_bytes(b"audio")
    playlist = tmp_path / "list.m3u"
    playlist.write_text("#EXTM3U\nMusic/song.mp3\nmissing.flac\n", encoding="utf-8")
    registry = FileRegistry()
    monkeypatch.setattr(file_tools, "get_registry", lambda: registry)

    result = file_tools.register_playlist(str(playlist))

    assert result["registered"][0]["line"] == 2
    assert result["registered"][0]["display_name"] == "song.mp3"
    assert registry.resolve(result["registered"][0]["token"]) == track.resolve()
    assert result["skipped"] == [{"line": 3, "error": "File not found"}]
    assert str(tmp_path) not in json.dumps(result)


def test_register_playlist_hides_playlist_path_on_error(tmp_path):
    from musicbee_tagger_mcp.tools.files import register_playlist

    missing_playlist = str(tmp_path / "private" / "missing.m3u")

    assert register_playlist(missing_playlist) == {"error": "Playlist not found"}
    unsupported_playlist = tmp_path / "private" / "list.txt"
    unsupported_playlist.parent.mkdir()
    unsupported_playlist.write_text("track.mp3", encoding="utf-8")
    assert register_playlist(str(unsupported_playlist)) == {
        "error": "Unsupported playlist format"
    }


def test_human_registration_cli_outputs_tokens_without_playlist_path(
    tmp_path, monkeypatch
):
    from io import StringIO

    from musicbee_tagger_mcp import register_playlist_cli
    from musicbee_tagger_mcp.file_registry import FileRegistry

    audio = tmp_path / "secret-folder" / "song.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"audio")
    playlist = tmp_path / "secret-folder" / "private-list.m3u"
    playlist.write_text("song.mp3\n", encoding="utf-8")
    registry = FileRegistry(tmp_path / "registered")
    monkeypatch.setattr(register_playlist_cli, "get_registry", lambda: registry)
    output = StringIO()

    result = register_playlist_cli.run(StringIO(f'"{playlist}"\n'), output)
    printed = output.getvalue()

    assert result == 0
    assert "playlist job" in printed  # prints a job id to hand to the agent
    assert "job id" in printed
    assert str(playlist) not in printed
    assert str(audio.parent) not in printed
    # Tokens stay in the private data dir — never printed, never sent over MCP.
    assert registry.list_tokens()[0]["token"] not in printed
    assert audio.name not in printed


def test_human_registration_cli_accepts_playlist_path_argument(
    tmp_path, monkeypatch, capsys
):
    import sys

    from musicbee_tagger_mcp import register_playlist_cli
    from musicbee_tagger_mcp.file_registry import FileRegistry

    audio = tmp_path / "secret-folder" / "song.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"audio")
    playlist = tmp_path / "secret-folder" / "Strange Tags.m3u"
    playlist.write_text("song.mp3\n", encoding="utf-8")
    registry = FileRegistry(tmp_path / "registered")
    monkeypatch.setattr(register_playlist_cli, "get_registry", lambda: registry)
    monkeypatch.setattr(sys, "argv", ["musicbee-tagger-register-playlist", str(playlist)])

    with pytest.raises(SystemExit) as exit_info:
        register_playlist_cli.main()
    printed = capsys.readouterr().out

    assert exit_info.value.code == 0
    assert "Playlist path (.m3u or .m3u8):" not in printed
    assert "playlist job" in printed
    assert str(playlist) not in printed
    assert str(audio.parent) not in printed
    assert registry.list_tokens()[0]["token"] not in printed
    assert audio.name not in printed


def test_human_registration_cli_never_echoes_failed_playlist_path(tmp_path):
    from io import StringIO

    from musicbee_tagger_mcp.register_playlist_cli import run

    playlist = tmp_path / "private-folder" / "missing.m3u"
    output = StringIO()

    result = run(StringIO(f"{playlist}\n"), output)

    assert result == 1
    assert "Playlist not found" in output.getvalue()
    assert str(playlist) not in output.getvalue()


def test_registration_cleanup_requires_confirmation(tmp_path, monkeypatch):
    from io import StringIO

    from musicbee_tagger_mcp import clear_registrations_cli

    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"audio")
    registry = FileRegistry(tmp_path / "registered")
    result = registry.register(str(audio))
    monkeypatch.setattr(clear_registrations_cli, "get_registry", lambda: registry)

    cancelled_output = StringIO()
    clear_registrations_cli.run(StringIO("NO\n"), cancelled_output)
    assert registry.is_registered(result["token"])

    confirmed_output = StringIO()
    clear_registrations_cli.run(StringIO("YES\n"), confirmed_output)
    assert not registry.is_registered(result["token"])
    assert "Removed 1 local file registration" in confirmed_output.getvalue()
    assert str(audio) not in confirmed_output.getvalue()


def test_parse_m3u_rejects_unsupported_playlist_extension(tmp_path):
    playlist = tmp_path / "list.txt"
    playlist.write_text("track.mp3", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported playlist format"):
        parse_m3u_playlist(str(playlist))


def test_parse_m3u_falls_back_to_windows_1252(tmp_path):
    track_name = "Beyoncé.mp3"
    playlist = tmp_path / "legacy.m3u"
    playlist.write_bytes(track_name.encode("cp1252"))

    entries = parse_m3u_playlist(str(playlist))

    assert entries == [(1, tmp_path / track_name, None)]
