"""Standardized MCP error codes and path-safe error reporting.

All MCP tool errors must be reported with:

* an ``error_code`` that is stable across processes and deployments
* an optional ``function`` naming the tool that failed
* an ``error`` message that is human-readable but never contains a filesystem path

Error codes are grouped by failure domain:

* ``E_UNKNOWN_TOKEN`` -- the registry token is not registered
* ``E_FILE_NOT_FOUND`` -- the underlying audio file is missing
* ``E_PERMISSION_DENIED`` -- filesystem access denied for the audio file
* ``E_UNSUPPORTED_FORMAT`` -- the audio format cannot be parsed
* ``E_PARSE_ERROR`` -- the audio file could not be parsed for another reason
* ``E_STAGING_FAILED`` -- tag staging (preview/write manifest) failed
* ``E_STAGE_NOT_FOUND`` -- the requested stage_id does not exist
* ``E_STAGE_CONFLICT`` -- revision mismatch or stale stage
* ``E_AUDIO_READ_FAILED`` -- reading audio bytes/tags failed
* ``E_PROVIDER_NOT_CONFIGURED`` -- external provider (ACRCloud) not configured
* ``E_PROVIDER_FAILED`` -- external provider request failed
* ``E_INVALID_INPUT`` -- caller supplied invalid arguments
* ``E_INTERNAL`` -- unexpected internal failure
"""

from typing import Optional

# --- Token / registry errors -------------------------------------------------

E_UNKNOWN_TOKEN = "E_UNKNOWN_TOKEN"

# --- Filesystem errors -------------------------------------------------------

E_FILE_NOT_FOUND = "E_FILE_NOT_FOUND"
E_PERMISSION_DENIED = "E_PERMISSION_DENIED"
E_UNSUPPORTED_FORMAT = "E_UNSUPPORTED_FORMAT"
E_PARSE_ERROR = "E_PARSE_ERROR"

# --- Staging errors ----------------------------------------------------------

E_STAGING_FAILED = "E_STAGING_FAILED"
E_STAGE_NOT_FOUND = "E_STAGE_NOT_FOUND"
E_STAGE_CONFLICT = "E_STAGE_CONFLICT"

# --- Audio read errors -------------------------------------------------------

E_AUDIO_READ_FAILED = "E_AUDIO_READ_FAILED"

# --- Provider errors ---------------------------------------------------------

E_PROVIDER_NOT_CONFIGURED = "E_PROVIDER_NOT_CONFIGURED"
E_PROVIDER_FAILED = "E_PROVIDER_FAILED"

# --- Input / internal errors -------------------------------------------------

E_INVALID_INPUT = "E_INVALID_INPUT"
E_INTERNAL = "E_INTERNAL"

# Map Python exception types to stable error codes.
_EXCEPTION_TO_CODE: dict[type[BaseException], str] = {
    FileNotFoundError: E_FILE_NOT_FOUND,
    PermissionError: E_PERMISSION_DENIED,
    ValueError: E_UNSUPPORTED_FORMAT,
    KeyError: E_UNKNOWN_TOKEN,
}


def _exception_code(exc: BaseException) -> str:
    """Return the stable error code for a Python exception."""
    for exc_type, code in _EXCEPTION_TO_CODE.items():
        if isinstance(exc, exc_type):
            return code
    return E_INTERNAL


def make_error(
    code: str,
    message: str,
    *,
    function: Optional[str] = None,
    path_free: bool = True,
) -> dict:
    """Build a path-safe MCP error dict.

    Parameters
    ----------
    code:
        Stable error code (one of the ``E_*`` constants above).
    message:
        Human-readable description. Must not contain filesystem paths when
        ``path_free`` is true.
    function:
        Name of the MCP tool that produced the error, e.g. ``extract_filename_clues``.
    path_free:
        When true, strip anything that looks like a filesystem path from
        ``message`` before returning.

    Returns
    -------
    dict with ``error_code``, ``error``, and optionally ``function`` keys.
    """
    safe_message = message
    if path_free:
        # Remove anything that looks like a Windows absolute path or a POSIX
        # absolute path so call sites never accidentally leak locations.
        import re

        safe_message = re.sub(r"[A-Za-z]:\\\\.*", "[path]", safe_message)
        safe_message = re.sub(r"/[^\\s]*", "[path]", safe_message)

    result: dict = {"error_code": code, "error": safe_message}
    if function is not None:
        result["function"] = function
    return result


def error_from_exception(
    exc: BaseException,
    *,
    function: Optional[str] = None,
    default_message: Optional[str] = None,
) -> dict:
    """Convert a caught exception into a path-safe MCP error dict."""
    code = _exception_code(exc)
    if default_message is None:
        default_message = {
            E_FILE_NOT_FOUND: "file not found",
            E_PERMISSION_DENIED: "access denied by filesystem",
            E_UNSUPPORTED_FORMAT: "unsupported audio format",
            E_PARSE_ERROR: "failed to parse audio file",
            E_UNKNOWN_TOKEN: "unknown or unregistered token",
            E_INTERNAL: "internal error",
        }.get(code, "internal error")
    return make_error(code, default_message, function=function)
