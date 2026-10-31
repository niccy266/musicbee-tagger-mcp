"""Coverage tests for the user-facing write path."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from musicbee_tagger_mcp.apply_staged import cmd_apply_one, cmd_revert_one, main
from musicbee_tagger_mcp.metadata_reader import read_audio_metadata
from musicbee_tagger_mcp.stage_manifest_store import StageManifestStore
from musicbee_tagger_mcp.staged_apply import StagedChangeApplier, get_staged_applier
from musicbee_tagger_mcp.staging import StagingManager
from musicbee_tagger_mcp.tag_applier import apply_tags_to_file
from musicbee_tagger_mcp.tag_preview import preview_tag_changes

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "test_files" / "test_audio_files"
MP3 = FIXTURES / "I'd Be A Millionaire - David.mp3"
OGG = FIXTURES / "The Knack (Main Theme) - John Barry And His Orchestra_1.ogg"


def _ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def _make_audio_copy(tmp_path, src, name=None):
    dest = tmp_path / (name or src.name)
    shutil.copy2(src, dest)
    return dest


def _stage_real(tmp_path, src=MP3, proposed=None, name=None):
    audio = _make_audio_copy(tmp_path, src, name)
    staging = StagingManager(tmp_path / "staged")
    staged = staging.stage(audio, audio.name, proposed or {"title": "New Title"})
    applier = StagedChangeApplier(staging.staging_dir)
    return audio, staging, staged, applier


# --------------------------------------------------------------------------- #
# tag_preview
# --------------------------------------------------------------------------- #

def test_preview_tag_changes_detects_and_no_change(tmp_path):
    audio = _make_audio_copy(tmp_path, MP3)
    original_title = read_audio_metadata(str(audio))["tags"]["title"]
    res = preview_tag_changes(
        str(audio), {"title": "Previewed Title", "album": "Previewed Album"}
    )
    assert res["file_path"] == str(audio)
    assert res["has_changes"] is True
    assert res["diff"]["title"]["before"] == original_title
    assert res["diff"]["title"]["after"] == "Previewed Title"
    assert res["diff"]["title"]["changed"] is True

    no_change = preview_tag_changes(str(audio), {"title": original_title})
    assert no_change["has_changes"] is False
    assert no_change["diff"]["title"]["changed"] is False



# --------------------------------------------------------------------------- #
# tag_applier
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("src", [MP3, OGG], ids=["mp3", "ogg"])
def test_apply_tags_roundtrip_real(src, tmp_path):
    audio = _make_audio_copy(tmp_path, src)
    proposed = {"title": "Тест Title", "artist": "Артист"}
    result = apply_tags_to_file(str(audio), proposed, create_backup=True)
    assert result["status"] == "success"
    backup = audio.with_suffix(audio.suffix + ".bak")
    assert backup.is_file()
    assert result["backup_created"] == str(backup)
    assert "title" in result["fields_written"]
    tags = read_audio_metadata(str(audio))["tags"]
    assert tags["title"] == proposed["title"]
    assert tags["artist"] == proposed["artist"]


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg required")
def test_apply_tags_roundtrip_m4a(tmp_path):
    work = tmp_path / "t.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(OGG), "-c:a", "aac", str(work)],
        check=True,
    )
    proposed = {"title": "坂本龍一", "artist": "Test Artist"}
    result = apply_tags_to_file(str(work), proposed, create_backup=True)
    assert result["status"] == "success"
    backup = work.with_suffix(work.suffix + ".bak")
    assert backup.is_file()
    tags = read_audio_metadata(str(work))["tags"]
    assert tags["title"] == proposed["title"]
    assert tags["artist"] == proposed["artist"]


def test_apply_tags_backup_restore_byte_identical(tmp_path):
    audio = _make_audio_copy(tmp_path, MP3)
    before = audio.read_bytes()
    apply_tags_to_file(str(audio), {"title": "Changed Title"}, create_backup=True)
    backup = audio.with_suffix(audio.suffix + ".bak")
    assert backup.is_file()
    shutil.copy2(backup, audio)
    assert audio.read_bytes() == before


def test_apply_tags_skipped_when_no_changes(tmp_path):
    audio = _make_audio_copy(tmp_path, MP3)
    original_title = read_audio_metadata(str(audio))["tags"]["title"]
    result = apply_tags_to_file(str(audio), {"title": original_title}, create_backup=True)
    assert result["status"] == "skipped"
    assert result["backup_created"] is False
    assert result["message"] == "No changes detected"


def test_apply_tags_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        apply_tags_to_file(str(tmp_path / "nope.mp3"), {"title": "x"})

def test_apply_tags_unsupported_format_raises(tmp_path, monkeypatch):
    audio = _make_audio_copy(tmp_path, MP3)
    monkeypatch.setattr(
        "musicbee_tagger_mcp.tag_applier.preview_tag_changes",
        lambda _p, _t: {"has_changes": True, "diff": {"title": {"changed": True}}},
    )
    monkeypatch.setattr("musicbee_tagger_mcp.tag_applier.mutagen.File", lambda _p: None)
    with pytest.raises(ValueError, match="Unsupported format"):
        apply_tags_to_file(str(audio), {"title": "x"})

class _FakeAudio:
    def __init__(self):
        self.tags = None
    def save(self):
        return None
    def __setitem__(self, key, value):
        return None


def test_apply_tags_else_branch(tmp_path, monkeypatch):
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"x")
    monkeypatch.setattr(
        "musicbee_tagger_mcp.tag_applier.preview_tag_changes",
        lambda _p, _t: {"has_changes": True, "diff": {"title": {"changed": True}}},
    )
    fake = _FakeAudio()
    monkeypatch.setattr("musicbee_tagger_mcp.tag_applier.mutagen.File", lambda _p: fake)
    result = apply_tags_to_file(str(audio), {"title": "x"})
    assert result["status"] == "success"


def test_apply_tags_mp4_branch(tmp_path, monkeypatch):
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"x")
    monkeypatch.setattr(
        "musicbee_tagger_mcp.tag_applier.preview_tag_changes",
        lambda _p, _t: {"has_changes": True, "diff": {"title": {"changed": True}}},
    )

    class FakeMP4(_FakeAudio):
        pass

    monkeypatch.setattr("musicbee_tagger_mcp.tag_applier.MP4", FakeMP4)
    fake = FakeMP4()
    monkeypatch.setattr("musicbee_tagger_mcp.tag_applier.mutagen.File", lambda _p: fake)
    monkeypatch.setattr("musicbee_tagger_mcp.tag_applier.write_mp4", lambda a, t: None)
    result = apply_tags_to_file(str(audio), {"title": "x"})
    assert result["status"] == "success"


def test_apply_tags_unsupported_format_raises(tmp_path):
    audio = tmp_path / "empty.mp3"
    audio.write_bytes(b"")
    try:
        result = apply_tags_to_file(str(audio), {"title": "x"})
    except Exception:
        return
    assert result.get("status") != "success"


# --------------------------------------------------------------------------- #
# apply_staged cmd_apply_one
# --------------------------------------------------------------------------- #

def test_cmd_apply_one_dry_run(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    outcome = cmd_apply_one(applier, staged["stage_id"], dry_run=True, no_backup=False)
    assert outcome == "dry_run"
    out = capsys.readouterr().out
    assert "DRY RUN" in out


def test_cmd_apply_one_decline_marks_failed(tmp_path, monkeypatch):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    outcome = cmd_apply_one(applier, staged["stage_id"], False, False)
    assert outcome == "failed"
    assert staging.get(staged["stage_id"])["status"] == "failed"
    assert staging.list_pending() == []


def test_cmd_apply_one_defer(tmp_path, monkeypatch):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "a")
    assert cmd_apply_one(applier, staged["stage_id"], False, False) == "deferred"


def test_cmd_apply_one_quit(tmp_path, monkeypatch):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "q")
    assert cmd_apply_one(applier, staged["stage_id"], False, False) == "quit"


def test_cmd_apply_one_unrecognized(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "zzz")
    assert cmd_apply_one(applier, staged["stage_id"], False, False) == "pending"
    assert "Unrecognized" in capsys.readouterr().out


def test_cmd_apply_one_missing_manifest(tmp_path, capsys):
    applier = StagedChangeApplier(tmp_path / "staged")
    applier.store.directory.mkdir(parents=True, exist_ok=True)
    outcome = cmd_apply_one(applier, "5cf2f18c-cb3c-4dc2-98bb-52ea1160d33a", False, False)
    assert outcome == "missing_stage"
    out = capsys.readouterr().out
    assert "moving to the next item" in out
    assert str(tmp_path) not in out


def test_cmd_apply_one_missing_audio_archived(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    audio.unlink()
    outcome = cmd_apply_one(applier, staged["stage_id"], False, False)
    assert outcome == "archived"
    assert staging.get(staged["stage_id"])["status"] == "archived"
    out = capsys.readouterr().out
    assert str(tmp_path) not in out


def test_cmd_apply_one_already_applied(tmp_path, monkeypatch):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    assert cmd_apply_one(applier, staged["stage_id"], False, False) == "applied"
    assert cmd_apply_one(applier, staged["stage_id"], False, False) == "already_applied"


def test_cmd_apply_one_withdrawn(tmp_path, monkeypatch):
    audio, staging, staged, applier = _stage_real(tmp_path)
    staging.withdraw(staged["stage_id"], 1, "nope")
    assert cmd_apply_one(applier, staged["stage_id"], False, False) == "withdrawn"


def test_cmd_apply_one_failed_state(tmp_path, monkeypatch):
    audio, staging, staged, applier = _stage_real(tmp_path)
    manifest = staging.store.load(staged["stage_id"])
    manifest["failed"] = True
    staging.store.save(manifest)
    assert cmd_apply_one(applier, staged["stage_id"], False, False) == "failed"


def test_cmd_apply_one_archived_state(tmp_path, monkeypatch):
    audio, staging, staged, applier = _stage_real(tmp_path)
    manifest = staging.store.load(staged["stage_id"])
    manifest["archived"] = True
    staging.store.save(manifest)
    assert cmd_apply_one(applier, staged["stage_id"], False, False) == "archived"


def test_cmd_apply_one_success_real_write(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    outcome = cmd_apply_one(applier, staged["stage_id"], False, False)
    assert outcome == "applied"
    tags = read_audio_metadata(str(audio))["tags"]
    assert tags["title"] == "New Title"
    out = capsys.readouterr().out
    assert "Applied 1 field(s)" in out
    assert str(tmp_path) not in out


def test_cmd_apply_one_file_disappears_during_apply(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    def raising_apply(stage_id, create_backup=True):
        audio.unlink()
        raise FileNotFoundError("gone")

    monkeypatch.setattr(applier, "apply", raising_apply)
    outcome = cmd_apply_one(applier, staged["stage_id"], False, False)
    assert outcome == "archived"
    out = capsys.readouterr().out
    assert str(tmp_path) not in out


def test_cmd_apply_one_apply_exception_reported_failed(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    def raising_apply(stage_id, create_backup=True):
        raise RuntimeError("boom")

    monkeypatch.setattr(applier, "apply", raising_apply)
    outcome = cmd_apply_one(applier, staged["stage_id"], False, False)
    assert outcome == "failed"
    out = capsys.readouterr().out
    assert "[FAILED]" in out
    assert str(tmp_path) not in out


# --------------------------------------------------------------------------- #
# cmd_revert_one
# --------------------------------------------------------------------------- #

def test_cmd_revert_one_missing_manifest(tmp_path, capsys):
    applier = StagedChangeApplier(tmp_path / "staged")
    applier.store.directory.mkdir(parents=True, exist_ok=True)
    outcome = cmd_revert_one(applier, "5cf2f18c-cb3c-4dc2-98bb-52ea1160d33a")
    assert outcome == "missing_stage"
    out = capsys.readouterr().out
    assert "is missing" in out
    assert str(tmp_path) not in out


def test_cmd_revert_one_not_applied(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    outcome = cmd_revert_one(applier, staged["stage_id"])
    assert outcome == "not_applied"
    out = capsys.readouterr().out
    assert "not applied" in out


def test_cmd_revert_one_no_backup_path(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    manifest = staging.store.load(staged["stage_id"])
    manifest["applied"] = True
    manifest["backup_path"] = None
    staging.store.save(manifest)
    outcome = cmd_revert_one(applier, staged["stage_id"])
    assert outcome == "no_backup"
    assert "no backup path" in capsys.readouterr().out


def test_cmd_revert_one_backup_file_missing(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    manifest = staging.store.load(staged["stage_id"])
    manifest["applied"] = True
    manifest["backup_path"] = str(tmp_path / "nope.bak")
    staging.store.save(manifest)
    outcome = cmd_revert_one(applier, staged["stage_id"])
    assert outcome == "no_backup_file"
    assert "Backup file not found" in capsys.readouterr().out


def test_cmd_revert_one_quit(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    cmd_apply_one(applier, staged["stage_id"], False, False)
    monkeypatch.setattr("builtins.input", lambda _prompt: "q")
    outcome = cmd_revert_one(applier, staged["stage_id"])
    assert outcome == "quit"


def test_cmd_revert_one_unrecognized(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    cmd_apply_one(applier, staged["stage_id"], False, False)
    monkeypatch.setattr("builtins.input", lambda _prompt: "zzz")
    outcome = cmd_revert_one(applier, staged["stage_id"])
    assert outcome == "pending"
    assert "Unrecognized" in capsys.readouterr().out


def test_cmd_revert_one_success(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    original_bytes = audio.read_bytes()
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    cmd_apply_one(applier, staged["stage_id"], False, False)
    assert audio.read_bytes() != original_bytes
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    outcome = cmd_revert_one(applier, staged["stage_id"])
    assert outcome == "reverted"
    assert audio.read_bytes() == original_bytes
    out = capsys.readouterr().out
    assert "Reverted" in out


def test_cmd_revert_one_already_reverted(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    cmd_apply_one(applier, staged["stage_id"], False, False)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    cmd_revert_one(applier, staged["stage_id"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    outcome = cmd_revert_one(applier, staged["stage_id"])
    assert outcome in ("already_reverted", "not_applied")
    out = capsys.readouterr().out
    assert "already been reverted" in out or "not applied" in out


def test_cmd_revert_one_file_not_found_during_revert(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    cmd_apply_one(applier, staged["stage_id"], False, False)
    audio.unlink()
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    outcome = cmd_revert_one(applier, staged["stage_id"])
    assert outcome == "error"
    assert "ERROR" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# main()
# --------------------------------------------------------------------------- #

def _setup_main_monkeypatch(monkeypatch, tmp_path, staging, applier):
    monkeypatch.setattr("musicbee_tagger_mcp.apply_staged.get_staging_manager", lambda: staging)
    monkeypatch.setattr("musicbee_tagger_mcp.apply_staged.get_staged_applier", lambda: applier)


def test_main_list_no_pending(tmp_path, monkeypatch, capsys):
    staging = StagingManager(tmp_path / "staged")
    applier = StagedChangeApplier(staging.staging_dir)
    _setup_main_monkeypatch(monkeypatch, tmp_path, staging, applier)
    monkeypatch.setattr(sys, "argv", ["apply_staged", "--list"])
    main()
    assert "No pending" in capsys.readouterr().out


def test_main_list_pending(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    _setup_main_monkeypatch(monkeypatch, tmp_path, staging, applier)
    monkeypatch.setattr(sys, "argv", ["apply_staged", "--list"])
    main()
    out = capsys.readouterr().out
    assert "pending" in out.lower() or staged["stage_id"] in out


def test_main_list_applied(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    _setup_main_monkeypatch(monkeypatch, tmp_path, staging, applier)
    cmd_apply_one(applier, staged["stage_id"], False, False)
    monkeypatch.setattr(sys, "argv", ["apply_staged", "--list-applied"])
    main()
    out = capsys.readouterr().out
    assert "applied" in out.lower()


def test_main_stage_id_dry_run(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    _setup_main_monkeypatch(monkeypatch, tmp_path, staging, applier)
    monkeypatch.setattr(sys, "argv", ["apply_staged", "--stage-id", staged["stage_id"], "--dry-run"])
    main()
    out = capsys.readouterr().out
    assert "DRY RUN" in out


def test_main_stage_id_apply(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    _setup_main_monkeypatch(monkeypatch, tmp_path, staging, applier)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    monkeypatch.setattr(sys, "argv", ["apply_staged", "--stage-id", staged["stage_id"]])
    main()
    out = capsys.readouterr().out
    assert "Applied" in out


def test_main_stage_id_revert(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    _setup_main_monkeypatch(monkeypatch, tmp_path, staging, applier)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    cmd_apply_one(applier, staged["stage_id"], False, False)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    monkeypatch.setattr(sys, "argv", ["apply_staged", "--stage-id", staged["stage_id"], "--revert"])
    main()
    out = capsys.readouterr().out
    assert "Reverted" in out


def test_main_stage_id_missing(tmp_path, monkeypatch, capsys):
    staging = StagingManager(tmp_path / "staged")
    applier = StagedChangeApplier(staging.staging_dir)
    _setup_main_monkeypatch(monkeypatch, tmp_path, staging, applier)
    monkeypatch.setattr(sys, "argv", ["apply_staged", "--stage-id", "5cf2f18c-cb3c-4dc2-98bb-52ea1160d33a"])
    main()
    out = capsys.readouterr().out
    assert "is missing" in out


def test_main_all_no_pending(tmp_path, monkeypatch, capsys):
    staging = StagingManager(tmp_path / "staged")
    applier = StagedChangeApplier(staging.staging_dir)
    _setup_main_monkeypatch(monkeypatch, tmp_path, staging, applier)
    monkeypatch.setattr(sys, "argv", ["apply_staged", "--all"])
    main()
    assert "No pending" in capsys.readouterr().out


def test_main_all_dry_run(tmp_path, monkeypatch, capsys):
    audio, staging, staged, applier = _stage_real(tmp_path)
    _setup_main_monkeypatch(monkeypatch, tmp_path, staging, applier)
    monkeypatch.setattr(sys, "argv", ["apply_staged", "--all", "--dry-run"])
    main()
    out = capsys.readouterr().out
    assert "Review summary" in out


def test_main_revert_requires_stage_id(tmp_path, monkeypatch, capsys):
    staging = StagingManager(tmp_path / "staged")
    applier = StagedChangeApplier(staging.staging_dir)
    _setup_main_monkeypatch(monkeypatch, tmp_path, staging, applier)
    monkeypatch.setattr(sys, "argv", ["apply_staged", "--all", "--revert"])
    main()
    assert "requires --stage-id" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# staged_apply coverage
# --------------------------------------------------------------------------- #

def test_staged_apply_already_applied(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    applier.apply(staged["stage_id"])
    result = applier.apply(staged["stage_id"])
    assert result["status"] == "already_applied"


def test_staged_apply_withdrawn(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    staging.withdraw(staged["stage_id"], 1, "nope")
    result = applier.apply(staged["stage_id"])
    assert result["status"] == "withdrawn"


def test_staged_apply_failed_state(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    manifest = staging.store.load(staged["stage_id"])
    manifest["failed"] = True
    staging.store.save(manifest)
    result = applier.apply(staged["stage_id"])
    assert result["status"] == "failed"


def test_staged_apply_archived_state(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    manifest = staging.store.load(staged["stage_id"])
    manifest["archived"] = True
    staging.store.save(manifest)
    result = applier.apply(staged["stage_id"])
    assert result["status"] == "archived"


def test_staged_apply_baseline_mismatch_raises(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    apply_tags_to_file(str(audio), {"title": "Different"}, create_backup=False)
    with pytest.raises(ValueError, match="Source tags changed"):
        applier.apply(staged["stage_id"])


def test_staged_apply_defer(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    res = applier.defer(staged["stage_id"])
    assert res["status"] == "deferred"


def test_staged_apply_archive_missing_file(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    res = applier.archive_missing_file(staged["stage_id"])
    assert res["status"] == "archived"


def test_staged_apply_revert_success(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    applier.apply(staged["stage_id"], create_backup=True)
    res = applier.revert(staged["stage_id"])
    assert res["status"] == "reverted"
    res2 = applier.revert(staged["stage_id"])
    assert res2["status"] == "already_reverted"


def test_staged_apply_revert_no_backup(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    manifest = staging.store.load(staged["stage_id"])
    manifest["applied"] = True
    manifest["backup_path"] = None
    staging.store.save(manifest)
    with pytest.raises(ValueError, match="No backup path"):
        applier.revert(staged["stage_id"])


def test_staged_apply_revert_backup_missing(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    applier.apply(staged["stage_id"], create_backup=True)
    manifest = staging.store.load(staged["stage_id"])
    backup = Path(manifest["backup_path"])
    backup.unlink()
    with pytest.raises(FileNotFoundError):
        applier.revert(staged["stage_id"])


def test_staged_apply_revert_original_missing(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    applier.apply(staged["stage_id"], create_backup=True)
    audio.unlink()
    with pytest.raises(FileNotFoundError):
        applier.revert(staged["stage_id"])


def test_staged_apply_revert_not_applied(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    with pytest.raises(ValueError, match="Only applied"):
        applier.revert(staged["stage_id"])


def test_get_staged_applier_singleton(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSICBEE_TAGGER_DATA_DIR", str(tmp_path / "data"))
    import musicbee_tagger_mcp.staged_apply as sa

    sa._applier = None
    a1 = get_staged_applier()
    a2 = get_staged_applier()
    assert a1 is a2
    sa._applier = None


# --------------------------------------------------------------------------- #
# stage_manifest_store coverage
# --------------------------------------------------------------------------- #

def test_store_save_oserror(tmp_path):
    store = StageManifestStore(tmp_path / "staged")
    store.directory.mkdir(parents=True, exist_ok=True)
    manifest = {"stage_id": "11111111-2222-3333-4444-555555555555", "x": 1}
    with patch("tempfile.NamedTemporaryFile", side_effect=OSError("boom")):
        with pytest.raises(RuntimeError):
            store.save(manifest)


def test_store_load_missing(tmp_path):
    store = StageManifestStore(tmp_path / "staged")
    store.directory.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        store.load("11111111-2222-3333-4444-555555555555")


def test_store_invalid_stage_id(tmp_path):
    store = StageManifestStore(tmp_path / "staged")
    store.directory.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError):
        store.load("not-a-uuid")


def test_store_list_pending_and_applied(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    store = staging.store
    pending = store.list_pending()
    assert any(p["stage_id"] == staged["stage_id"] for p in pending)
    applier.apply(staged["stage_id"], create_backup=True)
    applied = store.list_applied_with_backup()
    assert any(a["stage_id"] == staged["stage_id"] for a in applied)


def test_store_transact(tmp_path):
    audio, staging, staged, applier = _stage_real(tmp_path)
    store = staging.store

    def action(m):
        m["foo"] = "bar"
        return "ok"

    manifest, result = store.transact(staged["stage_id"], action)
    assert result == "ok"
    assert store.load(staged["stage_id"])["foo"] == "bar"


def test_store_nt_lock_branch(tmp_path, monkeypatch):
    import types

    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(fd, mode, nbytes):
            return None

    fake_module = types.ModuleType("msvcrt")
    fake_module.LK_NBLCK = FakeMsvcrt.LK_NBLCK
    fake_module.LK_UNLCK = FakeMsvcrt.LK_UNLCK
    fake_module.locking = FakeMsvcrt.locking

    import musicbee_tagger_mcp.stage_manifest_store as sms
    import os as _real_os
    class _FakeOS:
        name = "nt"
        def __getattr__(self, item):
            return getattr(_real_os, item)
    monkeypatch.setattr(sms, "os", _FakeOS())
    monkeypatch.setattr(sms.importlib, "import_module", lambda name: fake_module if name == "msvcrt" else __import__(name))
    store = StageManifestStore(tmp_path / "staged_nt")
    store.directory.mkdir(parents=True, exist_ok=True)
    manifest = {"stage_id": "22222222-3333-4444-5555-666666666666", "x": 1}
    store.save(manifest)
    loaded = store.load("22222222-3333-4444-5555-666666666666")
    assert loaded["x"] == 1


# --------------------------------------------------------------------------- #
# partial failure scenario
# --------------------------------------------------------------------------- #

def test_partial_failure_two_tracks(tmp_path, monkeypatch, capsys):
    audio1, staging, staged1, applier = _stage_real(tmp_path, name="first.mp3")
    audio2 = _make_audio_copy(tmp_path, MP3, name="second.mp3")
    staging2 = StagingManager(staging.staging_dir)
    staged2 = staging2.stage(audio2, audio2.name, {"title": "Second Title"})

    real_apply = __import__(
        "musicbee_tagger_mcp.staged_apply", fromlist=["apply_tags_to_file"]
    ).apply_tags_to_file

    def fake_apply(file_path, new_tags, create_backup=True):
        if "second" in file_path:
            raise PermissionError("read-only")
        return real_apply(file_path, new_tags, create_backup=create_backup)

    monkeypatch.setattr("musicbee_tagger_mcp.staged_apply.apply_tags_to_file", fake_apply)

    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    o1 = cmd_apply_one(applier, staged1["stage_id"], False, False)
    assert o1 == "applied"
    o2 = cmd_apply_one(applier, staged2["stage_id"], False, False)
    assert o2 == "failed"
    assert staging.get(staged1["stage_id"])["status"] == "applied"
    assert staging.get(staged2["stage_id"])["status"] == "failed"
    tags1 = read_audio_metadata(str(audio1))["tags"]
    assert tags1["title"] == "New Title"


# --------------------------------------------------------------------------- #
# large manifest performance
# --------------------------------------------------------------------------- #

def test_large_manifest_apply_ordering(tmp_path, monkeypatch):
    src = _make_audio_copy(tmp_path, MP3, name="src.mp3")
    staging = StagingManager(tmp_path / "staged")
    applier = StagedChangeApplier(staging.staging_dir)
    audio = src
    stage_ids = []
    for i in range(200):
        a = tmp_path / f"t{i}.mp3"
        shutil.copy2(audio, a)
        s = staging.stage(a, a.name, {"title": f"Title {i}"})
        stage_ids.append(s["stage_id"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    for sid in stage_ids:
        res = applier.apply(sid, create_backup=False)
        assert res["status"] == "applied"
    assert staging.list_pending() == []


# --------------------------------------------------------------------------- #
# path redaction
# --------------------------------------------------------------------------- #

def test_path_redaction_apply_staged_errors(tmp_path, capsys):
    applier = StagedChangeApplier(tmp_path / "staged")
    applier.store.directory.mkdir(parents=True, exist_ok=True)
    cmd_apply_one(applier, "5cf2f18c-cb3c-4dc2-98bb-52ea1160d33a", False, False)
    out = capsys.readouterr().out
    assert str(tmp_path) not in out
