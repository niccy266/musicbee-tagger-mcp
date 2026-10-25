"""Path-safe playlist registration used only by the local human CLI."""

from typing import Any, Callable, Dict, List, Optional

from ..file_registry import FileRegistry, get_registry
from ..playlist import parse_m3u_playlist


def register_playlist(
    playlist_path: str, registry: Optional[FileRegistry] = None,
    job_store: Any = None, job_id: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
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
    total = len(entries)
    if progress_callback is not None:
        progress_callback(0, total)
    for index, (line_number, entry_path, skip_reason) in enumerate(entries, start=1):
        if skip_reason:
            skipped.append({"line": line_number, "error": skip_reason})
            if progress_callback is not None:
                progress_callback(index, total)
            continue
        if entry_path is None:
            skipped.append({"line": line_number, "error": "Invalid playlist entry"})
            if progress_callback is not None:
                progress_callback(index, total)
            continue
        try:
            result = registry.register(str(entry_path))
            registered.append({"line": line_number, **result})
            if job_store is not None and job_id is not None:
                job_store.add_track(job_id, result["token"], result["display_name"])
        except FileNotFoundError:
            skipped.append({"line": line_number, "error": "File not found"})
        except OSError:
            skipped.append({"line": line_number, "error": "Unable to access file"})
        except (RuntimeError, ValueError):
            skipped.append({"line": line_number, "error": "Unable to resolve file"})
        if progress_callback is not None:
            progress_callback(index, total)
    playlist_name = playlist_path.replace("\\", "/").rsplit("/", 1)[-1]
    if job_store is not None and job_id is not None:
        try:
            job_store.set_skipped(job_id, len(skipped))
        except Exception:
            pass
    return {
        "registered": registered,
        "skipped": skipped,
        "playlist_name": playlist_name,
    }
