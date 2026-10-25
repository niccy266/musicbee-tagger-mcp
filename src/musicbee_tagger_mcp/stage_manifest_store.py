"""Filesystem persistence for pending tag-change manifests."""

import errno
import importlib
import json
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, List, Optional

from .data_paths import ensure_data_subdirectory

_MUTATION_LOCK = threading.RLock()


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
                import msvcrt

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
                    pending.append({
                        "stage_id": manifest["stage_id"],
                        "display_name": manifest["display_name"],
                        "created_at": manifest["created_at"],
                        "revision": manifest.get("revision", 1),
                        "diff_summary": manifest.get("diff", []),
                        "forensic_score": manifest.get("forensic_score"),
                        "deferred": bool(manifest.get("deferred", False)),
                        "deferred_at": manifest.get("deferred_at"),
                    })
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
