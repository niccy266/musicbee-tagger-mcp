"""#47: registering the same file twice must not create a second token."""

from musicbee_tagger_mcp.file_registry import FileRegistry


def test_duplicate_registration_returns_same_token(tmp_path):
    registry = FileRegistry(directory=tmp_path / "registry")
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"ID3")
    first = registry.register(str(audio))
    assert first.get("already_registered") is None

    second = registry.register(str(audio))
    assert second["token"] == first["token"]
    assert second["already_registered"] is True
    assert len(registry.list_tokens()) == 1


def test_duplicate_detection_survives_restart(tmp_path):
    directory = tmp_path / "registry"
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"ID3")
    first = FileRegistry(directory=directory).register(str(audio))

    reopened = FileRegistry(directory=directory)
    second = reopened.register(str(audio))
    assert second["token"] == first["token"]
    assert second["already_registered"] is True
