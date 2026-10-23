"""Token-based metadata and filename investigation tools."""

from typing import Any, Dict, List

from ..file_registry import get_registry
from ..filename_parser import extract_clues_from_filename
from ..metadata_reader import read_audio_metadata


def read_track_metadata(token: str) -> Dict[str, Any]:
    """Read metadata for a registered track without returning its path."""
    path = get_registry().resolve(token)
    metadata = read_audio_metadata(str(path))
    metadata.pop("file_path", None)
    return metadata


def extract_filename_clues(token: str) -> Dict[str, Any]:
    """Extract clues from the registered file's bare filename."""
    entry = get_registry().resolve(token)
    return extract_clues_from_filename(entry.name)


def get_batch_brief(tokens: List[str]) -> List[Dict[str, Any]]:
    """Return metadata and filename clues for each registered token."""
    registry = get_registry()
    briefs = []
    for token in tokens:
        try:
            path = registry.resolve(token)
            metadata = read_audio_metadata(str(path))
            briefs.append({
                "token": token,
                "display_name": path.name,
                "duration_seconds": metadata.get("duration_seconds"),
                "format": metadata.get("format"),
                "tags": metadata.get("tags", {}),
                "filename_clues": extract_clues_from_filename(path.name),
            })
        except Exception as error:
            briefs.append({"token": token, "error": str(error)})
    return briefs


def register_inspection_tools(app) -> None:
    app.tool()(read_track_metadata)
    app.tool()(extract_filename_clues)
    app.tool()(get_batch_brief)
