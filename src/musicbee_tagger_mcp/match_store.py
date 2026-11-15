"""In-memory and process-local store for safer MusicBrainz match handles."""

from typing import Any, Dict, Optional
import uuid

_HANDLES: Dict[str, Dict[str, Any]] = {}
_LATEST_BY_TOKEN: Dict[str, str] = {}
_LATEST_BY_RECORDING: Dict[str, str] = {}


def record_match(
    recording_id: str,
    release_id: Optional[str] = None,
    confidence: Optional[float] = None,
    token: Optional[str] = None,
    **extra: Any,
) -> str:
    handle = str(uuid.uuid4())
    entry = {
        "handle": handle,
        "recording_id": recording_id,
        "release_id": release_id,
        "confidence": confidence,
        "token": token,
    }
    entry.update({k: v for k, v in extra.items() if v is not None})
    _HANDLES[handle] = entry
    if token is not None:
        _LATEST_BY_TOKEN[token] = handle
    if isinstance(recording_id, str) and recording_id.strip():
        _LATEST_BY_RECORDING[recording_id.strip()] = handle
    return handle


def resolve_match(handle: Optional[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(handle, str):
        return None
    try:
        normalized = str(uuid.UUID(handle))
    except (TypeError, ValueError, AttributeError):
        return None
    return _HANDLES.get(normalized)


def latest_match_handle(token: Optional[str]) -> Optional[str]:
    if not isinstance(token, str):
        return None
    return _LATEST_BY_TOKEN.get(token)


def resolve_match_for_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    handle = latest_match_handle(token)
    if handle is None:
        return None
    return resolve_match(handle)


def resolve_match_for_recording(recording_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(recording_id, str) or not recording_id.strip():
        return None
    handle = _LATEST_BY_RECORDING.get(recording_id.strip())
    if handle is None:
        return None
    return resolve_match(handle)


def clear_matches() -> None:
    _HANDLES.clear()
    _LATEST_BY_TOKEN.clear()
    _LATEST_BY_RECORDING.clear()


record_verified_match = record_match
store_match = record_match
save_match = record_match
get_match = resolve_match
lookup_match = resolve_match
resolve_verified_match = resolve_match
match_for_token = resolve_match_for_token
latest_match = resolve_match_for_token
get_match_for_token = resolve_match_for_token
