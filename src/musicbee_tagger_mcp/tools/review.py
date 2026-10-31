"""MCP tool for durable, path-free human-review flags."""

from typing import Any, Dict, Optional

from .. import file_registry
from ..error_codes import (
    E_UNKNOWN_TOKEN,
    make_error,
    redact_paths,
)
from ..review_flags import ReviewFlagStore, get_review_store

# Module-level lookup so tests can monkeypatch this attribute.
get_registry = file_registry.get_registry


def _canonical_token(registry, token: str) -> Optional[str]:
    try:
        path = registry.resolve(token)
    except Exception:
        return None
    token_for_path = getattr(registry, "token_for_path", None)
    if callable(token_for_path):
        try:
            found = token_for_path(path)
            if found:
                return found
        except Exception:
            pass
    try:
        import uuid

        return str(uuid.UUID(token))
    except (TypeError, ValueError, AttributeError):
        return token


def flag_for_review(
    token: str,
    reason: str,
    candidate_summary: Any = None,
    verification_summary: Any = None,
    summary: Any = None,
    candidates: Any = None,
    verification: Any = None,
    candidate: Any = None,
    metadata: Any = None,
    display_name: Any = None,
) -> Dict[str, Any]:
    """Record a durable, path-free human-review flag for a registered track.

    Use this when investigation cannot confidently stage a proposal.  The flag
    is stored under the configured private data directory and survives MCP
    server restarts.  It is distinct from completed no-match archives and
    transient search-retry records.
    """
    registry = get_registry()
    try:
        registry.resolve(token)
    except KeyError:
        return make_error(
            E_UNKNOWN_TOKEN,
            "unknown or unregistered token",
            function="flag_for_review",
        )
    except Exception:
        return make_error(
            E_UNKNOWN_TOKEN,
            "unknown or unregistered token",
            function="flag_for_review",
        )

    canonical = _canonical_token(registry, token)
    if canonical is None:
        canonical = token

    bare_name = display_name
    if bare_name is None:
        try:
            bare_name = registry.resolve(canonical).name
        except Exception:
            try:
                bare_name = registry.resolve(token).name
            except Exception:
                bare_name = None

    if candidate is not None and candidate_summary is None:
        candidate_summary = candidate
    if candidates is not None and candidate_summary is None:
        candidate_summary = candidates
    if verification is not None and verification_summary is None:
        verification_summary = verification
    if summary is not None:
        if candidate_summary is None:
            candidate_summary = summary
        elif verification_summary is None:
            verification_summary = summary

    store = get_review_store()
    try:
        result = store.flag(
            canonical,
            reason,
            display_name=bare_name,
            candidate_summary=candidate_summary,
            verification_summary=verification_summary,
            metadata=metadata,
        )
    except ValueError as error:
        return {"error": redact_paths(str(error))}
    except Exception:
        return make_error(
            E_UNKNOWN_TOKEN,
            "unable to flag for review",
            function="flag_for_review",
        )
    return result


def list_review_flags(*args: Any, **kwargs: Any) -> Any:
    """List durable review flags (path-free)."""
    return get_review_store().list_flags(*args, **kwargs)


def resolve_review_flag(*args: Any, **kwargs: Any) -> Any:
    """Resolve a durable review flag (path-free)."""
    return get_review_store().resolve(*args, **kwargs)


def register_review_tools(app) -> None:
    app.tool()(flag_for_review)
