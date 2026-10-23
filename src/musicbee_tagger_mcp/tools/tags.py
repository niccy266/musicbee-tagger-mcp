"""MCP tag preview, staging, and pending-change tools (no audio writes)."""

from typing import Any, Dict, List, Optional

from ..file_registry import get_registry
from ..staging import get_staging_manager
from ..tag_writer import preview_tag_changes


def preview_tags(token: str, new_tags: Dict[str, Any]) -> Dict[str, Any]:
    """Preview proposed metadata changes without modifying audio."""
    path = get_registry().resolve(token)
    try:
        result = preview_tag_changes(str(path), new_tags)
    except Exception:
        # File-reader exceptions may include the absolute path.
        return {"error": "Unable to preview tag changes"}
    result.pop("file_path", None)
    return result


def stage_tag_changes(
    token: str,
    new_tags: Dict[str, Any],
    mb_recording_id: Optional[str] = None,
    mb_release_id: Optional[str] = None,
    forensic_score: Optional[float] = None,
    notes: str = "",
) -> Dict[str, Any]:
    """Save a pending manifest for user review; does not write audio."""
    entry = get_registry().resolve(token)
    try:
        return get_staging_manager().stage(
            absolute_path=entry,
            display_name=entry.name,
            proposed_tags=new_tags,
            mb_recording_id=mb_recording_id,
            mb_release_id=mb_release_id,
            forensic_score=forensic_score,
            notes=notes,
        )
    except Exception:
        # Staging errors can include the absolute path held by the manager.
        return {"error": "Unable to stage tag changes"}


def list_staged_changes() -> List[Dict[str, Any]]:
    """List pending staged changes using path-free summaries."""
    return get_staging_manager().list_pending()


def register_tag_tools(app) -> None:
    app.tool()(preview_tags)
    app.tool()(stage_tag_changes)
    app.tool()(list_staged_changes)
