"""Token-based metadata and filename investigation tools."""

from typing import Any, Dict, List

from ..error_codes import (
    E_FILE_NOT_FOUND,
    E_PERMISSION_DENIED,
    E_PARSE_ERROR,
    E_UNSUPPORTED_FORMAT,
    E_UNKNOWN_TOKEN,
    error_from_exception,
    make_error,
)
from ..file_registry import get_registry
from ..filename_parser import extract_clues_from_filename
from ..metadata_reader import read_audio_metadata


def read_track_metadata(token: str) -> Dict[str, Any]:
    """Read metadata for a registered track without returning its path.

    NEXT STEP: Call extract_filename_clues and search_canonical_release to
    find a matching MusicBrainz recording for verification.
    """
    try:
        path = get_registry().resolve(token)
    except KeyError:
        # Tokens may be unknown to this server process's registry/data dir.
        # Keep the response path-free and avoid an unhandled MCP tool error.
        return make_error(
            E_UNKNOWN_TOKEN,
            "unknown or unregistered token",
            function="read_track_metadata",
        )
    try:
        metadata = read_audio_metadata(str(path))
    except Exception as exc:
        # File-reader exceptions may include the absolute path.
        return error_from_exception(exc, function="read_track_metadata")

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
        return make_error(
            E_UNKNOWN_TOKEN,
            "unknown or unregistered token",
            function="extract_filename_clues",
        )
    try:
        return extract_clues_from_filename(str(entry))
    except Exception as exc:
        # Filename parsing should not fail, but if it does, report it
        # path-free with the tool's function name.
        return error_from_exception(exc, function="extract_filename_clues")


def get_batch_brief(tokens: List[str]) -> List[Dict[str, Any]]:
    """Return metadata and unverified filename research clues for each token."""
    registry = get_registry()
    briefs = []
    for token in tokens:
        try:
            path = registry.resolve(token)
        except KeyError:
            # Token is not registered in this server's file registry.
            # Return a consistent structure (matching successful entries)
            # so the agent can handle it uniformly — mark it unresolved
            # rather than leaving the model with an incomplete entry.
            briefs.append({
                "token": token,
                "display_name": None,
                "duration_seconds": None,
                "format": None,
                "tags": {},
                "filename_clues": {},
                "error_code": E_UNKNOWN_TOKEN,
                "error": "unknown or unregistered token",
                "function": "get_batch_brief",
            })
            continue
        try:
            metadata = read_audio_metadata(str(path))
        except Exception as exc:
            # File-reader exceptions may include the absolute path.
            briefs.append(error_from_exception(exc, function="get_batch_brief"))
            briefs[-1]["token"] = token
            continue
        briefs.append({
            "token": token,
            "display_name": path.name,
            "duration_seconds": metadata.get("duration_seconds"),
            "format": metadata.get("format"),
            "tags": metadata.get("tags", {}),
            "filename_clues": extract_clues_from_filename(str(path)),
        })


    return briefs


def register_inspection_tools(app) -> None:
    app.tool()(read_track_metadata)
    app.tool()(extract_filename_clues)
    app.tool()(get_batch_brief)
