"""CLI-only application service tests."""

from unittest.mock import patch

from musicbee_tagger_mcp.staged_apply import StagedChangeApplier
from musicbee_tagger_mcp.staging import StagingManager


def test_cli_applier_marks_manifest_applied_without_exposing_path(tmp_path):
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
    }
    assert applier.load(staged["stage_id"])["applied"] is True
