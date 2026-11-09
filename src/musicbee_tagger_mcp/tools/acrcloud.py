"""MCP tools for optional ACRCloud fingerprint identification."""

from typing import Any, Dict, Optional

from ..error_codes import (
    redact_paths,
    E_AUDIO_READ_FAILED,
    E_PROVIDER_FAILED,
    E_PROVIDER_NOT_CONFIGURED,
    E_UNKNOWN_TOKEN,
    make_error,
)
from ..file_registry import get_registry
from ..metadata_reader import read_audio_metadata
from ..acrcloud import get_acrcloud_provider


def identify_acrcloud(token: str) -> Dict[str, Any]:
    """Identify a registered track using ACRCloud audio fingerprinting (opt-in fallback).

    Returns identification evidence only; never stages tags. NEXT STEP: If
    ACRCloud returns a match, use the recording_id to call evaluate_match
    and then stage_tag_changes. If no match, mark the file unresolved.
    """
    try:
        path = get_registry().resolve(token)
    except Exception:
        return make_error(
            E_UNKNOWN_TOKEN,
            "unknown or unregistered token",
            function="identify_acrcloud",
        )

    try:
        metadata = read_audio_metadata(str(path))
    except Exception:
        metadata = {}
    duration = metadata.get("duration_seconds")

    try:
        audio_bytes = path.read_bytes()
    except Exception:
        return make_error(
            E_AUDIO_READ_FAILED,
            "access denied by filesystem",
            function="identify_acrcloud",
        )

    # Keep the upload small; ACRCloud only needs a short sample.
    audio_bytes = audio_bytes[:1_000_000]

    provider = get_acrcloud_provider()
    if not provider.is_configured():
        return make_error(
            E_PROVIDER_NOT_CONFIGURED,
            "ACRCloud not configured",
            function="identify_acrcloud",
        )

    try:
        result = provider.identify(
            audio_bytes,
            filename=path.name,
            duration_sec=duration,
        )
    except Exception as error:
        return make_error(
            E_PROVIDER_FAILED,
            redact_paths(f"ACRCloud request failed: {type(error).__name__}: {error}"),
            function="identify_acrcloud",
        )
    if isinstance(result, dict) and result.get("status") == "error":
        return make_error(
            E_PROVIDER_FAILED,
            redact_paths(str(result.get("error", "ACRCloud request failed"))),
            function="identify_acrcloud",
        )
    return result


def register_acrcloud_tools(app) -> None:
    app.tool()(identify_acrcloud)
