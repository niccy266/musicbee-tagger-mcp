"""MCP tools for shared, persistent batch-operation tracking."""

from typing import Any, Dict, List, Optional

from ..queue_store import OperationQueue

_queue: Optional[OperationQueue] = None


def _get_queue() -> OperationQueue:
    global _queue
    if _queue is None:
        _queue = OperationQueue()
    return _queue


def enqueue_batch_operation(
    title: str, details: str = "", batch: Optional[str] = None
) -> Dict[str, Any]:
    """Add a path-free operation to the persistent shared batch queue."""
    return _get_queue().enqueue(title=title, details=details, batch=batch)


def list_batch_operations(
    status: Optional[str] = None,
    batch: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Query shared batch operations by status or batch, with pagination."""
    return _get_queue().list_operations(
        status=status, batch=batch, limit=limit, offset=offset
    )


def update_batch_operation(
    operation_id: str, status: str, details: Optional[str] = None
) -> Dict[str, Any]:
    """Update a queued operation's status and optional progress details."""
    return _get_queue().update(
        operation_id=operation_id, status=status, details=details
    )


def register_queue_tools(app) -> None:
    app.tool()(enqueue_batch_operation)
    app.tool()(list_batch_operations)
    app.tool()(update_batch_operation)
