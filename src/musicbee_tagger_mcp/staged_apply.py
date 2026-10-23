"""CLI-only service for applying staged manifests to audio files."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .stage_manifest_store import StageManifestStore
from .staging import get_staging_manager
from .tag_applier import apply_tags_to_file


class StagedChangeApplier:
    """Load and apply manifests; this module is not imported by MCP tools."""

    def __init__(self, staging_dir: Path) -> None:
        self.store = StageManifestStore(staging_dir)

    def load(self, stage_id: str) -> dict:
        return self.store.load(stage_id)

    def apply(self, stage_id: str, create_backup: bool = True) -> dict:
        manifest = self.load(stage_id)
        if manifest.get("applied"):
            return {"status": "already_applied", "stage_id": stage_id}

        result = apply_tags_to_file(
            manifest["absolute_path"],
            manifest["proposed_tags"],
            create_backup=create_backup,
        )
        manifest["applied"] = True
        manifest["applied_at"] = datetime.now(timezone.utc).isoformat()
        self.store.save(manifest)
        return {
            "status": "applied",
            "stage_id": stage_id,
            "display_name": manifest["display_name"],
            "fields_written": result.get("fields_written", []),
            "backup_created": result.get("backup_created") is not None,
        }


_applier: Optional[StagedChangeApplier] = None


def get_staged_applier() -> StagedChangeApplier:
    global _applier
    if _applier is None:
        _applier = StagedChangeApplier(get_staging_manager().staging_dir)
    return _applier
