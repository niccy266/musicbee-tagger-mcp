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
    match_source: Optional[str] = None,
    match_confidence: Optional[float] = None,
    notes: str = "",
) -> Dict[str, Any]:
    """Save a pending manifest for user review; does not write audio.

    Filename-derived artist/title candidates are unverified research clues.
    Corroborate them with track metadata, duration, or release track listings
    before staging them as tag values.
    """
    entry = get_registry().resolve(token)
    try:
        return get_staging_manager().stage(
            absolute_path=entry,
            display_name=entry.name,
            proposed_tags=new_tags,
            mb_recording_id=mb_recording_id,
            mb_release_id=mb_release_id,
            forensic_score=forensic_score,
            match_source=match_source,
            match_confidence=match_confidence,
            notes=notes,
        )
    except Exception:
        # Staging errors can include the absolute path held by the manager.
        return {"error": "Unable to stage tag changes"}


def list_staged_changes() -> List[Dict[str, Any]]:
    """List pending staged changes using path-free summaries."""
    return get_staging_manager().list_pending()


def get_staged_change(stage_id: str) -> Dict[str, Any]:
    """Inspect a stage's notes, proposed values, current tags, and revision.

    The result excludes local file paths and registry tokens. Use the revision
    when amending or withdrawing so a stale review cannot overwrite newer work.
    """
    try:
        return get_staging_manager().get(stage_id)
    except (FileNotFoundError, ValueError) as error:
        return {"error": str(error)}
    except Exception:
        return {"error": "Unable to read staged change"}


def amend_staged_changes(
    stage_id: str,
    expected_revision: int,
    new_tags: Dict[str, Any],
    reason: str,
    remove_fields: Optional[List[str]] = None,
    mb_recording_id: Optional[str] = None,
    mb_release_id: Optional[str] = None,
    match_source: Optional[str] = None,
    match_confidence: Optional[float] = None,
) -> Dict[str, Any]:
    """Amend a pending proposal without writing audio.

    new_tags is merged into the existing proposal and must contain canonical
    field names with non-empty scalar values. Use remove_fields to drop incorrect
    field proposals, especially when the original tag is empty. The resulting
    change is re-previewed against current tags. Supply a path-free reason and
    the revision from list_staged_changes or get_staged_change; re-read a stale stage.
    """
    try:
        return get_staging_manager().amend(
            stage_id,
            expected_revision,
            new_tags,
            reason,
            remove_fields=remove_fields,
            mb_recording_id=mb_recording_id,
            mb_release_id=mb_release_id,
            match_source=match_source,
            match_confidence=match_confidence,
        )
    except (FileNotFoundError, ValueError) as error:
        return {"error": str(error)}
    except Exception:
        return {"error": "Unable to amend staged change"}


def withdraw_staged_change(
    stage_id: str,
    expected_revision: int,
    reason: str,
) -> Dict[str, Any]:
    """Soft-withdraw a pending proposal; it remains auditable and cannot apply.

    Supply the current revision and a path-free reason. Withdrawal only changes
    the local stage manifest and never modifies the audio file.
    """
    try:
        return get_staging_manager().withdraw(stage_id, expected_revision, reason)
    except (FileNotFoundError, ValueError) as error:
        return {"error": str(error)}
    except Exception:
        return {"error": "Unable to withdraw staged change"}


def register_tag_tools(app) -> None:
    app.tool()(preview_tags)
    app.tool()(stage_tag_changes)
    app.tool()(list_staged_changes)
    app.tool()(get_staged_change)
    app.tool()(amend_staged_changes)
    app.tool()(withdraw_staged_change)
