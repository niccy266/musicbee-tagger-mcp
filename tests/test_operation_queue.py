"""Tests for persistent operation coordination between MCP agents."""

import json

from musicbee_tagger_mcp.operation_queue import OperationQueue


def test_operations_persist_and_can_be_queried_by_another_agent(tmp_path):
    database = tmp_path / "queue" / "operations.sqlite3"
    first_agent = OperationQueue(database)
    created = first_agent.enqueue("Review metadata", "Investigate tokens A and B")

    second_agent = OperationQueue(database)
    result = second_agent.list_operations(status="pending")

    assert result["operations"][0]["operation_id"] == created["operation_id"]
    assert result["operations"][0]["description"] == "Investigate tokens A and B"
    assert str(tmp_path) not in json.dumps(result)


def test_batches_are_claimed_once_and_only_owner_can_complete(tmp_path):
    database = tmp_path / "queue.sqlite3"
    queue_one = OperationQueue(database)
    queue_two = OperationQueue(database)
    one = queue_one.enqueue("First", "First operation")
    two = queue_one.enqueue("Second", "Second operation")

    claimed = queue_one.claim_batch("agent-a", size=1)
    assert [item["operation_id"] for item in claimed["operations"]] == [one["operation_id"]]
    assert claimed["remaining"] == 1
    assert queue_two.claim_batch("agent-b", size=10)["operations"][0]["operation_id"] == two["operation_id"]

    assert queue_two.complete(one["operation_id"], "agent-b", True)["error"]
    assert queue_two.complete(one["operation_id"], "agent-a", True, "Verified") == {
        "operation_id": one["operation_id"],
        "status": "done",
    }
    assert queue_one.list_operations("done")["operations"][0]["result"] == "Verified"


def test_queue_rejects_paths_and_invalid_filters(tmp_path):
    queue = OperationQueue(tmp_path / "queue.sqlite3")

    assert "filesystem paths" in queue.enqueue("Inspect", r"Use K:\Music\secret.mp3")["error"]
    assert "filesystem paths" in queue.enqueue("Inspect", "Read /home/user/secret.mp3")["error"]
    assert "filesystem paths" in queue.enqueue("Inspect", "Read /secret.mp3")["error"]
    operation = queue.enqueue("Inspect", "Read token metadata")
    claimed = queue.claim_batch("agent")["operations"][0]
    assert "filesystem paths" in queue.complete(
        operation["operation_id"], "agent", True, r"K:\secret.mp3"
    )["error"]
    assert "status must be one of" in queue.list_operations("unknown")["error"]
    assert claimed["operation_id"] == operation["operation_id"]


def test_mcp_tools_include_shared_batch_queue(tmp_path, monkeypatch):
    import inspect

    class FakeApp:
        def __init__(self):
            self.tools = []

        def resource(self, *args, **kwargs):
            def decorate(function):
                return function
            return decorate

        def tool(self, *args, **kwargs):
            def decorate(function):
                self.tools.append(function)
                return function
            return decorate

    from musicbee_tagger_mcp.queue_store import OperationQueue
    from musicbee_tagger_mcp.tools import register_tools

    app = FakeApp()
    queue = OperationQueue(tmp_path)
    monkeypatch.setattr(
        "musicbee_tagger_mcp.tools.queue._get_queue", lambda: queue
    )
    register_tools(app)
    tools = {tool.__name__: tool for tool in app.tools}
    names = set(tools)
    assert {
        "enqueue_batch_operation",
        "list_batch_operations",
        "update_batch_operation",
    } <= names
    for tool in app.tools:
        assert not any(
            word in parameter.lower()
            for parameter in inspect.signature(tool).parameters
            for word in ("path", "file", "directory")
        )
    queued = tools["enqueue_batch_operation"]("Queued", "Process a token batch")
    assert tools["list_batch_operations"]()["items"][0]["operation_id"] == queued[
        "operation_id"
    ]
    updated = tools["update_batch_operation"](queued["operation_id"], "in_progress")
    assert updated["status"] == "in_progress"
