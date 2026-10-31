"""Standardized MCP error codes and path-safe error reporting."""

from typing import Any, Optional

E_UNKNOWN_TOKEN = "E_UNKNOWN_TOKEN"
E_FILE_NOT_FOUND = "E_FILE_NOT_FOUND"
E_PERMISSION_DENIED = "E_PERMISSION_DENIED"
E_UNSUPPORTED_FORMAT = "E_UNSUPPORTED_FORMAT"
E_PARSE_ERROR = "E_PARSE_ERROR"
E_STAGING_FAILED = "E_STAGING_FAILED"
E_STAGE_NOT_FOUND = "E_STAGE_NOT_FOUND"
E_STAGE_CONFLICT = "E_STAGE_CONFLICT"
E_AUDIO_READ_FAILED = "E_AUDIO_READ_FAILED"
E_PROVIDER_NOT_CONFIGURED = "E_PROVIDER_NOT_CONFIGURED"
E_PROVIDER_FAILED = "E_PROVIDER_FAILED"
E_INVALID_INPUT = "E_INVALID_INPUT"
E_INTERNAL = "E_INTERNAL"

import re
import urllib.parse


def redact_paths(text):
    """Remove anything that looks like a filesystem path from *text*.

    Handles plain text, URL-encoded payloads, and serialized/escaped Windows
    paths. Non-string containers are sanitized recursively.
    """
    if isinstance(text, dict):
        return {key: redact_paths(value) for key, value in text.items()}
    if isinstance(text, (list, tuple, set)):
        return [redact_paths(value) for value in text]
    if not isinstance(text, str):
        return text

    patterns = [
        re.compile(r"[A-Za-z]:[\/].*", re.DOTALL),
        re.compile(r"\\\\.*", re.DOTALL),
        re.compile(r"(?<!\S)/\S+$"),
    ]

    current = text
    for _ in range(10):
        previous = current
        try:
            decoded = urllib.parse.unquote(current, errors="replace")
        except Exception:
            decoded = current
        current = decoded
        for pattern in patterns:
            current = pattern.sub("[path]", current)
        if current == previous:
            break
    return current


def sanitize_path_text(text):
    return redact_paths(text)


_EXCEPTION_TO_CODE = {
    FileNotFoundError: E_FILE_NOT_FOUND,
    PermissionError: E_PERMISSION_DENIED,
    UnicodeError: E_PARSE_ERROR,
    SyntaxError: E_PARSE_ERROR,
    ValueError: E_UNSUPPORTED_FORMAT,
    KeyError: E_UNKNOWN_TOKEN,
}


def _exception_code(exc):
    for exc_type, code in _EXCEPTION_TO_CODE.items():
        if isinstance(exc, exc_type):
            return code
    return E_INTERNAL


def make_error(
    code: str,
    message: Any,
    *,
    function: Optional[str] = None,
    path_free: bool = True,
) -> dict:
    """Build a path-safe MCP error dict."""
    if path_free and not isinstance(message, str):
        message = str(message)
    safe_message = redact_paths(message) if path_free else message
    result = {"error_code": code, "error": safe_message}
    if function is not None:
        result["function"] = function
    return result
    if function is not None:
        result["function"] = function
    return result


def error_from_exception(exc, *, function=None, default_message=None):
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
