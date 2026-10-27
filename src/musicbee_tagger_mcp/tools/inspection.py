"""Token-based metadata and filename investigation tools."""

from typing import Any, Dict, List

from ..file_registry import get_registry
from ..filename_parser import extract_clues_from_filename
from ..metadata_reader import read_audio_metadata


def _read_error_reason(exc: Exception) -> str:
    """Map a metadata-read failure to a path-safe reason code."""
    if isinstance(exc, FileNotFoundError):
        return "file_missing"
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, ValueError):
        return "unsupported_format"
    return "parse_error"


def read_track_metadata(token: str) -> Dict[str, Any]:
    """Read metadata for a registered track without returning its path."""
    try:
        path = get_registry().resolve(token)
    except KeyError:
        # Tokens may be unknown to this server process's registry/data dir.
        # Keep the response path-free and avoid an unhandled MCP tool error.
        return {"error": "Unknown file token"}
    try:
        metadata = read_audio_metadata(str(path))
    except Exception as exc:
        # File-reader exceptions may include the absolute path.
        return {"error": _read_error_reason(exc)}

    metadata.pop("file_path", None)
    return metadata



def extract_filename_clues(token: str) -> Dict[str, Any]:
    """Extract unverified research clues from the registered file's filename.

    Artist/title candidates are ambiguous hypotheses, not tag evidence. A
    separator may split an artist, title, or unrelated text. Corroborate them
    with metadata, duration, or a release track listing before staging tags.
    """
    try:
        entry = get_registry().resolve(token)
    except KeyError:
        return {"error": "Unknown file token"}
    return extract_clues_from_filename(entry.name)


def get_batch_brief(tokens: List[str]) -> List[Dict[str, Any]]:
    """Return metadata and unverified filename research clues for each token."""
    registry = get_registry()
    briefs = []
    for token in tokens:
        try:
            path = registry.resolve(token)
        except KeyError:
            briefs.append({"token": token, "error": "unknown_token"})
            continue
        try:
            metadata = read_audio_metadata(str(path))
        except Exception as exc:
            # File-reader exceptions may include the absolute path.
            briefs.append({"token": token, "error": _read_error_reason(exc)})
            continue
        briefs.append({
            "token": token,
            "display_name": path.name,
            "duration_seconds": metadata.get("duration_seconds"),
            "format": metadata.get("format"),
            "tags": metadata.get("tags", {}),
            "filename_clues": extract_clues_from_filename(path.name),
        })


    return briefs


def register_inspection_tools(app) -> None:
    app.tool()(read_track_metadata)
    app.tool()(extract_filename_clues)
    app.tool()(get_batch_brief)
