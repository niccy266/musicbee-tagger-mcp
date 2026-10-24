"""Path-safe playlist registration used only by the local human CLI."""

from typing import Any, Dict, List, Optional

from ..file_registry import FileRegistry, get_registry
from ..playlist import parse_m3u_playlist


def register_playlist(
    playlist_path: str, registry: Optional[FileRegistry] = None
) -> Dict[str, Any]:
    """Register playlist entries locally and return tokens without paths."""
    try:
        entries = parse_m3u_playlist(playlist_path)
    except FileNotFoundError:
        return {"error": "Playlist not found"}
    except PermissionError:
        return {"error": "Unable to access playlist"}
    except OSError:
        return {"error": "Unable to read playlist"}
    except ValueError as error:
        if str(error) == "Unsupported playlist format":
            return {"error": "Unsupported playlist format"}
        return {"error": "Unable to resolve playlist"}
    except RuntimeError:
        return {"error": "Unable to resolve playlist"}

    registered: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    registry = registry or get_registry()
    for line_number, entry_path, skip_reason in entries:
        if skip_reason:
            skipped.append({"line": line_number, "error": skip_reason})
            continue
        if entry_path is None:
            skipped.append({"line": line_number, "error": "Invalid playlist entry"})
            continue
        try:
            result = registry.register(str(entry_path))
            registered.append({"line": line_number, **result})
        except FileNotFoundError:
            skipped.append({"line": line_number, "error": "File not found"})
        except OSError:
            skipped.append({"line": line_number, "error": "Unable to access file"})
        except (RuntimeError, ValueError):
            skipped.append({"line": line_number, "error": "Unable to resolve file"})
    return {"registered": registered, "skipped": skipped}
