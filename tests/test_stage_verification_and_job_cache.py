"""Verification signals for staging calls and per-connection job-id memory."""

import asyncio
import json
import types

from musicbee_tagger_mcp import session_cache
from musicbee_tagger_mcp import staging as staging_module
from musicbee_tagger_mcp.staging import StagingManager
from musicbee_tagger_mcp.tools import playlists as playlist_tools
from musicbee_tagger_mcp.tools import tags as tag_tools


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


def _manager(tmp_path, monkeypatch):
    monkeypatch.setattr(staging_module, "preview_tag_changes", _preview)
    monkeypatch.setattr(
        staging_module,
        "read_audio_metadata",
        lambda _path: {"tags": {"artist": "Original Artist", "title": "Original Title"}},
    )
    return StagingManager(tmp_path / "staged")


def _stage_track(manager, tmp_path, name, title):
    audio_file = tmp_path / name
    audio_file.write_bytes(b"synthetic audio placeholder")
    return manager.stage(audio_file, name, {"title": title})


class _FakeSession:
    """Stand-in for an MCP ServerSession; identity defines the connection."""


class _FakeContext:
    def __init__(self, session):
        self.request_context = types.SimpleNamespace(session=session)


def test_stage_response_proves_the_manifest_persisted(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)

    result = _stage_track(manager, tmp_path, "track.mp3", "Verified Title")

    assert result["verified"] is True
    assert result["persisted"] is True
    assert result["status"] == "pending"
    assert result["revision"] == 1
    assert result["stage_id"]
    manifest = manager.store.load(result["stage_id"])
    assert manifest["proposed_tags"] == {"title": "Verified Title"}
    assert str(tmp_path) not in json.dumps(result)


def test_amend_response_proves_the_manifest_persisted(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    staged = _stage_track(manager, tmp_path, "track.mp3", "First Title")

    result = manager.amend(
        staged["stage_id"],
        expected_revision=1,
        new_tags={"title": "Second Title"},
        reason="Corroborated by the release tracklist.",
    )

    assert result["verified"] is True
    assert result["persisted"] is True
    assert result["revision"] == 2
    assert manager.store.load(staged["stage_id"])["proposed_tags"] == {
        "title": "Second Title"
    }


def test_list_staged_changes_defaults_to_one_item(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    _stage_track(manager, tmp_path, "first.mp3", "First Title")
    _stage_track(manager, tmp_path, "second.mp3", "Second Title")

    page = manager.list_staged_changes()

    assert page["limit"] == 1
    assert page["total"] == 2
    assert len(page["items"]) == 1


def test_list_staged_changes_can_confirm_a_specific_stage(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    first = _stage_track(manager, tmp_path, "first.mp3", "First Title")
    second = _stage_track(manager, tmp_path, "second.mp3", "Second Title")

    page = manager.list_staged_changes(stage_id=second["stage_id"])

    assert page["total"] == 1
    assert page["items"][0]["stage_id"] == second["stage_id"]
    assert page["items"][0]["status"] == "pending"
    assert page["items"][0]["stage_id"] != first["stage_id"]



def test_job_id_cache_is_scoped_to_one_connection():
    session_a, session_b = _FakeSession(), _FakeSession()
    context_a, context_b = _FakeContext(session_a), _FakeContext(session_b)

    assert session_cache.resolve_job_id("job-a", context_a) == "job-a"
    assert session_cache.recall_job_id(context_a) == "job-a"
    assert session_cache.recall_job_id(context_b) is None

    assert session_cache.resolve_job_id(None, context_a) == "job-a"
    assert session_cache.resolve_job_id("job-b", context_b) == "job-b"
    assert session_cache.recall_job_id(context_a) == "job-a"

    assert session_cache.clear_job_id(context_a) is True
    assert session_cache.recall_job_id(context_a) is None


def test_cached_job_id_is_reused_without_a_context():
    assert session_cache.resolve_job_id("job-c", None) == "job-c"
    assert session_cache.recall_job_id(None) is None


def test_playlist_tools_reuse_the_connection_job_id(monkeypatch):
    calls = []

    class FakeStore:
        def next_batch(self, job_id, size=10):
            calls.append((job_id, size))
            return {"batch": []}

    monkeypatch.setattr(playlist_tools, "get_job_store", lambda: FakeStore())
    context = _FakeContext(_FakeSession())

    assert playlist_tools.next_batch(ctx=context) == {
        "error": playlist_tools._NO_ACTIVE_JOB["error"]
    }
    assert calls == []

    playlist_tools.next_batch(job_id="job-42", size=1, ctx=context)
    playlist_tools.next_batch(size=2, ctx=context)

    assert calls == [("job-42", 1), ("job-42", 2)]


def test_stage_tag_changes_attaches_the_connection_job_id(monkeypatch):
    captured = {}

    class FakeEntry:
        name = "track.mp3"

    class FakeRegistry:
        def resolve(self, _token):
            return FakeEntry()

    class FakeManager:
        def stage(self, **kwargs):
            captured.update(kwargs)
            return {"stage_id": "stage", "verified": True}

    monkeypatch.setattr(tag_tools, "get_registry", lambda: FakeRegistry())
    monkeypatch.setattr(tag_tools, "get_staging_manager", lambda: FakeManager())
    context = _FakeContext(_FakeSession())

    tag_tools.stage_tag_changes("token", {"genre": "Jazz"}, job_id="job-7", ctx=context)
    assert captured["job_id"] == "job-7"

    captured.clear()
    tag_tools.stage_tag_changes("token", {"genre": "Jazz"}, ctx=context)
    assert captured["job_id"] == "job-7"


def test_list_staged_changes_tool_defaults_to_one_and_reuses_job(monkeypatch):
    captured = {}

    class FakeManager:
        def list_staged_changes(self, **kwargs):
            captured.update(kwargs)
            return {"items": [], "total": 0, "limit": kwargs["limit"], "offset": 0}

    monkeypatch.setattr(tag_tools, "get_staging_manager", lambda: FakeManager())
    context = _FakeContext(_FakeSession())
    session_cache.resolve_job_id("job-9", context)

    tag_tools.list_staged_changes(ctx=context)

    assert captured["limit"] == 1
    assert captured["job_id"] == "job-9"


def test_tool_schemas_keep_job_id_optional_and_limit_default_one():
    from musicbee_tagger_mcp.server import app

    tools = {tool.name: tool for tool in asyncio.run(app.list_tools())}

    next_batch_schema = tools["next_batch"].input_schema
    assert "job_id" not in (next_batch_schema.get("required") or [])
    assert "ctx" not in next_batch_schema["properties"]

    staged_schema = tools["list_staged_changes"].input_schema
    assert staged_schema["properties"]["limit"]["default"] == 1
    assert "stage_id" in staged_schema["properties"]
    assert "ctx" not in staged_schema["properties"]

    stage_schema = tools["stage_tag_changes"].input_schema
    assert "ctx" not in stage_schema["properties"]
    assert "verified" in (tools["stage_tag_changes"].description or "")


class _Unweakrefable:
    """Instances of __slots__-without-__weakref__ classes cannot be weakref'd."""

    __slots__ = ("marker",)

    def __init__(self):
        self.marker = "no-weakref"


import pytest


def test_remember_job_id_survives_unweakrefable_sessions():
    """Bug #1 regression: TypeError from WeakKeyDictionary must not be silent."""
    import musicbee_tagger_mcp.session_cache as sc

    session = _FakeContext(_Unweakrefable())
    sc.remember_job_id("job-abc", session)
    assert sc.recall_job_id(session) == "job-abc"
    assert sc.clear_job_id(session) is True
    assert sc.recall_job_id(session) is None


def test_unweakrefable_cache_is_bounded():
    import musicbee_tagger_mcp.session_cache as sc

    for i in range(sc._UNWEAKREFABLE_LIMIT + 10):
        sc.remember_job_id(f"job-{i}", _FakeContext(_Unweakrefable()))
    assert len(sc._UNWEAKREFABLE_IDS) <= sc._UNWEAKREFABLE_LIMIT


def test_resolve_job_id_rejects_whitespace_instead_of_falling_back():
    """Bug #2 regression: blank job_id must raise, not reuse the old job."""
    import musicbee_tagger_mcp.session_cache as sc

    class _Session:
        pass

    session = _FakeContext(_Session())
    sc.remember_job_id("job-original", session)
    with pytest.raises(ValueError):
        sc.resolve_job_id("   ", session)
    # The cached job is untouched by the failed resolution.
    assert sc.recall_job_id(session) == "job-original"
    # Omitting job_id still resolves the remembered value.
    assert sc.resolve_job_id(None, session) == "job-original"
