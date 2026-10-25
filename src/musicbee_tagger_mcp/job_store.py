"""Playlist job store: tracks per-token processing status in the private data dir.

A job is created when the MCP server registers a playlist server-side. The
agent only ever sees opaque tokens and bare display names; the playlist path
and file paths never leave this module's boundaries.
"""

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .data_paths import ensure_data_subdirectory

STATUSES = ("pending", "in_progress", "done", "failed", "skipped")


def default_jobs_dir() -> Path:
    """Return the persistent playlist-jobs directory."""
    return ensure_data_subdirectory("playlists")


class JobStore:
    """Create playlist jobs and hand out pending tokens in batches."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = directory

    def _dir(self) -> Path:
        return self.directory or default_jobs_dir()

    def create_job(
        self, entries: List[Dict[str, Any]], playlist_name: str,
        skipped: int = 0,
    ) -> Dict[str, Any]:
        """Persist a job from registered token entries (plus skipped count)."""
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
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
        path = self._dir() / f"{job_id}.json"
        try:
            path.write_text(
                json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            raise RuntimeError("Unable to save playlist job") from None
        return {
            "job_id": job_id,
            "registered": len(job["tracks"]),
            "skipped": skipped,
        }

    def load_job(self, job_id: str) -> Dict[str, Any]:
        """Load a job by id, raising ValueError for unknown or malformed ids."""
        try:
            normalized = str(uuid.UUID(job_id))
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Unknown job id") from None
        path = self._dir() / f"{normalized}.json"
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise ValueError("Unknown job id") from None
        if job.get("job_id") != normalized or not isinstance(job.get("tracks"), list):
            raise ValueError("Unknown job id")
        return job

    def list_jobs(self) -> List[Dict[str, Any]]:
        """List jobs with pending tracks, without exposing track tokens or paths."""
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

    def _save(self, job: Dict[str, Any]) -> None:
        path = self._dir() / f"{job['job_id']}.json"
        try:
            path.write_text(
                json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            raise RuntimeError("Unable to update playlist job") from None

    def next_batch(self, job_id: str, size: int = 10) -> Dict[str, Any]:
        """Claim up to `size` pending tokens, marking them in_progress."""
        if not isinstance(size, int) or size < 1 or size > 50:
            return {"error": "Batch size must be between 1 and 50"}
        try:
            job = self.load_job(job_id)
        except ValueError as error:
            return {"error": str(error)}
        claimed = []
        for track in job["tracks"]:
            if len(claimed) >= size:
                break
            if track["status"] == "pending":
                track["status"] = "in_progress"
                claimed.append(
                    {"token": track["token"], "display_name": track["display_name"]}
                )
        if claimed:
            try:
                self._save(job)
            except RuntimeError as error:
                return {"error": str(error)}
        remaining = sum(1 for t in job["tracks"] if t["status"] == "pending")
        return {"batch": claimed, "remaining": remaining, "job_id": job_id}

    def peek_pending(self, job_id: str, size: int = 10) -> List[str]:
        """Return display names of the next pending tracks without claiming them."""
        if not isinstance(size, int) or size < 1 or size > 100:
            return []
        try:
            job = self.load_job(job_id)
        except ValueError:
            return []
        names = [
            track["display_name"]
            for track in job["tracks"]
            if track.get("status") == "pending"
            and isinstance(track.get("display_name"), str)
        ]
        return names[:size]


    def complete_batch(
        self, job_id: str, results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Apply agent outcomes: each result is {token, success, error?}."""
        try:
            job = self.load_job(job_id)
        except ValueError as error:
            return {"error": str(error)}
        by_token = {t["token"]: t for t in job["tracks"]}
        updated, unknown = 0, []
        for result in results:
            token = result.get("token")
            track = by_token.get(token) if isinstance(token, str) else None
            if track is None or track["status"] != "in_progress":
                unknown.append(token)
                continue
            track["status"] = "done" if result.get("success") else "failed"
            track["error"] = (
                str(result.get("error"))[:200] if not result.get("success") else None
            )
            updated += 1
        try:
            self._save(job)
        except RuntimeError as error:
            return {"error": str(error)}
        remaining = sum(1 for t in job["tracks"] if t["status"] == "pending")
        return {"updated": updated, "remaining": remaining, "unknown": unknown}

    def release_batch(self, job_id: str, tokens: List[str]) -> Dict[str, Any]:
        """Return selected in-progress claims to pending after an interrupted run."""
        if not isinstance(tokens, list) or any(not isinstance(token, str) for token in tokens):
            return {"error": "tokens must be a list of opaque token strings"}
        try:
            job = self.load_job(job_id)
        except ValueError as error:
            return {"error": str(error)}

        by_token = {track["token"]: track for track in job["tracks"]}
        released, unchanged = [], []
        for token in dict.fromkeys(tokens):
            track = by_token.get(token)
            if track is None or track["status"] != "in_progress":
                unchanged.append(token)
                continue
            track["status"] = "pending"
            track["error"] = None
            released.append(token)

        if released:
            try:
                self._save(job)
            except RuntimeError as error:
                return {"error": str(error)}
        remaining = sum(1 for track in job["tracks"] if track["status"] == "pending")
        return {"released": released, "unchanged": unchanged, "remaining": remaining}

    def job_status(self, job_id: str) -> Dict[str, Any]:
        """Return counts per status and failed display names (no tokens)."""
        try:
            job = self.load_job(job_id)
        except ValueError as error:
            return {"error": str(error)}
        counts = {status: 0 for status in STATUSES}
        failed = []
        for track in job["tracks"]:
            counts[track["status"]] = counts.get(track["status"], 0) + 1
            if track["status"] == "failed":
                failed.append(
                    {"display_name": track["display_name"], "error": track["error"]}
                )
        return {
            "job_id": job_id,
            "playlist_name": job["playlist_name"],
            "counts": counts,
            "skipped": job.get("skipped", 0),
            "failed": failed,
        }


def get_job_store() -> JobStore:
    """Return the process-wide job store backed by the data directory."""
    return JobStore()
