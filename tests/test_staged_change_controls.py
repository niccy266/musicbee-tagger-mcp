"""Agent-safe inspection, amendment, and withdrawal of staged proposals."""

import json

import pytest

from musicbee_tagger_mcp.staging import StagingManager


def _preview(_path, proposed_tags):
    current = {"artist": "Original Artist", "title": "Original Title"}
    return {
        "diff": {
            field: {
                "before": current.get(field),
                "after": value,
                "changed": str(current.get(field) or "") != str(value or ""),
            }
            for field, value in proposed_tags.items()
        }
    }


def _stage(tmp_path, monkeypatch):
    from musicbee_tagger_mcp import staging as staging_module

    audio_file = tmp_path / "track.mp3"
    audio_file.write_bytes(b"synthetic audio placeholder")
    monkeypatch.setattr(staging_module, "preview_tag_changes", _preview)
    monkeypatch.setattr(
        staging_module,
        "read_audio_metadata",
        lambda _path: {
            "tags": {"artist": "Original Artist", "title": "Original Title"}
        },
    )
    manager = StagingManager(tmp_path / "staged")
    result = manager.stage(
        audio_file,
        audio_file.name,
        {"title": "Incorrect Title"},
        mb_recording_id="recording-id",
        notes="Filename split is only a clue; title verified against release tracklist.",
    )
    return manager, result, audio_file


def test_get_staged_change_returns_review_context_without_paths(tmp_path, monkeypatch):
    manager, staged, audio_file = _stage(tmp_path, monkeypatch)
    manifest = manager.store.load(staged["stage_id"])
    manifest["notes"] += f" Avoid exposing source {audio_file}."
    manager.store.save(manifest)

    result = manager.get(staged["stage_id"])

    assert result["status"] == "pending"
    assert result["revision"] == 1
    assert result["notes"].startswith("Filename split")
    assert result["current_tags"]["artist"] == "Original Artist"
    assert "absolute_path" not in result
    assert "recording-id" in json.dumps(result)
    assert str(audio_file) not in json.dumps(result)
    assert "(local path omitted)" in result["notes"]


def test_amend_rechecks_diff_records_reason_and_rejects_stale_revision(
    tmp_path, monkeypatch
):
    manager, staged, audio_file = _stage(tmp_path, monkeypatch)

    result = manager.amend(
        staged["stage_id"],
        expected_revision=1,
        new_tags={"title": "Verified Title"},
        reason="Matched the MusicBrainz recording and release tracklist.",
        mb_recording_id="8f488e3a-ef97-4c17-a495-bc1f7ca5bc73",
    )

    assert result["revision"] == 2
    assert result["diff_summary"] == [{
        "field": "title",
        "old": "Original Title",
        "new": "Verified Title",
    }]
    manifest = manager.store.load(staged["stage_id"])
    assert manifest["proposed_tags"]["title"] == "Verified Title"
    assert manifest["mb_recording_id"] == "8f488e3a-ef97-4c17-a495-bc1f7ca5bc73"
    assert manifest["history"][1]["reason"].startswith("Matched")
    assert str(audio_file) not in json.dumps(result)
    with pytest.raises(ValueError, match="revision changed"):
        manager.withdraw(
            staged["stage_id"], 1, "Superseded by the corrected review."
        )


def test_amend_can_remove_one_field_and_keep_other_changes(tmp_path, monkeypatch):
    from musicbee_tagger_mcp import staging as staging_module

    audio_file = tmp_path / "track.mp3"
    audio_file.write_bytes(b"synthetic audio placeholder")
    monkeypatch.setattr(staging_module, "preview_tag_changes", _preview)
    manager = StagingManager(tmp_path / "staged")
    staged = manager.stage(
        audio_file,
        audio_file.name,
        {"artist": "Wrong Artist", "title": "Corrected Title"},
    )

    result = manager.amend(
        staged["stage_id"],
        expected_revision=1,
        new_tags={},
        remove_fields=["artist"],
        reason="The filename split was wrong; artist remains unverified.",
    )

    assert result["diff_summary"] == [{
        "field": "title",
        "old": "Original Title",
        "new": "Corrected Title",
    }]
    manifest = manager.store.load(staged["stage_id"])
    assert "artist" not in manifest["proposed_tags"]
    assert manifest["history"][0]["fields"] == ["removed:artist"]


def test_withdraw_is_auditable_and_blocks_apply(tmp_path, monkeypatch):
    manager, staged, _audio_file = _stage(tmp_path, monkeypatch)
    result = manager.withdraw(
        staged["stage_id"], 1, "Release identity could not be corroborated."
    )
    from musicbee_tagger_mcp.staged_apply import StagedChangeApplier

    def fail_audio_write(*_args, **_kwargs):
        raise AssertionError("A withdrawn stage must not write audio.")

    monkeypatch.setattr(
        "musicbee_tagger_mcp.staged_apply.apply_tags_to_file", fail_audio_write
    )
    applier = StagedChangeApplier(manager.staging_dir)
    assert result["status"] == "withdrawn"
    assert manager.list_pending() == []
    assert manager.get(staged["stage_id"])["status"] == "withdrawn"
    assert applier.apply(staged["stage_id"])["status"] == "withdrawn"


def test_amend_rejects_unknown_fields_empty_values_and_local_paths(tmp_path, monkeypatch):
    manager, staged, _audio_file = _stage(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="Unsupported tag field"):
        manager.amend(staged["stage_id"], 1, {"path": "x"}, "Invalid field.")
    with pytest.raises(ValueError, match="non-empty"):
        manager.amend(staged["stage_id"], 1, {"title": None}, "Empty tag.")
    with pytest.raises(ValueError, match="local filesystem path"):
        manager.amend(
            staged["stage_id"], 1, {"title": r"K:\\Music\\secret.mp3"},
            "Do not leak local paths.",
        )
