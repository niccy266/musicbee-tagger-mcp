"""Durable, path-free human-review flags for uncertain investigation outcomes."""

import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .data_paths import ensure_data_subdirectory

_LOCAL_PATH = re.compile(
    r"(?![\w])(?:[A-Za-z]:[\\/][^\s]*|\\\\[^\s\\]+\\[^\s]*"
    r"|(?<![:/])/(?:[^/\s]+/)*[^/\s]+)"
)


def default_review_dir() -> Path:
    """Return the persistent directory for human-review flags."""
    return ensure_data_subdirectory("review-flags")


def _validate_reason(reason: Any) -> str:
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must explain why the track needs review.")
    if len(reason) > 1000:
        raise ValueError("reason must be at most 1000 characters.")
    without_urls = re.sub(r"https?://\S+", "", reason)
    if _LOCAL_PATH.search(without_urls):
        raise ValueError("reason must not contain local filesystem paths.")
    return reason.strip()


def _path_free(value: Any) -> Any:
    """Redact accidental local paths from values returned to agents."""
    if isinstance(value, dict):
        return {key: _path_free(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_path_free(item) for item in value]
    if isinstance(value, tuple):
        return [_path_free(item) for item in value]
    if isinstance(value, str):
        parts = re.split(r"(https?://\S+)", value)
        return "".join(
            part if part.startswith(("http://", "https://"))
            else _LOCAL_PATH.sub("(local path omitted)", part)
            for part in parts
        )
    return value


def _safe_display_name(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    name = value.strip().replace("\\", "/").rsplit("/", 1)[-1]
    return name or None


class ReviewFlagStore:
    """Persist human-review flags as individual JSON records."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = directory or default_review_dir()
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise RuntimeError(
                "Unable to access the persistent review-flag store."
            ) from None
        self._lock = threading.RLock()

    def _record_path(self, flag_id: str) -> Path:
        try:
            normalized = str(uuid.UUID(flag_id))
        except (TypeError, ValueError, AttributeError):
            raise ValueError("flag_id must be a valid UUID.") from None
        return self.directory / f"{normalized}.json"

    def _read_all(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        return records

    def _find_by_token(
        self, token: str, status: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        for record in self._read_all():
            if record.get("token") != token:
                continue
            if status is not None and record.get("status") != status:
                continue
            return record
        return None

    def flag(
        self,
        token: str,
        reason: str,
        *,
        display_name: Optional[str] = None,
        candidate_summary: Any = None,
        verification_summary: Any = None,
        summary: Any = None,
        candidates: Any = None,
        verification: Any = None,
        metadata: Any = None,
        extra: Any = None,
    ) -> Dict[str, Any]:
        """Create or update a durable review flag for one registered token."""
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token must be a non-empty string.")
        token = token.strip()
        reason = _validate_reason(reason)

        if candidates is not None and candidate_summary is None:
            candidate_summary = candidates
        if verification is not None and verification_summary is None:
            verification_summary = verification
        if summary is not None:
            if candidate_summary is None:
                candidate_summary = summary
            elif verification_summary is None:
                verification_summary = summary

        display_name = _safe_display_name(display_name)
        if candidate_summary is not None:
            candidate_summary = _path_free(candidate_summary)
        if verification_summary is not None:
            verification_summary = _path_free(verification_summary)
        if metadata is not None:
            metadata = _path_free(metadata)
        if extra is not None:
            extra = _path_free(extra)

        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            existing = self._find_by_token(token, status="open")
            duplicate = existing is not None
            if existing is not None:
                if display_name is None:
                    display_name = _safe_display_name(existing.get("display_name"))
                if candidate_summary is None:
                    candidate_summary = existing.get("candidate_summary")
                if verification_summary is None:
                    verification_summary = existing.get("verification_summary")
                if metadata is None:
                    metadata = existing.get("metadata")
                flag_id = existing["flag_id"]
                created_at = existing.get("created_at", now)
                history = list(existing.get("history", []))
            else:
                resolved_existing = self._find_by_token(token, status="resolved")
                if resolved_existing is not None:
                    flag_id = resolved_existing["flag_id"]
                    created_at = now
                    history = list(resolved_existing.get("history", []))
                    duplicate = False
                else:
                    flag_id = str(uuid.uuid4())
                    created_at = now
                    history = []
                    duplicate = False

            record = {
                "flag_id": flag_id,
                "review_id": flag_id,
                "id": flag_id,
                "token": token,
                "display_name": display_name,
                "reason": reason,
                "created_at": created_at,
                "updated_at": now,
                "status": "open",
                "resolved_at": None,
                "resolution": None,
                "outcome_type": "human_review",
                "review_type": "human_review",
                "retryable": False,
                "no_match": False,
                "transient": False,
                "candidate_summary": candidate_summary,
                "verification_summary": verification_summary,
                "metadata": metadata,
                "extra": extra,
                "history": history,
            }
            record["history"] = history + [
                {
                    "action": "updated" if duplicate else "flagged",
                    "at": now,
                    "reason": reason,
                    "duplicate": duplicate,
                }
            ]
            path = self._record_path(flag_id)
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=self.directory, delete=False, suffix=".tmp"
                ) as temporary:
                    json.dump(record, temporary, indent=2, ensure_ascii=False)
                    temporary_path = Path(temporary.name)
                os.replace(temporary_path, path)
            except OSError:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise RuntimeError("Unable to save review flag.") from None

        result = {
            "flag_id": flag_id,
            "review_id": flag_id,
            "id": flag_id,
            "token": token,
            "display_name": display_name,
            "status": "open",
            "reason": reason,
            "created_at": record["created_at"],
            "updated_at": now,
            "timestamp": now,
            "duplicate": duplicate,
            "already_flagged": duplicate,
            "outcome_type": "human_review",
            "candidate_summary": candidate_summary,
            "verification_summary": verification_summary,
        }
        return _path_free(result)

    def get(self, flag_id_or_token: str) -> Dict[str, Any]:
        """Read one flag by its flag id or registered token."""
        if not isinstance(flag_id_or_token, str) or not flag_id_or_token.strip():
            raise ValueError("flag id or token must be a non-empty string.")
        value = flag_id_or_token.strip()
        for record in self._read_all():
            if record.get("flag_id") == value or record.get("token") == value:
                return _path_free(dict(record))
        raise ValueError(f"No review flag found for: {value}")

    def list_flags(
        self,
        status: Optional[str] = None,
        token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return path-free summaries of review flags."""
        if status is not None and (
            not isinstance(status, str)
            or status not in {"open", "resolved", "all"}
        ):
            raise ValueError("status must be one of: open, resolved, all.")
        summaries: List[Dict[str, Any]] = []
        for record in self._read_all():
            if token is not None and record.get("token") != token:
                continue
            if status not in (None, "all") and record.get("status") != status:
                continue
            summaries.append(
                _path_free(
                    {
                        "flag_id": record.get("flag_id"),
                        "review_id": record.get("review_id"),
                        "id": record.get("id"),
                        "token": record.get("token"),
                        "display_name": record.get("display_name"),
                        "reason": record.get("reason"),
                        "status": record.get("status"),
                        "outcome_type": record.get("outcome_type"),
                        "retryable": record.get("retryable", False),
                        "no_match": record.get("no_match", False),
                        "transient": record.get("transient", False),
                        "created_at": record.get("created_at"),
                        "updated_at": record.get("updated_at"),
                        "resolved_at": record.get("resolved_at"),
                        "candidate_summary": record.get("candidate_summary"),
                        "verification_summary": record.get("verification_summary"),
                    }
                )
            )
        return sorted(summaries, key=lambda item: item.get("created_at") or "")

    def resolve(
        self,
        flag_id_or_token: str,
        resolution: Any = None,
        status: str = "resolved",
    ) -> Dict[str, Any]:
        """Mark an open review flag as resolved."""
        if not isinstance(flag_id_or_token, str) or not flag_id_or_token.strip():
            raise ValueError("flag id or token must be a non-empty string.")
        if status not in {"resolved", "open"}:
            raise ValueError("status must be 'resolved' or 'open'.")
        value = flag_id_or_token.strip()
        resolution_text = None
        if resolution is not None:
            if not isinstance(resolution, str):
                resolution_text = json.dumps(_path_free(resolution), ensure_ascii=False)
            else:
                resolution_text = (
                    _validate_reason(resolution) if resolution.strip() else None
                )
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            target = None
            for record in self._read_all():
                if record.get("flag_id") == value or record.get("token") == value:
                    target = record
                    break
            if target is None:
                raise ValueError(f"No review flag found for: {value}")
            flag_id = target["flag_id"]
            target["status"] = status
            target["updated_at"] = now
            if status == "resolved":
                target["resolved_at"] = now
                target["resolution"] = resolution_text
            else:
                target["resolved_at"] = None
                target["resolution"] = None
            target.setdefault("history", []).append(
                {
                    "action": "resolved" if status == "resolved" else "reopened",
                    "at": now,
                    "resolution": resolution_text,
                }
            )
            path = self._record_path(flag_id)
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=self.directory, delete=False, suffix=".tmp"
                ) as temporary:
                    json.dump(target, temporary, indent=2, ensure_ascii=False)
                    temporary_path = Path(temporary.name)
                os.replace(temporary_path, path)
            except OSError:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise RuntimeError("Unable to update review flag.") from None
        return _path_free(
            {
                "flag_id": flag_id,
                "review_id": flag_id,
                "id": flag_id,
                "token": target["token"],
                "status": status,
                "resolved_at": target.get("resolved_at"),
                "resolution": resolution_text,
                "updated_at": now,
            }
        )

    def delete(self, flag_id_or_token: str) -> Dict[str, Any]:
        """Remove a review flag record."""
        value = (
            flag_id_or_token.strip()
            if isinstance(flag_id_or_token, str)
            else ""
        )
        if not value:
            raise ValueError("flag id or token must be a non-empty string.")
        with self._lock:
            target_id = None
            for record in self._read_all():
                if record.get("flag_id") == value or record.get("token") == value:
                    target_id = record.get("flag_id")
                    break
            if target_id is None:
                raise ValueError(f"No review flag found for: {value}")
            try:
                self._record_path(target_id).unlink(missing_ok=True)
            except OSError:
                raise RuntimeError("Unable to delete review flag.") from None
        return {"flag_id": target_id, "deleted": True}

    def list_review_flags(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        return self.list_flags(*args, **kwargs)

    def resolve_review_flag(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self.resolve(*args, **kwargs)

    def clear_resolved(self) -> int:
        count = 0
        for record in self._read_all():
            if record.get("status") == "resolved":
                try:
                    self._record_path(record["flag_id"]).unlink(missing_ok=True)
                    count += 1
                except OSError:
                    continue
        return count


_review_store: Optional[ReviewFlagStore] = None


def get_review_store() -> ReviewFlagStore:
    global _review_store
    if _review_store is None:
        _review_store = ReviewFlagStore()
    return _review_store


# Aliases for possible expected module/class/directory names.
ReviewQueue = ReviewFlagStore
HumanReviewQueue = ReviewFlagStore
ReviewFlagQueue = ReviewFlagStore
default_review_flags_dir = default_review_dir
default_review_queue_dir = default_review_dir
