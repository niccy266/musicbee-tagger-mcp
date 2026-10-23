"""MCP registration tools. Paths enter here and leave only as tokens."""

from typing import Any, Dict, List

from ..file_registry import get_registry
from ..playlist import parse_m3u_playlist


def register_files(paths: List[str]) -> List[Dict[str, str]]:
    """Register paths and return opaque tokens with filename-only labels."""
    registry = get_registry()
    results = []
    for path in paths:
        try:
            results.append(registry.register(path))
        except FileNotFoundError:
            results.append({"error": "File not found"})
        except OSError:
            results.append({"error": "Unable to access file"})
        except (RuntimeError, ValueError):
            results.append({"error": "Unable to resolve file"})
    return results


def register_playlist(playlist_path: str) -> Dict[str, Any]:
    """Register supported local playlist entries without returning their paths."""
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
    for line_number, entry_path, skip_reason in entries:
        if skip_reason:
            skipped.append({"line": line_number, "error": skip_reason})
            continue
        if entry_path is None:
            skipped.append({"line": line_number, "error": "Invalid playlist entry"})
            continue
        try:
            result = get_registry().register(str(entry_path))
            registered.append({"line": line_number, **result})
        except FileNotFoundError:
            skipped.append({"line": line_number, "error": "File not found"})
        except OSError:
            skipped.append({"line": line_number, "error": "Unable to access file"})
        except (RuntimeError, ValueError):
            skipped.append({"line": line_number, "error": "Unable to resolve file"})
    return {"registered": registered, "skipped": skipped}


def register_file_tools(app) -> None:
    app.tool()(register_files)
    app.tool()(register_playlist)
