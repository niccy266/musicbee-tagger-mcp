"""Transactional persistence for path-free batch operations."""

import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .data_paths import ensure_data_subdirectory

_STATUSES = {"pending", "in_progress", "done", "blocked", "failed"}
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
    """Store durable operations in one queue shared by all MCP agents."""

    def __init__(
        self,
        directory: Optional[Path] = None,
        database_path: Optional[Path] = None,
    ) -> None:
        self.directory = directory or (
            database_path.parent if database_path is not None else default_queue_dir()
        )
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise RuntimeError(
                "Unable to access the persistent operation queue."
            ) from None
        self.database = database_path or self.directory / "operations.sqlite3"
        self._initialize()

    @staticmethod
    def _create_operations_table(connection: sqlite3.Connection, name: str) -> None:
        connection.execute(
            f"""
            CREATE TABLE {name} (
                operation_id TEXT PRIMARY KEY,
                batch TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                priority INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                claimed_by TEXT,
                result TEXT
            )
            """
        )

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'operations'"
            ).fetchone()
            if table is None:
                self._create_operations_table(connection, "operations")
            else:
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(operations)"
                    )
                }
                required = {
                    "operation_id", "batch", "title", "details", "priority",
                    "status", "created_at", "updated_at", "claimed_by", "result",
                }
                if not required.issubset(columns):
                    rows = connection.execute("SELECT * FROM operations").fetchall()
                    connection.execute("DROP TABLE IF EXISTS operations_migrating")
                    self._create_operations_table(connection, "operations_migrating")
                    for row in rows:
                        values = dict(row)
                        connection.execute(
                            """
                            INSERT INTO operations_migrating
                                (operation_id, batch, title, details, priority, status,
                                 created_at, updated_at, claimed_by, result)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                values["operation_id"],
                                values.get("batch", ""),
                                values["title"],
                                values.get("details", values.get("description", "")),
                                values.get("priority", 0),
                                values["status"],
                                values["created_at"],
                                values["updated_at"],
                                values.get("claimed_by"),
                                values.get("result"),
                            ),
                        )
                    connection.execute("DROP TABLE operations")
                    connection.execute(
                        "ALTER TABLE operations_migrating RENAME TO operations"
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
        self,
        title: str,
        details: str = "",
        batch: Optional[str] = None,
        priority: int = 0,
    ) -> dict:
        """Add one path-free operation and return its durable record."""
        _validate_text(title, "title", required=True)
        _validate_text(details, "details")
        batch_name = "" if batch is None else batch
        _validate_text(batch_name, "batch")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError("priority must be an integer.")
        if not -100 <= priority <= 100:
            raise ValueError("priority must be between -100 and 100.")
        now = datetime.now(timezone.utc).isoformat()
        operation = {
            "operation_id": str(uuid.uuid4()),
            "batch": batch_name,
            "title": title,
            "details": details,
            "priority": priority,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "claimed_by": None,
            "result": None,
        }
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO operations
                    (operation_id, batch, title, details, priority, status,
                     created_at, updated_at, claimed_by, result)
                VALUES
                    (:operation_id, :batch, :title, :details, :priority, :status,
                     :created_at, :updated_at, :claimed_by, :result)
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
        if status is not None and (
            not isinstance(status, str) or status not in _STATUSES
        ):
            raise ValueError(f"status must be one of: {', '.join(sorted(_STATUSES))}.")
        if batch is not None:
            _validate_text(batch, "batch")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
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
                "ORDER BY priority DESC, created_at, operation_id LIMIT ? OFFSET ?",
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
        if not isinstance(status, str) or status not in _STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(_STATUSES))}.")
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

    def claim_batch(self, worker_id: str, size: int = 10) -> dict:
        """Atomically assign pending operations to one agent."""
        _validate_text(worker_id, "worker_id", required=True)
        if len(worker_id) > 100:
            raise ValueError("worker_id must be at most 100 characters.")
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 50:
            raise ValueError("batch size must be between 1 and 50.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM operations WHERE status = 'pending'
                ORDER BY priority DESC, created_at, operation_id LIMIT ?
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
                [(worker_id, now, operation_id) for operation_id in ids],
            )
            remaining = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE status = 'pending'"
            ).fetchone()[0]
        claimed = []
        for row in rows:
            item = self._record(row)
            item.update(status="in_progress", claimed_by=worker_id, updated_at=now)
            claimed.append(item)
        return {"operations": claimed, "remaining": remaining}

    def complete(
        self,
        operation_id: str,
        worker_id: str,
        success: bool,
        result: Optional[str] = None,
    ) -> dict:
        """Record an outcome only when called by the agent holding the claim."""
        try:
            normalized_id = str(uuid.UUID(operation_id))
        except (TypeError, ValueError, AttributeError):
            return {"error": "Unknown operation or worker"}
        _validate_text(worker_id, "worker_id", required=True)
        if len(worker_id) > 100:
            raise ValueError("worker_id must be at most 100 characters.")
        if not isinstance(success, bool):
            raise ValueError("success must be a boolean.")
        if result is not None:
            _validate_text(result, "result")
            if len(result) > 2000:
                raise ValueError("result must be at most 2000 characters.")
        status = "done" if success else "failed"
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE operations
                SET status = ?, result = ?, updated_at = ?
                WHERE operation_id = ? AND status = 'in_progress' AND claimed_by = ?
                """,
                (status, result, now, normalized_id, worker_id),
            )
        if cursor.rowcount != 1:
            return {"error": "Unknown operation or worker"}
        return {"operation_id": normalized_id, "status": status}
