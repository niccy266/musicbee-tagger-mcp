"""CLI-only application service tests."""

from unittest.mock import patch

from musicbee_tagger_mcp.stage_manifest_store import default_staging_dir
from musicbee_tagger_mcp.staged_apply import StagedChangeApplier
from musicbee_tagger_mcp.staging import StagingManager


def test_default_staging_dir_uses_configured_data_root(tmp_path, monkeypatch):
    """Use the configured private data root for staged manifests."""
    monkeypatch.setenv("MUSICBEE_TAGGER_DATA_DIR", str(tmp_path / "private-data"))

    assert default_staging_dir() == tmp_path / "private-data" / "staged"
    assert (tmp_path / "private-data" / "staged").is_dir()


def test_default_staging_dir_does_not_fall_back_on_permission_error(
    tmp_path, monkeypatch
):
    """Report an inaccessible configured data root without exposing its path."""
    monkeypatch.setenv("MUSICBEE_TAGGER_DATA_DIR", str(tmp_path / "private-data"))
    with patch(
        "musicbee_tagger_mcp.stage_manifest_store.Path.mkdir",
        side_effect=PermissionError("sensitive path"),
    ):
        try:
            default_staging_dir()
        except RuntimeError as exc:
            assert str(exc) == (
                "Unable to access the MusicBee Tagger MCP data directory; "
                "check MUSICBEE_TAGGER_DATA_DIR and local permissions."
            )
            assert "sensitive path" not in str(exc)
        else:
            raise AssertionError("Expected staging directory access to fail")


def test_cli_applier_marks_manifest_applied_without_exposing_path(tmp_path):
    """Apply a staged manifest through the user-only applier service."""
    audio = tmp_path / "track.ogg"
    audio.write_bytes(b"audio")
    staging_dir = tmp_path / "staged"
    staging_dir.mkdir()
    staging = StagingManager(staging_dir)
    with patch(
        "musicbee_tagger_mcp.staging.preview_tag_changes",
        return_value={
            "diff": {"title": {"before": "Old", "after": "New", "changed": True}}
        },
    ):
        staged = staging.stage(
            absolute_path=audio,
            display_name=audio.name,
            proposed_tags={"title": "New"},
        )

    applier = StagedChangeApplier(staging.staging_dir)
    with patch(
        "musicbee_tagger_mcp.staged_apply.apply_tags_to_file",
        return_value={"fields_written": ["title"], "backup_created": "track.ogg.bak"},
    ) as write_audio:
        result = applier.apply(staged["stage_id"])

    write_audio.assert_called_once_with(str(audio), {"title": "New"}, create_backup=True)
    assert result == {
        "status": "applied",
        "stage_id": staged["stage_id"],
        "display_name": audio.name,
        "fields_written": ["title"],
        "backup_created": True,
        "backup_path": "track.ogg.bak",
    }
    assert applier.load(staged["stage_id"])["applied"] is True
