"""Unit tests for tools/operations.py."""

from unittest.mock import MagicMock

from musicbee_tagger_mcp.tools.operations import (
    enqueue_operation,
    list_operations,
    claim_operations,
    complete_operation,
    register_operation_tools,
)


def test_enqueue_operation_success(monkeypatch):
    mock_queue = MagicMock()
    mock_queue.enqueue.return_value = {"operation_id": "op-1", "status": "pending"}
    monkeypatch.setattr(
        "musicbee_tagger_mcp.tools.operations.get_operation_queue",
        lambda: mock_queue,
    )
    res = enqueue_operation("Fix tags", "Fix album tags", priority=1)
    assert res == {"operation_id": "op-1", "status": "pending"}
    mock_queue.enqueue.assert_called_once_with("Fix tags", "Fix album tags", 1)


def test_enqueue_operation_error_wraps_error_code(monkeypatch):
    mock_queue = MagicMock()
    mock_queue.enqueue.return_value = {"error": "Invalid title at C:\\secret\\file.mp3"}
    monkeypatch.setattr(
        "musicbee_tagger_mcp.tools.operations.get_operation_queue",
        lambda: mock_queue,
    )
    res = enqueue_operation("", "desc")
    assert res["error_code"] == "E_INVALID_INPUT"
    assert "C:\\secret" not in res["error"]


def test_list_operations_success_and_error(monkeypatch):
    mock_queue = MagicMock()
    mock_queue.list_operations.return_value = {"operations": []}
    monkeypatch.setattr(
        "musicbee_tagger_mcp.tools.operations.get_operation_queue",
        lambda: mock_queue,
    )
    assert list_operations(status="pending", limit=10) == {"operations": []}

    mock_queue.list_operations.return_value = {"error": "Bad status"}
    res = list_operations(status="bogus")
    assert res["error_code"] == "E_INVALID_INPUT"


def test_claim_and_complete_operations(monkeypatch):
    mock_queue = MagicMock()
    mock_queue.claim_batch.return_value = {"claimed": [{"id": "op-1"}]}
    mock_queue.complete.return_value = {"status": "completed"}
    monkeypatch.setattr(
        "musicbee_tagger_mcp.tools.operations.get_operation_queue",
        lambda: mock_queue,
    )
    assert claim_operations("worker-1", 5) == {"claimed": [{"id": "op-1"}]}
    assert complete_operation("op-1", "worker-1", True, "done") == {"status": "completed"}

    mock_queue.complete.return_value = {"error": "Not claimed by worker"}
    res = complete_operation("op-1", "worker-2", False)
    assert res["error_code"] == "E_INVALID_INPUT"


def test_register_operation_tools(monkeypatch):
    mock_queue = MagicMock()
    mock_queue.enqueue.return_value = {"operation_id": "op-1"}
    mock_queue.list_operations.return_value = {"operations": []}
    mock_queue.claim_batch.return_value = {"claimed": []}
    mock_queue.complete.return_value = {"status": "completed"}
    monkeypatch.setattr(
        "musicbee_tagger_mcp.tools.operations.get_operation_queue",
        lambda: mock_queue,
    )

    class FakeApp:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def decorator(fn):
                self.tools[fn.__name__] = fn
                return fn
            return decorator

    app = FakeApp()
    register_operation_tools(app)
    assert set(app.tools) == {
        "enqueue_operation",
        "list_operations",
        "claim_operations",
        "complete_operation",
    }
    assert app.tools["enqueue_operation"]("t", "d", 1) == {"operation_id": "op-1"}
    assert app.tools["list_operations"]("pending", 5) == {"operations": []}
    assert app.tools["claim_operations"]("w-1", 2) == {"claimed": []}
    assert app.tools["complete_operation"]("op-1", "w-1", True, "ok") == {
        "status": "completed"
    }
