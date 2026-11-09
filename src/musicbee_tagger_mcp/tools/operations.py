"""MCP tools for coordinating long-running work between agents."""

from typing import Any, Dict, Optional

from ..error_codes import E_INVALID_INPUT, make_error, redact_paths
from ..operation_queue import get_operation_queue


def _enqueue_operation(
    title: str, description: str, priority: int = 0
) -> Dict[str, Any]:
    response = get_operation_queue().enqueue(title, description, priority)
    if isinstance(response, dict) and "error" in response and "error_code" not in response:
        return make_error(
            E_INVALID_INPUT,
            redact_paths(response["error"]),
            function="enqueue_operation",
        )
    return response


def _list_operations(status: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    response = get_operation_queue().list_operations(status, limit)
    if isinstance(response, dict) and "error" in response and "error_code" not in response:
        return make_error(
            E_INVALID_INPUT,
            redact_paths(response["error"]),
            function="list_operations",
        )
    return response


def _claim_operations(worker_id: str, size: int = 10) -> Dict[str, Any]:
    return get_operation_queue().claim_batch(worker_id, size)


def _complete_operation(
    operation_id: str,
    worker_id: str,
    success: bool,
    result: Optional[str] = None,
) -> Dict[str, Any]:
    response = get_operation_queue().complete(operation_id, worker_id, success, result)
    if isinstance(response, dict) and "error" in response and "error_code" not in response:
        return make_error(
            E_INVALID_INPUT,
            redact_paths(response["error"]),
            function="complete_operation",
        )
    return response


try:
    from .queue import (
        enqueue_batch_operation,
        list_batch_operations,
        register_queue_tools as register_batch_operation_tools,
        update_batch_operation,
    )
except Exception:  # pragma: no cover
    pass

# Module-level aliases so the wrappers are importable/testable without
# registering them on an MCP app.
enqueue_operation = _enqueue_operation
list_operations = _list_operations
claim_operations = _claim_operations
complete_operation = _complete_operation

def register_operation_tools(app) -> None:
    @app.tool()
    def enqueue_operation(
        title: str, description: str, priority: int = 0
    ) -> Dict[str, Any]:
        """Add a path-free operation to the persistent shared queue."""
        return _enqueue_operation(title, description, priority)

    @app.tool()
    def list_operations(status: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """Query queued work, optionally filtered by status."""
        return _list_operations(status, limit)

    @app.tool()
    def claim_operations(worker_id: str, size: int = 10) -> Dict[str, Any]:
        """Atomically claim a batch of pending operations for this agent."""
        return _claim_operations(worker_id, size)

    @app.tool()
    def complete_operation(
        operation_id: str,
        worker_id: str,
        success: bool,
        result: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record an operation outcome; only its claiming agent can complete it."""
        return _complete_operation(operation_id, worker_id, success, result)
