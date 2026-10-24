"""Persistent, path-free queue for work shared by MCP agents."""

import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .data_paths import ensure_data_subdirectory

STATUSES = ("pending", "in_progress", "done", "failed")
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)")
_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9:/])/(?!/)[^\s]+")


def default_queue_path() -> Path:
    """Return the shared operation queue database path."""
    return ensure_data_subdirectory("queue") / "operations.sqlite3"


class OperationQueue:
    """Store and coordinate path-free operations across server restarts."""

    def __init__(self, database_path: Optional[Path] = None) -> None:
        self.database_path = database_path

    def _path(self) -> Path:
        return self.database_path or default_queue_path()

    def _connect(self) -> sqlite3.Connection:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS operations (
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
        return connection

    @staticmethod
    def _validate_safe_text(value: Any, field: str, max_length: int) -> Optional[str]:
        if not isinstance(value, str) or not value.strip():
            return f"{field} must be a non-empty string"
        if len(value) > max_length:
            return f"{field} must be at most {max_length} characters"
        if _WINDOWS_PATH.search(value) or _POSIX_PATH.search(value):
            return f"{field} must not contain filesystem paths"
        return None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _item(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "operation_id": row["operation_id"],
            "title": row["title"],
            "description": row["description"],
            "priority": row["priority"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "claimed_by": row["claimed_by"],
            "result": row["result"],
        }

    def enqueue(
        self, title: str, description: str, priority: int = 0
    ) -> Dict[str, Any]:
        for value, field, max_length in (
            (title, "title", 200),
            (description, "description", 2000),
        ):
            error = self._validate_safe_text(value, field, max_length)
            if error:
                return {"error": error}
        if isinstance(priority, bool) or not isinstance(priority, int):
            return {"error": "priority must be an integer"}
        if priority < -100 or priority > 100:
            return {"error": "priority must be between -100 and 100"}

        operation_id = str(uuid.uuid4())
        now = self._now()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO operations
                        (operation_id, title, description, priority, status,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        operation_id,
                        title.strip(),
                        description.strip(),
                        priority,
                        now,
                        now,
                    ),
                )
        except (OSError, sqlite3.Error):
            return {"error": "Unable to save operation to the persistent queue"}
        return {"operation_id": operation_id, "status": "pending", "created_at": now}

    def list_operations(
        self, status: Optional[str] = None, limit: int = 50
    ) -> Dict[str, Any]:
        if status is not None and status not in STATUSES:
            return {"error": f"status must be one of: {', '.join(STATUSES)}"}
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            return {"error": "limit must be between 1 and 100"}

        try:
            with self._connect() as connection:
                if status is None:
                    rows = connection.execute(
                        """
                        SELECT * FROM operations
                        ORDER BY priority DESC, created_at ASC LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT * FROM operations WHERE status = ?
                        ORDER BY priority DESC, created_at ASC LIMIT ?
                        """,
                        (status, limit),
                    ).fetchall()
        except (OSError, sqlite3.Error):
            return {"error": "Unable to read the persistent operation queue"}
        return {"operations": [self._item(row) for row in rows]}

    def claim_batch(self, worker_id: str, size: int = 10) -> Dict[str, Any]:
        error = self._validate_safe_text(worker_id, "worker_id", 100)
        if error:
            return {"error": error}
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 50:
            return {"error": "batch size must be between 1 and 50"}

        now = self._now()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    """
                    SELECT * FROM operations WHERE status = 'pending'
                    ORDER BY priority DESC, created_at ASC LIMIT ?
                    """,
                    (size,),
                ).fetchall()
                ids = [row["operation_id"] for row in rows]
                connection.executemany(
                    """
                    UPDATE operations
                    SET status = 'in_progress', claimed_by = ?, updated_at = ?
                    WHERE operation_id = ? AND status = 'pending'
                    """,
                    [(worker_id.strip(), now, operation_id) for operation_id in ids],
                )
                remaining = connection.execute(
                    "SELECT COUNT(*) AS count FROM operations WHERE status = 'pending'"
                ).fetchone()["count"]
        except (OSError, sqlite3.Error):
            return {"error": "Unable to claim operations from the persistent queue"}
        claimed = []
        for row in rows:
            item = dict(self._item(row))
            item.update(status="in_progress", claimed_by=worker_id.strip(), updated_at=now)
            claimed.append(item)
        return {"operations": claimed, "remaining": int(remaining)}

    def complete(
        self,
        operation_id: str,
        worker_id: str,
        success: bool,
        result: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            normalized_id = str(uuid.UUID(operation_id))
        except (TypeError, ValueError, AttributeError):
            return {"error": "Unknown operation or worker"}
        error = self._validate_safe_text(worker_id, "worker_id", 100)
        if error:
            return {"error": error}
        if not isinstance(success, bool):
            return {"error": "success must be a boolean"}
        if result is not None:
            if not isinstance(result, str):
                return {"error": "result must be a string"}
            if len(result) > 2000:
                return {"error": "result must be at most 2000 characters"}
            if _WINDOWS_PATH.search(result) or _POSIX_PATH.search(result):
                return {"error": "result must not contain filesystem paths"}

        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE operations
                    SET status = ?, result = ?, updated_at = ?
                    WHERE operation_id = ? AND status = 'in_progress' AND claimed_by = ?
                    """,
                    (
                        "done" if success else "failed",
                        result,
                        self._now(),
                        normalized_id,
                        worker_id.strip(),
                    ),
                )
        except (OSError, sqlite3.Error):
            return {"error": "Unable to update the persistent operation queue"}
        if cursor.rowcount != 1:
            return {"error": "Unknown operation or worker"}
        return {"operation_id": normalized_id, "status": "done" if success else "failed"}


def get_operation_queue() -> OperationQueue:
    """Return the shared queue backed by the configured private data directory."""
    return OperationQueue()
