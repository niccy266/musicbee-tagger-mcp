"""MCP tools for optional AcoustID fingerprint investigation."""

from typing import Any, Dict, Optional

from ..error_codes import (
    E_AUDIO_READ_FAILED,
    E_INVALID_INPUT,
    E_PROVIDER_FAILED,
    E_PROVIDER_NOT_CONFIGURED,
    E_UNKNOWN_TOKEN,
    make_error,
    redact_paths,
)
from ..file_registry import get_registry
from ..metadata_reader import read_audio_metadata
from ..acoustid import (
    AcoustIDConfig,
    get_acoustid_provider,
    get_audio_fingerprint_for_path,
    lookup_acoustid_with_config,
)


def get_audio_fingerprint(token: str) -> Dict[str, Any]:
    """Compute an audio fingerprint for a registered track using fpcalc."""
    try:
        path = get_registry().resolve(token)
    except Exception:
        return make_error(
            E_UNKNOWN_TOKEN,
            "unknown or unregistered token",
            function="get_audio_fingerprint",
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
            function="get_audio_fingerprint",
        )
    del audio_bytes

    config = AcoustIDConfig.from_env()
    result = get_audio_fingerprint_for_path(path, config=config)
    if isinstance(result, dict) and result.get("status") == "error":
        return make_error(
            E_PROVIDER_FAILED,
            redact_paths(str(result.get("error", "fpcalc failed"))),
            function="get_audio_fingerprint",
        )
    if isinstance(result, dict):
        result.setdefault("token", None)
        result["duration_seconds"] = result.get("duration_seconds", duration)
        result["duration"] = result.get("duration", duration)
    return result


def lookup_acoustid(fingerprint: str, duration: Any) -> Dict[str, Any]:
    """Look up an AcoustID fingerprint and return recording evidence."""
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        return make_error(
            E_INVALID_INPUT,
            "a non-empty AcoustID fingerprint is required",
            function="lookup_acoustid",
        )
    try:
        duration_value = float(duration)
    except (TypeError, ValueError):
        return make_error(
            E_INVALID_INPUT,
            "duration must be a number of seconds",
            function="lookup_acoustid",
        )
    if duration_value <= 0:
        return make_error(
            E_INVALID_INPUT,
            "duration must be greater than zero seconds",
            function="lookup_acoustid",
        )

    config = AcoustIDConfig.from_env()
    provider = get_acoustid_provider(config)
    if not provider.is_configured():
        result = make_error(
            E_PROVIDER_NOT_CONFIGURED,
            (
                "AcoustID is not configured. Set ACOUSTID_API_KEY (or "
                "ACOUSTID_CLIENT / ACOUSTID_KEY) to your AcoustID client API key, "
                "then retry."
            ),
            function="lookup_acoustid",
        )
        result["status"] = "unconfigured"
        result["provider"] = "acoustid"
        result["configured"] = False
        return result

    result = lookup_acoustid_with_config(
        fingerprint.strip(), duration_value, config=config
    )
    if isinstance(result, dict) and result.get("status") == "error":
        return make_error(
            E_PROVIDER_FAILED,
            redact_paths(str(result.get("error", "AcoustID request failed"))),
            function="lookup_acoustid",
        )
    if isinstance(result, dict) and result.get("status") == "rate_limited":
        result.setdefault("error_code", E_PROVIDER_FAILED)
    return result


def register_acoustid_tools(app) -> None:
    app.tool()(get_audio_fingerprint)
    app.tool()(lookup_acoustid)
