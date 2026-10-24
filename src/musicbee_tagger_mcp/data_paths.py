"""Shared locations for private MusicBee Tagger state."""

import os
from pathlib import Path


def default_data_dir() -> Path:
    """Return the configured private data directory without creating it."""
    configured_root = os.environ.get("MUSICBEE_TAGGER_DATA_DIR")
    if configured_root:
        return Path(configured_root).expanduser()

    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home()
    return base / "musicbee-tagger-mcp"


def ensure_data_subdirectory(name: str) -> Path:
    """Create and return one private application data subdirectory."""
    directory = default_data_dir() / name
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise RuntimeError(
            "Unable to access the MusicBee Tagger MCP data directory; "
            "check MUSICBEE_TAGGER_DATA_DIR and local permissions."
        ) from None
    return directory
