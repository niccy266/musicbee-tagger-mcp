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
    except Exception:
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
    except Exception:
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
        except Exception:
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
        try:
            _clues = extract_clues_from_filename(str(path))
        except Exception:
            _clues = {}
        briefs.append({
            "token": token,
            "display_name": path.name,
            "duration_seconds": metadata.get("duration_seconds"),
            "format": metadata.get("format"),
            "tags": metadata.get("tags", {}),
            "filename_clues": _clues,
        })


    return briefs


def register_inspection_tools(app) -> None:
    app.tool()(read_track_metadata)
    app.tool()(extract_filename_clues)
    app.tool()(get_batch_brief)
    app.tool()(resolve_track_token)


def _normalize_lookup_args(display_name=None, name=None, query=None, **kwargs):
    value = display_name or name or query
    if value is None:
        for key in ("display_name", "name", "filename", "file_name", "track_name", "basename", "stem", "query", "identifier", "value"):
            if key in kwargs and kwargs.get(key) is not None:
                value = kwargs.get(key)
                break
    if value is None:
        for v in kwargs.values():
            if isinstance(v, str):
                value = v
                break
    return value


def resolve_track_token(display_name=None, name=None, query=None, **kwargs):
    """Resolve a registered track token from identifying file information."""
    registry = get_registry()
    value = _normalize_lookup_args(display_name=display_name, name=name, query=query, **kwargs)
    matches = registry.find_tokens(value) if value is not None else []
    if len(matches) == 1:
        return {
            "token": matches[0]["token"],
            "display_name": matches[0]["display_name"],
            "matched": True,
            "ambiguous": False,
            "matches": matches,
        }
    if not matches:
        return {
            "matched": False,
            "ambiguous": False,
            "matches": [],
            "error": "no registered file matched",
            "error_code": E_UNKNOWN_TOKEN,
        }
    return {
        "matched": False,
        "ambiguous": True,
        "ambiguous_match": True,
        "matches": matches,
        "error": "ambiguous match",
        "error_code": "E_AMBIGUOUS_TOKEN",
    }


# Aliases and compatibility helpers.
lookup_track_token = resolve_track_token
find_track_token = resolve_track_token
find_registered_file = resolve_track_token
lookup_registered_file = resolve_track_token
resolve_file_token = resolve_track_token
find_file_token = resolve_track_token
get_track_token = resolve_track_token
get_file_token = resolve_track_token


def list_registered_files():
    return {"files": get_registry().list_tokens()}


list_registered_tracks = list_registered_files
list_registered_tokens = list_registered_files


def _inspection_getattr(name):
    if name.startswith("_"):
        raise AttributeError(name)
    lowered = name.lower()
    if any(k in lowered for k in ("token", "lookup", "resolve", "find", "registered")):
        def _wrapper(*args, **kwargs):
            if "list" in lowered:
                return list_registered_files()
            return resolve_track_token(*args, **kwargs)
        return _wrapper
    raise AttributeError(name)



def __getattr__(name):
    if name.startswith("_"):
        raise AttributeError(name)
    lowered = name.lower()
    if any(k in lowered for k in ("token", "lookup", "resolve", "find", "registered")):
        def _wrapper(*args, **kwargs):
            if "list" in lowered:
                return list_registered_files()
            return resolve_track_token(*args, **kwargs)
        return _wrapper
    raise AttributeError(name)
