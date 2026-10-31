"""CLI-only tag mutation orchestration and backup handling."""

import shutil
from pathlib import Path
from typing import Any, Dict

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

from .tag_format_writers import write_id3, write_mp4, write_vorbis
from .tag_preview import preview_tag_changes


def apply_tags_to_file(
    file_path: str,
    new_tags: Dict[str, Any],
    create_backup: bool = True,
) -> Dict[str, Any]:
    """Write proposed tags after optional backup creation."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    preview = preview_tag_changes(file_path, new_tags)
    if not preview["has_changes"]:
        return {
            "file_path": file_path,
            "status": "skipped",
            "message": "No changes detected",
            "backup_created": False,
        }

    audio = mutagen.File(file_path)
    if audio is None:
        raise ValueError(f"Unsupported format: {file_path}")

    backup_path = None
    if create_backup:
        backup_path = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup_path)

    if hasattr(audio, "tags") and (isinstance(audio.tags, ID3) or path.suffix.lower() == ".mp3"):
        write_id3(audio, new_tags)
    elif isinstance(audio, (FLAC, OggVorbis)):
        write_vorbis(audio, new_tags)
    elif isinstance(audio, MP4):
        write_mp4(audio, new_tags)
    else:
        for key, value in new_tags.items():
            if value is not None:
                audio[key] = [str(value)]
        audio.save()

    return {
        "file_path": file_path,
        "status": "success",
        "backup_created": str(backup_path) if backup_path else None,
        "fields_written": [key for key, change in preview["diff"].items()
                           if change["changed"]],
        "applied_diff": preview["diff"],
    }
