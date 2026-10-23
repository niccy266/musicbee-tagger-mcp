"""Staging manager: writes proposed tag changes to a local manifest directory.

The agent calls stage_tag_changes() and receives back a stage_id (UUID).
It never sees the manifest path, the absolute file path, or the staging dir.

The USER applies staged changes via the CLI:
    python -m musicbee_tagger_mcp.apply_staged --stage-id <uuid>
    python -m musicbee_tagger_mcp.apply_staged --all --dry-run
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .stage_manifest_store import StageManifestStore
from .tag_writer import preview_tag_changes


class StagingManager:
    """Manages pending tag-change manifests on disk."""

    def __init__(self, staging_dir: Optional[Path] = None) -> None:
        self.store = StageManifestStore(staging_dir)
        self.staging_dir = self.store.directory

    def stage(
        self,
        absolute_path: Path,
        display_name: str,
        proposed_tags: Dict[str, Any],
        mb_recording_id: Optional[str] = None,
        mb_release_id: Optional[str] = None,
        forensic_score: Optional[float] = None,
        notes: str = "",
    ) -> dict:
        """Write a pending change manifest and return a stage_id + summary.

        The absolute_path is stored inside the manifest file on disk.
        It is NEVER returned to the caller.

        Returns:
            {"stage_id": str, "display_name": str, "diff_summary": list, "notes": str}
        """
        # Generate the field-by-field diff (reads file for current values)
        diff_result = preview_tag_changes(str(absolute_path), proposed_tags)
        preview_diff = diff_result.get("diff", {})
        if isinstance(preview_diff, dict):
            diff = [
                {
                    "field": field,
                    "old": change.get("before"),
                    "new": change.get("after"),
                }
                for field, change in preview_diff.items()
                if change.get("changed")
            ]
        elif isinstance(preview_diff, list):
            diff = preview_diff
        else:
            raise ValueError("Tag preview returned an invalid diff")

        stage_id = str(uuid.uuid4())
        manifest = {
            "stage_id": stage_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "display_name": display_name,
            "absolute_path": str(absolute_path),  # stored on disk, never returned
            "proposed_tags": proposed_tags,
            "diff": diff,
            "mb_recording_id": mb_recording_id,
            "mb_release_id": mb_release_id,
            "forensic_score": forensic_score,
            "notes": notes,
            "applied": False,
        }

        self.store.save(manifest)

        # Return only safe, non-path fields to the caller
        return {
            "stage_id": stage_id,
            "display_name": display_name,
            "diff_summary": diff,
            "notes": notes,
            "message": (
                f"Staged {len(diff)} field change(s) for '{display_name}'. "
                f"Run `python -m musicbee_tagger_mcp.apply_staged --stage-id {stage_id}` to apply."
            ),
        }

    def list_pending(self) -> List[dict]:
        """List all pending (not yet applied) staged changes — safe fields only."""
        return self.store.list_pending()

# Module-level singleton — lazily initialised on first access
_staging_manager: Optional[StagingManager] = None


def get_staging_manager() -> StagingManager:
    global _staging_manager
    if _staging_manager is None:
        _staging_manager = StagingManager()
    return _staging_manager
