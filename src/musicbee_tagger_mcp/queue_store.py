"""Transactional persistence for path-free batch operations."""

import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .data_paths import ensure_data_subdirectory

_STATUSES = {"pending", "in_progress", "done", "blocked"}
_LOCAL_PATH = re.compile(
    r"(?<![\w])(?:[A-Za-z]:[\\/][^\s]*|\\\\[^\s\\]+\\[^\s]*"
    r"|(?<![:/])/(?:[^/\s]+/)*[^/\s]+)"
)


def default_queue_dir() -> Path:
    """Return the user's persistent queue directory."""
    return ensure_data_subdirectory("queue")


def _validate_text(value: str, field: str, required: bool = False) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text.")
    if required and not value.strip():
        raise ValueError(f"{field} must not be empty.")
    without_urls = re.sub(r"https?://\S+", "", value)
    if _LOCAL_PATH.search(without_urls):
        raise ValueError(f"{field} must not contain local filesystem paths.")


class OperationQueue:
    """Store durable batch operations in a local SQLite database."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = directory or default_queue_dir()
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise RuntimeError(
                "Unable to access the persistent operation queue."
            ) from None
        self.database = self.directory / "operations.sqlite3"
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operations (
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
                "CREATE INDEX IF NOT EXISTS operations_status_batch_created "
                "ON operations (status, batch, created_at)"
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self.database, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
        except (OSError, sqlite3.Error):
            raise RuntimeError(
                "Unable to access the persistent operation queue."
            ) from None
        try:
            yield connection
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise RuntimeError(
                "Unable to access the persistent operation queue."
            ) from None
        finally:
            connection.close()

    @staticmethod
    def _record(row: sqlite3.Row) -> dict:
        return dict(row)

    def enqueue(
        self, title: str, details: str = "", batch: Optional[str] = None
    ) -> dict:
        """Add one path-free operation and return its durable record."""
        _validate_text(title, "title", required=True)
        _validate_text(details, "details")
        batch_name = batch or ""
        _validate_text(batch_name, "batch")
        now = datetime.now(timezone.utc).isoformat()
        operation = {
            "operation_id": str(uuid.uuid4()),
            "batch": batch_name,
            "title": title,
            "details": details,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO operations
                    (operation_id, batch, title, details, status, created_at, updated_at)
                VALUES
                    (:operation_id, :batch, :title, :details, :status, :created_at, :updated_at)
                """,
                operation,
            )
        return operation

    def list_operations(
        self,
        status: Optional[str] = None,
        batch: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """Query operations with optional filters and bounded pagination."""
        if status is not None and status not in _STATUSES:
            raise ValueError("status must be pending, in_progress, done, or blocked.")
        if batch is not None:
            _validate_text(batch, "batch")
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be zero or greater.")

        filters = []
        parameters = []
        if status is not None:
            filters.append("status = ?")
            parameters.append(status)
        if batch is not None:
            filters.append("batch = ?")
            parameters.append(batch)
        where = f" WHERE {' AND '.join(filters)}" if filters else ""
        with self._connection() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM operations{where}", parameters
            ).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM operations{where} "
                "ORDER BY created_at, operation_id LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
        return {
            "items": [self._record(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def update(
        self, operation_id: str, status: str, details: Optional[str] = None
    ) -> dict:
        """Update an operation's status and optional progress details."""
        if status not in _STATUSES:
            raise ValueError("status must be pending, in_progress, done, or blocked.")
        if details is not None:
            _validate_text(details, "details")
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            if details is None:
                cursor = connection.execute(
                    "UPDATE operations SET status = ?, updated_at = ? "
                    "WHERE operation_id = ?",
                    (status, now, operation_id),
                )
            else:
                cursor = connection.execute(
                    "UPDATE operations SET status = ?, details = ?, updated_at = ? "
                    "WHERE operation_id = ?",
                    (status, details, now, operation_id),
                )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"No queued operation found for operation_id: {operation_id}"
                )
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
        return self._record(row)
