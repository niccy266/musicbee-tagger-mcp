"""MCP tag preview, staging, and pending-change tools (no audio writes)."""

from typing import Any, Dict, List, Optional

from ..error_codes import (
    E_AUDIO_READ_FAILED,
    E_FILE_NOT_FOUND,
    E_PERMISSION_DENIED,
    E_STAGING_FAILED,
    E_STAGE_CONFLICT,
    E_STAGE_NOT_FOUND,
    E_UNKNOWN_TOKEN,
    error_from_exception,
    make_error,
)
from ..file_registry import get_registry
from ..staging import get_staging_manager
from ..tag_writer import preview_tag_changes


def preview_tags(token: str, new_tags: Dict[str, Any]) -> Dict[str, Any]:
    """Preview proposed metadata changes without modifying audio."""
    try:
        path = get_registry().resolve(token)
    except KeyError:
        return make_error(
            E_UNKNOWN_TOKEN,
            "unknown or unregistered token",
            function="preview_tags",
        )
    try:
        result = preview_tag_changes(str(path), new_tags)
    except Exception:
        # File-reader exceptions may include the absolute path.
        return make_error(
            E_AUDIO_READ_FAILED,
            "access denied by filesystem",
            function="preview_tags",
        )
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

    PREREQUISITE: Call evaluate_match first. Staging is BLOCKED unless the
    file has a verified recording (verified=true from evaluate_match).
    NEXT STEP: After staging, call finish_batch when all files are resolved.
    """
    try:
        entry = get_registry().resolve(token)
    except KeyError:
        return make_error(
            E_UNKNOWN_TOKEN,
            "unknown or unregistered token",
            function="stage_tag_changes",
        )
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
        return make_error(
            E_STAGING_FAILED,
            "unable to stage tag changes",
            function="stage_tag_changes",
        )


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
        return error_from_exception(error, function="get_staged_change")
    except Exception:
        return make_error(
            E_STAGE_NOT_FOUND,
            "unable to read staged change",
            function="get_staged_change",
        )


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
        return error_from_exception(error, function="amend_staged_changes")
    except Exception:
        return make_error(
            E_STAGE_CONFLICT,
            "unable to amend staged change",
            function="amend_staged_changes",
        )


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
        return error_from_exception(error, function="withdraw_staged_change")
    except Exception:
        return make_error(
            E_STAGE_CONFLICT,
            "unable to withdraw staged change",
            function="withdraw_staged_change",
        )


def register_tag_tools(app) -> None:
    app.tool()(preview_tags)
    app.tool()(stage_tag_changes)
    app.tool()(list_staged_changes)
    app.tool()(get_staged_change)
    app.tool()(amend_staged_changes)
    app.tool()(withdraw_staged_change)
