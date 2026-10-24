"""Tests for durable, path-free batch-operation tracking."""

import sqlite3
import uuid

import pytest

from musicbee_tagger_mcp.queue_store import OperationQueue, default_queue_dir
from musicbee_tagger_mcp.operation_queue import default_queue_path


def test_default_queue_dir_uses_configured_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSICBEE_TAGGER_DATA_DIR", str(tmp_path / "private-data"))

    assert default_queue_dir() == tmp_path / "private-data" / "queue"
    assert default_queue_path() == (
        tmp_path / "private-data" / "queue" / "operations.sqlite3"
    )
    assert (tmp_path / "private-data" / "queue").is_dir()


def test_operations_persist_and_filter_across_store_instances(tmp_path):
    first_store = OperationQueue(tmp_path / "queue")
    first = first_store.enqueue(
        "Investigate releases", "Check the unresolved tracks", "october"
    )
    second = first_store.enqueue("Review candidates", batch="october")
    first_store.update(first["operation_id"], "in_progress", "MusicBrainz review started")

    later_store = OperationQueue(tmp_path / "queue")
    result = later_store.list_operations(status="in_progress", batch="october")

    assert result["total"] == 1
    updated = result["items"][0]
    assert updated["operation_id"] == first["operation_id"]
    assert updated["status"] == "in_progress"
    assert updated["details"] == "MusicBrainz review started"
    assert updated["title"] == first["title"]
    assert updated["updated_at"] >= first["updated_at"]
    first_page = later_store.list_operations(batch="october", limit=1)
    second_page = later_store.list_operations(batch="october", limit=1, offset=1)
    assert first_page["items"][0]["operation_id"] == first["operation_id"]
    assert second_page["items"][0]["operation_id"] == second["operation_id"]


def test_both_agent_queue_apis_share_one_database(tmp_path):
    from musicbee_tagger_mcp.operation_queue import OperationQueue as AgentQueue

    database = tmp_path / "queue" / "operations.sqlite3"
    batch_queue = OperationQueue(tmp_path / "queue")
    agent_queue = AgentQueue(database)
    batch_item = batch_queue.enqueue("Batch item", "Details", "october")
    agent_item = agent_queue.enqueue("Agent item", "Description")

    assert [
        item["operation_id"]
        for item in batch_queue.list_operations(batch="october")["items"]
    ] == [batch_item["operation_id"]]
    agent_items = agent_queue.list_operations()["operations"]
    assert {item["operation_id"] for item in agent_items} == {
        batch_item["operation_id"],
        agent_item["operation_id"],
    }
    assert agent_items[0]["description"] == "Details"


def test_migrates_legacy_batch_queue_schema(tmp_path):
    directory = tmp_path / "legacy-batch"
    directory.mkdir()
    database = directory / "operations.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE operations (
                operation_id TEXT PRIMARY KEY,
                batch TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL
                    CHECK (status IN ('pending', 'in_progress', 'done', 'blocked')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.UUID("cc6bd376-96bc-4ddf-8e1c-e920c1c5669c")),
                "october", "Existing task", "Keep these details",
                "pending", "2026-10-23T00:00:00+00:00", "2026-10-23T00:00:00+00:00",
            ),
        )

    queue = OperationQueue(directory)
    existing = queue.list_operations(batch="october")["items"][0]
    claimed = queue.claim_batch("agent", size=1)["operations"][0]
    completed = queue.complete(
        "cc6bd376-96bc-4ddf-8e1c-e920c1c5669c", "agent", False, "Needs review"
    )

    assert existing["details"] == "Keep these details"
    assert claimed["operation_id"] == "cc6bd376-96bc-4ddf-8e1c-e920c1c5669c"
    assert completed["status"] == "failed"
    assert queue.list_operations(status="failed")["items"][0]["result"] == "Needs review"


def test_migrates_legacy_agent_queue_schema(tmp_path):
    from musicbee_tagger_mcp.operation_queue import OperationQueue as AgentQueue

    database = tmp_path / "legacy-agent.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE operations (
                operation_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                claimed_by TEXT,
                result TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "cc6bd376-96bc-4ddf-8e1c-e920c1c5669c",
                "Existing task", "Keep this description", 7,
                "pending", "2026-10-23T00:00:00+00:00",
                "2026-10-23T00:00:00+00:00", None, None,
            ),
        )

    queue = OperationQueue(database_path=database)
    existing = queue.list_operations()["items"][0]
    agent_queue = AgentQueue(database)

    assert existing["details"] == "Keep this description"
    assert existing["priority"] == 7
    assert agent_queue.list_operations()["operations"][0]["description"] == (
        "Keep this description"
    )


@pytest.mark.parametrize("text", [
    r"C:\Users\person\Music\track.mp3",
    r"\\server\share\playlist.m3u",
    "/home/person/Music/track.flac",
])
def test_queue_rejects_local_paths(text, tmp_path):
    queue = OperationQueue(tmp_path)

    with pytest.raises(ValueError, match="local filesystem paths"):
        queue.enqueue("Batch work", details=f"Review {text}")


def test_queue_allows_urls_and_relative_descriptions(tmp_path):
    queue = OperationQueue(tmp_path)

    operation = queue.enqueue(
        "Review source",
        "Compare https://musicbrainz.org/release/123 and folder/notes",
        "review",
    )

    assert operation["status"] == "pending"
    assert operation["batch"] == "review"


def test_queue_validates_status_pagination_and_missing_id(tmp_path):
    queue = OperationQueue(tmp_path)

    with pytest.raises(ValueError, match="status must be"):
        queue.list_operations(status="unknown")
    with pytest.raises(ValueError, match="limit must be"):
        queue.list_operations(limit=501)
    with pytest.raises(ValueError, match="No queued operation"):
        queue.update("missing", "done")
