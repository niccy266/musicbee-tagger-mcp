"""Playlist job tools: server-side registration and token batches over MCP.

The playlist path is received and resolved server-side; neither it nor any
file path is echoed back to the agent. Only opaque tokens and bare display
names cross the MCP boundary.
"""

from typing import Any, Dict, List

from ..file_registry import get_registry
from ..job_store import get_job_store
from ..playlist import parse_m3u_playlist
from ..tools.files import register_playlist


def register_playlist_job(playlist_location: str) -> Dict[str, Any]:
    """Register a playlist server-side and create a processing job.

    Returns the job id and counts only — never tokens, never paths.
    """
    registered = register_playlist(playlist_location)
    if "error" in registered:
        return registered
    if not registered["registered"]:
        return {"error": "No audio files found in playlist"}
    playlist_name = playlist_location.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    result = get_job_store().create_job(
        registered["registered"], playlist_name=playlist_name
    )
    result["skipped_entries"] = len(registered["skipped"])
    return result


def next_batch(job_id: str, size: int = 10) -> Dict[str, Any]:
    """Serve the next batch of unprocessed tokens for a job."""
    return get_job_store().next_batch(job_id, size=size)


def complete_batch(job_id: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Report per-token outcomes back to the job."""
    return get_job_store().complete_batch(job_id, results)


def job_status(job_id: str) -> Dict[str, Any]:
    """Return progress counts and failures for a job."""
    return get_job_store().job_status(job_id)


def register_playlist_tools(app) -> None:
    @app.tool()
    def register_playlist(playlist_location: str) -> Dict[str, Any]:
        """Register a local .m3u/.m3u8 playlist server-side and create a
        processing job. Returns a job id and counts only — never file paths."""
        return register_playlist_job(playlist_location)

    @app.tool()
    def next_batch(job_id: str, size: int = 10) -> Dict[str, Any]:
        """Get the next batch (default 10) of unprocessed tokens for a job."""
        return next_batch(job_id, size=size)

    @app.tool()
    def complete_batch(job_id: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Report outcomes: [{token, success, error?}] for a claimed batch."""
        return complete_batch(job_id, results)

    @app.tool()
    def job_status(job_id: str) -> Dict[str, Any]:
        """Get progress counts and any failed tracks for a playlist job."""
        return job_status(job_id)
