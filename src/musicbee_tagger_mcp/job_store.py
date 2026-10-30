"""Playlist job store: tracks per-token processing status in the private data dir.

A job is created when the MCP server registers a playlist server-side. The
agent only ever sees opaque tokens and bare display names; the playlist path
and file paths never leave this module's boundaries.

Job files are read and written under a cross-process lock (see
:class:`JobStore._mutation_lock`) so concurrent agents sharing one data
directory cannot claim overlapping tokens or lose status updates. Writes are
performed atomically (temp file + replace) to avoid partial reads.
"""

import importlib
import json
import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .data_paths import ensure_data_subdirectory

STATUSES = ("pending", "in_progress", "done", "failed", "skipped", "unresolved", "needs_review", "partial")

_MUTATION_LOCK = threading.RLock()


def default_jobs_dir() -> Path:
    """Return the persistent playlist-jobs directory."""
    return ensure_data_subdirectory("playlists")


class JobStore:
    """Create playlist jobs and hand out pending tokens in batches.

    Concurrent agents are supported when they share the same data directory:
    every load/save pair is serialized with a cross-process file lock, and
    ``next_batch`` claims tokens atomically. Interrupted runs can be recovered
    with ``release_batch`` (returning in-progress tokens to pending) or the
    agent loop's ``--resume`` flow.
    """

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = directory

    def _dir(self) -> Path:
        return self.directory or default_jobs_dir()

    @contextmanager
    def _mutation_lock(self) -> Any:
        """Serialize job reads/writes across threads and processes."""
        directory = self._dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise RuntimeError("Unable to access playlist jobs directory") from None
        lock_path = directory / ".jobs.lock"
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
                        if getattr(error, "errno", None) not in (None, 11, 13, 35):
                            raise RuntimeError("Unable to lock playlist jobs") from error
                        threading.Event().wait(0.05)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    try:
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
            else:
                fcntl = importlib.import_module("fcntl")
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _persist(self, path: Path, job: Dict[str, Any], error_message: str) -> None:
        temporary_path: Optional[Path] = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
            ) as temporary:
                json.dump(job, temporary, ensure_ascii=False, indent=2)
                temporary.flush()
                try:
                    os.fsync(temporary.fileno())
                except OSError:
                    pass
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, path)
        except OSError:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise RuntimeError(error_message) from None

    def _normalize_job_id(self, job_id: Any) -> str:
        try:
            return str(uuid.UUID(job_id))
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Unknown job id") from None

    def _load_job_unlocked(self, job_id: str) -> Dict[str, Any]:
        normalized = self._normalize_job_id(job_id)
        path = self._dir() / f"{normalized}.json"
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise ValueError("Unknown job id") from None
        if (
            not isinstance(job, dict)
            or job.get("job_id") != normalized
            or not isinstance(job.get("tracks"), list)
        ):
            raise ValueError("Unknown job id")
        return job

    def _save_unlocked(self, job: Dict[str, Any]) -> None:
        path = self._dir() / f"{job['job_id']}.json"
        self._persist(path, job, "Unable to update playlist job")

    def load_job(self, job_id: str) -> Dict[str, Any]:
        """Load a job by id, raising ValueError for unknown or malformed ids."""
        with self._mutation_lock():
            return self._load_job_unlocked(job_id)

    def _save(self, job: Dict[str, Any]) -> None:
        """Persist a job under the cross-process lock."""
        with self._mutation_lock():
            self._save_unlocked(job)

    def create_job(
        self, entries: List[Dict[str, Any]], playlist_name: str,
        skipped: int = 0, job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a job from registered token entries (plus skipped count)."""
        if job_id is None:
            normalized = str(uuid.uuid4())
        else:
            try:
                normalized = str(uuid.UUID(job_id))
            except (TypeError, ValueError, AttributeError):
                raise ValueError("Unknown job id") from None
        job = {
            "job_id": normalized,
            "playlist_name": playlist_name,
            "tracks": [
                {
                    "token": entry["token"],
                    "display_name": entry["display_name"],
                    "status": "pending",
                    "error": None,
                }
                for entry in entries
            ],
            "skipped": skipped,
        }
        path = self._dir() / f"{normalized}.json"
        with self._mutation_lock():
            self._persist(path, job, "Unable to save playlist job")
        return {
            "job_id": normalized,
            "registered": len(job["tracks"]),
            "skipped": skipped,
        }

    def add_track(
        self, job_id: str, token: str, display_name: str,
    ) -> Dict[str, Any]:
        with self._mutation_lock():
            job = self._load_job_unlocked(job_id)
            existing = {
                track["token"] for track in job["tracks"]
                if isinstance(track, dict) and isinstance(track.get("token"), str)
            }
            if token not in existing:
                job["tracks"].append(
                    {
                        "token": token,
                        "display_name": display_name,
                        "status": "pending",
                        "error": None,
                    }
                )
                self._save_unlocked(job)
            return {"job_id": job_id, "registered": len(job["tracks"])}

    def append_track(self, job_id: str, token: str, display_name: str) -> Dict[str, Any]:
        return self.add_track(job_id, token, display_name)

    def add_registered_entry(
        self, job_id: str, entry: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.add_track(job_id, entry["token"], entry["display_name"])

    def set_skipped(self, job_id: str, skipped: int) -> Dict[str, Any]:
        with self._mutation_lock():
            job = self._load_job_unlocked(job_id)
            job["skipped"] = skipped
            self._save_unlocked(job)
            return {"job_id": job_id, "skipped": skipped}

    def update_skipped(self, job_id: str, skipped: int) -> Dict[str, Any]:
        return self.set_skipped(job_id, skipped)

    def list_jobs(self) -> List[Dict[str, Any]]:
        """List jobs with pending tracks, without exposing track tokens or paths."""
        with self._mutation_lock():
            directory = self._dir()
            try:
                paths = sorted(directory.glob("*.json"))
            except OSError:
                raise RuntimeError("Unable to list playlist jobs") from None

            available = []
            for path in paths:
                try:
                    job = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    raise RuntimeError("Unable to read playlist job") from None
                if (
                    not isinstance(job, dict)
                    or not isinstance(job.get("tracks"), list)
                    or not isinstance(job.get("job_id"), str)
                ):
                    raise RuntimeError("Invalid playlist job record")
                try:
                    job_id = str(uuid.UUID(job["job_id"]))
                except ValueError:
                    raise RuntimeError("Invalid playlist job record") from None
                if job_id != path.stem:
                    raise RuntimeError("Invalid playlist job record")

                counts = {status: 0 for status in STATUSES}
                for track in job["tracks"]:
                    if (
                        not isinstance(track, dict)
                        or not isinstance(track.get("status"), str)
                        or track["status"] not in STATUSES
                    ):
                        raise RuntimeError("Invalid playlist job record")
                    counts[track["status"]] += 1
                if not counts["pending"]:
                    continue

                playlist_name = job.get("playlist_name")
                if not isinstance(playlist_name, str):
                    raise RuntimeError("Invalid playlist job record")
                playlist_name = playlist_name.replace("\\", "/").rsplit("/", 1)[-1]
                available.append(
                    {
                        "job_id": job_id,
                        "playlist_name": playlist_name,
                        "counts": counts,
                        "skipped": job.get("skipped", 0),
                    }
                )
            return available

    def next_batch(self, job_id: str, size: int = 10) -> Dict[str, Any]:
        """Claim up to `size` pending tokens, marking them in_progress."""
        if not isinstance(size, int) or size < 1 or size > 50:
            return {"error": "Batch size must be between 1 and 50"}
        try:
            with self._mutation_lock():
                job = self._load_job_unlocked(job_id)
                claimed = []
                for track in job["tracks"]:
                    if len(claimed) >= size:
                        break
                    if track.get("status") == "pending":
                        track["status"] = "in_progress"
                        claimed.append(
                            {"token": track["token"], "display_name": track["display_name"]}
                        )
                if claimed:
                    self._save_unlocked(job)
                remaining = sum(1 for t in job["tracks"] if t.get("status") == "pending")
                return {"batch": claimed, "remaining": remaining, "job_id": job_id}
        except ValueError as error:
            return {"error": str(error)}
        except RuntimeError as error:
            return {"error": str(error)}

    def preview_batch(self, job_id: str, size: int = 10) -> Dict[str, Any]:
        """Preview the next batch without claiming it (non-mutating)."""
        if not isinstance(size, int) or size < 1 or size > 50:
            return {"error": "Batch size must be between 1 and 50"}
        try:
            with self._mutation_lock():
                job = self._load_job_unlocked(job_id)
                preview = [
                    {"token": t["token"], "display_name": t["display_name"]}
                    for t in job["tracks"]
                    if t.get("status") == "pending"
                ][:size]
                counts = {status: 0 for status in STATUSES}
                for t in job["tracks"]:
                    counts[t.get("status", "pending")] = counts.get(t.get("status", "pending"), 0) + 1
                return {"preview": preview, "remaining": counts.get("pending", 0), "job_id": job_id}
        except ValueError as error:
            return {"error": str(error)}

    def peek_pending(self, job_id: str, size: int = 10) -> List[str]:
        """Return display names of the next pending tracks without claiming them."""
        if not isinstance(size, int) or size < 1 or size > 100:
            return []
        try:
            with self._mutation_lock():
                job = self._load_job_unlocked(job_id)
                names = [
                    track["display_name"]
                    for track in job["tracks"]
                    if track.get("status") == "pending"
                    and isinstance(track.get("display_name"), str)
                ]
                return names[:size]
        except ValueError:
            return []

    def complete_batch(
        self, job_id: str, results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Apply agent outcomes: each result is {token, success, error?}."""
        try:
            with self._mutation_lock():
                job = self._load_job_unlocked(job_id)
                by_token = {t.get("token"): t for t in job["tracks"] if isinstance(t, dict)}
                updated, unknown = 0, []
                for result in results or []:
                    if not isinstance(result, dict):
                        unknown.append(None)
                        continue
                    token = result.get("token")
                    track = by_token.get(token) if isinstance(token, str) else None
                    if track is None or track.get("status") != "in_progress":
                        unknown.append(token)
                        continue
                    requested_status = result.get("status")
                    if requested_status in ("unresolved", "needs_review", "partial"):
                        track["status"] = requested_status
                    else:
                        track["status"] = "done" if result.get("success") else "failed"
                    track["error"] = (
                        str(result.get("error"))[:200] if not result.get("success") else None
                    )
                    updated += 1
                self._save_unlocked(job)
                remaining = sum(1 for t in job["tracks"] if t.get("status") == "pending")
                return {"updated": updated, "remaining": remaining, "unknown": unknown}
        except ValueError as error:
            return {"error": str(error)}
        except RuntimeError as error:
            return {"error": str(error)}

    def release_batch(self, job_id: str, tokens: List[str]) -> Dict[str, Any]:
        """Return selected in-progress claims to pending after an interrupted run."""
        if not isinstance(tokens, list) or any(not isinstance(token, str) for token in tokens):
            return {"error": "tokens must be a list of opaque token strings"}
        try:
            with self._mutation_lock():
                job = self._load_job_unlocked(job_id)
                by_token = {
                    track["token"]: track for track in job["tracks"]
                    if isinstance(track, dict) and isinstance(track.get("token"), str)
                }
                released, unchanged = [], []
                released_tracks = []
                for token in dict.fromkeys(tokens):
                    track = by_token.get(token)
                    if track is None or track.get("status") != "in_progress":
                        unchanged.append(token)
                        continue
                    track["status"] = "pending"
                    track["error"] = None
                    released.append(token)
                    released_tracks.append(track)

                if released:
                    released_tokens = {track["token"] for track in released_tracks}
                    job["tracks"] = [
                        track for track in job["tracks"]
                        if not (isinstance(track, dict) and track.get("token") in released_tokens)
                    ] + released_tracks
                    self._save_unlocked(job)
                remaining = sum(
                    1 for track in job["tracks"] if track.get("status") == "pending"
                )
                return {"released": released, "unchanged": unchanged, "remaining": remaining}
        except ValueError as error:
            return {"error": str(error)}
        except RuntimeError as error:
            return {"error": str(error)}

    def job_status(self, job_id: str) -> Dict[str, Any]:
        """Return counts per status and failed display names (no tokens)."""
        try:
            with self._mutation_lock():
                job = self._load_job_unlocked(job_id)
                counts = {status: 0 for status in STATUSES}
                failed = []
                unresolved = []
                for track in job["tracks"]:
                    if not isinstance(track, dict):
                        continue
                    status = track.get("status")
                    counts[status] = counts.get(status, 0) + 1
                    if status == "failed":
                        failed.append(
                            {"display_name": track.get("display_name"), "error": track.get("error")}
                        )
                    elif status in ("unresolved", "needs_review", "partial"):
                        unresolved.append(
                            {"display_name": track.get("display_name"), "error": track.get("error")}
                        )
                return {
                    "job_id": job_id,
                    "playlist_name": job.get("playlist_name"),
                    "counts": counts,
                    "skipped": job.get("skipped", 0),
                    "failed": failed,
                    "unresolved": unresolved,
                }
        except ValueError as error:
            return {"error": str(error)}

    def transact(
        self, job_id: str, action: Callable[[Dict[str, Any]], Any]
    ) -> Tuple[Dict[str, Any], Any]:
        """Run ``action`` against one job under the cross-process lock."""
        with self._mutation_lock():
            job = self._load_job_unlocked(job_id)
            result = action(job)
            self._save_unlocked(job)
            return job, result

    def mutate(self, job_id: str, update: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
        job, _ = self.transact(job_id, update)
        return job


def get_job_store() -> JobStore:
    """Return the process-wide job store backed by the data directory."""
    return JobStore()
