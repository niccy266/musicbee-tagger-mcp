"""Read-only tag diff preview."""

from typing import Any, Dict

from .metadata_reader import read_audio_metadata


def preview_tag_changes(file_path: str, new_tags: Dict[str, Any]) -> Dict[str, Any]:
    """Return a field-by-field diff without writing to the audio file."""
    current_tags = read_audio_metadata(file_path).get("tags", {})
    diff = {}
    for key in sorted(set(current_tags) | set(new_tags)):
        before = current_tags.get(key)
        after = new_tags.get(key, before)
        changed = (
            str(before) if before is not None else ""
        ) != (
            str(after) if after is not None else ""
        ) and key in new_tags
        diff[key] = {
            "before": before,
            "after": after if key in new_tags else before,
            "changed": changed,
        }
    return {
        "file_path": file_path,
        "has_changes": any(item["changed"] for item in diff.values()),
        "diff": diff,
    }
