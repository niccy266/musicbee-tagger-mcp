"""Interactive staged review controls and missing-file handling."""

from musicbee_tagger_mcp.apply_staged import cmd_apply_one
from musicbee_tagger_mcp.staged_apply import StagedChangeApplier
from musicbee_tagger_mcp.staging import StagingManager


def _make_stage(tmp_path, monkeypatch, name="track.mp3", manager=None):
    from musicbee_tagger_mcp import staging as staging_module

    audio = tmp_path / name
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"synthetic audio")
    monkeypatch.setattr(
        staging_module,
        "preview_tag_changes",
        lambda _path, tags: {
            "diff": {
                key: {"before": "old", "after": value, "changed": True}
                for key, value in tags.items()
            }
        },
    )
    manager = manager or StagingManager(tmp_path / "staged")
    stage = manager.stage(audio, name, {"title": "new"})
    return audio, manager, stage, StagedChangeApplier(manager.staging_dir)


def test_enter_applies_current_item(monkeypatch, tmp_path, capsys):
    _audio, manager, stage, applier = _make_stage(tmp_path, monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    monkeypatch.setattr(
        "musicbee_tagger_mcp.staged_apply.apply_tags_to_file",
        lambda *_args, **_kwargs: {"fields_written": ["title"], "backup_created": "x.bak"},
    )

    outcome = cmd_apply_one(applier, stage["stage_id"], False, False)

    assert outcome == "applied"
    assert manager.get(stage["stage_id"])["status"] == "applied"
    assert "Applied 1 field(s)" in capsys.readouterr().out


def test_n_marks_failed_and_removes_from_pending(monkeypatch, tmp_path):
    _audio, manager, stage, applier = _make_stage(tmp_path, monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    assert cmd_apply_one(applier, stage["stage_id"], False, False) == "failed"
    assert manager.list_pending() == []
    assert manager.get(stage["stage_id"])["status"] == "failed"


def test_a_defers_stage_to_end_of_pending_list(monkeypatch, tmp_path):
    _audio, manager, first, applier = _make_stage(tmp_path, monkeypatch, "first.mp3")
    _audio, _manager, second, _applier = _make_stage(
        tmp_path, monkeypatch, "second.mp3", manager=manager
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "a")

    assert cmd_apply_one(applier, first["stage_id"], False, False) == "deferred"
    pending = manager.list_pending()
    assert [entry["stage_id"] for entry in pending] == [
        second["stage_id"], first["stage_id"]
    ]
    assert pending[-1]["deferred"] is True


def test_q_leaves_current_item_pending(monkeypatch, tmp_path):
    _audio, manager, stage, applier = _make_stage(tmp_path, monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _prompt: "q")

    assert cmd_apply_one(applier, stage["stage_id"], False, False) == "quit"
    assert manager.list_pending()[0]["stage_id"] == stage["stage_id"]


def test_missing_audio_is_logged_archived_and_skipped(
    monkeypatch, tmp_path, caplog, capsys
):
    audio, manager, stage, applier = _make_stage(tmp_path, monkeypatch)
    audio.unlink()

    outcome = cmd_apply_one(applier, stage["stage_id"], False, False)

    assert outcome == "archived"
    assert manager.list_pending() == []
    assert manager.get(stage["stage_id"])["status"] == "archived"
    assert "Source audio file is missing" in caplog.text
    assert "source file not found" in capsys.readouterr().out


def test_missing_manifest_is_logged_and_skipped(tmp_path, caplog, capsys):
    applier = StagedChangeApplier(tmp_path / "staged")
    outcome = cmd_apply_one(
        applier, "5cf2f18c-cb3c-4dc2-98bb-52ea1160d33a", False, False
    )

    assert outcome == "missing_stage"
    assert "is missing; skipping it" in caplog.text
    assert "moving to the next item" in capsys.readouterr().out
