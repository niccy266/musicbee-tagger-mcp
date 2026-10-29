"""Playlist job lifecycle: CLI registration → MCP-served batches → completion.

Registration is a local CLI command. The MCP server only serves unprocessed
tokens in batches and records outcomes — it never accepts a path.
"""

import json

import pytest

from musicbee_tagger_mcp.file_registry import FileRegistry
from musicbee_tagger_mcp.job_store import JobStore
from musicbee_tagger_mcp.register_playlist_cli import run as cli_run
from scripts.openrouter_agent_loop import select_job_id
from musicbee_tagger_mcp.tools.playlists import (
    complete_batch,
    job_status,
    list_jobs,
    next_batch,
    release_batch,
    register_playlist_tools,
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    reg = FileRegistry(directory=tmp_path / "reg")
    jobs = JobStore(directory=tmp_path / "jobs")
    (tmp_path / "jobs").mkdir()
    monkeypatch.setattr("musicbee_tagger_mcp.register_playlist_cli.get_registry", lambda: reg)
    monkeypatch.setattr("musicbee_tagger_mcp.register_playlist_cli.get_job_store", lambda: jobs)
    monkeypatch.setattr("musicbee_tagger_mcp.tools.playlists.get_job_store", lambda: jobs)
    return reg, jobs, tmp_path


def _playlist(tmp_path, count=25, missing=0):
    lines = ["#EXTM3U"]
    for i in range(count):
        (tmp_path / f"track_{i:02d}.mp3").write_bytes(b"\x00" * 8)
        lines.append(str(tmp_path / f"track_{i:02d}.mp3"))
    for i in range(missing):
        lines.append(str(tmp_path / f"absent_{i}.mp3"))
    playlist = tmp_path / "evening.m3u"
    playlist.write_text("\n".join(lines), encoding="utf-8")
    return playlist


def _register_cli(env, playlist, out):
    reg, jobs, tmp_path = env
    assert cli_run.__module__
    import io
    stream = io.StringIO()
    code = cli_run(input_stream=io.StringIO(f'"{playlist}"\n'), output_stream=stream)
    return code, stream.getvalue(), jobs


def test_cli_creates_job_with_batches_of_ten(env):
    reg, jobs, tmp_path = env
    playlist = _playlist(tmp_path, count=25, missing=2)
    import io
    stream = io.StringIO()
    code = cli_run(input_stream=io.StringIO(f'"{playlist}"\n'), output_stream=stream)
    assert code == 0
    text = stream.getvalue()
    assert "job" in text
    (job_id,) = [line.split()[-1].rstrip(".") for line in text.splitlines() if "playlist job" in line]
    job_id = job_id.rstrip(".")
    assert len(job_id) == 36  # uuid
    status = jobs.job_status(job_id)
    assert status["counts"]["pending"] == 25
    assert status["skipped"] == 2
    batch = next_batch(job_id, size=10)
    assert len(batch["batch"]) == 10
    assert batch["remaining"] == 15


def test_batches_and_completion(env):
    reg, jobs, tmp_path = env
    playlist = _playlist(tmp_path, count=25)
    import io
    stream = io.StringIO()
    cli_run(input_stream=io.StringIO(f'"{playlist}"\n'), output_stream=stream)
    (job_id,) = [line.split()[-1].rstrip(".") for line in stream.getvalue().splitlines() if "playlist job" in line]

    claimed = []
    for _ in range(3):
        batch = next_batch(job_id, size=10)
        claimed.extend(t["token"] for t in batch["batch"])
        complete_batch(job_id, [{"token": t["token"], "success": True} for t in batch["batch"]])
    assert len(claimed) == 25
    # empty pool
    assert next_batch(job_id)["batch"] == []
    status = jobs.job_status(job_id)
    assert status["counts"]["done"] == 25


def test_release_batch_returns_only_active_claims_to_pending(env):
    _reg, jobs, tmp_path = env
    playlist = _playlist(tmp_path, count=3)
    import io
    stream = io.StringIO()
    cli_run(input_stream=io.StringIO(f'"{playlist}"\n'), output_stream=stream)
    (job_id,) = [
        line.split()[-1].rstrip(".")
        for line in stream.getvalue().splitlines()
        if "playlist job" in line
    ]
    claimed = next_batch(job_id, size=2)["batch"]
    first, second = [item["token"] for item in claimed]

    result = release_batch(job_id, [first, "not-claimed"])

    assert result["released"] == [first]
    assert result["unchanged"] == ["not-claimed"]
    assert jobs.job_status(job_id)["counts"]["pending"] == 2
    assert jobs.job_status(job_id)["counts"]["in_progress"] == 1
    assert jobs.complete_batch(job_id, [{"token": second, "success": True}])["updated"] == 1


def test_failed_tokens_reported_with_display_names(env):
    reg, jobs, tmp_path = env
    playlist = _playlist(tmp_path, count=12)
    import io
    stream = io.StringIO()
    cli_run(input_stream=io.StringIO(f'"{playlist}"\n'), output_stream=stream)
    (job_id,) = [line.split()[-1].rstrip(".") for line in stream.getvalue().splitlines() if "playlist job" in line]
    batch = next_batch(job_id, size=10)
    results = [{"token": t["token"], "success": False, "error": "unresolvable"} for t in batch["batch"]]
    complete_batch(job_id, results)
    status = job_status(job_id)
    assert len(status["failed"]) == 10
    assert all(f["error"] == "unresolvable" for f in status["failed"])
    assert all("token" not in f for f in status["failed"])
    assert all("path" not in json.dumps(f).lower() for f in status["failed"])


def test_job_status_never_leaks_paths_or_tokens(env):
    reg, jobs, tmp_path = env
    playlist = _playlist(tmp_path, count=5)
    import io
    stream = io.StringIO()
    cli_run(input_stream=io.StringIO(f'"{playlist}"\n'), output_stream=stream)
    (job_id,) = [line.split()[-1].rstrip(".") for line in stream.getvalue().splitlines() if "playlist job" in line]
    dumped = json.dumps(job_status(job_id))
    assert str(tmp_path) not in dumped
    assert ".mp3" not in dumped
    assert "token" not in dumped


def test_list_jobs_returns_path_free_available_summaries(env):
    reg, jobs, tmp_path = env
    playlist = _playlist(tmp_path, count=3)
    import io
    stream = io.StringIO()
    cli_run(input_stream=io.StringIO(f'"{playlist}"\n'), output_stream=stream)
    (job_id,) = [
        line.split()[-1].rstrip(".")
        for line in stream.getvalue().splitlines()
        if "playlist job" in line
    ]

    result = list_jobs()
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["job_id"] == job_id
    assert result["jobs"][0]["playlist_name"] == "evening.m3u"
    assert result["jobs"][0]["counts"]["pending"] == 3
    serialized = json.dumps(result)
    assert str(tmp_path) not in serialized
    assert ".mp3" not in serialized
    assert "token" not in serialized


def test_list_jobs_excludes_jobs_without_pending_work(env):
    reg, jobs, tmp_path = env
    created = jobs.create_job([], "finished.m3u")

    assert list_jobs() == {"jobs": []}
    assert jobs.job_status(created["job_id"])["counts"]["pending"] == 0


def test_agent_loop_selects_the_only_available_job(env, capsys):
    _, jobs, tmp_path = env
    created = jobs.create_job(
        [{"token": "opaque-token", "display_name": "Track"}],
        "available.m3u",
    )

    selected = select_job_id(None, jobs)

    assert selected == created["job_id"]
    assert created["job_id"] in capsys.readouterr().out


def test_agent_loop_selects_first_available_job_when_multiple_jobs_are_available(env, capsys):
    _, jobs, _ = env
    first = jobs.create_job([{"token": "token-a", "display_name": "A"}], "first.m3u")
    second = jobs.create_job([{"token": "token-b", "display_name": "B"}], "second.m3u")

    selected = select_job_id(None, jobs)

    assert selected == jobs.list_jobs()[0]["job_id"]
    output = capsys.readouterr().out
    assert selected in output


def test_agent_loop_requires_registration_when_no_jobs_are_available(env):
    _, jobs, _ = env

    with pytest.raises(SystemExit, match="Register a playlist"):
        select_job_id(None, jobs)


def test_agent_loop_uses_requested_job_id(env):
    _, jobs, _ = env
    created = jobs.create_job([], "requested.m3u")

    assert select_job_id(created["job_id"], jobs) == created["job_id"]


def test_unknown_job_handled_safely():
    bad = next_batch("no-such-job")
    assert "error" in bad and "batch" not in bad
    assert "error" in complete_batch("no-such-job", [])
    assert job_status("no-such-job") == {"error": "Unknown job id"}


def test_registered_playlist_tools_dispatch_to_job_store(tmp_path, monkeypatch):
    class FakeApp:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def register(function):
                self.tools[function.__name__] = function
                return function

            return register

    jobs = JobStore(directory=tmp_path / "jobs")
    (tmp_path / "jobs").mkdir()
    monkeypatch.setattr(
        "musicbee_tagger_mcp.tools.playlists.get_job_store", lambda: jobs
    )
    entries = [
        {"token": f"opaque-token-{index}", "display_name": f"track-{index}.mp3"}
        for index in range(25)
    ]
    job = jobs.create_job(entries, playlist_name="private-playlist.m3u")
    app = FakeApp()
    register_playlist_tools(app)

    batch = app.tools["next_batch"](job["job_id"], size=25)
    assert len(batch["batch"]) == 25
    assert batch["remaining"] == 0
    assert app.tools["next_batch"](job["job_id"], size=25)["batch"] == []
    assert jobs.job_status(job["job_id"])["counts"]["in_progress"] == 25
    released = app.tools["release_batch"](
        job["job_id"], [batch["batch"][0]["token"]]
    )
    assert released["released"] == [batch["batch"][0]["token"]]
    assert app.tools["next_batch"](job["job_id"], size=1)["batch"][0]["token"] == batch["batch"][0]["token"]

    status = app.tools["job_status"](job["job_id"])
    assert status["counts"]["in_progress"] == 25
    completed = app.tools["complete_batch"](
        job["job_id"],
        [{"token": item["token"], "success": True} for item in batch["batch"]],
    )
    assert completed["updated"] == 25
    assert app.tools["job_status"](job["job_id"])["counts"]["done"] == 25
    assert app.tools["next_batch"]("not-a-valid-job-id", size=25) == {
        "error": "Unknown job id"
    }
    assert app.tools["job_status"]("not-a-valid-job-id") == {
        "error": "Unknown job id"
    }


def test_preview_batch_does_not_claim(env):
    """#40: preview_batch reports the next batch without mutating state."""
    reg, jobs, tmp_path = env
    playlist = _playlist(tmp_path, count=3)
    import io as _io
    code, text, _ = _register_cli(env, playlist, _io.StringIO())
    assert code == 0
    (job_id,) = [line.split()[-1].rstrip(".") for line in text.splitlines() if "playlist job" in line]

    result = jobs.preview_batch(job_id, size=2)
    assert len(result["preview"]) == 2
    assert result["remaining"] == 3
    # Nothing claimed: a following next_batch still starts at track 0.
    batch = jobs.next_batch(job_id, size=2)
    assert batch["batch"][0]["display_name"] == result["preview"][0]["display_name"]
    assert batch["remaining"] == 1


def test_preview_batch_rejects_bad_size(env):
    reg, jobs, tmp_path = env
    playlist = _playlist(tmp_path, count=1)
    import io as _io
    code, text, _ = _register_cli(env, playlist, _io.StringIO())
    (job_id,) = [line.split()[-1].rstrip(".") for line in text.splitlines() if "playlist job" in line]
    assert "error" in jobs.preview_batch(job_id, size=0)
    assert "error" in jobs.preview_batch(job_id, size=99)
