"""MCP tools for coordinating long-running work between agents."""

from typing import Any, Dict, Optional

from ..operation_queue import get_operation_queue


def _enqueue_operation(
    title: str, description: str, priority: int = 0
) -> Dict[str, Any]:
    return get_operation_queue().enqueue(title, description, priority)


def _list_operations(status: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    return get_operation_queue().list_operations(status, limit)


def _claim_operations(worker_id: str, size: int = 10) -> Dict[str, Any]:
    return get_operation_queue().claim_batch(worker_id, size)


def _complete_operation(
    operation_id: str,
    worker_id: str,
    success: bool,
    result: Optional[str] = None,
) -> Dict[str, Any]:
    return get_operation_queue().complete(operation_id, worker_id, success, result)


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
