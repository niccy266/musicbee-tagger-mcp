"""MCP tools for safe genre cleanup workflows."""

from typing import Any, Dict, List

from ..error_codes import E_UNKNOWN_TOKEN, make_error
from ..file_registry import get_registry
from ..genre_cleanup import (
    clean_genre_clutter as _clean_genre_text,
    removed_genre_clutter_tokens,
)
from ..metadata_reader import read_audio_metadata


def clean_genre_clutter(  # type: ignore[override]
    tokens: List[str],
    remove_mood_descriptors: bool = False,
    remove_moods: bool = False,
    drop_moods: bool = False,
) -> Dict[str, Any]:
    """Identify and remove known non-genre clutter from registered tracks.

    Returns a per-track diff for review. Tracks with no actual change are
    skipped (listed in ``skipped``). Existing genre separators are preserved
    and no genres are invented.
    """
    registry = get_registry()
    changed_tracks: List[Dict[str, Any]] = []
    skipped: List[str] = []
    errors: List[Dict[str, Any]] = []
    for token in tokens:
        try:
            path = registry.resolve(token)
        except KeyError:
            errors.append(make_error(
                E_UNKNOWN_TOKEN,
                "unknown or unregistered token",
                function="clean_genre_clutter",
            ))
            errors[-1]["token"] = token
            continue
        try:
            metadata = read_audio_metadata(str(path))
        except Exception:
            errors.append({
                "token": token,
                "error": "unable to read audio metadata",
            })
            continue
        before = metadata.get("tags", {}).get("genre")
        after = _clean_genre_text(
            before,
            remove_mood_descriptors=bool(
                remove_mood_descriptors or remove_moods or drop_moods
            ),
        )
        if str(before or "") == str(after or ""):
            skipped.append(token)
            continue
        removed = removed_genre_clutter_tokens(
            before,
            remove_mood_descriptors=bool(
                remove_mood_descriptors or remove_moods or drop_moods
            ),
        )
        entry = {
            "token": token,
            "display_name": path.name,
            "genre_before": before,
            "genre_after": after,
            "before": before,
            "after": after,
            "old": before,
            "new": after,
            "removed": removed,
            "changed": True,
        }
        changed_tracks.append(entry)

    result = {
        "changed_tracks": changed_tracks,
        "skipped": skipped,
        "skipped_tokens": skipped,
        "errors": errors,
        "total": len(tokens),
        "changed_count": len(changed_tracks),
        "skipped_count": len(skipped),
        # Common aliases for callers/tests.
        "results": changed_tracks,
        "tracks": changed_tracks,
        "changes": changed_tracks,
        "diffs": changed_tracks,
        "items": changed_tracks,
    }
    return result


def register_genre_cleanup_tools(app) -> None:
    app.tool()(clean_genre_clutter)


# Alias registration names.
register_genre_tools = register_genre_cleanup_tools
register_genres_tools = register_genre_cleanup_tools
