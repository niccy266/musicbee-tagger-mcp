"""MCP tools for optional ACRCloud fingerprint identification."""

from typing import Any, Dict, Optional

from ..file_registry import get_registry
from ..metadata_reader import read_audio_metadata
from ..acrcloud import get_acrcloud_provider


def identify_acrcloud(token: str) -> Dict[str, Any]:
    """Identify a registered track using ACRCloud (opt-in fallback).

    Credentials must be supplied by the user through environment variables.
    This tool only returns identification evidence; it never stages tags.
    """
    try:
        path = get_registry().resolve(token)
    except Exception:
        return {"error": "Unknown or unregistered token"}

    try:
        metadata = read_audio_metadata(str(path))
    except Exception:
        metadata = {}
    duration = metadata.get("duration_seconds")

    try:
        audio_bytes = path.read_bytes()
    except Exception:
        return {"error": "Unable to read track audio"}

    # Keep the upload small; ACRCloud only needs a short sample.
    audio_bytes = audio_bytes[:1_000_000]

    provider = get_acrcloud_provider()
    if not provider.is_configured():
        return provider.identify(b"", filename=path.name, duration_sec=duration)

    result = provider.identify(
        audio_bytes,
        filename=path.name,
        duration_sec=duration,
    )
    result.pop("raw", None)
    return result


def register_acrcloud_tools(app) -> None:
    app.tool()(identify_acrcloud)
