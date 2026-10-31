"""Local M3U playlist parsing for token-based batch registration."""

import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse


def _is_absolute_path(value: object) -> bool:
    text = str(value)
    if text.startswith("/"):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", text) is not None:
        return True
    if text.startswith("\\\\") or text.startswith("//"):
        return True
    return False

from .filename_parser import AUDIO_EXTS


def translate_audio_path(path: Path, container_audio_dir: str = "/audio") -> str:
    """Choops the path after 'musicbee' (and optional 'main') and returns container audio posix path string."""
    parts = path.parts
    musicbee_idx = -1
    for i, part in enumerate(parts):
        if part.lower() == "musicbee":
            musicbee_idx = i
            break
    
    if musicbee_idx != -1:
        start_idx = musicbee_idx + 1
        if start_idx < len(parts) and parts[start_idx].lower() == "main":
            start_idx += 1
        
        sub_parts = parts[start_idx:]
        if sub_parts:
            return container_audio_dir + "/" + "/".join(sub_parts)
            
    return path.as_posix()


def parse_m3u_playlist(
    playlist_path: str,
) -> List[Tuple[int, Optional[Path], Optional[str]]]:
    """Return local audio paths or safe skip reasons with playlist line numbers."""
    path = Path(str(playlist_path)).resolve()
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

        entry_path = Path(str(entry))
        if entry_path.suffix.lower() not in AUDIO_EXTS:
            entries.append((line_number, None, "Unsupported audio format"))
            continue

        if not (entry_path.is_absolute() or _is_absolute_path(entry_path)):
            entry_path = path.parent / entry_path

        entries.append((line_number, entry_path, None))

    return entries
