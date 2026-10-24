"""Tests for the playlist job lifecycle: register → batches → completion."""

import json

import pytest

from musicbee_tagger_mcp.file_registry import FileRegistry
from musicbee_tagger_mcp.job_store import JobStore
from musicbee_tagger_mcp.tools.playlists import register_playlist_job


@pytest.fixture
def env(tmp_path, monkeypatch):
    reg = FileRegistry(directory=tmp_path / "reg")
    jobs = JobStore(directory=tmp_path / "jobs")
    (tmp_path / "jobs").mkdir()
    for mod in ("musicbee_tagger_mcp.file_registry",
                "musicbee_tagger_mcp.tools.files",
                "musicbee_tagger_mcp.tools.playlists"):
        monkeypatch.setattr(f"{mod}.get_registry", lambda r=reg: r)
    monkeypatch.setattr(
        "musicbee_tagger_mcp.tools.playlists.get_job_store", lambda: jobs
    )
    return reg, jobs, tmp_path


def _playlist(tmp_path, count=25, missing=0):
    lines = ["#EXTM3U"]
    for i in range(count):
        p = tmp_path / f"track_{i:02d}.mp3"
        p.write_bytes(b"\x00" * 8)
        lines.append(str(p))
    for i in range(missing):
        lines.append(str(tmp_path / f"missing_{i}.mp3"))
    path = tmp_path / "mix.m3u"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_full_lifecycle(env):
    reg, jobs, tmp_path = env
    result = register_playlist_job(str(_playlist(tmp_path, count=25, missing=2)))
    assert result["registered"] == 25
    assert result["skipped_entries"] == 2
    assert str(tmp_path) not in json.dumps(result)

    # Batches of 10 until exhausted.
    claimed = []
    while True:
        batch = jobs.next_batch(result["job_id"])
        if not batch["batch"]:
            break
        assert len(batch["batch"]) == 10 or batch["remaining"] == 0
        claimed.extend(batch["batch"])
    assert len(claimed) == 25
    assert all(reg.resolve(t["token"]) for t in claimed)

    results = [
        {"token": t["token"], "success": i % 5 != 0}
        for i, t in enumerate(claimed)
    ]
    outcome = jobs.complete_batch(result["job_id"], results)
    assert outcome["updated"] == 25
    assert outcome["remaining"] == 0

    status = jobs.job_status(result["job_id"])
    assert status["counts"]["done"] == 20
    assert status["counts"]["failed"] == 5
    assert len(status["failed"]) == 5
    assert all("token" not in f for f in status["failed"])


def test_duplicate_tokens_not_reclaimed(env):
    reg, jobs, tmp_path = env
    result = register_playlist_job(str(_playlist(tmp_path, count=3)))
    job_id = result["job_id"]
    first = jobs.next_batch(job_id)["batch"]
    assert len(first) == 3
    assert jobs.next_batch(job_id)["batch"] == []


def test_in_progress_cannot_be_recompleted(env):
    reg, jobs, tmp_path = env
    job_id = register_playlist_job(str(_playlist(tmp_path, count=2)))["job_id"]
    batch = jobs.next_batch(job_id)["batch"]
    outcome = jobs.complete_batch(
        job_id, [{"token": batch[0]["token"], "success": True}]
    )
    assert outcome["updated"] == 1
    repeat = jobs.complete_batch(
        job_id, [{"token": batch[0]["token"], "success": True}]
    )
    assert repeat["updated"] == 0
    assert batch[0]["token"] in repeat["unknown"]


def test_unknown_job_ids_are_safe(env):
    reg, jobs, tmp_path = env
    assert "error" in jobs.next_batch("not-a-uuid")
    assert "error" in jobs.job_status(str(__import__("uuid").uuid4()))
    assert "error" in register_playlist_job(str(tmp_path / "nope.m3u"))


def test_error_messages_are_path_free(env):
    reg, jobs, tmp_path = env
    bad = register_playlist_job(str(tmp_path / "secret_dir" / "hidden.m3u"))
    assert str(tmp_path) not in json.dumps(bad)
