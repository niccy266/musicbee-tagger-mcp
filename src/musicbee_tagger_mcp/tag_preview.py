"""Read-only tag diff preview."""

from typing import Any, Dict

import re

from .field_map import normalize_for_matching
from .metadata_reader import read_audio_metadata

_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")


def _has_invisible(text: Any) -> bool:
    if text is None:
        return False
    return bool(_INVISIBLE_RE.search(str(text)))


def preview_tag_changes(file_path: str, new_tags: Dict[str, Any]) -> Dict[str, Any]:
    """Return a field-by-field diff without writing to the audio file."""
    current_tags = read_audio_metadata(file_path).get("tags", {})
    diff = {}
    invisible_fields = []
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
            "invisible_chars_omitted": _has_invisible(before) or _has_invisible(after),
        }
        if _has_invisible(before) or _has_invisible(after):
            invisible_fields.append(key)
    return {
        "file_path": file_path,
        "has_changes": any(item["changed"] for item in diff.values()),
        "diff": diff,
        "invisible_chars_omitted": bool(invisible_fields),
        "fields_with_invisible_chars": invisible_fields,
    }
