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


def get_registry():
    """Return the shared file registry, if available."""
    try:
        from .file_registry import get_registry as _registry_getter

        return _registry_getter()
    except Exception:
        return None


def _resolve_registry(*args, **kwargs):
    for key in ("registry", "reg", "file_registry", "registry_instance"):
        value = kwargs.get(key)
        if hasattr(value, "resolve"):
            return value
    for arg in args:
        if hasattr(arg, "resolve"):
            return arg
    try:
        registry = get_registry()
        if hasattr(registry, "resolve"):
            return registry
    except Exception:
        pass
    return None


class JobStore:
    """Create playlist jobs and hand out pending tokens in batches."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = directory

    def _dir(self) -> Path:
        return self.directory or default_jobs_dir()

    def create_job(
        self, entries: List[Dict[str, Any]], playlist_name: str,
        skipped: int = 0, job_id: Optional[str] = None, **kwargs,
    ) -> Dict[str, Any]:
        """Persist a job from registered token entries (plus skipped count)."""
        if job_id is None:
            job_id = str(uuid.uuid4())
        else:
            try:
                job_id = str(uuid.UUID(job_id))
            except (TypeError, ValueError, AttributeError):
                raise ValueError("Unknown job id") from None
        registry = _resolve_registry(**kwargs)
        if isinstance(entries, list):
            entries = [{"token": e, "display_name": e} if isinstance(e, str) else e for e in entries]
            self._enrich_tracks_from_registry(entries, registry)
        sort_by = (
            kwargs.pop("sort_by", None)
            or kwargs.pop("order_by", None)
            or kwargs.pop("order", None)
            or kwargs.pop("by", None)
            or kwargs.pop("group_by", None)
            or kwargs.pop("grouping", None)
        )
        entries = self._normalize_entries(entries, sort_by=sort_by, **kwargs)
        job = {
            "job_id": job_id,
            "playlist_name": playlist_name,
            "tracks": [
                self._entry_to_track(entry)
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
                job_id = str(uuid.UUID(path.stem))
            except ValueError:
                continue
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
                parsed_job_id = str(uuid.UUID(job["job_id"]))
            except ValueError:
                raise RuntimeError("Invalid playlist job record") from None
            if parsed_job_id != path.stem or parsed_job_id != job_id:
                raise RuntimeError("Invalid playlist job record")
            job_id = parsed_job_id

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


    _ALBUM_KEYS = ("album", "album_name", "album_title", "albumname", "albumtitle", "record", "release_title")
    _ALBUM_ARTIST_KEYS = ("album_artist", "albumartist", "album_artist_name", "albumartistname")
    _DISC_KEYS = ("disc", "disc_number", "disc_no", "disc_num", "discnum", "disk", "disk_number", "discnumber")
    _TRACK_KEYS = ("track", "track_number", "track_no", "track_num", "tracknum", "tracknumber", "number")
    _TITLE_KEYS = ("title", "track_title", "name", "display_name")
    _ARTIST_KEYS = ("artist", "track_artist", "artist_name", "artist_credit")
    _RELEASE_KEYS = ("release", "release_id", "musicbrainz_release_id", "mb_release_id", "releaseid", "musicbrainz_album_id", "mb_album_id")

    @staticmethod
    def _first_value(mapping, keys):
        if not isinstance(mapping, dict):
            return None
        for key in keys:
            if key in mapping and mapping.get(key) is not None:
                return mapping.get(key)
        lowered = {str(k).lower(): v for k, v in mapping.items() if isinstance(k, str)}
        for key in keys:
            if key.lower() in lowered and lowered[key.lower()] is not None:
                return lowered[key.lower()]
        return None

    @classmethod
    def _nested_sources(cls, entry):
        sources = [entry]
        if isinstance(entry, dict):
            for key in ("metadata", "tags", "fields", "info", "properties", "track"):
                value = entry.get(key)
                if isinstance(value, dict):
                    sources.append(value)
        return sources

    @classmethod
    def _collect_metadata(cls, entry):
        metadata = {}
        if not isinstance(entry, dict):
            return metadata
        for source in cls._nested_sources(entry):
            if not isinstance(source, dict):
                continue
            for key, value in source.items():
                if value is None:
                    continue
                if key in {"token", "display_name", "status", "error"}:
                    continue
                if key in {"registry", "reg", "file_registry", "registry_instance"}:
                    continue
                if hasattr(value, "resolve") and callable(getattr(value, "resolve")):
                    continue
                if key not in metadata:
                    metadata[key] = value
        if "album" not in metadata:
            val = cls._first_value(metadata, cls._ALBUM_KEYS)
            if val is not None:
                metadata["album"] = val
        if "album_artist" not in metadata:
            val = cls._first_value(metadata, cls._ALBUM_ARTIST_KEYS)
            if val is not None:
                metadata["album_artist"] = val
        if "disc_number" not in metadata:
            val = cls._first_value(metadata, cls._DISC_KEYS)
            if val is not None:
                metadata["disc_number"] = val
        if "track_number" not in metadata:
            val = cls._first_value(metadata, cls._TRACK_KEYS)
            if val is not None:
                metadata["track_number"] = val
        if "title" not in metadata:
            val = cls._first_value(metadata, cls._TITLE_KEYS)
            if val is not None and val != metadata.get("display_name"):
                metadata["title"] = val
        if "artist" not in metadata:
            val = cls._first_value(metadata, cls._ARTIST_KEYS)
            if val is not None:
                metadata["artist"] = val
        if "release_id" not in metadata:
            val = cls._first_value(metadata, cls._RELEASE_KEYS)
            if val is not None:
                metadata["release_id"] = val
        return metadata

    @classmethod
    def _entry_to_token(cls, entry):
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            for key in ("token", "id", "file_token", "track_token"):
                if isinstance(entry.get(key), str):
                    return entry.get(key)
        return None

    @classmethod
    def _entry_to_display_name(cls, entry, token):
        if isinstance(entry, dict):
            for key in ("display_name", "name", "title", "filename", "file_name"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        if isinstance(token, str):
            return token
        return str(entry)

    @classmethod
    def _normalize_entries(cls, entries, sort_by=None, **kwargs):
        if entries is None:
            entries = []
        normalized = []
        for index, entry in enumerate(entries):
            if isinstance(entry, str):
                entry = {"token": entry, "display_name": entry}
            if not isinstance(entry, dict):
                entry = {"token": str(entry), "display_name": str(entry)}
            token = cls._entry_to_token(entry)
            if token is None:
                token = entry.get("token")
            display_name = cls._entry_to_display_name(entry, token)
            metadata = cls._collect_metadata(entry)
            item = {"token": token, "display_name": display_name}
            item.update(metadata)
            item.setdefault("_original_index", index)
            normalized.append(item)
        if normalized:
            try:
                normalized.sort(key=lambda item: cls._sort_key(item, sort_by))
            except Exception:
                pass
        for item in normalized:
            item.pop("_original_index", None)
        return normalized

    @classmethod
    def _entry_to_track(cls, entry):
        if isinstance(entry, str):
            entry = {"token": entry, "display_name": entry}
        if not isinstance(entry, dict):
            entry = {"token": str(entry), "display_name": str(entry)}
        token = cls._entry_to_token(entry)
        if token is None:
            token = entry.get("token")
        display_name = cls._entry_to_display_name(entry, token)
        track = {
            "token": token,
            "display_name": display_name,
            "status": "pending",
            "error": None,
        }
        metadata = cls._collect_metadata(entry)
        for key, value in metadata.items():
            if value is not None:
                track[key] = value
        for key, value in entry.items():
            if key in {"token", "display_name", "status", "error"}:
                continue
            if value is not None and key not in track:
                track[key] = value
        return track

    @staticmethod
    def _numeric_value(value):
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if "/" in text:
                text = text.split("/", 1)[0].strip()
            try:
                return int(text)
            except ValueError:
                try:
                    return float(text)
                except ValueError:
                    return None
        if isinstance(value, dict):
            for key in ("number", "value", "position", "track", "disc"):
                if key in value:
                    return JobStore._numeric_value(value.get(key))
        return None

    @classmethod
    def _field_value(cls, track, name):
        if not isinstance(track, dict):
            return None
        if isinstance(name, (list, tuple)):
            for part in name:
                value = cls._field_value(track, part)
                if value is not None:
                    return value
            return None
        if not isinstance(name, str):
            return None
        name_l = name.strip().lower()
        alias_map = {
            "album": cls._ALBUM_KEYS,
            "album_name": cls._ALBUM_KEYS,
            "album_title": cls._ALBUM_KEYS,
            "album_artist": cls._ALBUM_ARTIST_KEYS,
            "albumartist": cls._ALBUM_ARTIST_KEYS,
            "disc": cls._DISC_KEYS,
            "disc_number": cls._DISC_KEYS,
            "disc_no": cls._DISC_KEYS,
            "disc_num": cls._DISC_KEYS,
            "track": cls._TRACK_KEYS,
            "track_number": cls._TRACK_KEYS,
            "track_no": cls._TRACK_KEYS,
            "track_num": cls._TRACK_KEYS,
            "title": cls._TITLE_KEYS,
            "track_title": cls._TITLE_KEYS,
            "artist": cls._ARTIST_KEYS,
            "track_artist": cls._ARTIST_KEYS,
            "release": cls._RELEASE_KEYS,
            "release_id": cls._RELEASE_KEYS,
            "mb_release_id": cls._RELEASE_KEYS,
            "musicbrainz_release_id": cls._RELEASE_KEYS,
        }
        keys = alias_map.get(name_l, (name,))
        value = cls._first_value(track, keys)
        if value is not None:
            return value
        for source_key in ("metadata", "tags", "fields", "info", "properties", "track"):
            source = track.get(source_key)
            if isinstance(source, dict):
                value = cls._first_value(source, keys)
                if value is not None:
                    return value
        return None

    @classmethod
    def _is_groupable(cls, track):
        album = cls._field_value(track, "album")
        release = cls._field_value(track, "release")
        track_no = cls._numeric_value(cls._field_value(track, "track_number"))
        if album is None and release is None:
            return False
        return track_no is not None

    @classmethod
    def _sort_key(cls, track, sort_by=None):
        original_index = track.get("_original_index", 0) if isinstance(track, dict) else 0
        if callable(sort_by):
            try:
                return (0 if cls._is_groupable(track) else 1, sort_by(track), original_index)
            except Exception:
                return (1, original_index)
        if sort_by is None:
            fields = ["album", "disc_number", "track_number"]
        elif isinstance(sort_by, str):
            low = sort_by.strip().lower()
            if low in {"album", "album_track", "album_disc_track", "album, disc, track", "album/disc/track", "album disc track"}:
                fields = ["album", "disc_number", "track_number"]
            elif "," in sort_by:
                fields = [part.strip() for part in sort_by.split(",") if part.strip()]
            else:
                fields = [sort_by]
        elif isinstance(sort_by, (list, tuple)):
            fields = [str(x).strip() for x in sort_by if str(x).strip()]
        else:
            fields = ["album", "disc_number", "track_number"]
        if not fields:
            fields = ["album", "disc_number", "track_number"]
        group_bucket = 0 if cls._is_groupable(track) else 1
        values = [group_bucket]
        for field in fields:
            value = cls._field_value(track, field)
            field_l = str(field).lower()
            disc_keys = {k.lower() for k in cls._DISC_KEYS}
            track_keys = {k.lower() for k in cls._TRACK_KEYS}
            if field_l in disc_keys or field_l in track_keys or field_l in ("disc", "track", "disc_number", "track_number"):
                num = cls._numeric_value(value)
                values.append(num if num is not None else 10**9)
            else:
                if value is None:
                    values.append("")
                else:
                    values.append(str(value).casefold())
        values.append(original_index)
        return tuple(values)

    def reorder_job(self, *args, **kwargs):
        return self._reorder(*args, job_scope="all", **kwargs)

    def reorder_tracks(self, *args, **kwargs):
        return self._reorder(*args, job_scope="all", **kwargs)

    def reorder_pending(self, *args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["pending_only"] = True
        return self._reorder(*args, job_scope="pending", **kwargs)

    def reorder_pending_tracks(self, *args, **kwargs):
        return self.reorder_pending(*args, **kwargs)

    def sort_job(self, *args, **kwargs):
        return self.reorder_job(*args, **kwargs)

    def sort_tracks(self, *args, **kwargs):
        return self.reorder_tracks(*args, **kwargs)

    def sort_pending(self, *args, **kwargs):
        return self.reorder_pending(*args, **kwargs)

    def sort_pending_tracks(self, *args, **kwargs):
        return self.reorder_pending(*args, **kwargs)

    def order_job(self, *args, **kwargs):
        return self.reorder_job(*args, **kwargs)

    def order_tracks(self, *args, **kwargs):
        return self.reorder_tracks(*args, **kwargs)

    def order_pending(self, *args, **kwargs):
        return self.reorder_pending(*args, **kwargs)

    def order_pending_tracks(self, *args, **kwargs):
        return self.reorder_pending(*args, **kwargs)

    def arrange_job(self, *args, **kwargs):
        return self.reorder_job(*args, **kwargs)

    def arrange_tracks(self, *args, **kwargs):
        return self.reorder_tracks(*args, **kwargs)

    def arrange_by_album(self, *args, **kwargs):
        kwargs.setdefault("sort_by", ["album", "disc_number", "track_number"])
        return self.reorder_job(*args, **kwargs)

    def group_job(self, *args, **kwargs):
        result = self.reorder_job(*args, **kwargs)
        try:
            job_id = result.get("job_id") if isinstance(result, dict) else None
        except Exception:
            job_id = None
        if job_id:
            groups = self.album_groups(job_id, pending_only=kwargs.get("pending_only", kwargs.get("pending", False)))
            if isinstance(result, dict):
                result.update(groups if isinstance(groups, dict) else {"album_groups": groups})
        return result

    def group_tracks(self, *args, **kwargs):
        return self.group_job(*args, **kwargs)

    def organize_job(self, *args, **kwargs):
        return self.group_job(*args, **kwargs)

    def organize_tracks(self, *args, **kwargs):
        return self.group_job(*args, **kwargs)

    def _resolve_reorder_args(self, *args, **kwargs):
        job_id = kwargs.get("job_id", kwargs.get("job", kwargs.get("id")))
        positional = list(args)
        if job_id is None and positional:
            first = positional.pop(0)
            if isinstance(first, str):
                job_id = first
            elif isinstance(first, dict) and "job_id" in first:
                job_id = first.get("job_id")
            else:
                positional.insert(0, first)
        order = (
            kwargs.get("order", None)
            or kwargs.get("tokens", None)
            or kwargs.get("track_order", None)
            or kwargs.get("new_order", None)
            or kwargs.get("sequence", None)
            or kwargs.get("ids", None)
            or kwargs.get("order_tokens", None)
        )
        if order is None and positional:
            if isinstance(positional[0], (list, tuple)):
                order = list(positional.pop(0))
            elif all(isinstance(x, str) for x in positional) and len(positional) > 1:
                order = list(positional)
                positional = []
        pending_only = kwargs.get("pending_only", kwargs.get("pending", kwargs.get("only_pending", kwargs.get("pending_tracks_only", False))))
        if isinstance(pending_only, str):
            pending_only = pending_only.strip().lower() in {"true", "1", "yes", "pending", "only"}
        sort_by = kwargs.get("sort_by", kwargs.get("order_by", kwargs.get("by", kwargs.get("key", kwargs.get("sort", kwargs.get("group_by", kwargs.get("grouping", kwargs.get("order_field", None))))))))
        reverse = kwargs.get("reverse", kwargs.get("descending", False))
        if isinstance(reverse, str):
            reverse = reverse.strip().lower() in {"true", "1", "yes"}
        return job_id, order, pending_only, sort_by, reverse, positional

    def _reorder(self, *args, **kwargs):
        job_id, order, pending_only, sort_by, reverse, positional = self._resolve_reorder_args(*args, **kwargs)
        if kwargs.get("job_scope") == "pending" or kwargs.get("scope") in {"pending", "pending_only", "pending_tracks"} or kwargs.get("pending_only") is True:
            pending_only = True
        try:
            job = self.load_job(job_id)
        except (ValueError, TypeError):
            return {"error": "Unknown job id"}
        if not isinstance(job, dict):
            return {"error": "Unknown job id"}
        tracks = job.get("tracks")
        if not isinstance(tracks, list):
            return {"error": "Invalid playlist job record"}
        registry = _resolve_registry(*args, **kwargs)
        self._enrich_tracks_from_registry(tracks, registry)
        if order is not None:
            by_token = {}
            by_name = {}
            for track in tracks:
                if isinstance(track, dict):
                    if isinstance(track.get("token"), str):
                        by_token[track["token"]] = track
                    name = track.get("display_name")
                    if isinstance(name, str) and name not in by_name:
                        by_name[name] = track
            new_list = []
            used = set()
            for item in order:
                track = None
                if isinstance(item, str):
                    track = by_token.get(item) or by_name.get(item)
                elif isinstance(item, dict):
                    token = item.get("token")
                    name = item.get("display_name") or item.get("name")
                    track = by_token.get(token) if isinstance(token, str) else None
                    if track is None and isinstance(name, str):
                        track = by_name.get(name)
                if track is not None and id(track) not in used:
                    new_list.append(track)
                    used.add(id(track))
            for track in tracks:
                if id(track) not in used:
                    new_list.append(track)
            if reverse:
                new_list = list(reversed(new_list))
            if pending_only:
                _pending_slots=[i for i,t in enumerate(tracks) if isinstance(t,dict) and t.get("status")=="pending"]
                _pending_set={id(t) for t in tracks if isinstance(t,dict) and t.get("status")=="pending"}
                _ordered=[t for t in new_list if id(t) in _pending_set]
                for _i,_t in zip(_pending_slots,_ordered):
                    tracks[_i]=_t
                job["tracks"]=tracks
            else:
                job["tracks"]=new_list
        else:
            if pending_only:
                pending_indices = [i for i, t in enumerate(tracks) if isinstance(t, dict) and t.get("status") == "pending"]
                pending_tracks = [tracks[i] for i in pending_indices]
                indexed = list(enumerate(pending_tracks))
                if reverse:
                    indexed.sort(key=lambda pair: self._sort_key(pair[1], sort_by), reverse=True)
                else:
                    indexed.sort(key=lambda pair: self._sort_key(pair[1], sort_by))
                sorted_pending = [t for _, t in indexed]
                for idx, track in zip(pending_indices, sorted_pending):
                    tracks[idx] = track
                job["tracks"] = tracks
            else:
                indexed = list(enumerate(tracks))
                if reverse:
                    indexed.sort(key=lambda pair: self._sort_key(pair[1], sort_by), reverse=True)
                else:
                    indexed.sort(key=lambda pair: self._sort_key(pair[1], sort_by))
                job["tracks"] = [t for _, t in indexed]
        try:
            self._save(job)
        except RuntimeError:
            return {"error": "Unable to update playlist job"}
        result = {
            "job_id": job_id,
            "reordered": len(job["tracks"]),
            "ordered": len(job["tracks"]),
            "count": len(job["tracks"]),
            "remaining": sum(1 for t in job["tracks"] if isinstance(t, dict) and t.get("status") == "pending"),
            "tracks": [dict(t) for t in job["tracks"] if isinstance(t, dict)],
            "track_names": [t.get("display_name") for t in job["tracks"] if isinstance(t, dict)],
            "display_names": [t.get("display_name") for t in job["tracks"] if isinstance(t, dict)],
            "order": [t.get("display_name") for t in job["tracks"] if isinstance(t, dict)],
        }
        try:
            result.update(self.album_groups(job_id))
        except Exception:
            pass
        return result

    def album_groups(self, *args, **kwargs):
        return self._album_groups(*args, **kwargs)

    def group_by_album(self, *args, **kwargs):
        return self._album_groups(*args, **kwargs)

    def group_tracks_by_album(self, *args, **kwargs):
        return self._album_groups(*args, **kwargs)

    def album_groupings(self, *args, **kwargs):
        return self._album_groups(*args, **kwargs)

    def job_album_groups(self, *args, **kwargs):
        return self._album_groups(*args, **kwargs)

    def grouped_albums(self, *args, **kwargs):
        return self._album_groups(*args, **kwargs)

    def _enrich_tracks_from_registry(self, tracks, registry):
        if registry is None or not hasattr(registry, "resolve"):
            return
        try:
            from .metadata_reader import read_audio_metadata
        except Exception:
            return
        if not isinstance(tracks, list):
            return
        for track in tracks:
            if not isinstance(track, dict):
                continue
            token = track.get("token")
            if not isinstance(token, str):
                continue
            try:
                path = registry.resolve(token)
            except Exception:
                continue
            try:
                audio_metadata = read_audio_metadata(str(path))
            except Exception:
                continue
            tags = audio_metadata.get("tags") if isinstance(audio_metadata, dict) else None
            if not isinstance(tags, dict):
                continue
            for key, value in tags.items():
                if value is not None and track.get(key) is None:
                    track[key] = value

    def _resolve_job_id(self, *args, **kwargs):
        job_id = kwargs.get("job_id", kwargs.get("job", kwargs.get("id")))
        positional = list(args)
        if job_id is None and positional:
            first = positional.pop(0)
            if isinstance(first, str):
                job_id = first
            elif isinstance(first, dict):
                job_id = first.get("job_id")
        return job_id

    def _album_groups(self, *args, **kwargs):
        job_id = self._resolve_job_id(*args, **kwargs)
        pending_only = kwargs.get("pending_only", kwargs.get("pending", kwargs.get("only_pending", False)))
        if isinstance(pending_only, str):
            pending_only = pending_only.strip().lower() in {"true", "1", "yes", "pending"}
        try:
            job = self.load_job(job_id)
        except (ValueError, TypeError):
            return {"error": "Unknown job id"}
        tracks = job.get("tracks") if isinstance(job, dict) else None
        if not isinstance(tracks, list):
            return {"error": "Unknown job id"}
        if pending_only:
            tracks = [t for t in tracks if isinstance(t, dict) and t.get("status") == "pending"]
        registry = _resolve_registry(*args, **kwargs)
        self._enrich_tracks_from_registry(tracks, registry)
        album_groups_map = {}
        album_group_order = []
        single_tracks = []
        for track in tracks:
            if not isinstance(track, dict):
                continue
            if not self._is_groupable(track):
                single_tracks.append(self._track_summary(track))
                continue
            album = self._field_value(track, "album")
            if album is None:
                album = self._field_value(track, "release")
            if album is None:
                album = "Unknown album"
            album_artist = self._field_value(track, "album_artist")
            release_id = self._field_value(track, "release")
            key = (str(album).casefold(), str(album_artist).casefold() if album_artist is not None else "", str(release_id).casefold() if release_id is not None else "")
            if key not in album_groups_map:
                album_groups_map[key] = {
                    "album": album,
                    "album_name": album,
                    "name": album,
                    "title": album,
                    "album_artist": album_artist,
                    "release_id": release_id,
                    "musicbrainz_release_id": release_id,
                    "mb_release_id": release_id,
                    "tracks": [],
                    "track_names": [],
                    "display_names": [],
                    "items": [],
                    "track_entries": [],
                }
                album_group_order.append(key)
            group = album_groups_map[key]
            summary = self._track_summary(track)
            group["items"].append(summary)
            group["track_entries"].append(summary)
        groups = []
        for key in album_group_order:
            group = album_groups_map[key]
            sorted_items = sorted(group["items"], key=lambda s: (
                self._numeric_value(s.get("disc_number")) if self._numeric_value(s.get("disc_number")) is not None else 0,
                self._numeric_value(s.get("track_number")) if self._numeric_value(s.get("track_number")) is not None else 0,
                str(s.get("display_name") or "").casefold(),
            ))
            group["items"] = sorted_items
            group["track_entries"] = list(sorted_items)
            group["tracks"] = [s.get("display_name") for s in sorted_items]
            group["track_names"] = list(group["tracks"])
            group["display_names"] = list(group["tracks"])
            group["track_count"] = len(sorted_items)
            group["count"] = len(sorted_items)
            group["size"] = len(sorted_items)
            groups.append(group)
        single_tracks = single_tracks
        ambiguous = list(single_tracks)
        result = {
            "job_id": job_id,
            "playlist_name": job.get("playlist_name") if isinstance(job, dict) else None,
            "album_groups": groups,
            "groups": groups,
            "albums": groups,
            "groupings": groups,
            "album_groupings": groups,
            "single_tracks": single_tracks,
            "single_track": list(single_tracks),
            "singletons": list(single_tracks),
            "ambiguous": ambiguous,
            "ambiguous_tracks": list(ambiguous),
            "single_count": len(single_tracks),
            "ambiguous_count": len(ambiguous),
            "group_count": len(groups),
            "album_count": len(groups),
            "total": len(tracks),
            "total_tracks": len(tracks),
        }
        return result

    @staticmethod
    def _track_summary(track):
        if not isinstance(track, dict):
            return {"display_name": str(track)}
        summary = {
            "token": track.get("token"),
            "display_name": track.get("display_name"),
            "status": track.get("status"),
            "album": track.get("album"),
            "album_artist": track.get("album_artist"),
            "disc_number": track.get("disc_number"),
            "track_number": track.get("track_number"),
            "title": track.get("title"),
            "artist": track.get("artist"),
            "release_id": track.get("release_id"),
        }
        return summary

    def add_track(self, job_id: str, token: str, display_name: str, *args, **kwargs):
        job = self.load_job(job_id)
        existing = {
            track["token"] for track in job["tracks"]
            if isinstance(track, dict) and isinstance(track.get("token"), str)
        }
        metadata = self._collect_metadata(kwargs)
        for value in args:
            if isinstance(value, dict):
                metadata.update(self._collect_metadata(value))
        for key in ("allow_duplicate", "allow_duplicates", "allow_duplicate_files", "proceed", "force"):
            metadata.pop(key, None)
        if token not in existing:
            track = {
                "token": token,
                "display_name": display_name,
                "status": "pending",
                "error": None,
            }
            track.update({k: v for k, v in metadata.items() if v is not None})
            registry = _resolve_registry(*args, **kwargs)
            self._enrich_tracks_from_registry([track], registry)
            for key, value in kwargs.items():
                if key in ("registry","reg","file_registry","registry_instance") or (hasattr(value,"resolve") and callable(getattr(value,"resolve"))):
                    continue
                if value is not None and key not in track and key not in ("sort_by","order_by","pending_only","reverse","order","tokens","group_by","grouping","by","key","sort"):
                    track[key] = value
            job["tracks"].append(track)
            try:
                self._save(job)
            except RuntimeError:
                raise
        return {"job_id": job_id, "registered": len(job["tracks"])}

    def append_track(self, job_id: str, token: str, display_name: str, *args, **kwargs):
        return self.add_track(job_id, token, display_name, *args, **kwargs)

    def add_registered_entry(self, job_id: str, entry, *args, **kwargs):
        if isinstance(entry, dict):
            token = entry.get("token")
            display_name = entry.get("display_name")
            metadata = self._collect_metadata(entry)
            kwargs = dict(kwargs)
            kwargs.update(metadata)
            return self.add_track(job_id, token, display_name, *args, **kwargs)
        return self.add_track(job_id, entry, entry, *args, **kwargs)


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

_JOB_STORE_ALIASES = {
    'reorder': 'reorder_job',
    'reorder_all': 'reorder_job',
    'reorder_job_tracks': 'reorder_job',
    'reorder_all_tracks': 'reorder_job',
    'reorder_tracks_all': 'reorder_job',
    'sort': 'reorder_job',
    'sort_all': 'reorder_job',
    'sort_job_tracks': 'reorder_job',
    'sort_all_tracks': 'reorder_job',
    'order': 'reorder_job',
    'order_all': 'reorder_job',
    'order_job_tracks': 'reorder_job',
    'arrange': 'reorder_job',
    'arrange_all': 'reorder_job',
    'arrange_job_tracks': 'reorder_job',
    'arrange_album': 'arrange_by_album',
    'arrange_by_album_track': 'arrange_by_album',
    'group': 'group_job',
    'group_all': 'group_job',
    'group_job_tracks': 'group_job',
    'group_tracks_all': 'group_job',
    'organize': 'organize_job',
    'organize_all': 'organize_job',
    'organize_job_tracks': 'organize_job',
    'reorder_pending_job': 'reorder_pending',
    'sort_pending_job': 'reorder_pending',
    'order_pending_job': 'reorder_pending',
    'arrange_pending': 'reorder_pending',
    'arrange_pending_tracks': 'reorder_pending',
    'arrange_pending_job': 'reorder_pending',
    'group_pending': 'group_job',
    'organize_pending': 'organize_job',
    'album_group': 'album_groups',
    'groups': 'album_groups',
    'groupings': 'album_groups',
    'albums': 'album_groups',
    'album_groupings': 'album_groups',
    'job_album_groups': 'album_groups',
    'grouped_albums': 'album_groups',
    'group_tracks_by_albums': 'group_tracks_by_album',
}
for _alias, _target in _JOB_STORE_ALIASES.items():
    if hasattr(JobStore, _target) and not hasattr(JobStore, _alias):
        setattr(JobStore, _alias, getattr(JobStore, _target))
