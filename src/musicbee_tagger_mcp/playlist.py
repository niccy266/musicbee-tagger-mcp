"""Local M3U playlist parsing for token-based batch registration."""

import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from .filename_parser import AUDIO_EXTS


def parse_m3u_playlist(
    playlist_path: str,
) -> List[Tuple[int, Optional[Path], Optional[str]]]:
    """Return local audio paths or safe skip reasons with playlist line numbers."""
    path = Path(playlist_path).resolve()
    if path.suffix.lower() not in {".m3u", ".m3u8"}:
        raise ValueError("Unsupported playlist format")

    content = path.read_bytes()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")

    entries: List[Tuple[int, Optional[Path], Optional[str]]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        entry = raw_line.strip()
        if not entry or entry.startswith("#"):
            continue

        is_windows_drive_path = re.match(r"^[A-Za-z]:[\\/]", entry) is not None
        if urlparse(entry).scheme and not is_windows_drive_path:
            entries.append((line_number, None, "Remote playlist entries are not supported"))
            continue

        entry_path = Path(entry)
        if entry_path.suffix.lower() not in AUDIO_EXTS:
            entries.append((line_number, None, "Unsupported audio format"))
            continue

        if not entry_path.is_absolute():
            entry_path = path.parent / entry_path

        entries.append((line_number, entry_path, None))

    return entries
