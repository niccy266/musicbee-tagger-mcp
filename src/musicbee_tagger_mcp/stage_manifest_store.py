"""Filesystem persistence for pending tag-change manifests."""

import errno
import importlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, List, Optional

from .data_paths import ensure_data_subdirectory

_LOCAL_PATH = re.compile(
    r"(?<![\w])(?:[A-Za-z]:[\/][^\s]*|\\[^\s\]+\[^\s]*"
    r"|(?<![:/])/(?:[^/\s]+/)*[^/\s]+)"
)

_MUTATION_LOCK = threading.RLock()


def _status(manifest: dict) -> str:
    if manifest.get("applied"):
        return "applied"
    if manifest.get("withdrawn"):
        return "withdrawn"
    if manifest.get("archived"):
        return "archived"
    if manifest.get("failed"):
        return "failed"
    return "pending"


def _summary(manifest: dict) -> dict:
    notes = manifest.get("notes", "")
    if not isinstance(notes, str):
        notes = "" if notes is None else str(notes)
    token = manifest.get("token")
    job_id = manifest.get("job_id")
    batch = manifest.get("batch")
    return {
        "stage_id": manifest["stage_id"],
        "display_name": manifest["display_name"],
        "file": manifest["display_name"],
        "file_identity": manifest["display_name"],
        "filename": manifest["display_name"],
        "token": token,
        "file_token": token,
        "job_id": job_id,
        "job": job_id,
        "batch": batch,
        "status": _status(manifest),
        "created_at": manifest.get("created_at"),
        "updated_at": manifest.get("updated_at", manifest.get("created_at")),
        "applied_at": manifest.get("applied_at"),
        "withdrawn_at": manifest.get("withdrawn_at"),
        "failed_at": manifest.get("failed_at"),
        "archived_at": manifest.get("archived_at"),
        "revision": manifest.get("revision", 1),
        "notes": notes,
        "note": manifest.get("note", notes),
        "rationale": manifest.get("rationale", notes),
        "diff_summary": manifest.get("diff", []),
        "forensic_score": manifest.get("forensic_score"),
        "match_source": manifest.get("match_source"),
        "match_confidence": manifest.get("match_confidence"),
        "deferred": bool(manifest.get("deferred", False)),
        "deferred_at": manifest.get("deferred_at"),
        "mb_recording_id": manifest.get("mb_recording_id"),
        "mb_release_id": manifest.get("mb_release_id"),
    }


def default_staging_dir() -> Path:
    """Return the user's persistent staging directory."""
    return ensure_data_subdirectory("staged")


class StageManifestStore:
    """Read and write manifest JSON while keeping path handling internal."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = directory or default_staging_dir()

    def save(self, manifest: dict) -> None:
        """Atomically persist one staged-change manifest."""
        path = self._manifest_path(manifest["stage_id"])
        temporary_path = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.directory,
                delete=False, suffix=".tmp",
            ) as temporary:
                json.dump(manifest, temporary, indent=2, ensure_ascii=False)
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, path)
        except OSError:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise RuntimeError("Unable to save staged change.") from None

    def load(self, stage_id: str) -> dict:
        """Load a manifest by its stage identifier."""
        path = self._manifest_path(stage_id)
        if not path.exists():
            raise FileNotFoundError(f"No staged change found for stage_id: {stage_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def mutate(self, stage_id: str, update: Callable[[dict], None]) -> dict:
        """Update one manifest atomically across threads and local processes."""
        manifest, _ = self.transact(stage_id, update)
        return manifest

    def transact(self, stage_id: str, action: Callable[[dict], object]) -> tuple[dict, object]:
        """Run an action against a manifest under its cross-process lock."""
        with self._mutation_lock():
            manifest = self.load(stage_id)
            result = action(manifest)
            self.save(manifest)
            return manifest, result

    @contextmanager
    def _mutation_lock(self) -> Iterator[None]:
        """Lock manifest mutations across MCP and CLI processes on this machine."""
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_path = self.directory / ".manifest.lock"
        with _MUTATION_LOCK, lock_path.open("a+b") as lock_file:
            if os.name == "nt":
                msvcrt = importlib.import_module("msvcrt")

                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"0")
                    lock_file.flush()
                lock_file.seek(0)
                while True:
                    lock_file.seek(0)
                    try:
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as error:
                        if (
                            error.errno not in (errno.EACCES, errno.EDEADLK)
                            and getattr(error, "winerror", None) not in (33, 36)
                        ):
                            raise
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _manifest_path(self, stage_id: str) -> Path:
        try:
            normalized_id = str(uuid.UUID(stage_id))
        except (TypeError, ValueError, AttributeError):
            raise ValueError("stage_id must be a valid stage UUID.") from None
        return self.directory / f"{normalized_id}.json"

    def list_pending(self) -> List[dict]:
        """Return only path-free summaries of manifests not yet applied."""
        pending = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if (
                    not manifest.get("applied", False)
                    and not manifest.get("withdrawn", False)
                    and not manifest.get("failed", False)
                    and not manifest.get("archived", False)
                ):
                    item = _summary(manifest)
                    pending.append(item)
            except Exception:
                continue
        return sorted(
            pending,
            key=lambda item: (
                item["deferred"],
                item["deferred_at"] or item["created_at"],
                item["stage_id"],
            ),
        )

    def _valid_statuses(self):
        return {"pending", "applied", "withdrawn", "failed", "archived"}

    def list_staged_changes(
        self,
        status=None,
        token=None,
        file=None,
        file_identity=None,
        display_name=None,
        filename=None,
        job_id=None,
        job=None,
        batch=None,
        query=None,
        search=None,
        text=None,
        limit=100,
        offset=0,
        **kwargs,
    ):
        if status is None:
            status_filter = None
        elif isinstance(status, str):
            lowered = status.strip().lower()
            if lowered in ("all", "*", "any"):
                status_filter = "all"
            elif lowered in self._valid_statuses():
                status_filter = [lowered]
            else:
                raise ValueError(
                    "status must be one of: "
                    + ", ".join(sorted(self._valid_statuses()))
                    + ", or 'all'."
                )
        elif isinstance(status, (list, tuple, set)):
            values = [str(item).strip().lower() for item in status]
            if any(value not in self._valid_statuses() for value in values):
                raise ValueError(
                    "status must be one of: "
                    + ", ".join(sorted(self._valid_statuses()))
                    + "."
                )
            status_filter = values
        else:
            raise ValueError("status must be text or a list of statuses.")

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be zero or greater.")

        # Accept aliases from kwargs.
        if token is None:
            token = kwargs.get("token") or kwargs.get("file_token")
        if file is None:
            file = kwargs.get("file")
        if file_identity is None:
            file_identity = kwargs.get("file_identity")
        if display_name is None:
            display_name = kwargs.get("display_name")
        if filename is None:
            filename = kwargs.get("filename")
        if job_id is None:
            job_id = kwargs.get("job_id") or kwargs.get("job")
        if batch is None:
            batch = kwargs.get("batch")
        if query is None:
            query = kwargs.get("query")
        if search is None:
            search = kwargs.get("search")
        if text is None:
            text = kwargs.get("text")

        file_filter = file or file_identity or display_name or filename
        job_filter = job_id or job
        query_filter = query or search or text

        manifests = []
        try:
            paths = sorted(self.directory.glob("*.json"))
        except Exception:
            paths = []
        for path in paths:
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(manifest, dict):
                continue
            manifests.append(manifest)

        filtered = []
        for manifest in manifests:
            manifest_status = _status(manifest)
            if status_filter not in (None, "all"):
                if isinstance(status_filter, list):
                    if manifest_status not in status_filter:
                        continue
                elif manifest_status != status_filter:
                    continue

            if token is not None:
                manifest_token = manifest.get("token")
                if str(token).lower() not in str(manifest_token or "").lower():
                    continue
            if file_filter is not None:
                name = str(manifest.get("display_name") or "")
                if str(file_filter).lower() not in name.lower():
                    continue
            if job_filter is not None:
                value = str(manifest.get("job_id") or "")
                if str(job_filter).lower() not in value.lower():
                    continue
            if batch is not None:
                value = str(manifest.get("batch") or "")
                if str(batch).lower() not in value.lower():
                    continue
            if query_filter is not None:
                haystack_parts = [
                    manifest.get("stage_id"),
                    manifest.get("display_name"),
                    manifest.get("token"),
                    manifest.get("job_id"),
                    manifest.get("batch"),
                    manifest.get("notes"),
                    manifest.get("note"),
                    manifest.get("rationale"),
                    manifest.get("mb_recording_id"),
                    manifest.get("mb_release_id"),
                    manifest.get("match_source"),
                    manifest_status,
                ]
                for item in manifest.get("diff", []) or []:
                    if isinstance(item, dict):
                        haystack_parts.extend(
                            [item.get("field"), item.get("old"), item.get("new")]
                        )
                haystack = " ".join(
                    "" if part is None else str(part) for part in haystack_parts
                ).lower()
                if str(query_filter).lower() not in haystack:
                    continue

            filtered.append(manifest)

        filtered.sort(
            key=lambda item: (
                str(item.get("created_at") or ""),
                str(item.get("stage_id") or ""),
            )
        )

        total = len(filtered)
        page = filtered[offset : offset + limit]
        return {
            "items": [_summary(manifest) for manifest in page],
            "total": total,
            "limit": limit,
            "offset": offset,
            "statuses": sorted(self._valid_statuses()),
        }

    # Backward/alias method names.
    def list(self, *args, **kwargs):
        return self.list_staged_changes(*args, **kwargs)

    def list_all(self, *args, **kwargs):
        return self.list_staged_changes(status="all", *args, **kwargs)

    def list_stages(self, *args, **kwargs):
        return self.list_staged_changes(*args, **kwargs)

    def search(self, *args, **kwargs):
        return self.list_staged_changes(*args, **kwargs)

    def search_staged_changes(self, *args, **kwargs):
        return self.list_staged_changes(*args, **kwargs)

    def list_staged(self, *args, **kwargs):
        return self.list_staged_changes(*args, **kwargs)

    def list_applied_with_backup(self) -> List[dict]:
        """Return path-free summaries of applied manifests that have a backup.

        These are the changes that can be reverted via :meth:`revert`.
        """
        applied = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if (
                    manifest.get("applied", False)
                    and not manifest.get("reverted", False)
                    and manifest.get("backup_path")
                ):
                    applied.append({
                        "stage_id": manifest["stage_id"],
                        "display_name": manifest["display_name"],
                        "applied_at": manifest.get("applied_at"),
                        "backup_path": manifest.get("backup_path"),
                        "diff_summary": manifest.get("diff", []),
                        "forensic_score": manifest.get("forensic_score"),
                        "notes": manifest.get("notes", ""),
                    })
            except Exception:
                continue
        return sorted(applied, key=lambda item: item.get("applied_at", "") or "")
