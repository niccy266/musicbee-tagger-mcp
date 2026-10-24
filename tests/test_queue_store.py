"""Tests for durable, path-free batch-operation tracking."""

import pytest

from musicbee_tagger_mcp.queue_store import OperationQueue, default_queue_dir


def test_default_queue_dir_uses_configured_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSICBEE_TAGGER_DATA_DIR", str(tmp_path / "private-data"))

    assert default_queue_dir() == tmp_path / "private-data" / "queue"
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
