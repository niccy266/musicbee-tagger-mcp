"""Per-connection memory for the active playlist job id.

Every MCP connection gets its own session object, so caching the active
``job_id`` against that session keeps one client's playlist from leaking into
another client's calls. The cache is intentionally best-effort: tools still
work without a ``Context`` (direct calls, scripts, tests) and always accept an
explicit ``job_id`` that overrides whatever was remembered.
"""

from typing import Any, Optional
from weakref import WeakKeyDictionary

_ACTIVE_JOB_IDS: "WeakKeyDictionary[Any, str]" = WeakKeyDictionary()


def _session_for(context: Any) -> Any:
    """Return the MCP session for a Context, or None when unavailable."""
    if context is None:
        return None
    try:
        session = context.request_context.session
    except Exception:
        # Context exists but is not bound to a request (unit calls, help mode).
        return None
    return session


def remember_job_id(job_id: Optional[str], context: Any = None) -> None:
    """Remember ``job_id`` for the connection that issued the call."""
    if not isinstance(job_id, str) or not job_id.strip():
        return
    session = _session_for(context)
    if session is None:
        return
    try:
        _ACTIVE_JOB_IDS[session] = job_id.strip()
    except TypeError:
        # Session objects that cannot be weakly referenced simply go uncached.
        return


def recall_job_id(context: Any = None) -> Optional[str]:
    """Return the job id previously remembered for this connection, if any."""
    session = _session_for(context)
    if session is None:
        return None
    try:
        return _ACTIVE_JOB_IDS.get(session)
    except TypeError:
        return None


def clear_job_id(context: Any = None) -> bool:
    """Forget the remembered job id for this connection."""
    session = _session_for(context)
    if session is None:
        return False
    try:
        return _ACTIVE_JOB_IDS.pop(session, None) is not None
    except TypeError:
        return False


def resolve_job_id(
    job_id: Optional[str] = None, context: Any = None
) -> Optional[str]:
    """Resolve the job id for a call, remembering explicit values.

    An explicit ``job_id`` always wins and becomes the connection's active
    job. When it is omitted, the value remembered for this connection is used.
    """
    if isinstance(job_id, str) and job_id.strip():
        resolved = job_id.strip()
        remember_job_id(resolved, context)
        return resolved
    return recall_job_id(context)
