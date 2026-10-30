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


def _first_present(mapping, keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if key in mapping and mapping.get(key) is not None:
            return mapping.get(key)
    return None

STATUSES = ("pending", "in_progress", "done", "failed", "skipped", "unresolved", "needs_review", "partial", "manually_staged", "manually_overridden", "overridden", "manual_override")


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
        skipped: int = 0, job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a job from registered token entries (plus skipped count)."""
        if job_id is None:
            job_id = str(uuid.uuid4())
        else:
            try:
                job_id = str(uuid.UUID(job_id))
            except (TypeError, ValueError, AttributeError):
                raise ValueError("Unknown job id") from None
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

    def add_track(
        self, job_id: str, token: str, display_name: str,
    ) -> Dict[str, Any]:
        job = self.load_job(job_id)
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
            try:
                self._save(job)
            except RuntimeError:
                raise
        return {"job_id": job_id, "registered": len(job["tracks"])}

    def append_track(self, job_id: str, token: str, display_name: str) -> Dict[str, Any]:
        return self.add_track(job_id, token, display_name)

    def add_registered_entry(
        self, job_id: str, entry: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.add_track(job_id, entry["token"], entry["display_name"])

    def set_skipped(self, job_id: str, skipped: int) -> Dict[str, Any]:
        job = self.load_job(job_id)
        job["skipped"] = skipped
        try:
            self._save(job)
        except RuntimeError:
            raise
        return {"job_id": job_id, "skipped": skipped}

    def update_skipped(self, job_id: str, skipped: int) -> Dict[str, Any]:
        return self.set_skipped(job_id, skipped)

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

    def preview_batch(self, job_id: str, size: int = 10) -> Dict[str, Any]:
        """Preview the next batch without claiming it (non-mutating)."""
        if not isinstance(size, int) or size < 1 or size > 50:
            return {"error": "Batch size must be between 1 and 50"}
        try:
            job = self.load_job(job_id)
        except ValueError as error:
            return {"error": str(error)}
        preview = [
            {"token": t["token"], "display_name": t["display_name"]}
            for t in job["tracks"]
            if t["status"] == "pending"
        ][:size]
        counts = {status: 0 for status in STATUSES}
        for t in job["tracks"]:
            counts[t["status"]] = counts.get(t["status"], 0) + 1
        return {"preview": preview, "remaining": counts["pending"], "job_id": job_id}

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
            # Support unresolved/partial outcomes: if result includes a "status"
            # field, use it; otherwise fall back to success/failed.
            requested_status = result.get("status")
            if requested_status in ("unresolved", "needs_review", "partial"):
                track["status"] = requested_status
            else:
                track["status"] = "done" if result.get("success") else "failed"
            track["error"] = (
                str(result.get("error"))[:200] if not result.get("success") else None
            )
            candidate = _candidate_from_result(result)
            if candidate:
                track["candidate"] = candidate
                track["best_candidate"] = dict(candidate)
                track["candidate_details"] = dict(candidate)
                for key in (
                    "recording_id", "mb_recording_id", "candidate_recording_id",
                    "title", "mb_title", "candidate_title", "artist", "mb_artist",
                    "candidate_artist", "duration", "duration_seconds",
                    "mb_duration_seconds", "candidate_duration_seconds",
                    "duration_diff_seconds", "duration_difference",
                    "verification_reason", "reason", "verification",
                ):
                    if key in candidate:
                        track[key] = candidate[key]
            if result.get("manual_override") or result.get("manual_stage") or result.get("override"):
                justification = (
                    result.get("manual_override_justification")
                    or result.get("override_justification")
                    or result.get("override_reason")
                    or result.get("reason")
                    or result.get("error")
                )
                track.setdefault("manual_overrides", []).append({
                    "justification": str(justification or ""),
                    "candidate": dict(candidate) if candidate else None,
                })
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
        released_tracks = []
        for token in dict.fromkeys(tokens):
            track = by_token.get(token)
            if track is None or track["status"] != "in_progress":
                unchanged.append(token)
                continue
            track["status"] = "pending"
            track["error"] = None
            released.append(token)
            released_tracks.append(track)

        if released:
            # Move released tracks to the end of the queue so problematic
            # tracks are not retried before other pending work.
            released_tokens = {track["token"] for track in released_tracks}
            job["tracks"] = [
                track for track in job["tracks"]
                if track["token"] not in released_tokens
            ] + released_tracks
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
        unresolved = []
        for track in job["tracks"]:
            counts[track["status"]] = counts.get(track["status"], 0) + 1
            candidate = None
            if isinstance(track, dict):
                candidate = track.get("candidate") or track.get("best_candidate") or track.get("candidate_details")
            if not isinstance(candidate, dict):
                candidate = {}
            if track["status"] == "failed":
                entry = {"display_name": track["display_name"], "error": track["error"]}
                if candidate:
                    entry["candidate"] = candidate
                    entry["best_candidate"] = dict(candidate)
                    entry["candidate_details"] = dict(candidate)
                    for key in (
                        "recording_id", "mb_recording_id", "candidate_recording_id",
                        "title", "mb_title", "candidate_title", "artist", "mb_artist",
                        "candidate_artist", "duration", "duration_seconds",
                        "mb_duration_seconds", "candidate_duration_seconds",
                        "duration_diff_seconds", "duration_difference",
                        "verification_reason", "reason", "verification",
                    ):
                        if key in track and track.get(key) is not None:
                            entry[key] = track.get(key)
                if track.get("manual_overrides"):
                    entry["manual_overrides"] = track.get("manual_overrides")
                failed.append(entry)
            elif track["status"] in ("unresolved", "needs_review", "partial", "manually_staged", "manually_overridden", "overridden"):
                entry = {"display_name": track["display_name"], "error": track["error"]}
                if candidate:
                    entry["candidate"] = candidate
                    entry["best_candidate"] = dict(candidate)
                    entry["candidate_details"] = dict(candidate)
                    for key in (
                        "recording_id", "mb_recording_id", "candidate_recording_id",
                        "title", "mb_title", "candidate_title", "artist", "mb_artist",
                        "candidate_artist", "duration", "duration_seconds",
                        "mb_duration_seconds", "candidate_duration_seconds",
                        "duration_diff_seconds", "duration_difference",
                        "verification_reason", "reason", "verification",
                    ):
                        if key in track and track.get(key) is not None:
                            entry[key] = track.get(key)
                if track.get("manual_overrides"):
                    entry["manual_overrides"] = track.get("manual_overrides")
                if track.get("manual_override_justification"):
                    entry["manual_override_justification"] = track.get("manual_override_justification")
                unresolved.append(entry)
        return {
            "job_id": job_id,
            "playlist_name": job["playlist_name"],
            "counts": counts,
            "skipped": job.get("skipped", 0),
            "failed": failed,
            "unresolved": unresolved,
        }


    def _apply_manual_override(self, job_id, token, justification=None, reason=None, status=None, candidate=None, **candidate_fields):
        if status is None:
            status = "manually_staged"
        if justification is None:
            justification = reason
        if justification is None:
            justification = candidate_fields.pop("justification", None)
        if justification is None:
            justification = candidate_fields.pop("override_reason", None)
        if not isinstance(justification, str) or not justification.strip():
            raise ValueError("justification is required for a manual override")
        justification = justification.strip()
        try:
            job = self.load_job(job_id)
        except ValueError as error:
            return {"error": str(error)}
        by_token = {track["token"]: track for track in job["tracks"]}
        track = by_token.get(token) if isinstance(token, str) else None
        if track is None:
            return {"error": "Unknown token"}
        cand = {}
        if isinstance(candidate, dict):
            cand.update(_candidate_from_result({"candidate": candidate}))
        if candidate_fields:
            cand.update(_candidate_from_result(candidate_fields))
        if cand:
            track["candidate"] = cand
            track["best_candidate"] = dict(cand)
            track["candidate_details"] = dict(cand)
            for key in (
                "recording_id", "mb_recording_id", "candidate_recording_id",
                "title", "mb_title", "candidate_title", "artist", "mb_artist",
                "candidate_artist", "duration", "duration_seconds",
                "mb_duration_seconds", "candidate_duration_seconds",
                "duration_diff_seconds", "duration_difference",
                "verification_reason", "reason", "verification",
            ):
                if key in cand:
                    track[key] = cand[key]
        track["status"] = status
        track["manual_override"] = True
        track["manual_override_justification"] = justification
        track["override_justification"] = justification
        track.setdefault("manual_overrides", []).append({
            "justification": justification,
            "status": status,
            "candidate": dict(cand) if cand else None,
        })
        try:
            self._save(job)
        except RuntimeError as error:
            return {"error": str(error)}
        return {
            "job_id": job_id,
            "status": status,
            "justification": justification,
            "display_name": track.get("display_name"),
            "candidate": cand if cand else None,
        }

    def manual_stage_override(self, *args, **kwargs):
        return self._apply_manual_override(*args, **kwargs)

    def manual_override(self, *args, **kwargs):
        return self._apply_manual_override(*args, **kwargs)

    def stage_manual_override(self, *args, **kwargs):
        return self._apply_manual_override(*args, **kwargs)

    def override_unresolved(self, *args, **kwargs):
        return self._apply_manual_override(*args, **kwargs)

    def record_manual_override(self, *args, **kwargs):
        return self._apply_manual_override(*args, **kwargs)

    def mark_manually_staged(self, *args, **kwargs):
        return self._apply_manual_override(*args, status="manually_staged", **kwargs)

    def apply_manual_override(self, *args, **kwargs):
        return self._apply_manual_override(*args, **kwargs)

    def manual_stage(self, *args, **kwargs):
        return self._apply_manual_override(*args, **kwargs)

    def review_unresolved(self, job_id):
        status = self.job_status(job_id)
        if "error" in status:
            return status
        return {"job_id": job_id, "unresolved": status.get("unresolved", [])}

    def list_unresolved_candidates(self, job_id):
        return self.review_unresolved(job_id)

    def get_unresolved_candidates(self, job_id):
        return self.review_unresolved(job_id)

    def get_unresolved_review(self, job_id):
        return self.review_unresolved(job_id)


def get_job_store() -> JobStore:
    """Return the process-wide job store backed by the data directory."""
    return JobStore()


def _candidate_from_result(result):
    if not isinstance(result, dict):
        return {}
    nested = []
    for key in ("candidate", "best_candidate", "bestCandidate", "candidate_details",
                "candidateDetails", "verification", "match", "best_match"):
        value = result.get(key)
        if isinstance(value, dict):
            nested.append(value)
    for key in ("candidates", "best_candidates", "matches"):
        value = result.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            nested.append(value[0])

    recording_keys = (
        "recording_id", "mb_recording_id", "candidate_recording_id",
        "best_recording_id", "musicbrainz_recording_id", "mbid", "recording",
    )
    title_keys = (
        "title", "mb_title", "candidate_title", "best_title",
        "recording_title", "candidate_recording_title",
    )
    artist_keys = (
        "artist", "mb_artist", "candidate_artist", "best_artist",
        "recording_artist", "candidate_recording_artist", "artist_credit",
    )
    duration_keys = (
        "duration", "duration_seconds", "mb_duration_seconds",
        "candidate_duration_seconds", "best_duration_seconds",
        "candidate_duration", "mb_duration", "length_seconds",
    )
    diff_keys = (
        "duration_diff_seconds", "duration_difference", "duration_diff",
        "candidate_duration_diff_seconds", "candidate_duration_difference",
        "best_duration_diff_seconds",
    )
    reason_keys = (
        "verification_reason", "verificationReason", "reason", "verification",
        "verification_result", "mismatch_reason", "mismatches",
    )

    pools = [result, *nested]
    recording_id = None
    title = None
    artist = None
    duration = None
    duration_diff = None
    reason = None
    for pool in pools:
        if recording_id is None:
            recording_id = _first_present(pool, recording_keys)
        if title is None:
            title = _first_present(pool, title_keys)
        if artist is None:
            artist = _first_present(pool, artist_keys)
        if duration is None:
            duration = _first_present(pool, duration_keys)
        if duration_diff is None:
            duration_diff = _first_present(pool, diff_keys)
        if reason is None:
            reason = _first_present(pool, reason_keys)

    if isinstance(reason, (list, tuple)):
        reason = "; ".join(str(item) for item in reason if item is not None)
    elif reason is not None:
        reason = str(reason)

    candidate = {}
    if recording_id is not None:
        candidate["recording_id"] = recording_id
        candidate["mb_recording_id"] = recording_id
        candidate["candidate_recording_id"] = recording_id
        candidate["best_recording_id"] = recording_id
    if title is not None:
        candidate["title"] = title
        candidate["mb_title"] = title
        candidate["candidate_title"] = title
        candidate["best_title"] = title
    if artist is not None:
        candidate["artist"] = artist
        candidate["mb_artist"] = artist
        candidate["candidate_artist"] = artist
        candidate["best_artist"] = artist
    if duration is not None:
        candidate["duration"] = duration
        candidate["duration_seconds"] = duration
        candidate["mb_duration_seconds"] = duration
        candidate["candidate_duration_seconds"] = duration
        candidate["best_duration_seconds"] = duration
    if duration_diff is not None:
        candidate["duration_diff_seconds"] = duration_diff
        candidate["duration_difference"] = duration_diff
        candidate["candidate_duration_diff_seconds"] = duration_diff
        candidate["best_duration_diff_seconds"] = duration_diff
    if reason is not None:
        candidate["verification_reason"] = reason
        candidate["reason"] = reason
        candidate["verification"] = reason
    for pool in pools:
        if isinstance(pool, dict):
            for key, value in pool.items():
                if value is not None and key not in candidate:
                    if key.startswith(("candidate_", "mb_", "best_")) or key in {
                        "recording_id", "title", "artist", "duration", "duration_seconds",
                        "duration_diff", "mismatches", "confidence", "verified",
                        "forensic_score", "top_release",
                    }:
                        candidate[key] = value
    return candidate
