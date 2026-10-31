"""Playlist job tools served over the MCP protocol.

Registration happens on the user's machine through the CLI command
(musicbee-tagger-register-playlist); the server only serves and updates
jobs. The same operations are both MCP tools available to the LLM and
callable directly by any MCP client — the boundary never carries paths.
"""

from typing import Any, Dict, List

from ..job_store import get_job_store


def list_jobs() -> Dict[str, Any]:
    """List available playlist jobs using path-free summaries."""
    try:
        return {"jobs": get_job_store().list_jobs()}
    except Exception:
        return {"error": "Unable to list playlist jobs"}


def next_batch(job_id: str, size: int = 10) -> Dict[str, Any]:
    """Serve the next batch of unprocessed tokens for a job."""
    return get_job_store().next_batch(job_id, size=size)


def preview_batch(job_id: str, size: int = 10) -> Dict[str, Any]:
    """Preview the next batch of tokens without claiming them."""
    return get_job_store().preview_batch(job_id, size=size)


def complete_batch(job_id: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Report per-token outcomes back to the job."""
    return get_job_store().complete_batch(job_id, results)


def release_batch(job_id: str, tokens: List[str]) -> Dict[str, Any]:
    """Return selected claimed tokens to pending after an interrupted batch."""
    return get_job_store().release_batch(job_id, tokens)


def job_status(job_id: str) -> Dict[str, Any]:
    """Return progress counts and failures for a job."""
    return get_job_store().job_status(job_id)


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
    @app.tool()
    def list_jobs() -> Dict[str, Any]:
        """List playlist jobs that still have pending tracks."""
        try:
            return {"jobs": get_job_store().list_jobs()}
        except Exception:
            return {"error": "Unable to list playlist jobs"}
    @app.tool()
    def next_batch(job_id: str, size: int = 10) -> Dict[str, Any]:
        """Get the next batch (default 10) of unprocessed tokens for a job."""
        return get_job_store().next_batch(job_id, size=size)

    @app.tool()
    def preview_batch(job_id: str, size: int = 10) -> Dict[str, Any]:
        """Preview the next batch (default 10) without claiming any tracks."""
        return get_job_store().preview_batch(job_id, size=size)

    @app.tool()
    def complete_batch(job_id: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Report outcomes: [{token, success, error?}] for a claimed batch."""
        return get_job_store().complete_batch(job_id, results)

    @app.tool()
    def release_batch(job_id: str, tokens: List[str]) -> Dict[str, Any]:
        """Return selected in-progress tokens to pending after interrupted work."""
        return get_job_store().release_batch(job_id, tokens)

    @app.tool()
    def job_status(job_id: str) -> Dict[str, Any]:
        """Get progress counts and any failed tracks for a playlist job."""
        return get_job_store().job_status(job_id)
