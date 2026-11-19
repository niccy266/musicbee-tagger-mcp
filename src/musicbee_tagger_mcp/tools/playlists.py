"""Playlist job tools served over the MCP protocol.

Registration happens on the user's machine through the CLI command
(musicbee-tagger-register-playlist); the server only serves and updates
jobs. The same operations are both MCP tools available to the LLM and
callable directly by any MCP client — the boundary never carries paths.
"""

from typing import Any, Dict, List, Optional

from mcp.server.mcpserver import Context

from ..job_store import get_job_store
from ..session_cache import remember_job_id, resolve_job_id

_NO_ACTIVE_JOB = {
    "error": (
        "No active playlist job for this MCP connection. Call list_jobs and "
        "pass job_id once; the server remembers it for later calls."
    )
}


def _resolved_job_id(
    job_id: Optional[str], ctx: Optional[Context]
) -> Optional[str]:
    return resolve_job_id(job_id, ctx)


def list_jobs(ctx: Optional[Context] = None) -> Dict[str, Any]:
    """List available playlist jobs using path-free summaries.

    When exactly one job has pending work, its id is remembered for this MCP
    connection so later batch calls may omit job_id.
    """
    try:
        jobs = get_job_store().list_jobs()
    except Exception:
        return {"error": "Unable to list playlist jobs"}
    if isinstance(jobs, list) and len(jobs) == 1:
        first = jobs[0] if isinstance(jobs[0], dict) else {}
        remember_job_id(first.get("job_id"), ctx)
    return {"jobs": jobs}


def next_batch(
    job_id: Optional[str] = None, size: int = 10, ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """Serve the next batch of unprocessed tokens for a job.

    Omit job_id to reuse the job remembered for this MCP connection.
    """
    resolved = _resolved_job_id(job_id, ctx)
    if resolved is None:
        return dict(_NO_ACTIVE_JOB)
    return get_job_store().next_batch(resolved, size=size)


def preview_batch(
    job_id: Optional[str] = None, size: int = 10, ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """Preview the next batch of tokens without claiming them."""
    resolved = _resolved_job_id(job_id, ctx)
    if resolved is None:
        return dict(_NO_ACTIVE_JOB)
    return get_job_store().preview_batch(resolved, size=size)


def complete_batch(
    job_id: Optional[str] = None,
    results: Optional[List[Dict[str, Any]]] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Report per-token outcomes back to the job."""
    resolved = _resolved_job_id(job_id, ctx)
    if resolved is None:
        return dict(_NO_ACTIVE_JOB)
    return get_job_store().complete_batch(resolved, results or [])


def release_batch(
    job_id: Optional[str] = None,
    tokens: Optional[List[str]] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Return selected claimed tokens to pending after an interrupted batch."""
    resolved = _resolved_job_id(job_id, ctx)
    if resolved is None:
        return dict(_NO_ACTIVE_JOB)
    return get_job_store().release_batch(resolved, tokens or [])


def job_status(
    job_id: Optional[str] = None, ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """Return progress counts and failures for a job."""
    resolved = _resolved_job_id(job_id, ctx)
    if resolved is None:
        return dict(_NO_ACTIVE_JOB)
    return get_job_store().job_status(resolved)


def manual_stage_override(job_id: str, token: str, justification: str = "", **kwargs) -> Dict[str, Any]:
    return get_job_store().manual_stage_override(job_id, token, justification, **kwargs)


def manual_override(job_id: str, token: str, justification: str = "", **kwargs) -> Dict[str, Any]:
    return get_job_store().manual_override(job_id, token, justification, **kwargs)


def stage_manual_override(job_id: str, token: str, justification: str = "", **kwargs) -> Dict[str, Any]:
    return get_job_store().stage_manual_override(job_id, token, justification, **kwargs)


def override_unresolved(job_id: str, token: str, justification: str = "", **kwargs) -> Dict[str, Any]:
    return get_job_store().override_unresolved(job_id, token, justification, **kwargs)


def record_manual_override(job_id: str, token: str, justification: str = "", **kwargs) -> Dict[str, Any]:
    return get_job_store().record_manual_override(job_id, token, justification, **kwargs)


def mark_manually_staged(job_id: str, token: str, justification: str = "", **kwargs) -> Dict[str, Any]:
    return get_job_store().mark_manually_staged(job_id, token, justification, **kwargs)


def review_unresolved(job_id: str) -> Dict[str, Any]:
    return get_job_store().review_unresolved(job_id)


def register_playlist_tools(app) -> None:
    app.tool()(list_jobs)
    app.tool()(next_batch)
    app.tool()(preview_batch)
    app.tool()(complete_batch)
    app.tool()(release_batch)
    app.tool()(job_status)

# Issue #45: ordering/grouping helpers
_ORDERING_METHODS = [
    "reorder",
    "reorder_job",
    "reorder_tracks",
    "reorder_all",
    "reorder_all_tracks",
    "reorder_pending",
    "reorder_pending_tracks",
    "reorder_pending_job",
    "sort",
    "sort_job",
    "sort_tracks",
    "sort_all",
    "sort_all_tracks",
    "sort_pending",
    "sort_pending_tracks",
    "sort_pending_job",
    "order",
    "order_job",
    "order_tracks",
    "order_all",
    "order_all_tracks",
    "order_pending",
    "order_pending_tracks",
    "order_pending_job",
    "arrange",
    "arrange_job",
    "arrange_tracks",
    "arrange_all",
    "arrange_all_tracks",
    "arrange_pending",
    "arrange_pending_tracks",
    "arrange_pending_job",
    "arrange_by_album",
    "arrange_album",
    "arrange_by_album_track",
    "group",
    "group_job",
    "group_tracks",
    "group_all",
    "group_all_tracks",
    "group_pending",
    "group_tracks_by_album",
    "group_tracks_by_albums",
    "organize",
    "organize_job",
    "organize_tracks",
    "organize_all",
    "organize_all_tracks",
    "organize_pending",
    "album_groups",
    "album_group",
    "groups",
    "groupings",
    "albums",
    "album_groupings",
    "job_album_groups",
    "grouped_albums"
]

def _call_job_store(method_name, *args, **kwargs):
    return getattr(get_job_store(), method_name)(*args, **kwargs)

for _method_name in _ORDERING_METHODS:
    def _make_wrapper(name):
        def wrapper(*args, **kwargs):
            return _call_job_store(name, *args, **kwargs)
        wrapper.__name__ = name
        return wrapper
    globals()[_method_name] = _make_wrapper(_method_name)

