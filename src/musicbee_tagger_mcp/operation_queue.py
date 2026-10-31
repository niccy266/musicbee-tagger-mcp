"""Compatibility API for shared, persistent work coordination between agents."""

import re
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from .queue_store import OperationQueue as _PersistentQueue, default_queue_dir
from .error_codes import redact_paths

_STATUSES = {"pending", "in_progress", "done", "blocked", "failed"}
_LOCAL_PATH = re.compile(
    r"(?<![\w])(?:[A-Za-z]:[\\/][^\s]*|\\\\[^\s\\]+\\[^\s]*"
    r"|(?<![:/])/(?:[^/\s]+/)*[^/\s]+)"
)


def default_queue_path() -> Path:
    """Return the database path shared by all queue tools."""
    return default_queue_dir() / "operations.sqlite3"


def _safe_text(value: Any, field: str, required: bool = False) -> Optional[str]:
    if not isinstance(value, str):
        return f"{field} must be a non-empty string" if required else f"{field} must be text"
    if required and not value.strip():
        return f"{field} must be a non-empty string"
    without_urls = re.sub(r"https?://\S+", "", value)
    if _LOCAL_PATH.search(without_urls):
        return f"{field} must not contain filesystem paths"
    return None


class OperationQueue:
    """Expose the original operation API over the common persistent queue."""

    def __init__(self, database_path: Optional[Path] = None) -> None:
        self._queue = _PersistentQueue(database_path=database_path)

    def enqueue(
        self, title: str, description: str, priority: int = 0
    ) -> Dict[str, Any]:
        for value, field, maximum in (
            (title, "title", 200),
            (description, "description", 2000),
        ):
            error = _safe_text(value, field, required=True)
            if error:
                return {"error": error}
            if len(value) > maximum:
                return {"error": f"{field} must be at most {maximum} characters"}
        if isinstance(priority, bool) or not isinstance(priority, int):
            return {"error": "priority must be an integer"}
        if not -100 <= priority <= 100:
            return {"error": "priority must be between -100 and 100"}
        try:
            operation = self._queue.enqueue(
                title.strip(), description.strip(), priority=priority
            )
        except ValueError as error:
            return {"error": redact_paths(str(error))}
        return {
            "operation_id": operation["operation_id"],
            "status": operation["status"],
            "created_at": operation["created_at"],
        }

    @staticmethod
    def _operation(item: Dict[str, Any]) -> Dict[str, Any]:
        return {**item, "description": item["details"]}

    def list_operations(
        self, status: Optional[str] = None, limit: int = 50
    ) -> Dict[str, Any]:
        if status is not None and (
            not isinstance(status, str) or status not in _STATUSES
        ):
            return {"error": f"status must be one of: {', '.join(sorted(_STATUSES))}"}
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            return {"error": "limit must be between 1 and 100"}
        try:
            result = self._queue.list_operations(status=status, limit=limit)
        except ValueError as error:
            return {"error": redact_paths(str(error))}
        return {"operations": [self._operation(item) for item in result["items"]]}

    def claim_batch(self, worker_id: str, size: int = 10) -> Dict[str, Any]:
        error = _safe_text(worker_id, "worker_id", required=True)
        if error:
            return {"error": error}
        if len(worker_id) > 100:
            return {"error": "worker_id must be at most 100 characters"}
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 50:
            return {"error": "batch size must be between 1 and 50"}
        try:
            result = self._queue.claim_batch(worker_id.strip(), size=size)
        except ValueError as error:
            return {"error": redact_paths(str(error))}
        return {
            "operations": [self._operation(item) for item in result["operations"]],
            "remaining": result["remaining"],
        }

    def complete(
        self,
        operation_id: str,
        worker_id: str,
        success: bool,
        result: Optional[str] = None,
    ) -> Dict[str, Any]:
        error = _safe_text(worker_id, "worker_id", required=True)
        if error:
            return {"error": error}
        if result is not None:
            error = _safe_text(result, "result")
            if error:
                return {"error": error}
        try:
            return self._queue.complete(
                operation_id, worker_id.strip(), success, result
            )
        except ValueError as error:
            return {"error": redact_paths(str(error))}


def get_operation_queue() -> OperationQueue:
    """Return the queue backed by the configured private data directory."""
    return OperationQueue()
