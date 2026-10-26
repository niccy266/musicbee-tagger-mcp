"""Persistent memory helpers for the OpenRouter agent."""
import hashlib
import os
from pathlib import Path

import pytest

from scripts import openrouter_agent_loop as agent


def test_memory_path_uses_configured_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSICBEE_TAGGER_DATA_DIR", str(tmp_path / "private-data"))
    path = agent.default_memory_path()
    assert path == tmp_path / "private-data" / "agent_memory" / "agent_memory.txt"
    assert agent._resolve_memory_path() == path


def test_write_and_append_memory_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSICBEE_TAGGER_DATA_DIR", str(tmp_path / "private-data"))
    result = agent.write_memory("first")
    assert result["status"] == "ok"
    assert agent.read_memory() == "first"
    agent.append_memory("second")
    assert "first" in agent.read_memory()
    assert "second" in agent.read_memory()


def test_memory_metadata_and_staleness(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSICBEE_TAGGER_DATA_DIR", str(tmp_path / "private-data"))
    agent.write_memory("hello")
    metadata = agent.memory_file_metadata()
    assert metadata["exists"] is True
    assert metadata["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert agent.memory_is_stale({"memory_path": metadata["path"],
                                 "memory_mtime": metadata["mtime"],
                                 "memory_sha256": metadata["sha256"]}) is False
    agent.write_memory("changed")
    assert agent.memory_is_stale({"memory_path": metadata["path"],
                                 "memory_mtime": metadata["mtime"],
                                 "memory_sha256": metadata["sha256"]}) is True


def test_review_scratchpad_dedupes_and_limits():
    text = "- important note\n- important note\n- another important note"
    reviewed = agent.review_scratchpad(text, max_lines=2)
    assert reviewed.count("important note") == 1 or reviewed.count("another") == 1
    assert len(reviewed.splitlines()) <= 2
    assert len(set(reviewed.splitlines())) == len(reviewed.splitlines())


def test_compact_context_dedupes_lines():
    context = "same line\nsame line\nother line"
    compacted = agent.compact_context(context, max_chars=100)
    assert compacted.count("same line") == 1


def test_write_successes_to_memory_timestamps_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSICBEE_TAGGER_DATA_DIR", str(tmp_path / "private-data"))
    agent.write_successes_to_memory(["Track A"])
    first = agent.read_memory()
    assert "Success: Track A" in first
    agent.write_successes_to_memory(["Track A"])
    second = agent.read_memory()
    assert second.count("Success: Track A") == 1