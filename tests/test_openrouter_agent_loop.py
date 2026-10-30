"""OpenRouter loop logging, verification gate, and debug checkpoints."""

import json

from scripts import openrouter_agent_loop as agent


def _tool_call(name, args, call_id="call-1"):
    return {
        "id": call_id,
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _response(*calls, content=None):
    return {"choices": [{"message": {"content": content, "tool_calls": list(calls)}}]}


def test_debug_pauses_only_when_enabled(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(
        AssertionError("non-debug run must not pause")
    ))
    assert agent.debug_checkpoint(False, "safe point") is True

    monkeypatch.setattr("builtins.input", lambda _prompt: "q")
    assert agent.debug_checkpoint(True, "safe point") is False


def test_jsonl_run_log_records_visible_summaries_and_sanitizes_paths(tmp_path):
    log_path = tmp_path / "run.jsonl"
    log = agent.RunLog(log_path, "run-id")
    log.write("progress", summary="Matched track", error=r"Could not read K:\\secret\\song.mp3")

    event = json.loads(log_path.read_text(encoding="utf-8"))
    assert event["event"] == "progress"
    assert event["summary"] == "Matched track"
    assert "secret" not in json.dumps(event)


def test_batch_logs_tools_and_requires_verified_candidate_before_staging(
    monkeypatch, tmp_path
):
    token = "opaque-token"
    recording_id = "cdd0e7e6-b624-4bdb-95d7-c741b8c40be6"
    release_id = "15886515-8083-4c26-a9fc-0b3493ed12ab"
    monkeypatch.setattr(agent, "get_batch_brief", lambda _tokens: [{
        "token": token, "display_name": "Song.mp3", "tags": {"title": "Song"}
    }])
    monkeypatch.setattr(agent, "read_track_metadata", lambda _token: {
        "tags": {"title": "Song", "artist": "Artist"},
        "duration_seconds": 180.0,
    })
    monkeypatch.setattr(agent, "evaluate_match", lambda **_kwargs: {
        "verified": True, "confidence": 91.0, "recording_id": recording_id,
        "mb_title": "Song", "mb_artist": "Artist", "genre": "Rock; Indie",
        "top_release": {"release_id": release_id},
    })
    staged_calls = []
    monkeypatch.setitem(agent.LOCAL_TOOLS, "stage_tag_changes", lambda **kwargs: (
        staged_calls.append(kwargs) or {"stage_id": "stage-1"}
    ))
    responses = iter([
        _response(_tool_call("evaluate_match", {"token": token,
                                                "mb_recording_id": recording_id})),
        _response(_tool_call("stage_tag_changes", {
            "token": token, "new_tags": {"title": "Song", "genre": "Rock; Indie"},
            "mb_recording_id": recording_id,
        })),
        _response(_tool_call("finish_batch", {"summary": "one staged"})),
    ])
    monkeypatch.setattr(agent, "call_openrouter", lambda *_args, **_kwargs: next(responses))
    state = {"batch": 1, "staged": [], "unresolved": [], "finished": False}
    log = agent.RunLog(tmp_path / "agent.jsonl", "run-id")

    agent.run_batch([token], "openrouter/free", "unused", 5, state,
                    tmp_path / "state.json", run_log=log)

    assert state["finished"] is True
    assert state["staged"] == [token]
    assert staged_calls[0]["forensic_score"] == 91.0
    assert staged_calls[0]["mb_release_id"] == release_id
    events = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
    assert any(item["event"] == "tool_call" for item in events)
    assert any(item["event"] == "tool_result" for item in events)
    assert any(item["event"] == "batch_finished" for item in events)


def test_staging_is_blocked_until_matching_verification(monkeypatch, tmp_path):
    token = "opaque-token"
    staged_calls = []
    monkeypatch.setattr(agent, "get_batch_brief", lambda _tokens: [])
    monkeypatch.setitem(agent.LOCAL_TOOLS, "stage_tag_changes",
                        lambda **kwargs: staged_calls.append(kwargs))
    responses = iter([
        _response(_tool_call("stage_tag_changes", {
            "token": token, "new_tags": {"title": "Maybe"},
            "mb_recording_id": "cdd0e7e6-b624-4bdb-95d7-c741b8c40be6",
        })),
        _response(_tool_call("mark_unresolved", {
            "token": token, "reason": "No matching verification was performed."
        })),
        _response(_tool_call("finish_batch", {"summary": "unresolved"})),
    ])
    monkeypatch.setattr(agent, "call_openrouter", lambda *_args, **_kwargs: next(responses))
    state = {"batch": 1, "staged": [], "unresolved": [], "finished": False}

    agent.run_batch([token], "openrouter/free", "unused", 5, state,
                    tmp_path / "state.json")

    assert staged_calls == []
    assert state["staged"] == []
    assert state["unresolved"] == [token]
    assert state["finished"] is True

def test_load_system_prompt_and_modes():
    prompt = agent.load_system_prompt()
    assert len(prompt) > 0
    assert "OpenRouter" in prompt or "tagger" in prompt.lower()

    # Check agent mode prompt additions
    assert "Speed mode" in agent._AGENT_MODE_ADDITIONS["lazy"]
    assert agent._AGENT_MODE_ADDITIONS["thorough"] == ""


def test_tool_exception_handling_in_batch(monkeypatch, tmp_path):
    token = "opaque-token"
    monkeypatch.setattr(agent, "get_batch_brief", lambda _tokens: [{
        "token": token, "display_name": "Error.mp3", "tags": {}
    }])
    monkeypatch.setitem(agent.LOCAL_TOOLS, "read_track_metadata", lambda **_kwargs: (_ for _ in ()).throw(
        ValueError("Corrupt track metadata")
    ))
    responses = iter([
        _response(_tool_call("read_track_metadata", {"token": token})),
        _response(_tool_call("mark_unresolved", {"token": token, "reason": "metadata corrupt"})),
        _response(_tool_call("finish_batch", {"summary": "handled error"})),
    ])
    monkeypatch.setattr(agent, "call_openrouter", lambda *_args, **_kwargs: next(responses))
    state = {"batch": 1, "staged": [], "unresolved": [], "finished": False}
    log = agent.RunLog(tmp_path / "agent.jsonl", "run-id")

    agent.run_batch([token], "openrouter/free", "unused", 5, state,
                    tmp_path / "state.json", run_log=log)
    assert state["finished"] is True
    assert state["unresolved"] == [token]

