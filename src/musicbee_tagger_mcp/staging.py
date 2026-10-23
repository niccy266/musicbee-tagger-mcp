"""Staging manager: writes proposed tag changes to a local manifest directory.

The agent calls stage_tag_changes() and receives back a stage_id (UUID).
It never sees the manifest path, the absolute file path, or the staging dir.

The USER applies staged changes via the CLI:
    python -m musicbee_tagger_mcp.apply_staged --stage-id <uuid>
    python -m musicbee_tagger_mcp.apply_staged --all --dry-run
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .tag_writer import preview_tag_changes, apply_tags_to_file

# Staging directory: %APPDATA%\musicbee-tagger-mcp\staged\
# Falls back to user home if APPDATA is not set.
def _default_staging_dir() -> Path:
    import os
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home()
    d = base / "musicbee-tagger-mcp" / "staged"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Fallback to a temp directory (e.g. in sandboxed test environments)
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="musicbee-tagger-staged-"))
    return d


class StagingManager:
    """Manages pending tag-change manifests on disk."""

    def __init__(self, staging_dir: Optional[Path] = None) -> None:
        self.staging_dir = staging_dir or _default_staging_dir()

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

        manifest_path = self.staging_dir / f"{stage_id}.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

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

    def load(self, stage_id: str) -> dict:
        """Load a manifest by stage_id. Returns full manifest including path (internal use)."""
        manifest_path = self.staging_dir / f"{stage_id}.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"No staged change found for stage_id: {stage_id}")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def list_pending(self) -> List[dict]:
        """List all pending (not yet applied) staged changes — safe fields only."""
        results = []
        for p in sorted(self.staging_dir.glob("*.json")):
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
                if not m.get("applied", False):
                    results.append({
                        "stage_id": m["stage_id"],
                        "display_name": m["display_name"],
                        "created_at": m["created_at"],
                        "diff_summary": m.get("diff", []),
                        "forensic_score": m.get("forensic_score"),
                    })
            except Exception:
                continue
        return results

    def apply(self, stage_id: str, create_backup: bool = True) -> dict:
        """Apply a staged change to disk. INTERNAL — called by CLI only, not MCP.

        Returns a result dict with applied field count and backup path.
        """
        manifest = self.load(stage_id)
        if manifest.get("applied"):
            return {"status": "already_applied", "stage_id": stage_id}

        absolute_path = manifest["absolute_path"]
        proposed_tags = manifest["proposed_tags"]

        result = apply_tags_to_file(absolute_path, proposed_tags, create_backup=create_backup)

        # Mark manifest as applied
        manifest["applied"] = True
        manifest["applied_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path = self.staging_dir / f"{stage_id}.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        return {
            "status": "applied",
            "stage_id": stage_id,
            "display_name": manifest["display_name"],
            "fields_written": result.get("fields_written", []),
            "backup_created": result.get("backup_path") is not None,
        }


# Module-level singleton — lazily initialised on first access
_staging_manager: Optional[StagingManager] = None


def get_staging_manager() -> StagingManager:
    global _staging_manager
    if _staging_manager is None:
        _staging_manager = StagingManager()
    return _staging_manager
